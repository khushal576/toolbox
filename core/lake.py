"""
core/lake.py — the data catalog behind the Vault's 📦 Data section (roadmap L1).

Organised like the AWS Glue Data Catalog: **workspaces** (≈ Glue databases, e.g. `migration_staging`) contain
**tables**; a table is always named `workspace.table` (plain lowercase identifiers, so the same name works in SQL
later — L3). Data is stored like a lakehouse: a *managed* table is Parquet files in Toolbox's S3 storage
(`lake/<table id>/<table id>.v<version>.<part>.parquet` — by id, so renaming/moving a table never moves files); an
*external* table (L2) points at files where they already are. Owner decision: tables are plain Parquet (queryable
and fast); secrets stay encrypted in the Vault.

    lake.create_workspace("sales")
    lake.write_table("sales", "orders", [Path("a.parquet")], source={"kind": "upload", "file": "orders.csv"})
    lake.list_tables("sales"); lake.get_table("sales", "orders"); lake.preview("sales", "orders", 50)
    lake.rename_table("sales", "orders", new_name="orders_2026"); lake.drop_table("sales", "orders_2026")

Catalog in Toolbox's Postgres (schema `lake`, core/state/sqlstore.py): workspaces, tables (columns, rows, size,
files, source, version), history (every create/overwrite/append/rename/drop). Writing a new version switches the
catalog to it only after all its files are stored; the old version's files are deleted afterwards — a reader never
sees half a table. Reading Parquet (stats, preview) needs DuckDB: call these from the data runtime / worker.

Scoped access like the Vault's secrets: plugin code uses `lake.scoped("<plugin>")`, allowed by its manifest
`vault: {data: none | read | write}`. Only the Vault tool itself and core/ use the unscoped functions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from core.state.filecache import FileCache
from core.state.sqlstore import SqlStore

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lake"   # standalone SQLite + local file cache
IMPORT_WORKSPACE = "datasets"                                         # where old Vault datasets are imported

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tables (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- managed | external
    format TEXT NOT NULL,               -- parquet (managed); csv/json/... for external tables (L2)
    location TEXT NOT NULL,             -- managed: storage prefix "lake/<id>/"; external: path/pattern/URL
    version INTEGER NOT NULL DEFAULT 1,
    parts INTEGER NOT NULL DEFAULT 0,
    columns TEXT NOT NULL DEFAULT '[]', -- JSON [{name, type}]
    row_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '{}',  -- JSON: where the data came from (upload, dataset, database, query...)
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, name)
);
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    table_name TEXT NOT NULL,
    at TEXT NOT NULL,
    action TEXT NOT NULL,               -- create | overwrite | append | register | rename | drop
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_lake_history_table ON history(table_id, at);
CREATE TABLE IF NOT EXISTS _lake_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS profiles (
    table_id TEXT PRIMARY KEY,          -- roadmap L5: column profile of the table's current version (cache)
    version INTEGER NOT NULL,
    profile TEXT NOT NULL,              -- JSON
    created_at TEXT NOT NULL
);
"""

STORE = SqlStore("lake", sqlite_path=DATA_DIR / "lake.db", ddl=_SCHEMA)
FILES = FileCache("lake", Path(os.environ.get("LAKE_CACHE_DIR", "/tmp/lake-cache")),
                  budget_mb=int(os.environ.get("LAKE_CACHE_MB", "2048")))
_connect = STORE.connect
_ready = False
_ready_lock = threading.Lock()
_write_lock = threading.Lock()  # one writer per process at a time (versions/parts are read-modify-write)


class LakeError(ValueError):
    """A user-facing problem (bad name, missing workspace/table, name taken…)."""


class NotFound(LakeError):
    pass


