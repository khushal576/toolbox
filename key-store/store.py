"""
Key Store: the entries (roadmap KS2). Pure logic: it is handed a *scoped* Vault (`vault_store.scoped("key-store")`), so a
test can give it a real, temporary one. Nothing here touches the network, the disk or process memory.

How an entry is stored (docs: key-store/CLAUDE.md):
  * Vault `kind`  = "key_store"  (its own kind: never mixes with database connections, SSH logins or datasets);
  * Vault `name`  = "ks-<random>"  — the Vault's name column is NOT encrypted, so the real name is kept inside;
  * everything else, including the name, value, tags and note, is in the Fernet-encrypted JSON `data`.
Values leave this module only through get() (edit / reveal) and copy() (clipboard). Lists never contain a value.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

KIND = "key_store"
SCHEMA = 1
TRASH_DAYS = 30

# key -> (label, icon). The page gets this list from GET meta, so adding a type here is the only change needed.
TYPES: dict[str, tuple[str, str]] = {
    "password": ("Password", "🔑"),
    "api_key": ("API key", "🗝️"),
    "token": ("Token / secret", "🎫"),
    "connection_string": ("Connection string", "🔌"),
    "url": ("URL", "🌐"),
    "host": ("Host / server", "🖥️"),
    "ssh_key": ("SSH / private key", "🔐"),
    "note": ("Note", "📝"),
    "other": ("Other", "📦"),
}
ENVIRONMENTS = ("prod", "non-prod")

MAX_NAME, MAX_VALUE, MAX_NOTE, MAX_TAGS, MAX_TAG = 120, 20000, 2000, 20, 40


class KeyStoreError(Exception):
    status = 400


class Invalid(KeyStoreError):
    status = 400


class Missing(KeyStoreError):
    status = 404


class Conflict(KeyStoreError):
    status = 409


# ------------------------------------------------------------------------------------------------ cleaning input

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _name(v: Any) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if not s:
        raise Invalid("Give the entry a name.")
    if len(s) > MAX_NAME:
        raise Invalid(f"The name is too long (maximum {MAX_NAME} characters).")
    if _CONTROL.search(s):
        raise Invalid("The name contains characters that are not allowed.")
    return s


def _value(v: Any) -> str:
    s = "" if v is None else str(v)
    if not s.strip():
        raise Invalid("The value is empty.")
    if len(s) > MAX_VALUE:
        raise Invalid(f"The value is too long (maximum {MAX_VALUE} characters).")
    if "\x00" in s:
        raise Invalid("The value contains a null character, which cannot be stored.")
    return s


def _type(v: Any) -> str:
    s = str(v or "password")
    if s not in TYPES:
        raise Invalid("Unknown type: " + s)
    return s


def _env(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s not in ENVIRONMENTS and s != "":
        raise Invalid("Environment must be prod, non-prod or empty.")
    return s


def _note(v: Any) -> str:
    s = "" if v is None else str(v)
    if len(s) > MAX_NOTE:
        raise Invalid(f"The note is too long (maximum {MAX_NOTE} characters).")
    return s


def _tags(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, (list, tuple)):
        raise Invalid("Tags must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for t in v:
        s = re.sub(r"\s+", " ", str(t).replace(",", " ")).strip()
        if not s:
            continue
        if len(s) > MAX_TAG:
            raise Invalid(f"A tag is too long (maximum {MAX_TAG} characters).")
        if s.casefold() in seen:
            continue
        seen.add(s.casefold())
        out.append(s)
    if len(out) > MAX_TAGS:
        raise Invalid(f"Too many tags (maximum {MAX_TAGS}).")
    return out


# ------------------------------------------------------------------------------------------------ safe previews
# A list row may show a value only when it is clearly not a secret. Everything else stays masked until the owner presses
# the eye or Copy. (A URL can hide a password in its user-info, query string or path: Slack/Discord webhooks do.)

_TOKENISH = re.compile(r"[A-Za-z0-9_\-]{20,}")


def safe_preview(type_: str, value: str) -> Optional[str]:
    if "\n" in value or len(value) > 120:
        return None
    if type_ == "host":
        return None if re.search(r"[@=\s]", value) else value
    if type_ == "url":
        try:
            u = urlsplit(value)
        except ValueError:
            return None
        if u.scheme not in ("http", "https", "ftp", "sftp", "ssh") or not u.hostname:
            return None
        if u.username or u.password or u.query or u.fragment:
            return None
        if any(_TOKENISH.fullmatch(seg) for seg in u.path.split("/") if seg):
            return None
        return value
    return None


# ------------------------------------------------------------------------------------------------ the store

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class KeyStore:
    def __init__(self, vault: Any, now: Optional[Callable[[], datetime]] = None):
        self.vault = vault
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ---- reading ---------------------------------------------------------------------------------------------
    def _rows(self) -> list[tuple[dict, dict]]:
        rows = []
        for meta in self.vault.list_secrets(KIND):
            try:
                data = self.vault.get_secret(meta["id"])
            except KeyError:                       # deleted between the list and the read
                continue
            if isinstance(data, dict) and data.get("name") and "value" in data:
                rows.append((meta, data))
        return rows

    def _one(self, secret_id: str) -> tuple[dict, dict]:
        for meta, data in self._rows():
            if meta["id"] == secret_id:
                return meta, data
        raise Missing("No such entry.")

    def _public(self, meta: dict, data: dict) -> dict:
        trashed = _parse(data.get("trashed_at"))
        left = None
        if trashed:
            left = max(0, (trashed + timedelta(days=TRASH_DAYS) - self._now()).days)
        value = data.get("value", "")
        return {
            "id": meta["id"], "name": data["name"], "type": data.get("type", "other"), "tags": data.get("tags", []),
            "note": data.get("note", ""), "environment": data.get("environment", ""), "pinned": bool(data.get("pinned")),
            "created_at": meta.get("created_at"), "updated_at": meta.get("updated_at"), "last_used": data.get("last_used"),
            "trashed_at": data.get("trashed_at"), "days_left": left, "value_length": len(value),
            "preview": safe_preview(data.get("type", ""), value),
        }

    def get(self, secret_id: str) -> dict:
        """The entry WITH its value: for the edit form and the eye button only."""
        meta, data = self._one(secret_id)
        out = self._public(meta, data)
        out["value"] = data["value"]
        return out

    def search(self, q: str = "", type_: str = "", env: str = "", tag: str = "", in_values: bool = False,
               trash: bool = False, sort: str = "name") -> dict:
        """{"entries": [...], "counts": {...}}. Values are never in the result; `in_values` only lets the query MATCH
        inside them (decrypted here, never returned)."""
        self._purge_expired()
        rows = self._rows()
        active = [(m, d) for m, d in rows if not d.get("trashed_at")]
        counts = self._counts(active, len(rows) - len(active))
        pool = [(m, d) for m, d in rows if bool(d.get("trashed_at")) == bool(trash)]
        terms = [t for t in re.split(r"\s+", (q or "").casefold().strip()) if t]
        out = []
        for meta, data in pool:
            if type_ and data.get("type") != type_:
                continue
            if env == "unset" and data.get("environment"):
                continue
            if env in ENVIRONMENTS and data.get("environment") != env:
                continue
            if tag and tag.casefold() not in [t.casefold() for t in data.get("tags", [])]:
                continue
            score = self._score(data, terms, in_values)
            if score is None:
                continue
            out.append((score, meta, data))
        key = {"recent": lambda x: (not x[2].get("pinned"), -_ts(x[2].get("last_used") or x[1].get("updated_at"))),
               "new": lambda x: (not x[2].get("pinned"), -_ts(x[1].get("created_at")))}.get(
            sort, lambda x: (not x[2].get("pinned"), x[0], x[2]["name"].casefold()))
        out.sort(key=key)
        return {"entries": [self._public(m, d) for _, m, d in out], "counts": counts}

    @staticmethod
    def _score(data: dict, terms: list[str], in_values: bool) -> Optional[int]:
        if not terms:
            return 0
        name = data["name"].casefold()
        tags = [t.casefold() for t in data.get("tags", [])]
        label = TYPES.get(data.get("type", ""), ("", ""))[0].casefold()
        hay = " ".join([name, " ".join(tags), label, data.get("type", ""), data.get("note", "").casefold(),
                        data.get("environment", "")])
        value = data.get("value", "").casefold() if in_values else ""
        for t in terms:
            if t not in hay and (not in_values or t not in value):
                return None
        full = " ".join(terms)
        if name == full:
            return 0
        if name.startswith(full):
            return 1
        if all(t in name for t in terms):
            return 2
        if any(t in tags for t in terms):
            return 3
        return 4

    @staticmethod
    def _counts(active: list[tuple[dict, dict]], trashed: int) -> dict:
        types: dict[str, int] = {}
        envs = {"prod": 0, "non-prod": 0, "unset": 0}
        tags: dict[str, list] = {}
        for _, d in active:
            types[d.get("type", "other")] = types.get(d.get("type", "other"), 0) + 1
            envs[d.get("environment") or "unset"] += 1
            for t in d.get("tags", []):
                e = tags.setdefault(t.casefold(), [t, 0])
                e[1] += 1
        top = sorted(tags.values(), key=lambda x: (-x[1], x[0].casefold()))[:40]
        return {"total": len(active), "trash": trashed, "types": types, "environments": envs, "tags": top}

    # ---- writing ---------------------------------------------------------------------------------------------
    def _unique(self, name: str, exclude: Optional[str] = None) -> None:
        for meta, data in self._rows():
            if meta["id"] != exclude and not data.get("trashed_at") and data["name"].casefold() == name.casefold():
                raise Conflict(f"An entry named “{data['name']}” already exists.")

    def create(self, fields: dict) -> str:
        data = {
            "v": SCHEMA, "name": _name(fields.get("name")), "value": _value(fields.get("value")),
            "type": _type(fields.get("type")), "tags": _tags(fields.get("tags")), "note": _note(fields.get("note")),
            "environment": _env(fields.get("environment")), "pinned": bool(fields.get("pinned")),
            "last_used": None, "trashed_at": None,
        }
        self._unique(data["name"])
        return self.vault.save_secret("ks-" + uuid.uuid4().hex[:12], KIND, data)

    def update(self, secret_id: str, fields: dict) -> None:
        _, data = self._one(secret_id)
        if data.get("trashed_at"):
            raise Conflict("This entry is in the trash. Restore it first.")
        if "name" in fields:
            data["name"] = _name(fields["name"])
            self._unique(data["name"], exclude=secret_id)
        if "value" in fields and fields["value"] is not None:
            data["value"] = _value(fields["value"])
        if "type" in fields:
            data["type"] = _type(fields["type"])
        if "tags" in fields:
            data["tags"] = _tags(fields["tags"])
        if "note" in fields:
            data["note"] = _note(fields["note"])
        if "environment" in fields:
            data["environment"] = _env(fields["environment"])
        if "pinned" in fields:
            data["pinned"] = bool(fields["pinned"])
        self.vault.update_secret(secret_id, data)

    def copy(self, secret_id: str) -> str:
        """The value, for the clipboard. Remembers when it was last used (Recently used sort)."""
        _, data = self._one(secret_id)
        if data.get("trashed_at"):
            raise Conflict("This entry is in the trash. Restore it first.")
        data["last_used"] = _iso(self._now())
        self.vault.update_secret(secret_id, data)
        return data["value"]

    def duplicate(self, secret_id: str) -> str:
        _, data = self._one(secret_id)
        base = data["name"] + " (copy)"
        name, n = base, 2
        taken = {d["name"].casefold() for _, d in self._rows() if not d.get("trashed_at")}
        while name.casefold() in taken:
            name, n = f"{base} {n}", n + 1
        return self.create({**data, "name": name, "pinned": False})

    def trash(self, secret_id: str) -> None:
        _, data = self._one(secret_id)
        if not data.get("trashed_at"):
            data["trashed_at"] = _iso(self._now())
            data["pinned"] = False
            self.vault.update_secret(secret_id, data)

    def restore(self, secret_id: str) -> str:
        """Back from the trash. If the name was taken meanwhile, the restored entry gets “(restored)” instead of failing."""
        _, data = self._one(secret_id)
        if not data.get("trashed_at"):
            return data["name"]
        taken = {d["name"].casefold() for m, d in self._rows() if m["id"] != secret_id and not d.get("trashed_at")}
        name, n = data["name"], 2
        if name.casefold() in taken:
            base = data["name"] + " (restored)"
            name = base
            while name.casefold() in taken:
                name, n = f"{base} {n}", n + 1
        data["name"], data["trashed_at"] = name, None
        self.vault.update_secret(secret_id, data)
        return name

    def delete_forever(self, secret_id: str) -> None:
        _, data = self._one(secret_id)
        if not data.get("trashed_at"):
            raise Conflict("Move the entry to the trash first.")
        self.vault.delete_secret(secret_id)

    def empty_trash(self) -> int:
        n = 0
        for meta, data in self._rows():
            if data.get("trashed_at"):
                self.vault.delete_secret(meta["id"])
                n += 1
        return n

    def _purge_expired(self) -> None:
        limit = self._now() - timedelta(days=TRASH_DAYS)
        for meta, data in self._rows():
            when = _parse(data.get("trashed_at"))
            if when and when < limit:
                self.vault.delete_secret(meta["id"])


def _ts(s: Any) -> float:
    d = _parse(s)
    return d.timestamp() if d else 0.0


def meta() -> dict:
    return {"types": [{"key": k, "label": v[0], "icon": v[1]} for k, v in TYPES.items()], "trash_days": TRASH_DAYS,
            "limits": {"name": MAX_NAME, "value": MAX_VALUE, "note": MAX_NOTE, "tags": MAX_TAGS, "tag": MAX_TAG}}
