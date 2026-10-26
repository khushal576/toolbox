"""
data-lake/query.py — SQL over Vault Data (roadmap L3, "Athena" style).

Every query gets a fresh in-memory DuckDB in which ONLY the tables it names are mounted, as views called
`workspace.table` (a schema per workspace): managed tables read their Parquet parts, external tables their files in
place (core.lake.read_expr). A table name without a workspace works when exactly one workspace has it.

Read-only by construction: one statement, and it must be a SELECT (EXPLAIN in front is fine) — checked on DuckDB's
own parse tree (`json_serialize_sql`), which also lists every table and table function the query uses. Files can't
be read directly (`read_csv('/etc/…')`, `FROM 'file.csv'`): only workspace tables and harmless generators
(`range`, `generate_series`, `unnest`). `CREATE [OR REPLACE] TABLE ws.t AS SELECT …` is the one write: the SELECT
runs like any other and its result becomes a managed table through core.lake (this tool's `data: write` scope).

Every result is written to a Parquet file in S3 storage (FileCache "data-lake-results", kept RESULT_DAYS) so any
process can page through it, download it or save it as a table later without running the query again. History and
saved queries live in Toolbox's Postgres (schema `data_lake`).

    plan = analyse("SELECT * FROM sales.orders o JOIN crm.customers c USING (customer_id)")
    record = execute(new_id(), plan, mode="instant")       # in the web process, TIMEOUT seconds at most
    run_query_job(ctx, query_id, sql)                       # the same as a worker job (no time limit)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core import lake as lake_store
from core.state.filecache import FileCache
from core.state.sqlstore import SqlStore

INSTANT_SECONDS = float(os.environ.get("DATA_LAKE_INSTANT_SECONDS", "30"))
INSTANT_MEMORY = os.environ.get("DATA_LAKE_QUERY_MEMORY", "384MB")      # web process (rt-data): spills above this
JOB_MEMORY = os.environ.get("DATA_LAKE_MEMORY_LIMIT", "1GB")            # worker
RESULT_DAYS = float(os.environ.get("DATA_LAKE_RESULT_DAYS", "7"))
HISTORY_KEEP = 500
PAGE_MAX = 1000
ALLOWED_FUNCTIONS = {"range", "generate_series", "unnest"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    sql TEXT NOT NULL,
    mode TEXT NOT NULL,                 -- instant | background
    state TEXT NOT NULL,                -- queued | running | done | failed
    started_at TEXT NOT NULL,
    finished_at TEXT,
    seconds REAL,
    row_count INTEGER,
    columns TEXT,                       -- JSON [{name, type}]
    result_bytes INTEGER,
    tables TEXT,                        -- JSON ["ws.t", ...]
    saved_as TEXT,                      -- "ws.t" after CREATE TABLE AS / Save as table
    error TEXT
);
CREATE TABLE IF NOT EXISTS saved (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sql TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

STORE = SqlStore("data_lake", sqlite_path=lake_store.DATA_DIR / "data_lake.db", ddl=_SCHEMA)
RESULTS = FileCache("data-lake-results", Path(os.environ.get("DATA_LAKE_RESULTS_DIR", "/tmp/data-lake-results")))
_ready = False
_ready_lock = threading.Lock()


class QueryError(ValueError):
    pass


def _connect():
    global _ready
    if not _ready:
        with _ready_lock:
            if not _ready:
                STORE.init()
                _ready = True
    return STORE.connect()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def result_name(qid: str) -> str:
    return f"{qid}.parquet"


# ---- reading the SQL -------------------------------------------------------------------------------------------

_CTAS = re.compile(r"^\s*create\s+(or\s+replace\s+)?table\s+(\"?)([A-Za-z_][A-Za-z0-9_]*)\2\s*\.\s*(\"?)"
                   r"([A-Za-z_][A-Za-z0-9_]*)\4\s+as\s+(.+)$", re.I | re.S)
_EXPLAIN = re.compile(r"^\s*explain(\s+analyze)?\s+", re.I)


@dataclass
class Plan:
    sql: str                                  # what the user typed (trailing ';' removed)
    select: str                               # the SELECT that runs
    explain: bool = False
    target: Optional[tuple[str, str]] = None  # CREATE TABLE ws.t AS …
    replace: bool = False
    tables: dict[tuple[str, str], dict] = field(default_factory=dict)   # (schema to mount in, name) → lake table


def _walk(node: Any, out: dict[str, list]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("cte_map"), dict):
            out["ctes"] += [e.get("key", "").lower() for e in node["cte_map"].get("map", [])]
        t = node.get("type")
        if t == "BASE_TABLE":
            out["refs"].append((node.get("catalog_name") or "", node.get("schema_name") or "", node.get("table_name") or ""))
        elif t == "TABLE_FUNCTION":
            out["funcs"].append(((node.get("function") or {}).get("function_name") or "").lower())
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def _strip(sql: str) -> str:
    return re.sub(r"[\s;]+$", "", sql or "").strip()


def analyse(sql: str, lookup: Optional[Callable[[str, str], dict]] = None,
            find: Optional[Callable[[str], list[dict]]] = None) -> Plan:
    """Check the query and work out which lake tables it needs. Raises QueryError with a message for people."""
    import duckdb

    sql = _strip(sql)
    if not sql:
        raise QueryError("Write a query first.")
    lookup = lookup or lake_store.get_table
    find = find or _find_table
    con = duckdb.connect(":memory:")
    try:
        try:
            statements = con.extract_statements(sql)
        except duckdb.Error as exc:
            raise QueryError(_first_line(exc)) from None
        if len(statements) != 1:
            raise QueryError("Run one statement at a time.")
        plan = Plan(sql=sql, select=sql)
        m = _CTAS.match(sql)
        if m:
            plan.replace, plan.target, plan.select = bool(m.group(1)), (m.group(3).lower(), m.group(5).lower()), m.group(6)
            for part, what in zip(plan.target, ("workspace name", "table name")):
                try:
                    lake_store.check_name(part, what)
                except lake_store.LakeError as exc:
                    raise QueryError(str(exc)) from None
        e = _EXPLAIN.match(plan.select)
        if e and not m:
            plan.explain, plan.select = True, plan.select[e.end():]
        tree = json.loads(con.execute("SELECT json_serialize_sql(?)", [plan.select]).fetchone()[0])
    finally:
        con.close()
    if tree.get("error"):
        msg = tree.get("error_message") or "Could not read the query."
        if "Only SELECT" in msg:
            msg = ("Only SELECT queries run here — data is changed by loading files, or with "
                   "CREATE TABLE workspace.table AS SELECT …")
        raise QueryError(msg)
    found: dict[str, list] = {"ctes": [], "refs": [], "funcs": []}
    _walk(tree, found)
    for f in found["funcs"]:
        if f not in ALLOWED_FUNCTIONS:
            raise QueryError(f"{f}(…) isn't available here: files are read by loading them into a table first (or "
                             f"as a read-in-place table in the Data Lake). Allowed: {', '.join(sorted(ALLOWED_FUNCTIONS))}.")
    ctes = set(found["ctes"])
    for catalog, schema, name in found["refs"]:
        schema, name = schema.lower(), name.lower()
        if catalog:
            raise QueryError(f"Use workspace.table names ('{catalog}.{schema}.{name}' has three parts).")
        if not schema and name in ctes:
            continue
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or (schema and not re.fullmatch(r"[a-z_][a-z0-9_]*", schema)):
            raise QueryError(f"'{name}' isn't a table: files can't be read directly — load them into a table first.")
        if schema:
            try:
                plan.tables[(schema, name)] = lookup(schema, name)
            except lake_store.NotFound:
                raise QueryError(f"Table {schema}.{name} doesn't exist.") from None
        else:
            hits = find(name)
            if not hits:
                raise QueryError(f"Table '{name}' doesn't exist — write it as workspace.table.")
            if len(hits) > 1:
                raise QueryError(f"'{name}' is in several workspaces ({', '.join(t['full_name'] for t in hits)}) — "
                                 f"write it as workspace.table.")
            plan.tables[("main", name)] = hits[0]
    return plan


def _find_table(name: str) -> list[dict]:
    return [t for w in lake_store.list_workspaces() for t in lake_store.list_tables(w["name"]) if t["name"] == name]


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:500] if str(exc).strip() else type(exc).__name__


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


# ---- running ---------------------------------------------------------------------------------------------------

def _record(qid: str, **cols: Any) -> None:
    cols = {k: (json.dumps(v) if k in ("columns", "tables") and v is not None else v) for k, v in cols.items()}
    with _connect() as con:
        if con.execute("SELECT 1 FROM queries WHERE id = ?", (qid,)).fetchone():
            if cols:
                con.execute(f"UPDATE queries SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                            (*cols.values(), qid))
        else:
            keys = ["id", *cols]
            con.execute(f"INSERT INTO queries ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                        (qid, *cols.values()))


def start_record(qid: str, sql: str, mode: str, state: str) -> None:
    _record(qid, sql=_strip(sql), mode=mode, state=state, started_at=_now())


def execute(qid: str, plan: Plan, *, mode: str = "instant", timeout: Optional[float] = None,
            cancel: Optional[threading.Event] = None, progress: Optional[dict] = None,
            log: Optional[Callable[..., None]] = None) -> dict[str, Any]:
    """Run a checked query, store its result (Parquet) and record it. Returns the history record.
    Raises QueryError (recorded as failed) when DuckDB refuses it, it is stopped, or it runs past `timeout`."""
    import duckdb

    log = log or (lambda *a: None)
    progress = progress if progress is not None else {}
    lake = lake_store.scoped("data-lake")
    t0 = time.monotonic()
    names = sorted({t["full_name"] for t in plan.tables.values()})
    try:
        get(qid)
    except lake_store.NotFound:
        start_record(qid, plan.sql, mode, "running")
    _record(qid, state="running", tables=names)
    work = Path(tempfile.mkdtemp(prefix="lake_query_", dir=os.environ.get("DATA_LAKE_TMP")))
    con = duckdb.connect(":memory:")
    why = {"stop": None}
    done = threading.Event()
    try:
        con.execute(f"SET memory_limit = '{INSTANT_MEMORY if mode == 'instant' else JOB_MEMORY}'")
        con.execute(f"SET temp_directory = '{work / 'spill'}'")
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("SET autoload_known_extensions = false")
        if mode == "instant":
            con.execute("SET threads = 2")
        progress["phase"] = "reading tables"
        for (schema, name), t in plan.tables.items():
            expr = lake.read_expr(t["workspace"], t["name"])  # managed: downloads its parts once per process
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote(schema)}")
            con.execute(f"CREATE VIEW {_quote(schema)}.{_quote(name)} AS SELECT * FROM {expr}")
        con.execute("SET lock_configuration = true")
        log("info", "tables: " + (", ".join(names) or "none"))

        def watch():
            while not done.wait(0.5):  # (DuckDB 1.2's Python API reports no progress: the page shows elapsed time)
                if cancel is not None and cancel.is_set():
                    why["stop"] = "Stopped."
                elif timeout and time.monotonic() - t0 > timeout:
                    why["stop"] = (f"Took longer than {timeout:g} s — use “Run in background” for big queries "
                                   f"(no time limit, you can close the page).")
                if why["stop"]:
                    try:
                        con.interrupt()
                    except Exception:  # noqa: BLE001
                        pass
                    return

        threading.Thread(target=watch, daemon=True).start()
        progress["phase"] = "running"
        out = work / result_name(qid)
        try:
            if plan.explain:
                rows = con.execute(plan.sql).fetchall()
                con.execute("CREATE TEMP TABLE _plan (explain_key VARCHAR, explain_value VARCHAR)")
                con.executemany("INSERT INTO _plan VALUES (?, ?)", [(str(r[0]), str(r[1])) for r in rows])
                con.execute(f"COPY _plan TO '{out}' (FORMAT PARQUET)")
            else:
                # Parquet has no 128-bit integers (sum() of BIGINT gives one) and DuckDB would store them as DOUBLE:
                # keep whole numbers exact as DECIMAL(38,0) instead
                huge = [r[0] for r in con.execute(f"DESCRIBE {plan.select}").fetchall() if r[1] in ("HUGEINT", "UHUGEINT")]
                select = plan.select
                if huge:
                    casts = ", ".join(f"CAST({_quote(c)} AS DECIMAL(38,0)) AS {_quote(c)}" for c in huge)
                    select = f"SELECT * REPLACE ({casts}) FROM ({plan.select})"
                con.execute(f"COPY ({select}) TO '{out}' (FORMAT PARQUET)")
        except duckdb.InterruptException:
            raise QueryError(why["stop"] or "Stopped.") from None
        except duckdb.Error as exc:
            if why["stop"]:
                raise QueryError(why["stop"]) from None
            raise QueryError(_first_line(exc)) from None
        finally:
            done.set()
        cols = [{"name": r[0], "type": r[1]} for r in
                con.execute(f"DESCRIBE SELECT * FROM read_parquet('{out}')").fetchall()]
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
        progress["phase"] = "storing result"
        RESULTS.local_dir.mkdir(parents=True, exist_ok=True)
        out = Path(shutil.move(str(out), RESULTS.local(result_name(qid))))  # the cache folder is the local home
        RESULTS.publish(qid, out)
        saved_as = None
        if plan.target:
            ws, name = plan.target
            t = lake.write_table(ws, name, [out], mode="overwrite" if plan.replace else "create",
                                 source={"kind": "query", "query_id": qid, "sql": plan.sql[:4000], "tables": names},
                                 create_workspace_if_missing=True)
            saved_as = t["full_name"]
            log("ok", f"created {saved_as} ({t['row_count']:,} rows)")
        seconds = round(time.monotonic() - t0, 2)
        _record(qid, state="done", finished_at=_now(), seconds=seconds, row_count=int(rows), columns=cols,
                result_bytes=out.stat().st_size, saved_as=saved_as)
        progress.update(phase="done", rows=int(rows), seconds=seconds)
        log("ok", f"{rows:,} row(s) in {seconds} s")
        return get(qid)
    except (QueryError, lake_store.LakeError) as exc:
        _record(qid, state="failed", finished_at=_now(), seconds=round(time.monotonic() - t0, 2), error=str(exc))
        progress.update(phase="failed", error=str(exc))
        log("error", str(exc))
        raise QueryError(str(exc)) from None
    finally:
        done.set()
        con.close()
        shutil.rmtree(work, ignore_errors=True)
        _tidy()


def run_query_job(ctx: Any, qid: str, sql: str) -> None:
    """Worker job body (JobRunner): the same query without a time limit."""
    try:
        plan = analyse(sql)
    except QueryError as exc:
        _record(qid, state="failed", finished_at=_now(), error=str(exc))
        ctx.progress.update(phase="failed", error=str(exc))
        ctx.log("error", str(exc))
        return
    try:
        execute(qid, plan, mode="background", cancel=ctx.cancel, progress=ctx.progress, log=ctx.log)
    except QueryError:
        pass  # recorded + logged by execute


_last_tidy = [0.0]


def _tidy() -> None:
    """Old results out of storage, old history rows out of Postgres — at most every 10 minutes per process."""
    if time.monotonic() - _last_tidy[0] < 600:
        return
    _last_tidy[0] = time.monotonic()
    try:
        RESULTS.sweep(None, RESULT_DAYS * 86400)
        with _connect() as con:
            old = con.execute("SELECT id FROM queries ORDER BY started_at DESC LIMIT -1 OFFSET ?"
                              if STORE.backend == "sqlite" else
                              "SELECT id FROM queries ORDER BY started_at DESC OFFSET ?", (HISTORY_KEEP,)).fetchall()
            for r in old:
                con.execute("DELETE FROM queries WHERE id = ?", (r["id"],))
    except Exception:  # noqa: BLE001 - tidying never fails a query
        pass


# ---- results ---------------------------------------------------------------------------------------------------

def _row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["columns"] = json.loads(d["columns"]) if d.get("columns") else []
    d["tables"] = json.loads(d["tables"]) if d.get("tables") else []
    return d


def get(qid: str) -> dict[str, Any]:
    with _connect() as con:
        r = con.execute("SELECT * FROM queries WHERE id = ?", (qid,)).fetchone()
    if r is None:
        raise lake_store.NotFound("Unknown query.")
    return _row(r)


def result_file(qid: str) -> Path:
    q = get(qid)
    if q["state"] != "done":
        raise QueryError("This query has no result.")
    p = RESULTS.fetch(qid, result_name(qid))
    if p is None:
        raise QueryError(f"The result is gone (results are kept {RESULT_DAYS:g} days) — run the query again.")
    return p


def page(qid: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    import duckdb

    p = result_file(qid)
    limit, offset = max(1, min(int(limit), PAGE_MAX)), max(0, int(offset))
    con = duckdb.connect(":memory:")
    try:
        cur = con.execute(f"SELECT * FROM read_parquet('{p}') LIMIT {limit} OFFSET {offset}")
        cols = [d[0] for d in cur.description]
        rows = json.loads(json.dumps(cur.fetchall(), default=_json_value))
    finally:
        con.close()
    return {"columns": cols, "rows": rows, "offset": offset}


def _json_value(v: Any) -> Any:
    """Decimals a browser number holds exactly — whole numbers < 2**53, others with ≤ 15 significant digits — as
    numbers; longer ones as exact text."""
    from decimal import Decimal

    if isinstance(v, Decimal) and v.is_finite():
        if v == v.to_integral_value() and abs(v) < 2**53:
            return int(v)
        if len(v.normalize().as_tuple().digits) <= 15:
            return float(v)
    return str(v)


def export_csv(qid: str, dest: Path) -> Path:
    import duckdb

    p = result_file(qid)
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"COPY (SELECT * FROM read_parquet('{p}')) TO '{dest}' (FORMAT CSV, HEADER)")
    finally:
        con.close()
    return dest


def save_as_table(qid: str, workspace: str, name: str, mode: str = "create") -> dict[str, Any]:
    q = get(qid)
    t = lake_store.scoped("data-lake").write_table(
        workspace, name, [result_file(qid)], mode=mode, create_workspace_if_missing=True,
        source={"kind": "query", "query_id": qid, "sql": q["sql"][:4000], "tables": q["tables"]})
    _record(qid, saved_as=t["full_name"])
    return t


def history(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM queries ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    return [_row(r) for r in rows]


def forget(qid: str) -> None:
    RESULTS.remove_all(qid)
    with _connect() as con:
        con.execute("DELETE FROM queries WHERE id = ?", (qid,))


# ---- saved queries ---------------------------------------------------------------------------------------------

def list_saved() -> list[dict[str, Any]]:
    with _connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM saved ORDER BY name").fetchall()]


def save_query(name: str, sql: str, description: str = "") -> dict[str, Any]:
    name, sql = (name or "").strip(), _strip(sql)
    if not name or len(name) > 120:
        raise QueryError("Give the query a name (up to 120 characters).")
    if not sql:
        raise QueryError("There is no SQL to save.")
    now = _now()
    with _connect() as con:
        old = con.execute("SELECT id FROM saved WHERE name = ?", (name,)).fetchone()
        if old:
            con.execute("UPDATE saved SET sql = ?, description = ?, updated_at = ? WHERE id = ?",
                        (sql, description, now, old["id"]))
            sid = old["id"]
        else:
            sid = new_id()
            con.execute("INSERT INTO saved (id, name, sql, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (sid, name, sql, description, now, now))
        return dict(con.execute("SELECT * FROM saved WHERE id = ?", (sid,)).fetchone())


def delete_saved(sid: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM saved WHERE id = ?", (sid,))