class ScopeError(PermissionError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ready_store() -> None:
    global _ready
    if not _ready:
        with _ready_lock:
            if not _ready:
                STORE.init()
                _ready = True


def check_name(name: str, what: str = "name") -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise LakeError(f"Invalid {what} {name!r}: use lowercase letters, digits and _ (start with a letter, max 63).")
    return name


def safe_name(text: str) -> str:
    """Turn any label (a file name, a dataset name) into a valid table name."""
    n = re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")
    n = re.sub(r"_+", "_", n)
    if not n or not n[0].isalpha():
        n = "t_" + n
    return n[:63].rstrip("_") or "t"


def _history(con, table_id: str, ws: str, name: str, action: str, **detail: Any) -> None:
    con.execute("INSERT INTO history (id, table_id, workspace, table_name, at, action, detail) VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, table_id, ws, name, _now(), action, json.dumps(detail, default=str)))


# ---- workspaces ---------------------------------------------------------------------------------------------------

def list_workspaces() -> list[dict[str, Any]]:
    _ready_store()
    with _connect() as con:
        rows = con.execute(
            "SELECT w.id, w.name, w.description, w.created_at, w.updated_at, COUNT(t.id) AS tables, "
            "COALESCE(SUM(t.row_count), 0) AS row_count, COALESCE(SUM(t.size_bytes), 0) AS size_bytes "
            "FROM workspaces w LEFT JOIN tables t ON t.workspace_id = w.id "
            "GROUP BY w.id, w.name, w.description, w.created_at, w.updated_at ORDER BY w.name").fetchall()
    return [dict(r) for r in rows]


def _workspace(con, name: str) -> dict[str, Any]:
    row = con.execute("SELECT * FROM workspaces WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise NotFound(f"No workspace '{name}'.")
    return dict(row)


def get_workspace(name: str) -> dict[str, Any]:
    _ready_store()
    with _connect() as con:
        return _workspace(con, name)


def create_workspace(name: str, description: str = "") -> dict[str, Any]:
    _ready_store()
    name = check_name(name, "workspace name")
    with _connect() as con:
        if con.execute("SELECT 1 FROM workspaces WHERE name = ?", (name,)).fetchone():
            raise LakeError(f"Workspace '{name}' already exists.")
        now = _now()
        con.execute("INSERT INTO workspaces (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
                    (uuid.uuid4().hex, name, description or "", now, now))
        return _workspace(con, name)


def _ensure_workspace(name: str) -> None:
    """Create it unless it exists — two loads into a new workspace can race here from different worker processes
    (the write lock is per process): whoever loses finds it created and carries on."""
    try:
        create_workspace(name)
    except Exception as exc:
        try:
            get_workspace(name)
        except NotFound:
            raise exc from None  # not a race: the real error
        logger.debug("workspace %s was created concurrently", name)


def update_workspace(name: str, new_name: Optional[str] = None, description: Optional[str] = None) -> dict[str, Any]:
    _ready_store()
    with _connect() as con:
        ws = _workspace(con, name)
        target = check_name(new_name, "workspace name") if new_name and new_name != name else name
        if target != name and con.execute("SELECT 1 FROM workspaces WHERE name = ?", (target,)).fetchone():
            raise LakeError(f"Workspace '{target}' already exists.")
        con.execute("UPDATE workspaces SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                    (target, ws["description"] if description is None else description, _now(), ws["id"]))
        return _workspace(con, target)


def delete_workspace(name: str, drop_tables: bool = False) -> int:
    """Delete a workspace. Refuses one with tables unless drop_tables=True (then their files are deleted too)."""
    _ready_store()
    with _connect() as con:
        ws = _workspace(con, name)
        tids = [r["id"] for r in con.execute("SELECT id FROM tables WHERE workspace_id = ?", (ws["id"],))]
        if tids and not drop_tables:
            raise LakeError(f"Workspace '{name}' still has {len(tids)} table(s) — delete them first, or confirm.")
        for r in con.execute("SELECT id, name FROM tables WHERE workspace_id = ?", (ws["id"],)).fetchall():
            _history(con, r["id"], name, r["name"], "drop", reason="workspace deleted")
        con.execute("DELETE FROM workspaces WHERE id = ?", (ws["id"],))  # tables cascade
    for tid in tids:
        _remove_files(tid)
    return len(tids)


# ---- tables -------------------------------------------------------------------------------------------------------

_SQL_TYPES = {"VARCHAR": "varchar", "BIGINT": "bigint", "INTEGER": "integer", "SMALLINT": "smallint",
              "TINYINT": "smallint", "UBIGINT": "numeric(20,0)", "UINTEGER": "bigint", "USMALLINT": "integer",
              "UTINYINT": "smallint", "HUGEINT": "numeric(38,0)", "DOUBLE": "double precision", "FLOAT": "real",
              "BOOLEAN": "boolean", "DATE": "date", "TIME": "time", "TIMESTAMP": "timestamp",
              "TIMESTAMP WITH TIME ZONE": "timestamptz", "TIMESTAMP_NS": "timestamp", "TIMESTAMP_MS": "timestamp",
              "TIMESTAMP_S": "timestamp", "INTERVAL": "interval", "BLOB": "bytea", "UUID": "uuid", "JSON": "json"}
_PG_SHORT = [(r"^character varying", "varchar"), (r"^character\b", "char"), (r"^timestamp(\(\d\))? with time zone", "timestamptz"),
             (r"^timestamp(\(\d\))? without time zone", "timestamp"), (r"^time(\(\d\))? without time zone", "time"),
             (r"^double precision", "double precision")]


def sql_type(duckdb_type: Optional[str], declared: Optional[str] = None) -> str:
    """A column type the way SQL Studio shows it (roadmap L5): the source database's own declared type when the
    table was copied from one (varchar(100), numeric(12,2)…), else the Parquet/DuckDB type in SQL words
    (VARCHAR → varchar, DECIMAL(12,2) → numeric(12,2), TIMESTAMP WITH TIME ZONE → timestamptz). Parquet keeps no
    varchar length, so file-loaded text is plain `varchar`."""
    if declared:
        t = str(declared).strip().lower()
        for pat, short in _PG_SHORT:
            t = re.sub(pat, short, t)
        return t
    t = str(duckdb_type or "").strip().upper()
    m = re.match(r"^DECIMAL\((\d+),\s*(\d+)\)$", t)
    if m:
        return f"numeric({m.group(1)},{m.group(2)})"
    return _SQL_TYPES.get(t, t.lower())


def _table_dict(row: Any, ws_name: str) -> dict[str, Any]:
    d = dict(row)
    d["columns"] = json.loads(d["columns"] or "[]")
    d["source"] = json.loads(d["source"] or "{}")
    declared = d["source"].get("column_types") or {}
    for c in d["columns"]:
        c["sql_type"] = sql_type(c.get("type"), declared.get(c["name"]))
    d["workspace"] = ws_name
    d["full_name"] = f"{ws_name}.{d['name']}"
    return d


def list_tables(workspace: str) -> list[dict[str, Any]]:
    _ready_store()
    with _connect() as con:
        ws = _workspace(con, workspace)
        rows = con.execute("SELECT * FROM tables WHERE workspace_id = ? ORDER BY name", (ws["id"],)).fetchall()
    return [_table_dict(r, workspace) for r in rows]


def _table(con, workspace: str, name: str) -> dict[str, Any]:
    ws = _workspace(con, workspace)
    row = con.execute("SELECT * FROM tables WHERE workspace_id = ? AND name = ?", (ws["id"], name)).fetchone()
    if row is None:
        raise NotFound(f"No table '{workspace}.{name}'.")
    return _table_dict(row, workspace)


def get_table(workspace: str, name: str) -> dict[str, Any]:
    _ready_store()
    with _connect() as con:
        return _table(con, workspace, name)


def table_history(workspace: str, name: str, limit: int = 50) -> list[dict[str, Any]]:
    t = get_table(workspace, name)
    with _connect() as con:
        rows = con.execute("SELECT at, action, workspace, table_name, detail FROM history WHERE table_id = ? "
                           "ORDER BY at DESC LIMIT ?", (t["id"], limit)).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in rows]


def _part_name(table_id: str, version: int, part: int) -> str:
    return f"{table_id}.v{version}.{part:05d}.parquet"


def _remove_files(table_id: str) -> None:
    try:
        FILES.remove_all(table_id)
    except Exception:  # noqa: BLE001 - catalog already updated; orphan files are only wasted space
        logger.exception("lake: could not delete the files of table %s", table_id)


def _stats(paths: list[Path]) -> dict[str, Any]:
    """Columns + row count of Parquet files (DuckDB reads only the footers/metadata for the count)."""
    import duckdb

    files = [str(p) for p in paths]
    con = duckdb.connect(":memory:")
    try:
        cols = con.execute("DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)", [files]).fetchall()
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?, union_by_name=true)", [files]).fetchone()[0]
    finally:
        con.close()
    return {"columns": [{"name": c[0], "type": c[1]} for c in cols], "row_count": int(rows)}


def write_table(workspace: str, name: str, parquet_files: Iterable[Path], *, mode: str = "create",
                source: Optional[dict[str, Any]] = None, description: Optional[str] = None,
                create_workspace_if_missing: bool = False) -> dict[str, Any]:
    """Store Parquet files as a managed table. mode: create (fails if it exists) | overwrite (new version, the old
    one is deleted after the switch) | append (more parts in the current version; columns must stay compatible)."""
    _ready_store()
    if mode not in ("create", "overwrite", "append"):
        raise LakeError("mode must be create, overwrite or append")
    name = check_name(name, "table name")
    files = [Path(p) for p in parquet_files]
    if not files:
        raise LakeError("No data files to store.")
    new = _stats(files)
    size = sum(p.stat().st_size for p in files)
    with _write_lock:
        with _connect() as con:
            try:
                ws = _workspace(con, workspace)
            except NotFound:
                if not create_workspace_if_missing:
                    raise
                ws = None
        if ws is None:
            _ensure_workspace(workspace)
        with _connect() as con:
            ws = _workspace(con, workspace)
            existing = con.execute("SELECT * FROM tables WHERE workspace_id = ? AND name = ?",
                                   (ws["id"], name)).fetchone()
        if existing is not None and mode == "create":
            raise LakeError(f"Table '{workspace}.{name}' already exists — choose overwrite or append.")
        if existing is None and mode == "append":
            mode = "create"
        if existing is None:
            tid, version, first_part = uuid.uuid4().hex, 1, 0
        else:
            tid = existing["id"]
            version = existing["version"] + 1 if mode == "overwrite" else existing["version"]
            first_part = 0 if mode == "overwrite" else existing["parts"]
            if mode == "append":
                old_cols = {c["name"]: c["type"] for c in json.loads(existing["columns"])}
                clash = [f"{c['name']} ({old_cols[c['name']]} → {c['type']})" for c in new["columns"]
                         if c["name"] in old_cols and old_cols[c["name"]] != c["type"]]
                if clash:
                    raise LakeError("Can't append: column types differ — " + ", ".join(clash) + ". Use overwrite.")
        # 1) store every file of the new data (nothing in the catalog points at them yet)
        stored = []
        try:
            FILES.local_dir.mkdir(parents=True, exist_ok=True)
            for i, src in enumerate(files):
                dest = FILES.local(_part_name(tid, version, first_part + i))
                shutil.copyfile(src, dest)
                FILES.publish(tid, dest)
                stored.append(dest.name)
        except Exception:
            for n in stored:
                FILES.remove(tid, n)
            raise
        # 2) switch the catalog in one transaction
        now = _now()
        with _connect() as con:
            if existing is None:
                con.execute(
                    "INSERT INTO tables (id, workspace_id, name, kind, format, location, version, parts, columns, "
                    "row_count, size_bytes, source, description, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, ws["id"], name, "managed", "parquet", f"lake/{tid}/", version, len(files),
                     json.dumps(new["columns"]), new["row_count"], size, json.dumps(source or {}, default=str),
                     description or "", now, now))
            elif mode == "overwrite":
                con.execute("UPDATE tables SET version = ?, parts = ?, columns = ?, row_count = ?, size_bytes = ?, "
                            "source = ?, description = COALESCE(?, description), updated_at = ? WHERE id = ?",
                            (version, len(files), json.dumps(new["columns"]), new["row_count"], size,
                             json.dumps(source or {}, default=str), description, now, tid))
            else:  # append: union the column lists (new columns appear, null in older parts)
                cols = json.loads(existing["columns"])
                known = {c["name"] for c in cols}
                cols += [c for c in new["columns"] if c["name"] not in known]
                con.execute("UPDATE tables SET parts = parts + ?, columns = ?, row_count = row_count + ?, "
                            "size_bytes = size_bytes + ?, updated_at = ? WHERE id = ?",
                            (len(files), json.dumps(cols), new["row_count"], size, now, tid))
            _history(con, tid, workspace, name, mode, rows=new["row_count"], bytes=size, parts=len(files),
                     version=version, source=source or {})
        # 3) the previous version's files are no longer referenced
        if existing is not None and mode == "overwrite":
            for part in range(existing["parts"]):
                FILES.remove(tid, _part_name(tid, existing["version"], part))
    return get_table(workspace, name)


def rename_table(workspace: str, name: str, new_name: Optional[str] = None,
                 new_workspace: Optional[str] = None) -> dict[str, Any]:
    """Rename and/or move a table to another workspace (catalog only — files stay where they are)."""
    _ready_store()
    target_ws = new_workspace or workspace
    target = check_name(new_name, "table name") if new_name else name
    with _connect() as con:
        t = _table(con, workspace, name)
        ws = _workspace(con, target_ws)
        if (target_ws, target) != (workspace, name) and con.execute(
                "SELECT 1 FROM tables WHERE workspace_id = ? AND name = ?", (ws["id"], target)).fetchone():
            raise LakeError(f"Table '{target_ws}.{target}' already exists.")
        con.execute("UPDATE tables SET workspace_id = ?, name = ?, updated_at = ? WHERE id = ?",
                    (ws["id"], target, _now(), t["id"]))
        _history(con, t["id"], target_ws, target, "rename", old=f"{workspace}.{name}")
    return get_table(target_ws, target)


def update_table(workspace: str, name: str, description: str) -> dict[str, Any]:
    _ready_store()
    with _connect() as con:
        t = _table(con, workspace, name)
        con.execute("UPDATE tables SET description = ?, updated_at = ? WHERE id = ?", (description, _now(), t["id"]))
    return get_table(workspace, name)


def drop_table(workspace: str, name: str) -> None:
    _ready_store()
    with _connect() as con:
        t = _table(con, workspace, name)
        con.execute("DELETE FROM tables WHERE id = ?", (t["id"],))
        con.execute("DELETE FROM profiles WHERE table_id = ?", (t["id"],))
        _history(con, t["id"], workspace, name, "drop")
    if t["kind"] == "managed":
        _remove_files(t["id"])


def register_external(workspace: str, name: str, location: str, fmt: str, *, options: Optional[dict] = None,
                      source: Optional[dict[str, Any]] = None, description: str = "",
                      create_workspace_if_missing: bool = False, replace: bool = False) -> dict[str, Any]:
    """An EXTERNAL table: files read in place (e.g. a pattern in the shared data folder), never copied. Columns and
    row count are read now; the data is read again on every query, so new/changed files show up there."""
    import duckdb

    from core.file_source import build_multi_read_expr

    _ready_store()
    name = check_name(name, "table name")
    opts = dict(options or {})
    if location.startswith("s3://") and not opts.get("s3_location"):
        raise LakeError("An s3:// table needs an S3 location from the Vault (credentials).")
    expr = build_multi_read_expr([location], fmt, header=opts.get("header"), delimiter=opts.get("delimiter"))
    con = duckdb.connect(":memory:")
    try:
        if location.startswith("s3://"):
            use_s3(con, opts["s3_location"], location)
        try:
            cols = con.execute(f"DESCRIBE SELECT * FROM {expr}").fetchall()
            rows = con.execute(f"SELECT COUNT(*) FROM {expr}").fetchone()[0]
        except duckdb.Error as exc:
            raise LakeError(f"Could not read {location}: {str(exc).splitlines()[0][:300]}") from None
    finally:
        con.close()
    columns = [{"name": c[0], "type": c[1]} for c in cols]
    with _write_lock:
        try:
            get_workspace(workspace)
        except NotFound:
            if not create_workspace_if_missing:
                raise
            _ensure_workspace(workspace)
        now = _now()
        with _connect() as con:
            ws = _workspace(con, workspace)
            old = con.execute("SELECT * FROM tables WHERE workspace_id = ? AND name = ?", (ws["id"], name)).fetchone()
            if old is not None and not replace:
                raise LakeError(f"Table '{workspace}.{name}' already exists.")
            if old is not None and old["kind"] == "managed":
                raise LakeError(f"'{workspace}.{name}' is a loaded (managed) table — drop it first or pick another name.")
            tid = old["id"] if old is not None else uuid.uuid4().hex
            if old is not None:
                con.execute("DELETE FROM tables WHERE id = ?", (tid,))
            con.execute(
                "INSERT INTO tables (id, workspace_id, name, kind, format, location, version, parts, columns, row_count, "
                "size_bytes, source, description, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, ws["id"], name, "external", fmt, location, 1, 0, json.dumps(columns), int(rows), 0,
                 json.dumps({**(source or {}), "options": opts}, default=str), description,
                 old["created_at"] if old is not None else now, now))
            _history(con, tid, workspace, name, "register", location=location, format=fmt, rows=int(rows))
    return get_table(workspace, name)


