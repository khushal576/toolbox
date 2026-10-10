"""
duck-lab/engine.py

Session state and DuckDB plumbing. One process, in-memory-keyed sessions
(SESSIONS dict keyed by a cookie'd session id) — same shape as
df-studio/engine.py's SESSIONS, not sql-studio's single global STATE,
because each browser tab legitimately wants its own independent set of
loaded files (see ../CLAUDE.md's "Standing rule: stateful tools and
--workers").

Why DuckDB instead of pandas (like df-studio): CSV/JSON sources are never
read into Python memory here — read_csv_auto()/read_json_auto() point
DuckDB directly at the file on disk and it scans it itself, vectorized, in
its own engine. The only thing fully loaded into Python memory is XML (no
native DuckDB reader for it — see load_xml below), which is the same
ceiling core/normalizer.py's XML handling already has for DataDiff Pro.

Query results are never fully pulled into Python either: `run_query()`
materializes the result as a TEMP TABLE *inside* DuckDB (which can spill to
disk — see MEMORY_LIMIT/session temp_directory below), and `fetch_page()`
re-slices that same table with LIMIT/OFFSET. Only one page's worth of rows
(default 100) is ever turned into JSON.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
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

DATA_ROOT = Path(__file__).resolve().parent / "data"

# Bounds how much memory one session's DuckDB connection will use before it
# spills intermediate/materialized results to disk (temp_directory, set per
# session below) instead of growing unbounded — this is the actual
# mechanism that keeps a big join from crashing the container.
MEMORY_LIMIT = "512MB"

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


class QueryError(ValueError):
    pass


@dataclass
class TableMeta:
    name: str
    format: str  # "csv" | "json" | "xml" | "parquet"
    columns: list[str]
    row_count: int
    source_file: str | None  # filename as uploaded, for display only


@dataclass
class Session:
    sid: str
    con: duckdb.DuckDBPyConnection
    data_dir: Path
    tables: dict[str, TableMeta] = field(default_factory=dict)
    # Keeps XML-derived DataFrames alive — con.register() holds a view backed
    # directly by the Python object, not a copy; if it were garbage
    # collected the view would break.
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    result_columns: list[str] | None = None
    result_total_rows: int = 0
    has_result: bool = False


SESSIONS: dict[str, Session] = {}


def _new_connection(data_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    spill_dir = data_dir / "spill"
    spill_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory='{spill_dir}'")
    return con


def get_or_create_session(sid: str) -> Session:
    session = SESSIONS.get(sid)
    if session is not None:
        return session
    data_dir = DATA_ROOT / sid
    data_dir.mkdir(parents=True, exist_ok=True)
    session = Session(sid=sid, con=_new_connection(data_dir), data_dir=data_dir)
    SESSIONS[sid] = session
    return session


def reset_session(session: Session) -> Session:
    """Drop everything for this session and start fresh (same sid)."""
    session.con.close()
    shutil.rmtree(session.data_dir, ignore_errors=True)
    session.data_dir.mkdir(parents=True, exist_ok=True)
    fresh = Session(sid=session.sid, con=_new_connection(session.data_dir), data_dir=session.data_dir)
    SESSIONS[session.sid] = fresh
    return fresh


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


def load_file(session: Session, saved_path: Path, filename: str) -> TableMeta:
    """Load a CSV/JSON/Parquet file as a lazy DuckDB view — the view reads
    straight off disk, nothing is pulled into Python memory here. Format
    is detected from the extension (core.file_source), same mapping
    server.py's /upload route already used to decide whether to even
    reach this function (vs. XML, a separate parse-then-register path —
    see load_xml below)."""
    fmt = detect_format(filename)
    name = _sanitize_name(filename, session.tables)
    session.con.execute(
        f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM {build_read_expr(str(saved_path))}'
    )
    meta = TableMeta(
        name=name, format=fmt,
        columns=_columns_of(session.con, name),
        row_count=_row_count_of(session.con, name),
        source_file=filename,
    )
    session.tables[name] = meta
    return meta


def load_xml(session: Session, raw_text: str, filename: str) -> TableMeta:
    """DuckDB has no native XML reader. Parse once via the same
    core/normalizer.py logic DataDiff Pro uses, build a DataFrame, and
    register it into DuckDB as a view. This fully loads the XML into
    Python memory once — an accepted ceiling matching DataDiff Pro's own
    XML scope (single root element), not silently hidden.
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

    name = _sanitize_name(filename, session.tables)
    frame_var = f"_frame_{name}"
    session.frames[frame_var] = df
    session.con.register(frame_var, df)
    session.con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM {frame_var}')
    meta = TableMeta(
        name=name, format="xml",
        columns=_columns_of(session.con, name),
        row_count=_row_count_of(session.con, name),
        source_file=filename,
    )
    session.tables[name] = meta
    return meta


def remove_table(session: Session, name: str) -> None:
    meta = session.tables.pop(name, None)
    if meta is None:
        raise QueryError(f"No loaded table named '{name}'")
    session.con.execute(f'DROP VIEW IF EXISTS "{name}"')
    frame_var = f"_frame_{name}"
    if frame_var in session.frames:
        session.con.unregister(frame_var)
        del session.frames[frame_var]


PREVIEW_ROWS = 20


def preview_table(session: Session, name: str) -> dict[str, Any]:
    """First PREVIEW_ROWS rows of a loaded source, straight off the view —
    no _result involved, this is independent of whatever query was last run.
    """
    if name not in session.tables:
        raise QueryError(f"No loaded table named '{name}'")
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
    started = time.perf_counter()
    try:
        session.con.execute(f"CREATE OR REPLACE TEMP TABLE _result AS {body}")
    except duckdb.Error as exc:
        raise QueryError(_friendly_error(exc, session)) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    columns = _columns_of(session.con, "_result")
    total = _row_count_of(session.con, "_result")
    session.result_columns = columns
    session.result_total_rows = total
    session.has_result = True

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
    rows = session.con.execute(
        f'SELECT * FROM _result LIMIT {limit} OFFSET {offset}'
    ).fetchall()
    columns = session.result_columns or []
    return {
        "columns": columns,
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
    if not session.has_result:
        raise QueryError("Run a query first")
    out_path = session.data_dir / f"export_{uuid.uuid4().hex}.{fmt}"
    if fmt == "csv":
        session.con.execute(f"COPY _result TO '{out_path}' (FORMAT CSV, HEADER)")
    elif fmt == "json":
        session.con.execute(f"COPY _result TO '{out_path}' (FORMAT JSON, ARRAY true)")
    elif fmt == "parquet":
        session.con.execute(f"COPY _result TO '{out_path}' (FORMAT PARQUET)")
    else:
        raise QueryError(f"Unsupported export format: {fmt}")
    return out_path
