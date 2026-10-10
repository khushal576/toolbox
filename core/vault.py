"""
core/vault.py

A generic, encrypted secret store shared by any tool in the Toolbox —
not DB-specific. Storage: SQLite at /app/data/vault/vault.db, on the
`vault_data` Docker volume (see ../docker-compose.yml), following
schema-map/project_store.py's exact precedent (survive an image rebuild,
zero new infrastructure, stdlib sqlite3).

Security posture, explicitly chosen by the owner: NO vault master
password. The encryption key (vault.key, Fernet, restrictive 0600
permissions) lives on the same persistent volume as the encrypted data.
This protects secrets at rest (the DB file itself, a stray backup, an
accidental `git add -A`) but NOT from someone with access to the running
container — matching this toolbox's existing single-user/local-machine
trust model (same posture df-studio/CLAUDE.md documents for
custom_code's unsandboxed exec()). If the threat model ever changes
(multi-user, remote access), this needs a real redesign (a master
password, a KMS, etc.), not a silent patch.

`kind` is a free-form tag ("postgres_connection", "ssh_credential", or
whatever a future tool needs) — this module has no opinion on what
fields a given kind's JSON blob contains. list_secrets() never returns
decrypted data, only metadata — safe to render on a page. get_secret()
decrypts and should only ever be called at the moment a tool is actually
about to use the secret (e.g. connecting), never for display.

Two storage shapes share one table, distinguished by whether `blob_path`
is set:
  - A CREDENTIAL (the original shape): small, whole-value Fernet
    encryption of a JSON blob into `ciphertext`. `blob_path` stays NULL.
  - A DATASET (added for cross-tool data hand-off — e.g. "save a
    transformed Postgres query result, feed it into DataDiff Pro"):
    `ciphertext` holds only small metadata (format/columns/row_count);
    the actual bulk data is encrypted separately in fixed-size chunks
    into a file under blobs/, named by `blob_path`. This bounds memory
    to one chunk (CHUNK_SIZE) regardless of how large the dataset is —
    the whole reason this is a second code path instead of just stuffing
    bigger values through save_secret()/get_secret().
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Optional

from cryptography.fernet import Fernet

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "vault"
DB_PATH = DATA_DIR / "vault.db"
KEY_PATH = DATA_DIR / "vault.key"
BLOBS_DIR = DATA_DIR / "blobs"

# Bounds memory use during dataset encrypt/decrypt to this size regardless
# of total dataset size — the whole point of the chunked format below.
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB

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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_cached_key: bytes | None = None


def _load_or_create_key() -> bytes:
    # Cached after first load — every encrypt/decrypt call used to re-read
    # this file and rebuild a Fernet instance; the key never changes during
    # a process's lifetime, so there's nothing to gain by re-reading it.
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        _cached_key = KEY_PATH.read_bytes()
        return _cached_key
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    KEY_PATH.chmod(0o600)
    _cached_key = key
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def save_secret(name: str, kind: str, data: dict[str, Any]) -> str:
    """Encrypt *data* and store it under *name*/*kind*. Returns the new
    secret's id."""
    ciphertext = _fernet().encrypt(json.dumps(data).encode("utf-8"))
    secret_id = uuid.uuid4().hex
    now = _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO secrets (id, name, kind, created_at, updated_at, ciphertext, blob_path) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (secret_id, name, kind, now, now, ciphertext),
        )
    return secret_id


def _encrypt_file_chunked(source_path: Path, dest_path: Path) -> None:
    fernet = _fernet()
    with source_path.open("rb") as src, dest_path.open("wb") as dst:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            ciphertext = fernet.encrypt(chunk)
            dst.write(len(ciphertext).to_bytes(4, "big"))
            dst.write(ciphertext)


def _decrypt_file_chunked(source_path: Path, dest: BinaryIO) -> None:
    fernet = _fernet()
    with source_path.open("rb") as src:
        while True:
            length_bytes = src.read(4)
            if not length_bytes:
                break
            length = int.from_bytes(length_bytes, "big")
            ciphertext = src.read(length)
            dest.write(fernet.decrypt(ciphertext))


def save_dataset(name: str, kind: str, meta: dict[str, Any], source_path: Path) -> str:
    """Save a dataset: *meta* (format/columns/row_count — small) is
    encrypted the normal whole-value way; *source_path*'s actual bytes
    are encrypted separately in CHUNK_SIZE pieces so memory use during
    encryption is bounded by CHUNK_SIZE, not by the dataset's size.
    Returns the new secret's id. Does not delete source_path — the
    caller's temp file to clean up."""
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    secret_id = uuid.uuid4().hex
    blob_name = f"{secret_id}.blob"
    _encrypt_file_chunked(source_path, BLOBS_DIR / blob_name)

    ciphertext = _fernet().encrypt(json.dumps(meta).encode("utf-8"))
    now = _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO secrets (id, name, kind, created_at, updated_at, ciphertext, blob_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (secret_id, name, kind, now, now, ciphertext, blob_name),
        )
    return secret_id


def load_dataset_file(secret_id: str) -> Path:
    """Decrypt a dataset's bulk data to a fresh temp file (named with the
    right extension from its saved format) and return its path. Streams
    chunk-by-chunk — memory use is bounded by CHUNK_SIZE, not by the
    dataset's size. The caller reads it and should delete it when done."""
    with _connect() as con:
        row = con.execute(
            "SELECT ciphertext, blob_path FROM secrets WHERE id = ?", (secret_id,)
        ).fetchone()
    if row is None or row[1] is None:
        raise SecretNotFound(secret_id)
    meta = json.loads(_fernet().decrypt(row[0]).decode("utf-8"))
    fmt = meta.get("format", "bin")

    fd, tmp_path = tempfile.mkstemp(suffix=f".{fmt}", prefix="vault_dataset_")
    tmp_path = Path(tmp_path)
    with open(fd, "wb") as dest:
        _decrypt_file_chunked(BLOBS_DIR / row[1], dest)
    return tmp_path


class DatasetTooLargeForPreview(ValueError):
    """Raised by preview_dataset_as_csv() when a dataset has more rows
    than the caller's cap allows. Carries the real row count so the
    caller can report it."""

    def __init__(self, row_count: int, max_rows: int):
        super().__init__(
            f"This dataset has {row_count:,} rows — over the {max_rows:,}-row "
            f"cap for loading into a browser. Use the orchestrator's "
            f"--left-vault-dataset/--right-vault-dataset instead for anything this size."
        )
        self.row_count = row_count


def preview_dataset_as_csv(secret_id: str, max_rows: int) -> tuple[str, int]:
    """For DataDiff Pro's "Load from Vault" button: return (csv_text,
    row_count) for a dataset IF its real row count is at or under
    max_rows — raises DatasetTooLargeForPreview otherwise, rather than
    ever pasting something unbounded into a browser textarea (the exact
    risk the chunked-blob design elsewhere in this module exists to
    avoid). The row-count check always happens before any row data is
    read, so an oversized dataset never gets materialized here at all.
    """
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
    """Metadata only — id/name/kind/timestamps/has_data. Never decrypted
    data (has_data just reports whether blob_path is set, not its
    contents)."""
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
        {
            "id": r[0], "name": r[1], "kind": r[2], "created_at": r[3], "updated_at": r[4],
            "has_data": r[5] is not None,
        }
        for r in rows
    ]


class SecretNotFound(KeyError):
    pass


def get_secret(secret_id: str) -> dict[str, Any]:
    """Decrypt and return the real data for *secret_id* (a credential's
    full data, or a dataset's small metadata — never its bulk blob; see
    load_dataset_file() for that). Only call this at the moment a tool is
    actually about to use the secret."""
    with _connect() as con:
        row = con.execute("SELECT ciphertext FROM secrets WHERE id = ?", (secret_id,)).fetchone()
    if row is None:
        raise SecretNotFound(secret_id)
    plaintext = _fernet().decrypt(row[0])
    return json.loads(plaintext.decode("utf-8"))


def find_id_by_name(name: str, kind: Optional[str] = None) -> str:
    """Resolve a name to an id — the shared lookup get_secret_by_name()
    and the dataset-loading callers both need. A direct query, not a
    scan over list_secrets() — no need to fetch/build every metadata row
    just to find the one with a matching name. Raises SecretNotFound if
    no match (picks the first by id on a genuine name collision; rename
    if that's ever a real problem)."""
    with _connect() as con:
        if kind:
            row = con.execute(
                "SELECT id FROM secrets WHERE name = ? AND kind = ? ORDER BY id LIMIT 1",
                (name, kind),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT id FROM secrets WHERE name = ? ORDER BY id LIMIT 1", (name,)
            ).fetchone()
    if row is None:
        raise SecretNotFound(name)
    return row[0]


def get_secret_by_name(name: str, kind: Optional[str] = None) -> dict[str, Any]:
    """Convenience for CLI/script callers (e.g. orchestrator's
    --load-vault) that naturally have a name, not an id."""
    return get_secret(find_id_by_name(name, kind))


def load_dataset_file_by_name(name: str, kind: Optional[str] = None) -> Path:
    """Convenience for CLI/script callers (e.g. orchestrator's
    --*-vault-dataset) that naturally have a name, not an id."""
    return load_dataset_file(find_id_by_name(name, kind))


def delete_secret(secret_id: str) -> None:
    with _connect() as con:
        row = con.execute("SELECT blob_path FROM secrets WHERE id = ?", (secret_id,)).fetchone()
        if row and row[0]:
            (BLOBS_DIR / row[0]).unlink(missing_ok=True)
        con.execute("DELETE FROM secrets WHERE id = ?", (secret_id,))


def clear_all() -> None:
    """Deletes every saved secret/dataset and wipes the blobs directory.
    The key file is left in place — clearing all rows (and blobs)
    already makes any old ciphertext unrecoverable."""
    with _connect() as con:
        con.execute("DELETE FROM secrets")
    shutil.rmtree(BLOBS_DIR, ignore_errors=True)