def prepare(con: Any, table: dict[str, Any]) -> None:
    """Give a DuckDB connection what it needs to read `table` (roadmap L5: an external table in S3 gets its
    credentials as a temporary, bucket-scoped secret). Call before using read_expr() on that connection."""
    if table.get("kind") == "external" and str(table.get("location", "")).startswith("s3://"):
        loc = ((table.get("source") or {}).get("options") or {}).get("s3_location")
        if not loc:
            raise LakeError(f"{table.get('full_name', 'table')}: no S3 location (credentials) recorded.")
        use_s3(con, loc, table["location"])


def read_expr(workspace: str, name: str) -> str:
    """A DuckDB expression that reads the table (managed: its Parquet parts; external: its files in place — for an
    s3:// table call prepare(con, table) on the connection first)."""
    from core.file_source import build_multi_read_expr

    t = get_table(workspace, name)
    if t["kind"] == "external":
        o = (t["source"] or {}).get("options") or {}
        return build_multi_read_expr([t["location"]], t["format"], header=o.get("header"), delimiter=o.get("delimiter"))
    return build_multi_read_expr([str(p) for p in local_files(workspace, name)], "parquet")


def recent_history(limit: int = 20) -> list[dict[str, Any]]:
    """Latest catalog changes across every table (newest first)."""
    _ready_store()
    with _connect() as con:
        rows = con.execute("SELECT at, action, workspace, table_name, detail FROM history ORDER BY at DESC LIMIT ?",
                           (limit,)).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in rows]


