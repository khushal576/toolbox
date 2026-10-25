"""
duck-lab/engine.py

Session state and DuckDB plumbing. Sessions are keyed by a cookie'd session id (each browser tab owns its own
set of loaded files) and, since roadmap B3, live OUTSIDE the process (session_store.py):

- the session's table list + current result in Redis (with a version counter),
- every uploaded file and every query result as an object in S3 storage.

Each worker process keeps a LOCAL working copy per session (`_Local`: a DuckDB connection + a cache directory
with the files downloaded on demand). When the session's version in Redis is newer than the local copy, the
local views are rebuilt — so any worker (or node) can serve any request for any session.

Why DuckDB instead of pandas (like df-studio): CSV/JSON sources are never read into Python memory here —
read_csv_auto()/read_json_auto() point DuckDB directly at the (locally cached) file and it scans it itself.
XML has no native DuckDB reader: it is parsed once (core/normalizer.py), written to Parquet, and from then on
treated like any other file-backed table.

Query results are never fully pulled into Python either: `run_query()` materializes the result inside DuckDB,
writes it ONCE to Parquet (local + S3), and every page/export reads that Parquet file with LIMIT/OFFSET —
the same result is therefore available to every worker. Only one page's worth of rows (default 100) is ever
turned into JSON.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core.normalizer import normalize as _normalize_xml
    from core.file_source import build_read_expr, detect_format
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.normalizer import normalize as _normalize_xml
    from core.file_source import build_read_expr, detect_format

try:  # package import when mounted inside the toolbox (duck_lab.*)
    from duck_lab import session_store
except ImportError:  # flat import when run standalone from within this folder
    import session_store

# Per-worker local working copies (downloaded files, DuckDB spill files, result Parquet). Disposable: anything
# here can be re-downloaded from S3 storage.
CACHE_ROOT = Path(os.environ.get("DUCK_LAB_CACHE_DIR") or Path(tempfile.gettempdir()) / "duck-lab-cache")
LOCAL_SESSIONS = max(1, int(os.environ.get("DUCK_LAB_LOCAL_SESSIONS") or 8))

# Bounds how much memory one session's DuckDB connection will use before it
# spills intermediate/materialized results to disk (temp_directory, set per
# session below) instead of growing unbounded — this is the actual
# mechanism that keeps a big join from crashing the container.
MEMORY_LIMIT = "512MB"

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")

BACKEND = session_store.make_backend()


class QueryError(ValueError):
    pass


@dataclass
class TableMeta:
    name: str
    format: str  # "csv" | "json" | "xml" | "parquet"  (xml is stored as Parquet; the label is for display)
    columns: list[str]
    row_count: int
    source_file: str | None  # filename as uploaded, for display only
    object_key: str = ""  # where the file lives in storage (S3 key, or a local path in memory mode)
    local_name: str = ""  # file name inside the local cache dir

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "format": self.format, "columns": self.columns, "row_count": self.row_count,
                "source_file": self.source_file, "object_key": self.object_key, "local_name": self.local_name}


class _Local:
    """This process's working copy of one session: DuckDB connection + cache dir. Rebuilt from metadata."""

    def __init__(self, sid: str):
        self.sid = sid
        self.data_dir = CACHE_ROOT / sid
        (self.data_dir / "files").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "results").mkdir(parents=True, exist_ok=True)
        self.con = _new_connection(self.data_dir)
        self.version = -1  # metadata version the views were built from
        self.result_id: str | None = None  # result Parquet the _result view points at
        self.lock = threading.RLock()  # one request at a time per session per process

    def close(self) -> None:
        try:
            self.con.close()
        finally:
            shutil.rmtree(self.data_dir, ignore_errors=True)


@dataclass
class Session:
    sid: str
    con: duckdb.DuckDBPyConnection
    data_dir: Path
    tables: dict[str, TableMeta] = field(default_factory=dict)
    result: dict[str, Any] | None = None  # {"id", "columns", "total_rows", "object_key"}
    version: int = 0
    local: _Local | None = None

    # Kept for server.py/export callers that predate B3.
    @property
    def has_result(self) -> bool:
        return self.result is not None

    @property
    def result_columns(self) -> list[str] | None:
        return self.result["columns"] if self.result else None

    @property
    def result_total_rows(self) -> int:
        return self.result["total_rows"] if self.result else 0


