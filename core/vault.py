"""
core/vault.py

A generic, encrypted secret store shared by any tool in the Toolbox — not DB-specific.

Storage (roadmap B7): rows in Toolbox's Postgres, schema `vault` (core/state/sqlstore.py), dataset blobs in S3
storage (`vault/<id>/<id>.blob`, core/state/filecache.py; the local `blobs/` folder is only a cache of ENCRYPTED
chunks). Standalone (no TOOLBOX_DATABASE_URL / S3) it is the original SQLite file + local blobs. The old
/app/data/vault/vault.db is copied into Postgres once on first start (sqlstore's migration) and old blob files
are uploaded at the same time; both stay on the `vault_data` volume as a backup.

The encryption key (Fernet) comes from, in order:
  1. TOOLBOX_VAULT_KEY (env — compose passes it from the git-ignored .env),
  2. TOOLBOX_VAULT_KEY_FILE (a mounted secret file),
  3. the legacy key file /app/data/vault/vault.key on the data volume (read, never written while 1/2 exist;
     created there only if nothing else exists, as before). `key_info()` / `/api/state/health` say which.
A fingerprint of the key (a Fernet token of a fixed string) is stored in `vault._meta`, so starting with the WRONG
key fails loudly ("VaultKeyMismatch") instead of silently failing every decrypt later.

Security posture, explicitly chosen by the owner: NO vault master password. Secrets are protected at rest (a
database dump, a stray backup, an accidental `git add -A` of a data folder) but NOT from someone with access to
the running container — the toolbox's single-user/local-machine trust model. If the threat model ever changes
(multi-user, remote access), this needs a real redesign (a master password, a KMS, …), not a silent patch.

Scoped access (roadmap B7): plugin code reaches secrets through `scoped("<plugin name>")`, which only allows the
kinds its manifest declares under `vault:` (read / write / datasets — docs/architecture/plugin-manifest.md).
The same scopes guard the HTTP read API in vault/server.py (`/api/v1/...`, per-plugin HMAC token from
`plugin_token()`) for runtimes that run outside this process (phase C). The module-level functions below are the
UNSCOPED store, for the Vault tool itself and trusted host code (orchestrator CLI) only.

`kind` is a free-form tag ("postgres_connection", "ssh_server", …). list_secrets() never returns decrypted data.
get_secret() decrypts and should only be called at the moment a tool is about to use the secret.

Two storage shapes share one table, distinguished by whether `blob_path` is set:
  - a CREDENTIAL: small, whole-value Fernet encryption of a JSON blob into `ciphertext`; `blob_path` NULL.
  - a DATASET (cross-tool data hand-off, e.g. "save a query result, feed it into DataDiff Pro"): `ciphertext`
    holds small metadata (format/columns/row_count); the bulk data is encrypted in fixed-size chunks into a blob,
    so memory stays bounded by CHUNK_SIZE whatever the dataset's size.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken

from core.state.filecache import FileCache
from core.state.sqlstore import SqlStore

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "vault"
DB_PATH = DATA_DIR / "vault.db"          # standalone store / one-time migration source
KEY_PATH = DATA_DIR / "vault.key"        # legacy key location (see module docstring)
BLOBS_DIR = DATA_DIR / "blobs"           # local cache of encrypted dataset blobs

# Bounds memory use during dataset encrypt/decrypt to this size regardless of total dataset size.
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB
_KEY_CHECK_PLAIN = b"toolbox-vault-key-check"
BACKUP_FORMAT = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    blob_path TEXT
);
CREATE TABLE IF NOT EXISTS _vault_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

STORE = SqlStore("vault", sqlite_path=DB_PATH, ddl=_SCHEMA)
BLOBS = FileCache("vault", BLOBS_DIR, budget_mb=int(os.environ.get("VAULT_BLOB_CACHE_MB", "1024")))
_connect = STORE.connect
_ready = False
_ready_lock = threading.Lock()


class SecretNotFound(KeyError):
    pass


class VaultKeyMismatch(RuntimeError):
    pass


class ScopeError(PermissionError):
    """A plugin asked for a secret kind (or dataset access) its manifest doesn't grant."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------------------------------- key

_cached_key: bytes | None = None
_key_source: str = ""