def local_files(workspace: str, name: str) -> list[Path]:
    """Local paths of a managed table's current Parquet parts (downloaded from storage when this process has no copy)."""
    t = get_table(workspace, name)
    if t["kind"] != "managed":
        raise LakeError("External tables are read in place (roadmap L2).")
    out = []
    for part in range(t["parts"]):
        p = FILES.fetch(t["id"], _part_name(t["id"], t["version"], part))
        if p is None:
            raise LakeError(f"A data file of '{workspace}.{name}' is missing from storage (part {part}).")
        out.append(p)
    return out


def preview(workspace: str, name: str, limit: int = 50) -> dict[str, Any]:
    """The first `limit` rows (max 500), JSON-safe."""
    import duckdb

    from core.file_source import build_multi_read_expr

    t = get_table(workspace, name)
    if t["kind"] == "managed":  # the first rows live in the first part: don't fetch a multi-GB table to show 50 rows
        first = FILES.fetch(t["id"], _part_name(t["id"], t["version"], 0))
        if first is None:
            raise LakeError(f"A data file of '{workspace}.{name}' is missing from storage (part 0).")
        expr = build_multi_read_expr([str(first)], "parquet")
    else:
        expr = read_expr(workspace, name)
    con = duckdb.connect(":memory:")
    try:
        prepare(con, t)
        select = "*"
        if t["kind"] == "managed":  # part 0 may predate columns added by a later append: show those as NULL
            have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {expr}").fetchall()}
            q = lambda c: '"' + c.replace('"', '""') + '"'  # noqa: E731
            select = ", ".join(q(c["name"]) if c["name"] in have else f"NULL AS {q(c['name'])}" for c in t["columns"]) or "*"
        cur = con.execute(f"SELECT {select} FROM {expr} LIMIT {max(1, min(int(limit), 500))}")
        cols = [d[0] for d in cur.description]
        rows = json.loads(json.dumps(cur.fetchall(), default=str))
    finally:
        con.close()
    return {"columns": cols, "rows": rows}


