"""
Drop Rooms: rooms, devices and items (roadmap DR1). Pure logic: it is handed a SqlStore (Postgres in Toolbox, SQLite in tests),
a *scoped* Vault (`vault_store.scoped("drop-rooms")`), a clock and a rate limiter, so a test can give it temporary ones.

The model, in plain words (docs: drop-rooms/CLAUDE.md):
  * A DEVICE is a browser. It gets a random token in an HttpOnly cookie; only the token's SHA-256 is stored. There are no accounts.
  * A ROOM has a long random KEY (125 bits). Anyone who joins with the key sees everything in the room. The key's SHA-256 is
    stored for lookup; the key itself is kept in the Vault (kind `drop_room_key`) so members can re-share the invite.
  * A MEMBER is a device that joined a room with a nickname. The creator is the OWNER. Resetting the key bumps the room's
    `epoch`, which silently removes every member who joined with the old key.
  * An ITEM is a piece of text, a file or a folder (a ZIP built by the browser). It has an expiry (5 s to 30 days; the page offers 1 h to 30 days).
    Expired or deleted items are invisible to everybody at once (every query filters them), and are erased a little later.
  * Every change to a room bumps `rooms.rev`; a device that polls with the rev it already has gets a tiny "unchanged" answer.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
import uuid
from typing import Any, Callable, Optional

KIND = "drop_room_key"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_secret_id TEXT NOT NULL,
    default_retention INTEGER NOT NULL,
    rev INTEGER NOT NULL DEFAULT 0,
    epoch INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    owner_device TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    room_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    role TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    joined_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    PRIMARY KEY (room_id, device_id)
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT,
    file_name TEXT,
    size INTEGER,
    mime TEXT,
    s3_key TEXT,
    device_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    edited_at INTEGER,
    edited_by TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    expires_at INTEGER NOT NULL,
    deleted_at INTEGER,
    deleted_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_room ON items (room_id, seq);
CREATE INDEX IF NOT EXISTS idx_items_expires ON items (expires_at);
CREATE INDEX IF NOT EXISTS idx_members_device ON members (device_id);
"""

PRESETS = (3600, 10800, 21600, 43200, 86400, 259200, 604800, 2592000)    # 1 h, 3 h, 6 h, 12 h, 1 d, 3 d, 7 d, 30 d
MIN_RETENTION, MAX_RETENTION, DEFAULT_RETENTION = 5, 2592000, 21600       # the API accepts 5 s to 30 days; the page offers PRESETS
UNDO_SECONDS = 10                  # the device that deleted an item can bring it back for this long
ERASE_AFTER = 20                   # a deleted item is really erased this many seconds after the delete
DEVICE_IDLE_DAYS = 30              # a device not seen for this long is forgotten (and so are its memberships)

MAX_TEXT, MAX_ROOM_NAME, MAX_NICK = 20000, 60, 30
MAX_ROOMS_TOTAL, MAX_ROOMS_PER_DEVICE, MAX_MEMBERS = 200, 20, 50
MAX_ITEMS_PER_ROOM = 2000

# files and folders (roadmap DR2)
MAX_FILE = 100 * 1024 * 1024                       # per file or folder-ZIP
ROOM_QUOTA = 1024 ** 3                             # live bytes per room
TOTAL_QUOTA = 20 * 1024 ** 3                       # live bytes in the whole tool
MAX_ZIP_ENTRIES = 5000
MAX_NAME_LEN = 150
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")        # the ONLY types ever shown inline (no SVG: it can carry script)
TEXT_EXTS = frozenset(("txt", "md", "log", "json", "csv", "tsv", "yaml", "yml", "xml", "ini", "conf", "cfg", "toml", "sql", "sh", "py", "js", "ts", "css",
                       "html", "htm", "env", "properties", "gitignore", "dockerfile"))
TEXT_PREVIEW_MAX = 5 * 1024 * 1024                 # larger files are download-only
TEXT_PREVIEW_BYTES = 200_000