_locals: "OrderedDict[str, _Local]" = OrderedDict()
_locals_lock = threading.Lock()


def _new_connection(data_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    spill_dir = data_dir / "spill"
    spill_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory='{spill_dir}'")
    return con


def _local_for(sid: str) -> _Local:
    with _locals_lock:
        local = _locals.get(sid)
        if local is None:
            local = _Local(sid)
            _locals[sid] = local
        _locals.move_to_end(sid)
        while len(_locals) > LOCAL_SESSIONS:
            _, old = _locals.popitem(last=False)
            old.close()
        return local


def _drop_local(sid: str) -> None:
    with _locals_lock:
        local = _locals.pop(sid, None)
    if local is not None:
        local.close()


def _quote_path(p: Path) -> str:
    return str(p).replace("'", "''")


def _empty_meta() -> dict[str, Any]:
    return {"version": 0, "tables": {}, "result": None}


def _ensure_local_file(local: _Local, meta: TableMeta) -> Path:
    path = local.data_dir / "files" / meta.local_name
    if not path.exists():
        if not BACKEND.get_file(meta.object_key, path):
            raise QueryError(f"The file behind table '{meta.name}' has expired — upload it again.")
    return path


def _sync(local: _Local, meta: dict[str, Any]) -> None:
    """Make this process's views match the session metadata (rebuild only when the version changed)."""
    if local.version == meta["version"]:
        return
    existing = {r[0] for r in local.con.execute(
        "SELECT view_name FROM duckdb_views() WHERE NOT internal AND view_name <> '_result'").fetchall()}
    wanted = {name: TableMeta(**t) for name, t in meta["tables"].items()}
    for name in existing - set(wanted):
        local.con.execute(f'DROP VIEW IF EXISTS "{name}"')
    for name, t in wanted.items():
        path = _ensure_local_file(local, t)
        local.con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM {build_read_expr(str(path))}')
    local.version = meta["version"]


def _ensure_result_view(local: _Local, result: dict[str, Any]) -> None:
    if local.result_id == result["id"]:
        return
    path = local.data_dir / "results" / f"{result['id']}.parquet"
    if not path.exists() and not BACKEND.get_file(result["object_key"], path):
        raise QueryError("This query result has expired — run the query again.")
    local.con.execute(f"CREATE OR REPLACE TEMP VIEW _result AS SELECT * FROM read_parquet('{_quote_path(path)}')")
    local.result_id = result["id"]


def _session_from(sid: str, meta: dict[str, Any], local: _Local) -> Session:
    return Session(sid=sid, con=local.con, data_dir=local.data_dir,
                   tables={n: TableMeta(**t) for n, t in meta["tables"].items()},
                   result=meta.get("result"), version=meta["version"], local=local)


def _save(session: Session) -> None:
    session.version += 1
    BACKEND.save_meta(session.sid, {"version": session.version,
                                    "tables": {n: m.to_dict() for n, m in session.tables.items()},
                                    "result": session.result})
    if session.local is not None:
        session.local.version = session.version


def get_or_create_session(sid: str) -> Session:
    """The session for this cookie, with this process's views brought up to date. Call from a worker thread
    (may download files). A brand-new sid is not written anywhere until it is first changed."""
    meta = BACKEND.load_meta(sid) or _empty_meta()
    local = _local_for(sid)
    with local.lock:
        _sync(local, meta)
    return _session_from(sid, meta, local)


def reset_session(session: Session) -> Session:
    """Drop everything for this session (stored files, result, metadata, local copy) and start fresh."""
    BACKEND.delete(session.sid)
    _drop_local(session.sid)
    return get_or_create_session(session.sid)


def _sanitize_name(filename: str, existing: dict[str, TableMeta]) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = _NAME_RE.sub("_", stem).strip("_") or "table"
    if name[0].isdigit():
        name = f"t_{name}"
    base = name
    i = 2
    while name in existing:
        name = f"{base}_{i}"
        i += 1
    return name


def _columns_of(con: duckdb.DuckDBPyConnection, name: str) -> list[str]:
    return [row[0] for row in con.execute(f'DESCRIBE "{name}"').fetchall()]


def _row_count_of(con: duckdb.DuckDBPyConnection, name: str) -> int:
    return con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]