# ---- one-time import of the old Vault datasets --------------------------------------------------------------------

def import_vault_datasets(again: bool = False) -> dict[str, Any]:
    """Copy Vault *datasets* (Duck Lab / SQL Studio "Save to Vault") into workspace `datasets` as Parquet tables.
    Automatically once (first look at Vault Data); `again=True` imports the ones added since (a dataset already
    imported — matched by its id in the table's source — is skipped). The originals stay in the Vault untouched."""
    _ready_store()
    with _connect() as con:
        done = con.execute("SELECT value FROM _lake_meta WHERE key = 'vault_datasets_imported'").fetchone()
        have = {json.loads(r["source"] or "{}").get("dataset_id") for r in con.execute("SELECT source FROM tables")}
    if done and not again:
        return json.loads(done["value"])
    import duckdb

    from core import vault
    from core.file_source import build_read_expr

    imported, failed = [], []
    for s in vault.list_secrets():
        if not s["has_data"] or s["id"] in have:
            continue
        src = None
        try:
            src = vault.load_dataset_file(s["id"])
            with tempfile.TemporaryDirectory(prefix="lake_import_") as tmp:
                out = Path(tmp) / "data.parquet"
                con = duckdb.connect(":memory:")
                try:
                    con.execute(f"COPY (SELECT * FROM {build_read_expr(str(src))}) TO '{out}' (FORMAT PARQUET)")
                finally:
                    con.close()
                base = safe_name(s["name"])
                name, i = base, 2
                while True:
                    try:
                        get_table(IMPORT_WORKSPACE, name)
                        name, i = f"{base[:58]}_{i}", i + 1
                    except NotFound:
                        break
                write_table(IMPORT_WORKSPACE, name, [out], create_workspace_if_missing=True,
                            source={"kind": "vault_dataset", "dataset": s["name"], "dataset_id": s["id"],
                                    "dataset_kind": s["kind"]})
            imported.append({"dataset": s["name"], "table": f"{IMPORT_WORKSPACE}.{name}"})
        except Exception as exc:  # noqa: BLE001 - one bad dataset must not stop the others
            failed.append({"dataset": s["name"], "error": str(exc)[:300]})
        finally:
            if src is not None:
                Path(src).unlink(missing_ok=True)
    result = {"at": _now(), "imported": imported, "failed": failed}
    with _connect() as con:
        con.execute("DELETE FROM _lake_meta WHERE key = 'vault_datasets_imported'")
        con.execute("INSERT INTO _lake_meta (key, value) VALUES ('vault_datasets_imported', ?)", (json.dumps(result),))
    logger.info("lake: imported %d Vault dataset(s), %d failed", len(imported), len(failed))
    return result


# ---- AWS S3 / S3-compatible locations (roadmap L5) ----------------------------------------------------------------
# A Vault secret of kind `s3_location` holds {access_key_id, secret_access_key, region, endpoint?, url_style?,
# use_ssl?, session_token?}. External tables (and loads) on s3://bucket/... record its id in their options; every
# DuckDB connection that reads them gets a TEMPORARY secret scoped to that bucket (nothing written to disk).

S3_KIND = "s3_location"


def _lit(v: Any) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def s3_bucket(path: str) -> str:
    m = re.match(r"^s3://([^/]+)", path or "")
    if not m:
        raise LakeError("An S3 path looks like s3://bucket/folder/*.parquet")
    return m.group(1)