KEY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"                         # Crockford base32: no I L O U
_LENIENT = str.maketrans("ILO", "110")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DropError(Exception):
    status = 400


class BadRequest(DropError):
    status = 400


class Forbidden(DropError):
    status = 403


class NotFound(DropError):
    status = 404


class Conflict(DropError):
    status = 409

    def __init__(self, msg: str, current: Optional[dict] = None):
        super().__init__(msg)
        self.current = current


class TooMany(DropError):
    status = 429


class TooLarge(DropError):
    status = 413


# ------------------------------------------------------------------------------------------------ keys and input

def new_key() -> str:
    """25 characters from a 32-letter alphabet = 125 bits, shown as XXXXX-XXXXX-XXXXX-XXXXX-XXXXX."""
    return "-".join("".join(secrets.choice(KEY_ALPHABET) for _ in range(5)) for _ in range(5))


def normalize_key(raw: Any) -> str:
    s = re.sub(r"[\s\-_]", "", str(raw or "")).upper().translate(_LENIENT)
    if len(s) != 25 or any(c not in KEY_ALPHABET for c in s):
        raise BadRequest("That does not look like a room key. It has 25 letters and numbers, like ABCDE-23456-…")
    return s


def key_hash(raw: Any) -> str:
    return hashlib.sha256(normalize_key(raw).encode()).hexdigest()


def pretty_key(raw: Any) -> str:
    s = normalize_key(raw)
    return "-".join(s[i:i + 5] for i in range(0, 25, 5))


def _clean(v: Any, what: str, maxlen: int) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if not s:
        raise BadRequest(f"Please give {what}.")
    if len(s) > maxlen:
        raise BadRequest(f"The {what.replace('a ', '').replace('an ', '')} is too long (maximum {maxlen} characters).")
    if _CONTROL.search(s):
        raise BadRequest(f"The {what.replace('a ', '').replace('an ', '')} has characters that are not allowed.")
    return s


def _text(v: Any) -> str:
    s = "" if v is None else str(v)
    if not s.strip():
        raise BadRequest("The message is empty.")
    if len(s) > MAX_TEXT:
        raise BadRequest(f"The text is too long (maximum {MAX_TEXT:,} characters).")
    if "\x00" in s:
        raise BadRequest("The text contains a null character, which cannot be stored.")
    return s