def _register_file(session: Session, local_path: Path, name: str, fmt: str, source_file: str) -> TableMeta:
    """Store the file (S3 or memory), move it into the local cache, create the view, save metadata."""
    ext = local_path.suffix or ".dat"
    local_name = f"{name}{ext}"
    object_key = BACKEND.put_file(session.sid, f"files/{local_name}", local_path)
    final = session.data_dir / "files" / local_name
    if local_path.resolve() != final.resolve():
        shutil.move(str(local_path), str(final))
    session.con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM {build_read_expr(str(final))}')
    meta = TableMeta(name=name, format=fmt, columns=_columns_of(session.con, name),
                     row_count=_row_count_of(session.con, name), source_file=source_file,
                     object_key=object_key, local_name=local_name)
    session.tables[name] = meta
    _save(session)
    return meta


def load_file(session: Session, saved_path: Path, filename: str) -> TableMeta:
    """Load a CSV/JSON/Parquet file as a lazy DuckDB view — the view reads
    straight off the (locally cached) file, nothing is pulled into Python memory
    here. The file is also stored in S3 storage so other workers can rebuild the
    view. Format is detected from the extension (core.file_source), same mapping
    server.py's /upload route already used to decide whether to even
    reach this function (vs. XML, see load_xml below)."""
    fmt = detect_format(filename)
    with session.local.lock:
        name = _sanitize_name(filename, session.tables)
        return _register_file(session, saved_path, name, fmt, filename)


def load_xml(session: Session, raw_text: str, filename: str) -> TableMeta:
    """DuckDB has no native XML reader. Parse once via the same
    core/normalizer.py logic DataDiff Pro uses, build a DataFrame, write it to
    Parquet ONCE, and from then on treat it like any other file-backed table
    (roadmap B3 — before that the DataFrame stayed registered in memory for the
    whole session). The XML is fully read into Python memory once, at upload —
    an accepted ceiling matching DataDiff Pro's own XML scope (single root
    element), not silently hidden.
    """
    parsed, error = _normalize_xml(raw_text, "xml")
    if error:
        raise QueryError(f"XML parse error: {error}")
    # normalize("xml") keeps the root tag as a single-key wrapper (xmltodict's
    # own shape: {"<root>": ...}), and a single nested container tag
    # (e.g. <records><record>...) produces another single-key wrapper one
    # level down. Drill through those wrapper layers to find the real
    # row list/dict — otherwise every XML file would load as exactly one
    # row with one column holding the entire nested document.
    data = parsed
    while isinstance(data, dict) and len(data) == 1:
        data = next(iter(data.values()))
    records = data if isinstance(data, list) else [data]
    df = pd.json_normalize(records)

    with session.local.lock:
        name = _sanitize_name(filename, session.tables)
        tmp = session.data_dir / "files" / f"{uuid.uuid4().hex}.parquet"
        frame_var = f"_xml_{uuid.uuid4().hex}"
        session.con.register(frame_var, df)
        try:
            session.con.execute(f"COPY (SELECT * FROM {frame_var}) TO '{_quote_path(tmp)}' (FORMAT PARQUET)")
        finally:
            session.con.unregister(frame_var)
        return _register_file(session, tmp, name, "xml", filename)


def remove_table(session: Session, name: str) -> None:
    with session.local.lock:
        meta = session.tables.pop(name, None)
        if meta is None:
            raise QueryError(f"No loaded table named '{name}'")
        session.con.execute(f'DROP VIEW IF EXISTS "{name}"')
        (session.data_dir / "files" / meta.local_name).unlink(missing_ok=True)
        BACKEND.delete_file(meta.object_key)
        _save(session)


PREVIEW_ROWS = 20


def preview_table(session: Session, name: str) -> dict[str, Any]:
    """First PREVIEW_ROWS rows of a loaded source, straight off the view —
    no _result involved, this is independent of whatever query was last run.
    """
    if name not in session.tables:
        raise QueryError(f"No loaded table named '{name}'")
    with session.local.lock:
        rows = session.con.execute(f'SELECT * FROM "{name}" LIMIT {PREVIEW_ROWS}').fetchall()
    return {
        "columns": session.tables[name].columns,
        "rows": [_row_to_jsonable(r) for r in rows],
    }