def _load_or_create_key() -> bytes:
    """Cached for the process lifetime (the key never changes while running)."""
    global _cached_key, _key_source
    if _cached_key is not None:
        return _cached_key
    env = (os.environ.get("TOOLBOX_VAULT_KEY") or "").strip()
    key_file = (os.environ.get("TOOLBOX_VAULT_KEY_FILE") or "").strip()
    if env:
        key, source = env.encode(), "env TOOLBOX_VAULT_KEY"
    elif key_file:
        key, source = Path(key_file).read_bytes().strip(), f"file {key_file}"
    elif KEY_PATH.exists():
        key, source = KEY_PATH.read_bytes().strip(), "legacy key file on the data volume"
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
        KEY_PATH.chmod(0o600)
        source = "legacy key file on the data volume (newly created)"
    Fernet(key)  # raises ValueError on a malformed key — better here than at the first decrypt
    _cached_key, _key_source = key, source
    return key


def invalidate_key_cache() -> None:
    """Forget the cached key (tests; a changed TOOLBOX_VAULT_KEY_FILE)."""
    global _cached_key, _ready
    _cached_key = None
    _ready = False


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def key_info() -> dict[str, Any]:
    _ready_store()
    return {"source": _key_source, "on_data_volume": _key_source.startswith("legacy"),
            "fingerprint": hashlib.sha256(_load_or_create_key()).hexdigest()[:12]}


# ---------------------------------------------------------------------------------------------------- setup

def _ready_store() -> None:
    """Create tables (+ one-time SQLite → Postgres copy), check the key against the stored fingerprint, and give
    pre-B7 local blobs a home in S3 storage. Runs once per process."""
    global _ready
    if _ready:
        return
    with _ready_lock:
        if _ready:
            return
        STORE.init()
        fernet = _fernet()
        with _connect() as con:
            row = con.execute("SELECT value FROM _vault_meta WHERE key = 'key_check'").fetchone()
            if row is None:
                # first start with a fingerprint: an existing secret (e.g. just migrated) must decrypt with this key
                sample = con.execute("SELECT ciphertext FROM secrets LIMIT 1").fetchone()
                if sample is not None:
                    try:
                        fernet.decrypt(bytes(sample["ciphertext"]))
                    except InvalidToken:
                        raise VaultKeyMismatch(
                            f"The Vault key ({_key_source}) cannot decrypt the existing secrets. Set "
                            "TOOLBOX_VAULT_KEY in .env to the original key (/app/data/vault/vault.key).") from None
                con.execute("INSERT INTO _vault_meta (key, value) VALUES ('key_check', ?)",
                            (fernet.encrypt(_KEY_CHECK_PLAIN).decode(),))
            else:
                try:
                    fernet.decrypt(row["value"].encode())
                except InvalidToken:
                    raise VaultKeyMismatch(
                        f"The Vault key ({_key_source}) is not the key the stored secrets were encrypted with. "
                        "Set TOOLBOX_VAULT_KEY in .env to the original key (the old one is in "
                        "/app/data/vault/vault.key or in a Vault backup zip).") from None
            blobs = [r["blob_path"] for r in con.execute("SELECT blob_path FROM secrets WHERE blob_path IS NOT NULL")]
        if BLOBS.remote:
            for name in blobs:  # fetch() uploads a local file that storage doesn't have yet (pre-B7 blobs)
                if (BLOBS_DIR / name).exists():
                    try:
                        BLOBS.fetch(name.split(".", 1)[0], name)
                    except Exception:  # noqa: BLE001 - retried on next start / on first load
                        logger.exception("vault: could not upload legacy blob %s", name)
        _ready = True


# ---------------------------------------------------------------------------------------------------- chunked blobs

def _encrypt_stream(src: BinaryIO, dst: BinaryIO, fernet: Fernet) -> None:
    while True:
        chunk = src.read(CHUNK_SIZE)
        if not chunk:
            break
        ciphertext = fernet.encrypt(chunk)
        dst.write(len(ciphertext).to_bytes(4, "big"))
        dst.write(ciphertext)


def _decrypt_stream(src: BinaryIO, dest: BinaryIO, fernet: Fernet) -> None:
    while True:
        length_bytes = src.read(4)
        if not length_bytes:
            break
        dest.write(fernet.decrypt(src.read(int.from_bytes(length_bytes, "big"))))


def _encrypt_file_chunked(source_path: Path, dest_path: Path) -> None:
    with source_path.open("rb") as src, dest_path.open("wb") as dst:
        _encrypt_stream(src, dst, _fernet())