def clean_filename(name: Any) -> str:
    """A name that is safe to store and to put in a Content-Disposition header: no path, no control characters, no characters Windows
    refuses, at most MAX_NAME_LEN characters (the extension is kept)."""
    s = str(name or "").replace("\\", "/").split("/")[-1]
    s = _CONTROL.sub("", s)
    s = re.sub(r'[<>:"|?*]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s:
        return "file"
    if len(s) > MAX_NAME_LEN:
        base, dot, ext = s.rpartition(".")
        s = (base[:MAX_NAME_LEN - len(ext) - 1] + "." + ext) if dot and 0 < len(ext) < 20 else s[:MAX_NAME_LEN]
    return s


def sniff_image(head: bytes) -> Optional[str]:
    """The real type of an image from its first bytes (never from the name or the browser's claim)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def check_zip(fileobj: Any) -> int:
    """A folder arrives as a ZIP. Refuse anything that is not a real ZIP, has too many entries, or has paths that could write outside the
    folder when someone extracts it (absolute paths, `..`, drive letters). Returns the number of files in it."""
    import zipfile

    fileobj.seek(0)
    try:
        names = zipfile.ZipFile(fileobj).namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise BadRequest("That is not a valid folder (ZIP) upload.")
    finally:
        fileobj.seek(0)
    if not names:
        raise BadRequest("The folder is empty.")
    if len(names) > MAX_ZIP_ENTRIES:
        raise BadRequest(f"The folder has too many files (maximum {MAX_ZIP_ENTRIES:,}).")
    for n in names:
        parts = n.replace("\\", "/").split("/")
        if n.startswith(("/", "\\")) or ".." in parts or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
            raise BadRequest("The folder contains unsafe file paths, so it was not uploaded.")
    return len([n for n in names if not n.endswith("/")])


def is_text_name(name: str) -> bool:
    n = (name or "").lower()
    return n.rpartition(".")[2] in TEXT_EXTS if "." in n else n in TEXT_EXTS


def human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} bytes" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def clamp_retention(v: Any, default: int = DEFAULT_RETENTION) -> int:
    if v is None or v == "":
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadRequest("Retention must be a number of seconds.")
    if n < MIN_RETENTION:
        raise BadRequest("Retention is too short.")
    return min(n, MAX_RETENTION)


# ------------------------------------------------------------------------------------------------ the service

class DropRooms:
    def __init__(self, store: Any, vault: Any, clock: Callable[[], float] = time.time):
        self.db, self.vault, self._clock = store, vault, clock
        # The file bytes' storage (DR2): put(key, fileobj, content_type), delete(key), head(key, n). The server gives it Toolbox's S3 storage;
        # a test gives it a dictionary. `delete` is called whenever a file item is erased (expiry, delete, room deletion).
        self.files: Any = None

    def now(self) -> int:
        return int(self._clock())

    # ---- devices -------------------------------------------------------------------------------------------
    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(str(token).encode()).hexdigest()

    def new_device(self) -> tuple[str, str]:
        token, did, now = secrets.token_urlsafe(32), uuid.uuid4().hex, self.now()
        with self.db.connect() as con:
            con.execute("INSERT INTO devices (id, token_hash, created_at, last_seen) VALUES (?, ?, ?, ?)",
                        (did, self._hash_token(token), now, now))
        return did, token

    def device_for_token(self, token: Optional[str]) -> Optional[str]:
        if not token or len(token) > 200:
            return None
        now = self.now()
        with self.db.connect() as con:
            row = con.execute("SELECT id, last_seen FROM devices WHERE token_hash = ?", (self._hash_token(token),)).fetchone()
            if not row:
                return None
            if now - row["last_seen"] > 60:
                con.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, row["id"]))
            return row["id"]

    # ---- helpers ---------------------------------------------------------------------------------------------
    @staticmethod
    def _bump(con: Any, room_id: str) -> int:
        con.execute("UPDATE rooms SET rev = rev + 1 WHERE id = ?", (room_id,))
        return con.execute("SELECT rev FROM rooms WHERE id = ?", (room_id,)).fetchone()["rev"]

    def _member(self, con: Any, device_id: str, room_id: str, owner: bool = False) -> dict:
        """The room as this device may see it. Anything else (no such room, not a member, removed by a key reset) is the SAME
        'not found', so a wrong id never reveals that a room exists."""
        row = con.execute(
            "SELECT r.id, r.name, r.default_retention, r.rev, r.epoch, r.key_secret_id, r.owner_device, r.created_at, "
            "m.nickname AS my_nick, m.role AS my_role, m.last_seen AS m_seen FROM rooms r "
            "JOIN members m ON m.room_id = r.id AND m.device_id = ? AND m.epoch = r.epoch WHERE r.id = ?",
            (device_id, room_id)).fetchone()
        if not row:
            raise NotFound("Room not found. You may have been removed, or the room was deleted.")
        if owner and row["my_role"] != "owner":
            raise Forbidden("Only the room owner can do that.")
        now = self.now()
        if now - row["m_seen"] > 30:
            con.execute("UPDATE members SET last_seen = ? WHERE room_id = ? AND device_id = ?", (now, room_id, device_id))
        return row

    def _public_room(self, r: dict, **extra: Any) -> dict:
        out = {"id": r["id"], "name": r["name"], "default_retention": r["default_retention"], "rev": r["rev"],
               "role": r["my_role"], "nickname": r["my_nick"], "created_at": r["created_at"]}
        out.update(extra)
        return out

    # ---- rooms ----------------------------------------------------------------------------------------------
    def create_room(self, device_id: str, name: str, nickname: str, default_retention: Any = None) -> dict:
        name, nick = _clean(name, "a room name", MAX_ROOM_NAME), _clean(nickname, "a nickname", MAX_NICK)
        retention = clamp_retention(default_retention)
        now, rid, key = self.now(), uuid.uuid4().hex, new_key()
        with self.db.connect() as con:
            if con.execute("SELECT COUNT(*) AS n FROM rooms").fetchone()["n"] >= MAX_ROOMS_TOTAL:
                raise BadRequest("This Toolbox has reached its limit of rooms.")
            if con.execute("SELECT COUNT(*) AS n FROM rooms WHERE owner_device = ?", (device_id,)).fetchone()["n"] >= MAX_ROOMS_PER_DEVICE:
                raise BadRequest(f"One device can own at most {MAX_ROOMS_PER_DEVICE} rooms.")
        secret_id = self.vault.save_secret("dr-" + rid, KIND, {"key": key, "room": rid})
        try:
            with self.db.connect() as con:
                con.execute("INSERT INTO rooms (id, name, key_hash, key_secret_id, default_retention, rev, epoch, created_at, owner_device) "
                            "VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)", (rid, name, key_hash(key), secret_id, retention, now, device_id))
                con.execute("INSERT INTO members (room_id, device_id, nickname, role, epoch, joined_at, last_seen) VALUES (?, ?, ?, 'owner', 1, ?, ?)",
                            (rid, device_id, nick, now, now))
                room = self._member(con, device_id, rid)
        except Exception:
            self.vault.delete_secret(secret_id)               # never leave a key behind for a room that was not created
            raise
        return self._public_room(room, key=key)

    def join(self, device_id: str, key: str, nickname: str) -> dict:
        nick, h, now = _clean(nickname, "a nickname", MAX_NICK), key_hash(key), self.now()
        with self.db.connect() as con:
            room = con.execute("SELECT id, epoch FROM rooms WHERE key_hash = ?", (h,)).fetchone()
            if not room:
                raise NotFound("That key does not match any room.")
            mine = con.execute("SELECT epoch FROM members WHERE room_id = ? AND device_id = ?", (room["id"], device_id)).fetchone()
            if mine:
                con.execute("UPDATE members SET epoch = ?, nickname = ?, last_seen = ? WHERE room_id = ? AND device_id = ?",
                            (room["epoch"], nick, now, room["id"], device_id))
            else:
                if con.execute("SELECT COUNT(*) AS n FROM members WHERE room_id = ? AND epoch = ?", (room["id"], room["epoch"])).fetchone()["n"] >= MAX_MEMBERS:
                    raise BadRequest(f"This room is full ({MAX_MEMBERS} devices).")
                con.execute("INSERT INTO members (room_id, device_id, nickname, role, epoch, joined_at, last_seen) VALUES (?, ?, ?, 'member', ?, ?, ?)",
                            (room["id"], device_id, nick, room["epoch"], now, now))
            self._bump(con, room["id"])
            return self._public_room(self._member(con, device_id, room["id"]))

    def rooms(self, device_id: str) -> list[dict]:
        now = self.now()
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT r.id, r.name, r.default_retention, r.rev, r.created_at, m.role AS my_role, m.nickname AS my_nick, "
                "(SELECT COUNT(*) FROM members x WHERE x.room_id = r.id AND x.epoch = r.epoch) AS member_count, "
                "(SELECT COUNT(*) FROM items i WHERE i.room_id = r.id AND i.deleted_at IS NULL AND i.expires_at > ?) AS item_count "
                "FROM rooms r JOIN members m ON m.room_id = r.id AND m.device_id = ? AND m.epoch = r.epoch ORDER BY r.created_at, r.id",
                (now, device_id)).fetchall()
        return [self._public_room(r, members=r["member_count"], items=r["item_count"]) for r in rows]

    def room(self, device_id: str, room_id: str) -> dict:
        now = self.now()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            members = con.execute("SELECT device_id, nickname, role, joined_at, last_seen FROM members WHERE room_id = ? AND epoch = ? ORDER BY joined_at, device_id",
                                  (room_id, r["epoch"])).fetchall()
        return self._public_room(r, members=[{"id": m["device_id"], "nickname": m["nickname"], "role": m["role"], "you": m["device_id"] == device_id,
                                              "online": now - m["last_seen"] <= 20} for m in members])

    def invite_key(self, device_id: str, room_id: str) -> str:
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
        return pretty_key(self.vault.get_secret(r["key_secret_id"])["key"])

    def rename_room(self, device_id: str, room_id: str, name: Optional[str] = None, default_retention: Any = None) -> dict:
        with self.db.connect() as con:
            self._member(con, device_id, room_id, owner=True)
            if name is not None:
                con.execute("UPDATE rooms SET name = ? WHERE id = ?", (_clean(name, "a room name", MAX_ROOM_NAME), room_id))
            if default_retention is not None:
                con.execute("UPDATE rooms SET default_retention = ? WHERE id = ?", (clamp_retention(default_retention), room_id))
            self._bump(con, room_id)
        return self.room(device_id, room_id)

    def set_nickname(self, device_id: str, room_id: str, nickname: str) -> dict:
        nick = _clean(nickname, "a nickname", MAX_NICK)
        with self.db.connect() as con:
            self._member(con, device_id, room_id)
            con.execute("UPDATE members SET nickname = ? WHERE room_id = ? AND device_id = ?", (nick, room_id, device_id))
            self._bump(con, room_id)
        return self.room(device_id, room_id)

    def reset_key(self, device_id: str, room_id: str) -> str:
        """A new key. Everyone who joined with the old one is out (their epoch no longer matches); only the owner stays."""
        key = new_key()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id, owner=True)
            epoch = r["epoch"] + 1
            con.execute("UPDATE rooms SET key_hash = ?, epoch = ? WHERE id = ?", (key_hash(key), epoch, room_id))
            con.execute("UPDATE members SET epoch = ? WHERE room_id = ? AND device_id = ?", (epoch, room_id, device_id))
            con.execute("DELETE FROM members WHERE room_id = ? AND epoch <> ?", (room_id, epoch))
            self.vault.update_secret(r["key_secret_id"], {"key": key, "room": room_id})
            self._bump(con, room_id)
        return key

    def remove_member(self, device_id: str, room_id: str, member_id: str) -> None:
        with self.db.connect() as con:
            self._member(con, device_id, room_id, owner=True)
            if member_id == device_id:
                raise BadRequest("The owner cannot be removed. Delete the room instead.")
            con.execute("DELETE FROM members WHERE room_id = ? AND device_id = ?", (room_id, member_id))
            self._bump(con, room_id)

    def leave(self, device_id: str, room_id: str) -> None:
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            if r["my_role"] == "owner":
                raise BadRequest("The owner cannot leave. Delete the room, or reset the key to remove everyone else.")
            con.execute("DELETE FROM members WHERE room_id = ? AND device_id = ?", (room_id, device_id))
            self._bump(con, room_id)

    def delete_room(self, device_id: str, room_id: str) -> None:
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id, owner=True)
            keys = [x["s3_key"] for x in con.execute("SELECT s3_key FROM items WHERE room_id = ? AND s3_key IS NOT NULL", (room_id,)).fetchall()]
            con.execute("DELETE FROM items WHERE room_id = ?", (room_id,))
            con.execute("DELETE FROM members WHERE room_id = ?", (room_id,))
            con.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        self.vault.delete_secret(r["key_secret_id"])
        self._erase_files(keys)

    # ---- items ----------------------------------------------------------------------------------------------
    @staticmethod
    def _item(row: dict, me: str) -> dict:
        return {"id": row["id"], "kind": row["kind"], "text": row["text"], "file_name": row["file_name"], "size": row["size"], "mime": row["mime"],
                "nickname": row["nickname"], "mine": row["device_id"] == me, "created_at": row["created_at"], "edited_at": row["edited_at"],
                "edited_by": row["edited_by"], "version": row["version"], "expires_at": row["expires_at"],
                "image": row["kind"] == "file" and row["mime"] in IMAGE_TYPES,
                "text_preview": row["kind"] == "file" and is_text_name(row["file_name"] or "") and (row["size"] or 0) <= TEXT_PREVIEW_MAX}

    def _live_item(self, con: Any, room_id: str, item_id: str) -> dict:
        row = con.execute("SELECT * FROM items WHERE id = ? AND room_id = ? AND deleted_at IS NULL AND expires_at > ?",
                          (item_id, room_id, self.now())).fetchone()
        if not row:
            raise NotFound("That item is gone (deleted or expired).")
        return row

    def items(self, device_id: str, room_id: str, since_rev: Any = None) -> dict:
        self.purge()
        now = self.now()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            if since_rev is not None and str(since_rev).lstrip("-").isdigit() and int(since_rev) == r["rev"]:
                return {"changed": False, "rev": r["rev"], "now": now}
            rows = con.execute("SELECT * FROM items WHERE room_id = ? AND deleted_at IS NULL AND expires_at > ? ORDER BY seq DESC LIMIT 500",
                               (room_id, now)).fetchall()
            used_room, _ = self._usage(con, room_id)
        return {"changed": True, "rev": r["rev"], "now": now, "items": [self._item(x, device_id) for x in reversed(rows)],
                "room": self._public_room(r), "usage": {"room_bytes": used_room, "room_quota": ROOM_QUOTA}}

    def add_text(self, device_id: str, room_id: str, text: Any, retention: Any = None) -> dict:
        body, now = _text(text), self.now()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            if con.execute("SELECT COUNT(*) AS n FROM items WHERE room_id = ? AND deleted_at IS NULL AND expires_at > ?", (room_id, now)).fetchone()["n"] >= MAX_ITEMS_PER_ROOM:
                raise BadRequest("This room has too many items. Delete some first.")
            seconds = clamp_retention(retention, r["default_retention"])
            rev, iid = self._bump(con, room_id), uuid.uuid4().hex
            con.execute("INSERT INTO items (id, room_id, seq, kind, text, device_id, nickname, created_at, version, expires_at) VALUES (?, ?, ?, 'text', ?, ?, ?, ?, 1, ?)",
                        (iid, room_id, rev, body, device_id, r["my_nick"], now, now + seconds))
            return self._item(con.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone(), device_id)

    def edit_text(self, device_id: str, room_id: str, item_id: str, text: Any, version: Any, restart_retention: Any = None) -> dict:
        body, now = _text(text), self.now()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            row = self._live_item(con, room_id, item_id)
            if row["kind"] != "text":
                raise BadRequest("Only text can be edited.")
            if int(version) != row["version"]:
                raise Conflict(f"{row['edited_by'] or row['nickname']} changed this while you were editing.", current=self._item(row, device_id))
            expires = row["expires_at"] if restart_retention in (None, "", False) else now + clamp_retention(restart_retention)
            con.execute("UPDATE items SET text = ?, version = version + 1, edited_at = ?, edited_by = ?, expires_at = ? WHERE id = ?",
                        (body, now, r["my_nick"], expires, item_id))
            self._bump(con, room_id)
            return self._item(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone(), device_id)

    def set_retention(self, device_id: str, room_id: str, item_id: str, seconds: Any) -> dict:
        now = self.now()
        with self.db.connect() as con:
            self._member(con, device_id, room_id)
            self._live_item(con, room_id, item_id)
            con.execute("UPDATE items SET expires_at = ? WHERE id = ?", (now + clamp_retention(seconds), item_id))
            self._bump(con, room_id)
            return self._item(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone(), device_id)

    def delete_item(self, device_id: str, room_id: str, item_id: str) -> dict:
        """Gone for everyone at once. The deleting device may undo for UNDO_SECONDS; after ERASE_AFTER the data is really erased."""
        now = self.now()
        with self.db.connect() as con:
            self._member(con, device_id, room_id)
            self._live_item(con, room_id, item_id)
            con.execute("UPDATE items SET deleted_at = ?, deleted_by = ? WHERE id = ?", (now, device_id, item_id))
            self._bump(con, room_id)
        return {"undo_seconds": UNDO_SECONDS}

    def undo_delete(self, device_id: str, room_id: str, item_id: str) -> dict:
        now = self.now()
        with self.db.connect() as con:
            self._member(con, device_id, room_id)
            row = con.execute("SELECT * FROM items WHERE id = ? AND room_id = ? AND deleted_at IS NOT NULL AND expires_at > ?", (item_id, room_id, now)).fetchone()
            if not row or row["deleted_by"] != device_id or now - row["deleted_at"] > UNDO_SECONDS:
                raise NotFound("It is too late to undo that.")
            con.execute("UPDATE items SET deleted_at = NULL, deleted_by = NULL WHERE id = ?", (item_id,))
            self._bump(con, room_id)
            return self._item(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone(), device_id)

    # ---- files and folders (DR2) -----------------------------------------------------------------------------------
    @staticmethod
    def _usage(con: Any, room_id: str) -> tuple[int, int]:
        """(bytes this room holds, bytes the whole tool holds): everything whose file has not been erased yet."""
        mine = con.execute("SELECT COALESCE(SUM(size), 0) AS n FROM items WHERE room_id = ? AND s3_key IS NOT NULL", (room_id,)).fetchone()["n"]
        total = con.execute("SELECT COALESCE(SUM(size), 0) AS n FROM items WHERE s3_key IS NOT NULL").fetchone()["n"]
        return int(mine), int(total)

    def upload_ticket(self, device_id: str, room_id: str) -> dict:
        """Called BEFORE the body of an upload is read: is this device in the room, and is there room left? Saves receiving 100 MB to refuse it."""
        self.purge()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            used_room, used_total = self._usage(con, room_id)
        free = min(ROOM_QUOTA - used_room, TOTAL_QUOTA - used_total, MAX_FILE)
        if ROOM_QUOTA - used_room <= 0:
            raise TooLarge(f"This room is full ({human_size(ROOM_QUOTA)}). Delete something, or wait for items to expire.")
        if TOTAL_QUOTA - used_total <= 0:
            raise TooLarge("Drop Rooms storage on this Toolbox is full. Ask the owner to free some space.")
        return {"max_bytes": free, "default_retention": r["default_retention"]}

    def add_file(self, device_id: str, room_id: str, name: Any, fileobj: Any, size: int, kind: str = "file", retention: Any = None) -> dict:
        if kind not in ("file", "folder"):
            raise BadRequest("Unknown upload type.")
        if size <= 0:
            raise BadRequest("That file is empty.")
        if size > MAX_FILE:
            raise TooLarge(f"That is {human_size(size)}. The limit is {human_size(MAX_FILE)} per file.")
        fname = clean_filename(name)
        if kind == "folder" and not fname.lower().endswith(".zip"):
            fname += ".zip"
        self.purge()
        now = self.now()
        with self.db.connect() as con:
            r = self._member(con, device_id, room_id)
            used_room, used_total = self._usage(con, room_id)
            if used_room + size > ROOM_QUOTA:
                raise TooLarge(f"This room has {human_size(max(0, ROOM_QUOTA - used_room))} left and this is {human_size(size)}. Delete something, or wait for items to expire.")
            if used_total + size > TOTAL_QUOTA:
                raise TooLarge("Drop Rooms storage on this Toolbox is full. Ask the owner to free some space.")
            if con.execute("SELECT COUNT(*) AS n FROM items WHERE room_id = ? AND deleted_at IS NULL AND expires_at > ?", (room_id, now)).fetchone()["n"] >= MAX_ITEMS_PER_ROOM:
                raise BadRequest("This room has too many items. Delete some first.")
            seconds = clamp_retention(retention, r["default_retention"])
        if self.files is None:
            raise BadRequest("File storage is not available.")
        fileobj.seek(0)
        head = fileobj.read(16)
        fileobj.seek(0)
        caption, mime = None, "application/octet-stream"
        if kind == "folder":
            caption, mime = f"{check_zip(fileobj)} files", "application/zip"
        else:
            mime = sniff_image(head) or "application/octet-stream"          # the real type, never the browser's claim
        iid = uuid.uuid4().hex
        key = f"drop-rooms/{room_id}/{iid}"
        self.files.put(key, fileobj, mime)
        try:
            with self.db.connect() as con:
                r = self._member(con, device_id, room_id)                   # still a member after a long upload?
                rev = self._bump(con, room_id)
                con.execute("INSERT INTO items (id, room_id, seq, kind, text, file_name, size, mime, s3_key, device_id, nickname, created_at, version, expires_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                            (iid, room_id, rev, kind, caption, fname, size, mime, key, device_id, r["my_nick"], now, now + seconds))
                row = con.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone()
        except Exception:
            self.files.delete(key)                                          # never leave bytes behind for an item that was not recorded
            raise
        return self._item(row, device_id)

    def file_for_download(self, device_id: str, room_id: str, item_id: str, preview: bool = False) -> dict:
        with self.db.connect() as con:
            self._member(con, device_id, room_id)
            row = self._live_item(con, room_id, item_id)
        if row["kind"] not in ("file", "folder") or not row["s3_key"]:
            raise NotFound("That item has no file.")
        if preview and row["mime"] not in IMAGE_TYPES:
            raise NotFound("There is no preview for this file.")
        return {"key": row["s3_key"], "name": row["file_name"], "size": row["size"], "mime": row["mime"]}

    def text_preview(self, device_id: str, room_id: str, item_id: str) -> dict:
        info = self.file_for_download(device_id, room_id, item_id)
        if not is_text_name(info["name"] or "") or (info["size"] or 0) > TEXT_PREVIEW_MAX or info["mime"] == "application/zip":
            raise BadRequest("This file cannot be previewed as text. Download it instead.")
        data = self.files.head(info["key"], TEXT_PREVIEW_BYTES + 1)
        if b"\x00" in data:
            raise BadRequest("This file is not text. Download it instead.")
        return {"name": info["name"], "text": data[:TEXT_PREVIEW_BYTES].decode("utf-8", errors="replace"), "truncated": len(data) > TEXT_PREVIEW_BYTES}

    # ---- erasing ----------------------------------------------------------------------------------------------
    def _erase_files(self, keys: list) -> None:
        if self.files is not None:
            for k in keys:
                if k:
                    self.files.delete(k)

    def purge(self) -> int:
        """Really erase expired and deleted items (and forget idle devices). Cheap when there is nothing to do; correctness never
        depends on it, because every read already hides expired and deleted items."""
        now = self.now()
        with self.db.connect() as con:
            if not con.execute("SELECT 1 AS x FROM items WHERE expires_at <= ? OR (deleted_at IS NOT NULL AND deleted_at <= ?) LIMIT 1",
                               (now, now - ERASE_AFTER)).fetchone():
                rows = []
            else:
                rows = con.execute("SELECT id, s3_key FROM items WHERE expires_at <= ? OR (deleted_at IS NOT NULL AND deleted_at <= ?) LIMIT 500",
                                   (now, now - ERASE_AFTER)).fetchall()
                for x in rows:
                    con.execute("DELETE FROM items WHERE id = ?", (x["id"],))
            idle = now - DEVICE_IDLE_DAYS * 86400
            for d in con.execute("SELECT id FROM devices WHERE last_seen < ? LIMIT 200", (idle,)).fetchall():
                con.execute("DELETE FROM members WHERE device_id = ?", (d["id"],))
                con.execute("DELETE FROM devices WHERE id = ?", (d["id"],))
        self._erase_files([x["s3_key"] for x in rows])
        return len(rows)


def meta() -> dict:
    return {"presets": list(PRESETS), "default_retention": DEFAULT_RETENTION, "max_retention": MAX_RETENTION, "undo_seconds": UNDO_SECONDS,
            "limits": {"text": MAX_TEXT, "room_name": MAX_ROOM_NAME, "nickname": MAX_NICK, "members": MAX_MEMBERS, "file": MAX_FILE, "room_quota": ROOM_QUOTA,
                       "zip_entries": MAX_ZIP_ENTRIES}}