def _count_top_level_semicolons(sql: str) -> int:
    """Best-effort: count ';' outside of '...'/"..." strings. Good enough to
    reject an obvious multi-statement paste; anything subtler just surfaces
    as a DuckDB parse error from the wrapped CREATE TABLE AS statement.
    """
    count = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        c = sql[i]
        if in_single:
            if c == "'":
                in_single = False
        elif in_double:
            if c == '"':
                in_double = False
        elif c == "'":
            in_single = True
        elif c == '"':
            in_double = True
        elif c == ";":
            count += 1
        i += 1
    return count


def _validate_single_statement(sql: str) -> str:
    stripped = sql.strip()
    if not stripped:
        raise QueryError("Query is empty")
    trailing = stripped.endswith(";")
    body = stripped[:-1] if trailing else stripped
    if _count_top_level_semicolons(body) > 0:
        raise QueryError("Only one statement at a time is supported — remove the extra ';'-separated statement(s)")
    return body


def _friendly_error(exc: duckdb.Error, session: Session) -> str:
    """DuckDB's own messages are generally good (Parser Error includes a
    caret at the exact position) — this only adds a hint for the one
    confusion that's actually common here: referencing a table name that
    isn't one of the currently loaded sources.
    """
    message = str(exc)
    if "does not exist" in message and "Table" in message.split("\n", 1)[0]:
        loaded = ", ".join(sorted(session.tables)) or "(none loaded yet)"
        return f"{message}\nLoaded tables: {loaded}"
    return message


def run_query(session: Session, sql: str) -> dict[str, Any]:
    body = _validate_single_statement(sql)
    with session.local.lock:
        started = time.perf_counter()
        try:
            session.con.execute(f"CREATE OR REPLACE TEMP TABLE _result_build AS {body}")
        except duckdb.Error as exc:
            raise QueryError(_friendly_error(exc, session)) from exc
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        columns = _columns_of(session.con, "_result_build")
        total = _row_count_of(session.con, "_result_build")
        rid = uuid.uuid4().hex
        path = session.data_dir / "results" / f"{rid}.parquet"
        session.con.execute(f"COPY _result_build TO '{_quote_path(path)}' (FORMAT PARQUET)")
        session.con.execute("DROP TABLE _result_build")
        object_key = BACKEND.put_file(session.sid, f"results/{rid}.parquet", path)

        old = session.result
        session.result = {"id": rid, "columns": columns, "total_rows": total, "object_key": object_key}
        _ensure_result_view(session.local, session.result)
        _save(session)
        if old:  # one result per session: drop the previous one everywhere
            BACKEND.delete_file(old["object_key"])
            (session.data_dir / "results" / f"{old['id']}.parquet").unlink(missing_ok=True)

        page = fetch_page(session, 0, DEFAULT_PAGE_SIZE)
    return {
        "columns": columns,
        "total_rows": total,
        "page_size": DEFAULT_PAGE_SIZE,
        "rows": page["rows"],
        "elapsed_ms": elapsed_ms,
    }


def fetch_page(session: Session, offset: int, limit: int) -> dict[str, Any]:
    if not session.has_result:
        raise QueryError("Run a query first")
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    with session.local.lock:
        _ensure_result_view(session.local, session.result)
        rows = session.con.execute(f"SELECT * FROM _result LIMIT {limit} OFFSET {offset}").fetchall()
    return {
        "columns": session.result_columns or [],
        "rows": [_row_to_jsonable(r) for r in rows],
        "offset": offset,
        "limit": limit,
        "total_rows": session.result_total_rows,
    }


def _row_to_jsonable(row: tuple) -> list:
    out = []
    for v in row:
        if isinstance(v, (bytes, bytearray)):
            out.append(v.hex())
        elif hasattr(v, "isoformat"):
            out.append(v.isoformat())
        else:
            out.append(v)
    return out


def export_result(session: Session, fmt: str) -> Path:
    """Write the full current result to a new file in this process's cache dir (caller deletes it)."""
    if not session.has_result:
        raise QueryError("Run a query first")
    out_path = session.data_dir / f"export_{uuid.uuid4().hex}.{fmt}"
    options = {"csv": "FORMAT CSV, HEADER", "json": "FORMAT JSON, ARRAY true", "parquet": "FORMAT PARQUET"}
    if fmt not in options:
        raise QueryError(f"Unsupported export format: {fmt}")
    with session.local.lock:
        _ensure_result_view(session.local, session.result)
        session.con.execute(f"COPY (SELECT * FROM _result) TO '{_quote_path(out_path)}' ({options[fmt]})")
    return out_path