def _decrypt_file_chunked(source_path: Path, dest: BinaryIO) -> None:
    with source_path.open("rb") as src:
        _decrypt_stream(src, dest, _fernet())


def _blob_local(secret_id: str, blob_name: str) -> Path:
    path = BLOBS.fetch(secret_id, blob_name)
    if path is None:
        raise SecretNotFound(f"{secret_id} (dataset file missing)")
    return path


# ---------------------------------------------------------------------------------------------------- the store (unscoped)

def save_secret(name: str, kind: str, data: dict[str, Any]) -> str:
    """Encrypt *data* and store it under *name*/*kind*. Returns the new secret's id."""
    _ready_store()
    ciphertext = _fernet().encrypt(json.dumps(data).encode("utf-8"))
    secret_id, now = uuid.uuid4().hex, _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO secrets (id, name, kind, created_at, updated_at, ciphertext, blob_path) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (secret_id, name, kind, now, now, ciphertext),
        )
    return secret_id


def update_secret(secret_id: str, data: dict[str, Any]) -> None:
    """Replace the encrypted data of an existing CREDENTIAL in place, keeping its id (so every tool that stored the
    id keeps working). Used to PIN an SSH server's host key after the user confirmed it. Never for datasets."""
    _ready_store()
    ciphertext = _fernet().encrypt(json.dumps(data).encode("utf-8"))
    with _connect() as con:
        cur = con.execute(
            "UPDATE secrets SET ciphertext = ?, updated_at = ? WHERE id = ? AND blob_path IS NULL",
            (ciphertext, _now(), secret_id),
        )
        if cur.rowcount == 0:
            raise SecretNotFound(secret_id)


def save_dataset(name: str, kind: str, meta: dict[str, Any], source_path: Path) -> str:
    """Save a dataset: *meta* (small) is encrypted whole; *source_path*'s bytes are encrypted in CHUNK_SIZE pieces
    into a blob (memory bounded by CHUNK_SIZE) and stored. Does not delete source_path (the caller's temp file)."""
    _ready_store()
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    secret_id = uuid.uuid4().hex
    blob_name = f"{secret_id}.blob"
    _encrypt_file_chunked(source_path, BLOBS_DIR / blob_name)
    try:
        BLOBS.publish(secret_id, BLOBS_DIR / blob_name)
    except Exception:
        BLOBS.remove(secret_id, blob_name)
        raise
    ciphertext = _fernet().encrypt(json.dumps(meta).encode("utf-8"))
    now = _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO secrets (id, name, kind, created_at, updated_at, ciphertext, blob_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (secret_id, name, kind, now, now, ciphertext, blob_name),
        )
    return secret_id


def _row(secret_id: str) -> Any:
    _ready_store()
    with _connect() as con:
        row = con.execute("SELECT id, kind, ciphertext, blob_path FROM secrets WHERE id = ?", (secret_id,)).fetchone()
    if row is None:
        raise SecretNotFound(secret_id)
    return row


def load_dataset_file(secret_id: str) -> Path:
    """Decrypt a dataset's bulk data to a fresh temp file (with the extension of its saved format) and return its
    path. Streams chunk by chunk. The caller reads it and deletes it when done."""
    row = _row(secret_id)
    if row["blob_path"] is None:
        raise SecretNotFound(secret_id)
    meta = json.loads(_fernet().decrypt(bytes(row["ciphertext"])).decode("utf-8"))
    blob = _blob_local(secret_id, row["blob_path"])
    fd, tmp_path = tempfile.mkstemp(suffix=f".{meta.get('format', 'bin')}", prefix="vault_dataset_")
    with open(fd, "wb") as dest:
        _decrypt_file_chunked(blob, dest)
    return Path(tmp_path)


class DatasetTooLargeForPreview(ValueError):
    """Raised by preview_dataset_as_csv() when a dataset has more rows than the caller's cap allows."""

    def __init__(self, row_count: int, max_rows: int):
        super().__init__(
            f"This dataset has {row_count:,} rows — over the {max_rows:,}-row "
            f"cap for loading into a browser. Use the orchestrator's "
            f"--left-vault-dataset/--right-vault-dataset instead for anything this size."
        )
        self.row_count = row_count