def s3_secret_sql(data: dict[str, Any], name: str, scope: Optional[str] = None) -> str:
    parts = ["TYPE S3", f"KEY_ID {_lit(data.get('access_key_id', ''))}", f"SECRET {_lit(data.get('secret_access_key', ''))}",
             f"REGION {_lit(data.get('region') or 'us-east-1')}"]
    if data.get("session_token"):
        parts.append(f"SESSION_TOKEN {_lit(data['session_token'])}")
    if data.get("endpoint"):
        ep = re.sub(r"^https?://", "", str(data["endpoint"])).rstrip("/")
        parts.append(f"ENDPOINT {_lit(ep)}")
        parts.append(f"URL_STYLE {_lit(data.get('url_style') or 'path')}")
        use_ssl = data.get("use_ssl")
        if use_ssl is None:
            use_ssl = not str(data["endpoint"]).startswith("http://")
        parts.append(f"USE_SSL {'true' if use_ssl else 'false'}")
    if scope:
        parts.append(f"SCOPE {_lit(scope)}")
    return f"CREATE OR REPLACE TEMPORARY SECRET {name} ({', '.join(parts)})"


def s3_error_text(exc: Exception) -> str:
    """DuckDB's S3 errors in plain words (the raw text names an HTTP request, not the problem)."""
    raw = str(exc).splitlines()[0][:300]
    if "403" in raw:
        return "S3 said access denied (403) — check the access key / secret, the region and the bucket's permissions."
    if "404" in raw or "NoSuchBucket" in raw:
        return "S3 says that bucket or path doesn't exist (404)."
    if "Could not establish connection" in raw or "resolve" in raw.lower() or "timed out" in raw.lower():
        return f"Couldn't reach S3 — check the endpoint / network. ({raw})"
    return f"S3: {raw}"


def use_s3(con: Any, location_id: str, path: str, data: Optional[dict] = None) -> None:
    """Let `con` read `path` (s3://bucket/...) with the Vault S3 location `location_id` (or explicit `data`, used
    by the Vault's "test" button before saving)."""
    from core import vault

    if data is None:
        try:
            data = vault.get_secret(location_id)
        except vault.SecretNotFound:
            raise LakeError("The S3 location for this table is no longer in the Vault.") from None
    bucket = s3_bucket(path)
    con.execute("LOAD httpfs")
    name = "s3_" + re.sub(r"[^a-z0-9]", "_", f"{(location_id or 'test')[:12]}_{bucket}".lower())
    con.execute(s3_secret_sql(data, name, scope=f"s3://{bucket}"))


def s3_match(location_id: Optional[str], pattern: str, data: Optional[dict] = None, limit: int = 20) -> dict[str, Any]:
    """Which objects a pattern matches (count + first `limit`) — the Data Lake's live preview and the Vault's
    "test" button. A folder (ending in /) means everything under it."""
    import duckdb

    pat = pattern.strip()
    if pat.endswith("/"):
        pat += "**"
    con = duckdb.connect(":memory:")
    try:
        use_s3(con, location_id or "", pat, data)
        try:
            files = [r[0] for r in con.execute("SELECT file FROM glob(?) ORDER BY file", [pat]).fetchall()]
        except duckdb.Error as exc:
            raise LakeError(s3_error_text(exc)) from None
    finally:
        con.close()
    return {"pattern": pat, "count": len(files), "sample": files[:limit]}


# ---- column profiles (roadmap L5) ---------------------------------------------------------------------------------