def preview_dataset_as_csv(secret_id: str, max_rows: int) -> tuple[str, int]:
    """For DataDiff Pro's "Load from Vault" button: (csv_text, row_count) IF the dataset has at most max_rows rows,
    DatasetTooLargeForPreview otherwise. The row count is checked before any row data is read."""
    import csv
    import io

    import duckdb

    from core.file_source import build_read_expr

    tmp_path = load_dataset_file(secret_id)
    try:
        con = duckdb.connect(":memory:")
        try:
            source = build_read_expr(str(tmp_path))
            row_count = con.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
            if row_count > max_rows:
                raise DatasetTooLargeForPreview(row_count, max_rows)
            result = con.execute(f"SELECT * FROM {source}")
            columns = [d[0] for d in result.description]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            writer.writerows(result.fetchall())
            return buf.getvalue(), row_count
        finally:
            con.close()
    finally:
        tmp_path.unlink(missing_ok=True)


def list_secrets(kind: Optional[str] = None) -> list[dict[str, Any]]:
    """Metadata only — id/name/kind/timestamps/has_data. Never decrypted data."""
    _ready_store()
    with _connect() as con:
        if kind:
            rows = con.execute(
                "SELECT id, name, kind, created_at, updated_at, blob_path FROM secrets WHERE kind = ? ORDER BY name",
                (kind,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, name, kind, created_at, updated_at, blob_path FROM secrets ORDER BY name"
            ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "kind": r["kind"], "created_at": r["created_at"],
         "updated_at": r["updated_at"], "has_data": r["blob_path"] is not None}
        for r in rows
    ]


def get_secret(secret_id: str) -> dict[str, Any]:
    """Decrypt and return the real data for *secret_id* (a credential's data, or a dataset's small metadata — see
    load_dataset_file() for the bulk). Only call this when a tool is about to use the secret."""
    return json.loads(_fernet().decrypt(bytes(_row(secret_id)["ciphertext"])).decode("utf-8"))


def secret_kind(secret_id: str) -> str:
    return _row(secret_id)["kind"]


def find_id_by_name(name: str, kind: Optional[str] = None) -> str:
    """Resolve a name to an id (first by id on a genuine name collision). Raises SecretNotFound."""
    _ready_store()
    with _connect() as con:
        if kind:
            row = con.execute("SELECT id FROM secrets WHERE name = ? AND kind = ? ORDER BY id LIMIT 1",
                              (name, kind)).fetchone()
        else:
            row = con.execute("SELECT id FROM secrets WHERE name = ? ORDER BY id LIMIT 1", (name,)).fetchone()
    if row is None:
        raise SecretNotFound(name)
    return row["id"]


def get_secret_by_name(name: str, kind: Optional[str] = None) -> dict[str, Any]:
    return get_secret(find_id_by_name(name, kind))


def load_dataset_file_by_name(name: str, kind: Optional[str] = None) -> Path:
    return load_dataset_file(find_id_by_name(name, kind))


def delete_secret(secret_id: str) -> None:
    _ready_store()
    with _connect() as con:
        con.execute("DELETE FROM secrets WHERE id = ?", (secret_id,))
    BLOBS.remove_all(secret_id)


def clear_all() -> None:
    """Delete every secret/dataset and every blob. The key stays — without rows the old ciphertext is gone anyway."""
    _ready_store()
    with _connect() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM secrets WHERE blob_path IS NOT NULL")]
        con.execute("DELETE FROM secrets")
    for sid in ids:
        BLOBS.remove_all(sid)
    shutil.rmtree(BLOBS_DIR, ignore_errors=True)


def health() -> dict[str, Any]:
    info = key_info()
    with _connect() as con:
        n = con.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
    out = {"secrets": n, "key_source": info["source"], "storage": STORE.backend}
    if info["on_data_volume"]:
        out["warning"] = "the Vault key is on the data volume — move it to TOOLBOX_VAULT_KEY in .env"
    return out


# ---------------------------------------------------------------------------------------------------- backup / restore

def export_backup(dest_path: Path) -> None:
    """One zip with every row (ciphertext as stored), the key needed to read them, and every dataset blob.
    Written straight to disk (blobs can be large). Format 2; import_backup() also reads the pre-B7 format 1
    (vault.db + vault.key + blobs/)."""
    _ready_store()
    with _connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, name, kind, created_at, updated_at, ciphertext, blob_path FROM secrets ORDER BY id")]
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            r["ciphertext"] = base64.b64encode(bytes(r["ciphertext"])).decode()
            if r["blob_path"]:
                zf.write(_blob_local(r["id"], r["blob_path"]), f"blobs/{r['blob_path']}")
        zf.writestr("vault.json", json.dumps({"format": BACKUP_FORMAT, "created_at": _now(), "secrets": rows}))
        zf.writestr("vault.key", _load_or_create_key())


def _backup_rows(zf: zipfile.ZipFile, workdir: Path) -> list[dict[str, Any]]:
    names = zf.namelist()
    if "vault.json" in names:
        rows = json.loads(zf.read("vault.json"))["secrets"]
        for r in rows:
            r["ciphertext"] = base64.b64decode(r["ciphertext"])
        return rows
    if "vault.db" in names:  # format 1 (before B7): a SQLite file
        zf.extract("vault.db", workdir)
        con = sqlite3.connect(workdir / "vault.db")
        try:
            return [{"id": r[0], "name": r[1], "kind": r[2], "created_at": r[3], "updated_at": r[4],
                     "ciphertext": bytes(r[5]), "blob_path": r[6]} for r in con.execute(
                "SELECT id, name, kind, created_at, updated_at, ciphertext, blob_path FROM secrets")]
        finally:
            con.close()
    raise ValueError("This doesn't look like a Vault backup — missing vault.json/vault.db.")


def import_backup(zip_path: Path) -> dict[str, int]:
    """Replace the ENTIRE vault with a backup. Secrets are re-encrypted with THIS vault's key when the backup was
    made with another one (the key now comes from the environment, so a restore can't swap keys). Every secret is
    decrypted first: a damaged backup is refused before anything is replaced."""
    _ready_store()
    current = _fernet()
    with tempfile.TemporaryDirectory(prefix="vault_restore_") as tmp, zipfile.ZipFile(zip_path) as zf:
        workdir = Path(tmp)
        if "vault.key" not in zf.namelist():
            raise ValueError("This doesn't look like a Vault backup — missing vault.key.")
        old = Fernet(zf.read("vault.key").strip())
        same_key = zf.read("vault.key").strip() == _load_or_create_key()
        rows = _backup_rows(zf, workdir)
        staged: list[tuple[str, Path]] = []
        for r in rows:
            try:
                plain = old.decrypt(r["ciphertext"])
            except InvalidToken:
                raise ValueError(f"Secret {r['name']!r} in this backup can't be decrypted with its key.") from None
            if not same_key:
                r["ciphertext"] = current.encrypt(plain)
            if r["blob_path"]:
                member = f"blobs/{r['blob_path']}"
                if member not in zf.namelist():
                    raise ValueError(f"Dataset {r['name']!r} is missing its data file in this backup.")
                out = workdir / r["blob_path"]
                with zf.open(member) as src, out.open("wb") as dst:
                    if same_key:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    else:  # decrypt chunk by chunk with the old key, encrypt with the current one
                        with tempfile.TemporaryFile() as plain_f:
                            _decrypt_stream(src, plain_f, old)
                            plain_f.seek(0)
                            _encrypt_stream(plain_f, dst, current)
                staged.append((r["id"], out))
        clear_all()
        BLOBS_DIR.mkdir(parents=True, exist_ok=True)
        for sid, path in staged:
            final = BLOBS_DIR / path.name
            shutil.move(str(path), final)
            BLOBS.publish(sid, final)
        with _connect() as con:
            for r in rows:
                con.execute(
                    "INSERT INTO secrets (id, name, kind, created_at, updated_at, ciphertext, blob_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r["id"], r["name"], r["kind"], r["created_at"], r["updated_at"], r["ciphertext"], r["blob_path"]),
                )
    return {"secrets": len(rows), "datasets": len(staged), "re_encrypted": int(not same_key)}


# ---------------------------------------------------------------------------------------------------- scoped access

class Scope:
    """What one plugin may do: decrypt `read` kinds, create/update `write` kinds, and datasets
    ('none' | 'read' = load any dataset | 'write' = also save them)."""

    def __init__(self, name: str, read: Iterable[str] = (), write: Iterable[str] = (), datasets: str = "none",
                 data: str = "none"):
        if datasets not in ("none", "read", "write") or data not in ("none", "read", "write"):
            raise ValueError("datasets / data must be none | read | write")
        self.name, self.read, self.write, self.datasets = name, frozenset(read) | frozenset(write), frozenset(write), datasets
        self.data = data  # Vault Data — lake tables (roadmap L1, enforced by core.lake.scoped)

    def as_dict(self) -> dict[str, Any]:
        return {"plugin": self.name, "read": sorted(self.read), "write": sorted(self.write), "datasets": self.datasets,
                "data": self.data}