PROFILE_SAMPLE = int(os.environ.get("LAKE_PROFILE_SAMPLE", "200000"))
_NUMERIC = re.compile(r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|FLOAT|DOUBLE|"
                      r"REAL|DECIMAL.*)$", re.I)


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def profile(workspace: str, name: str, refresh: bool = False) -> dict[str, Any]:
    """Per column: type, count, nulls %, distinct (approx.), min / max, mean / std / quartiles for numbers, and the
    most common values. Exact over the whole table (DuckDB SUMMARIZE); most-common values from a sample of
    PROFILE_SAMPLE rows on bigger tables. Cached per table version (external tables: until refreshed)."""
    import duckdb

    _ready_store()
    t = get_table(workspace, name)
    if not refresh:
        with _connect() as con:
            r = con.execute("SELECT * FROM profiles WHERE table_id = ?", (t["id"],)).fetchone()
        if r is not None and r["version"] == t["version"]:
            return {**json.loads(r["profile"]), "cached": True}
    expr = read_expr(workspace, name)
    con = duckdb.connect(":memory:")
    try:
        prepare(con, t)
        con.execute(f"SET memory_limit = '{os.environ.get('LAKE_EXPORT_MEMORY', '512MB')}'")
        con.execute(f"SET temp_directory = '{tempfile.gettempdir()}/lake-profile-spill'")
        cur = con.execute(f"SUMMARIZE SELECT * FROM {expr}")
        keys = [d[0] for d in cur.description]
        summary = [dict(zip(keys, row)) for row in cur.fetchall()]
        total = int(summary[0]["count"]) if summary else 0
        sampled = total > PROFILE_SAMPLE
        con.execute(f"CREATE TEMP TABLE _s AS SELECT * FROM {expr}"
                    + (f" USING SAMPLE {PROFILE_SAMPLE} ROWS" if sampled else ""))
        cols = []
        for srow in summary:
            c = srow["column_name"]
            top = con.execute(f"SELECT {_q(c)}::VARCHAR AS v, count(*) AS n FROM _s WHERE {_q(c)} IS NOT NULL "
                              f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5").fetchall()
            numeric = bool(_NUMERIC.match(str(srow["column_type"])))
            nulls = float(srow.get("null_percentage") or 0)
            cols.append({
                "name": c, "type": srow["column_type"], "null_pct": round(nulls, 2),
                "distinct": int(srow["approx_unique"] or 0),
                "min": None if srow["min"] is None else str(srow["min"]),
                "max": None if srow["max"] is None else str(srow["max"]),
                **({"mean": _num(srow.get("avg")), "std": _num(srow.get("std")), "q25": _num(srow.get("q25")),
                    "q50": _num(srow.get("q50")), "q75": _num(srow.get("q75"))} if numeric else {}),
                "top": [{"value": v[:200], "count": int(n)} for v, n in top],
            })
    except duckdb.Error as exc:
        raise LakeError(f"Could not profile {t['full_name']}: {str(exc).splitlines()[0][:300]}") from None
    finally:
        con.close()
    out = {"table": t["full_name"], "rows": total, "columns": cols, "version": t["version"],
           "top_from_sample": PROFILE_SAMPLE if sampled else None, "created_at": _now()}
    with _connect() as con:
        con.execute("DELETE FROM profiles WHERE table_id = ?", (t["id"],))
        con.execute("INSERT INTO profiles (table_id, version, profile, created_at) VALUES (?, ?, ?, ?)",
                    (t["id"], t["version"], json.dumps(out, default=str), out["created_at"]))
    return {**out, "cached": False}


def _num(v: Any) -> Any:
    if v is None:
        return None
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return str(v)


# ---- suggested joins (roadmap L5) ---------------------------------------------------------------------------------

def _type_family(t: str) -> str:
    t = (t or "").upper()
    if re.match(r"^(U?TINYINT|U?SMALLINT|U?INTEGER|U?BIGINT|HUGEINT|DECIMAL\(\d+, ?0\))$", t):
        return "int"
    if t.startswith(("VARCHAR", "CHAR", "TEXT", "STRING")):
        return "text"
    if t == "UUID":
        return "text"
    if t.startswith(("DATE", "TIMESTAMP")):
        return t.split()[0]
    return t


def _singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    return name[:-1] if name.endswith("s") else name


_GENERIC = {"id", "name", "value", "description", "status", "type", "created_at", "updated_at", "date", "note", "notes",
            "title", "comment", "amount", "price", "count", "total", "_source_file"}   # same name ≠ same thing
MIN_OVERLAP = 5.0   # % of my sampled values found in the other column; below that it's coincidence


def suggest_joins(workspace: str, name: str, limit: int = 10, max_checks: int = 25) -> list[dict[str, Any]]:
    """Columns of `workspace.name` that look joinable with columns of other tables: same / `<table>_id` ↔ `id`
    names and a compatible type, then CHECKED on the data — the share of this column's distinct values (a sample of
    up to 2000) found in the other column. Best first; each comes with a ready JOIN clause."""
    import duckdb

    me = get_table(workspace, name)
    tables = [t for w in list_workspaces() for t in list_tables(w["name"])]
    cands = []
    for c in me["columns"]:
        cn, cf = c["name"].lower(), _type_family(c.get("type"))
        for u in tables:
            if u["id"] == me["id"]:
                continue
            for d in u["columns"]:
                dn = d["name"].lower()
                if _type_family(d.get("type")) != cf:
                    continue
                score = 0
                if cn == dn and cn not in _GENERIC and cf not in ("DATE", "TIMESTAMP"):  # dates rarely are keys
                    score = 3 if cn.endswith("id") else 2
                if dn == "id" and cn in (f"{_singular(u['name'])}_id", f"{u['name']}_id"):
                    score = 5
                if cn == "id" and dn in (f"{_singular(me['name'])}_id", f"{me['name']}_id"):
                    score = 5
                if score:
                    cands.append((score, c, u, d))
    cands.sort(key=lambda x: -x[0])
    out = []
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit = '{os.environ.get('LAKE_EXPORT_MEMORY', '512MB')}'")
        con.execute(f"SET temp_directory = '{tempfile.gettempdir()}/lake-joins-spill'")
        prepare(con, me)
        mine: dict[str, tuple[str, int]] = {}  # my column → (temp table of up to 2000 of its distinct values, count)
        for score, c, u, d in cands[:max_checks]:
            try:
                if c["name"] not in mine:
                    tmp = f"_mine_{len(mine)}"
                    con.execute(f"CREATE TEMP TABLE {tmp} AS SELECT DISTINCT {_q(c['name'])} AS v FROM "
                                f"{read_expr(workspace, name)} WHERE {_q(c['name'])} IS NOT NULL LIMIT 2000")
                    mine[c["name"]] = (tmp, con.execute(f"SELECT count(*) FROM {tmp}").fetchone()[0])
                tmp, n = mine[c["name"]]
                if not n:
                    continue
                prepare(con, u)
                found = con.execute(f"SELECT count(*) FROM {tmp} WHERE v IN (SELECT {_q(d['name'])} FROM "
                                    f"{read_expr(u['workspace'], u['name'])})").fetchone()[0]
            except (duckdb.Error, LakeError):
                continue
            if 100.0 * found / n < MIN_OVERLAP:
                continue
            alias = u["name"] if u["name"] != name else "other"
            out.append({"column": c["name"], "table": u["full_name"], "other_column": d["name"],
                        "overlap_pct": round(100.0 * found / n, 1), "checked_values": n, "name_score": score,
                        "join": f"JOIN {u['full_name']}{' AS other' if alias == 'other' else ''} "
                                f"ON {name}.{_q(c['name'])} = {alias}.{_q(d['name'])}"})
    finally:
        con.close()
    out.sort(key=lambda j: (-j["overlap_pct"], -j["name_score"]))
    return out[:limit]


# ---- moving data in and out (roadmap L4: every tool's "Load from / Save to Vault Data") ---------------------------

def catalog() -> list[dict[str, Any]]:
    """Every workspace with its tables (name, kind, rows, size, columns) — what a tool's table picker shows."""
    out = []
    for w in list_workspaces():
        out.append({"name": w["name"], "description": w.get("description") or "",
                    "tables": [{"name": t["name"], "full_name": t["full_name"], "kind": t["kind"],
                                "row_count": t["row_count"], "size_bytes": t["size_bytes"],
                                "columns": [{"name": c["name"], "type": c.get("type"), "sql_type": c.get("sql_type")}
                                            for c in t["columns"]]}
                               for t in list_tables(w["name"])]})
    return out


def export_table(workspace: str, name: str, dest: Path, fmt: str = "parquet", limit: Optional[int] = None) -> dict[str, Any]:
    """Write a table (or its first `limit` rows) to ONE local file, csv or parquet — streamed by DuckDB, never the
    whole table in Python. Returns {path, rows, columns}. The caller owns (and deletes) the file."""
    import duckdb

    if fmt not in ("parquet", "csv"):
        raise LakeError("format must be parquet or csv")
    expr = read_expr(workspace, name)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lim = f" LIMIT {int(limit)}" if limit else ""
    opts = "FORMAT PARQUET" if fmt == "parquet" else "FORMAT CSV, HEADER"
    t = get_table(workspace, name)
    con = duckdb.connect(":memory:")
    try:
        prepare(con, t)
        con.execute(f"SET memory_limit = '{os.environ.get('LAKE_EXPORT_MEMORY', '512MB')}'")
        con.execute(f"SET temp_directory = '{tempfile.gettempdir()}/lake-export-spill'")
        con.execute(f"COPY (SELECT * FROM {expr}{lim}) TO '{dest}' ({opts})")
    finally:
        con.close()
    rows = min(t["row_count"], int(limit)) if limit else t["row_count"]
    return {"path": dest, "rows": int(rows), "columns": [c["name"] for c in t["columns"]]}


def import_file(workspace: str, name: str, path: Path, *, mode: str = "create", source: Optional[dict] = None,
                description: Optional[str] = None, create_workspace_if_missing: bool = True) -> dict[str, Any]:
    """Store a local csv / json / parquet file as a managed table (converted to Parquet by DuckDB, streamed).
    Same modes as write_table. The caller's file is left alone."""
    import duckdb

    from core.file_source import build_multi_read_expr, detect_any

    path = Path(path)
    fmt = detect_any(str(path))
    if fmt not in ("csv", "json", "parquet"):
        raise LakeError(f"Can't store a {fmt} file as a table here — csv, json or parquet only.")
    work = Path(tempfile.mkdtemp(prefix="lake_import_"))
    try:
        out = work / "data.parquet"
        con = duckdb.connect(":memory:")
        try:
            con.execute(f"SET memory_limit = '{os.environ.get('LAKE_EXPORT_MEMORY', '512MB')}'")
            con.execute(f"SET temp_directory = '{work / 'spill'}'")
            con.execute(f"COPY (SELECT * FROM {build_multi_read_expr([str(path)], fmt)}) TO '{out}' (FORMAT PARQUET)")
        except duckdb.Error as exc:
            raise LakeError(f"Could not read the data: {str(exc).splitlines()[0][:300]}") from None
        finally:
            con.close()
        return write_table(workspace, name, [out], mode=mode, source=source, description=description,
                           create_workspace_if_missing=create_workspace_if_missing)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- scoped access ------------------------------------------------------------------------------------------------

class ScopedLake:
    """The lake as one plugin sees it: `data: read` → list/describe/preview/read files; `write` → also create,
    write, rename, drop. Granted by the plugin manifest's `vault: {data: ...}`."""

    LakeError, NotFound, ScopeError = LakeError, NotFound, ScopeError

    def __init__(self, plugin: str, access: str):
        self.plugin, self.access = plugin, access

    def _need(self, level: str) -> None:
        if level == "read" and self.access in ("read", "write"):
            return
        if level == "write" and self.access == "write":
            return
        raise ScopeError(f"plugin '{self.plugin}' may not {level} Vault Data (add `data: {level}` under `vault:` "
                         "in its manifest.yaml)")

    def list_workspaces(self):
        self._need("read")
        return list_workspaces()

    def list_tables(self, workspace):
        self._need("read")
        return list_tables(workspace)

    def get_table(self, workspace, name):
        self._need("read")
        return get_table(workspace, name)

    def preview(self, workspace, name, limit=50):
        self._need("read")
        return preview(workspace, name, limit)

    def read_expr(self, workspace, name):
        self._need("read")
        return read_expr(workspace, name)

    def recent_history(self, limit=20):
        self._need("read")
        return recent_history(limit)

    def register_external(self, workspace, name, location, fmt, **kw):
        self._need("write")
        return register_external(workspace, name, location, fmt, **kw)

    def local_files(self, workspace, name):
        self._need("read")
        return local_files(workspace, name)

    def create_workspace(self, name, description=""):
        self._need("write")
        return create_workspace(name, description)

    def write_table(self, workspace, name, parquet_files, **kw):
        self._need("write")
        return write_table(workspace, name, parquet_files, **kw)

    def rename_table(self, workspace, name, **kw):
        self._need("write")
        return rename_table(workspace, name, **kw)

    def drop_table(self, workspace, name):
        self._need("write")
        return drop_table(workspace, name)

    def catalog(self):
        self._need("read")
        return catalog()

    def export_table(self, workspace, name, dest, fmt="parquet", limit=None):
        self._need("read")
        return export_table(workspace, name, dest, fmt, limit)

    def import_file(self, workspace, name, path, **kw):
        self._need("write")
        return import_file(workspace, name, path, **kw)

    def prepare(self, con, table):
        self._need("read")
        return prepare(con, table)

    def profile(self, workspace, name, refresh=False):
        self._need("read")
        return profile(workspace, name, refresh)

    def suggest_joins(self, workspace, name, limit=10):
        self._need("read")
        return suggest_joins(workspace, name, limit)

    def s3_match(self, location_id, pattern):
        self._need("read")
        return s3_match(location_id, pattern)


def scoped(plugin: str) -> ScopedLake:
    from core.vault import scope_for

    return ScopedLake(plugin, scope_for(plugin).data)