_scope_cache: dict[str, Scope] = {}


def scope_for(plugin: str) -> Scope:
    """The scope a plugin's manifest declares (`vault:`); a plugin without one gets no access."""
    if plugin not in _scope_cache:
        from core_plugins import discover

        repo = Path(__file__).resolve().parent.parent
        m = discover(repo).plugins.get(plugin)
        v = m.vault if m is not None else None
        _scope_cache[plugin] = Scope(plugin, v.read, v.write, v.datasets, v.data) if v else Scope(plugin)
    return _scope_cache[plugin]


class ScopedVault:
    """The Vault as one plugin sees it. Every call checks the plugin's scope; a refusal raises ScopeError (and a
    secret of another kind looks like a missing one in list results — it is simply not listed)."""

    SecretNotFound = SecretNotFound  # so callers can keep `except vault.SecretNotFound`
    ScopeError = ScopeError

    def __init__(self, scope: Scope):
        self.scope = scope

    def _deny(self, what: str) -> ScopeError:
        return ScopeError(f"plugin '{self.scope.name}' may not {what} (add it to `vault:` in its manifest.yaml)")

    def _need_read(self, kind: str) -> None:
        if kind not in self.scope.read:
            raise self._deny(f"read Vault secrets of kind '{kind}'")

    def list_secrets(self, kind: str) -> list[dict[str, Any]]:
        self._need_read(kind)
        return list_secrets(kind)

    def get_secret(self, secret_id: str) -> dict[str, Any]:
        row = _row(secret_id)
        if row["blob_path"] is not None:
            raise self._deny("read datasets as credentials")
        self._need_read(row["kind"])
        return json.loads(_fernet().decrypt(bytes(row["ciphertext"])).decode("utf-8"))

    def get_secret_by_name(self, name: str, kind: str) -> dict[str, Any]:
        self._need_read(kind)
        return get_secret(find_id_by_name(name, kind))

    def save_secret(self, name: str, kind: str, data: dict[str, Any]) -> str:
        if kind not in self.scope.write:
            raise self._deny(f"save Vault secrets of kind '{kind}'")
        return save_secret(name, kind, data)

    def update_secret(self, secret_id: str, data: dict[str, Any]) -> None:
        kind = _row(secret_id)["kind"]
        if kind not in self.scope.write:
            raise self._deny(f"update Vault secrets of kind '{kind}'")
        update_secret(secret_id, data)

    def load_dataset_file(self, secret_id: str) -> Path:
        if self.scope.datasets == "none":
            raise self._deny("load datasets")
        return load_dataset_file(secret_id)

    def load_dataset_file_by_name(self, name: str, kind: Optional[str] = None) -> Path:
        if self.scope.datasets == "none":
            raise self._deny("load datasets")
        return load_dataset_file_by_name(name, kind)

    def save_dataset(self, name: str, kind: str, meta: dict[str, Any], source_path: Path) -> str:
        if self.scope.datasets != "write":
            raise self._deny("save datasets")
        return save_dataset(name, kind, meta, source_path)


def scoped(plugin: str) -> ScopedVault:
    """The only way plugin code should reach secrets: `vault.scoped("data-syncer").get_secret(id)`."""
    return ScopedVault(scope_for(plugin))


def plugin_token(plugin: str) -> str:
    """Bearer token for the HTTP scoped API (vault/server.py /api/v1). Derived from the Vault key, so nothing is
    stored and a key change revokes every token. Print one: `python -m core.vault token <plugin>`."""
    return hmac.new(_load_or_create_key(), f"toolbox-vault-plugin:{plugin}".encode(), hashlib.sha256).hexdigest()


def verify_token(plugin: str, token: str) -> bool:
    return bool(plugin and token) and hmac.compare_digest(plugin_token(plugin), token)


if __name__ == "__main__":  # python -m core.vault token <plugin> | key-info
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "token":
        print(plugin_token(sys.argv[2]))
    elif len(sys.argv) == 2 and sys.argv[1] == "key-info":
        print(json.dumps(key_info(), indent=2))
    else:
        print("usage: python -m core.vault token <plugin> | key-info", file=sys.stderr)
        sys.exit(2)
