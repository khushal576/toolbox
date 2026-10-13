"""
data-syncer/engine.py

The resumable sync loop. Pure orchestration: it reads/writes progress via
state_store, talks to databases only through sync_ops, and reports through
a `log(level, message, table=None)` callback (runner.py turns that into the
bounded ring buffer the UI shows) — so it runs identically from a thread
inside the web app or from a plain script/test.

Per table, per chunk (a key range — see sync_ops.py for why a range and not
LIMIT):

    1. find the chunk's upper bound          (source, read-only, cheap)
    2. record `inflight` (copy mode)         (SQLite)
    3. stream the chunk source -> target     (ONE target transaction)
    4. advance last_key, rows_done           (SQLite, one transaction)
    5. check the stop flag

Crash safety, honestly: steps 3 and 4 are in two different databases and
cannot be atomic. Dying between them leaves the chunk written but not
recorded. Upsert mode doesn't care — re-running a chunk just rewrites the
same rows. Copy mode would hit duplicate keys, which is exactly what the
`inflight` marker is for: whatever range was in flight gets deleted from
the target before it is copied again. A STOP request also aborts a chunk
mid-stream (the target transaction rolls back, nothing partial is kept), so
Stop is quick even with a huge batch size.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import psycopg

try:  # package import when mounted inside the toolbox (data_syncer.*)
    from data_syncer import connections, state_store as store
    from data_syncer.connections import Endpoint
    from data_syncer.sync_ops import get_ops
except ImportError:  # flat import when run standalone from within this folder
    import connections
    import state_store as store
    from connections import Endpoint
    from sync_ops import get_ops

try:
    from core.postgres_conn import scrub_password
except ImportError:
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.postgres_conn import scrub_password

LogFn = Callable[..., None]  # log(level, message, table=None)

# Only transient/connection-level failures are worth retrying. A constraint
# violation, a missing column, bad data: retrying just repeats it.
RETRYABLE = (psycopg.OperationalError, psycopg.InterfaceError, OSError, TimeoutError, connections.ConnectionError_)


class Stopped(Exception):
    """Raised inside a run when the stop flag is set."""


class TableFailed(Exception):
    """A table cannot continue; the message is user-facing."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg(exc: BaseException) -> str:
    text = scrub_password(str(exc)).strip() or exc.__class__.__name__
    text = " ".join(text.split())
    return text[:600]


def _key_str(key: Optional[list]) -> str:
    return ", ".join("NULL" if v is None else str(v) for v in key) if key else "—"


def _fmt(n: Optional[int]) -> str:
    return f"{n:,}" if n is not None else "?"


# ------------------------------------------------------------------ ordering

def order_tables(tables: list[dict], edges: list[tuple[tuple[str, str], tuple[str, str]]]) -> tuple[list[dict], list[str]]:
    """Parents before children (target-side foreign keys), otherwise keeping
    the user's order. Returns (ordered, notes) — notes name any cycle or
    self-reference, which no ordering can fix (those need deferrable
    constraints on the target)."""
    ident = {(t["target_schema"], t["target_table"]): i for i, t in enumerate(tables)}
    parents: dict[int, set[int]] = {i: set() for i in range(len(tables))}
    notes: list[str] = []
    for child, parent in edges:
        if child in ident and parent in ident:
            c, p = ident[child], ident[parent]
            if c == p:
                notes.append(f"{child[0]}.{child[1]} has a foreign key to itself — rows must arrive parent-first or the target must defer the constraint.")
            else:
                parents[c].add(p)
    ordered: list[dict] = []
    placed: set[int] = set()
    remaining = list(range(len(tables)))
    while remaining:
        ready = [i for i in remaining if parents[i] <= placed]
        if not ready:
            names = ", ".join(f"{tables[i]['target_schema']}.{tables[i]['target_table']}" for i in remaining)
            notes.append(f"Foreign-key cycle among: {names} — kept in your order; loads may fail unless constraints are deferrable.")
            ordered += [tables[i] for i in remaining]
            break
        pick = ready[0]  # stable: first in the user's order that is ready
        ordered.append(tables[pick])
        placed.add(pick)
        remaining.remove(pick)
    return ordered, notes


# ------------------------------------------------------------------ one table

def _cleanup_inflight(ops: Any, tgt: Endpoint, project: dict, t: dict, log: LogFn, tkey: list[str]) -> None:
    """Copy mode only: delete whatever a cut-off chunk may have left in the
    target. Uses the range that was RECORDED, not the one we'd compute now
    (the batch size or the source may have changed since). *tkey* is the key's
    column names ON THE TARGET (they can differ from the source's by spaces)."""
    fresh = store.get_table(t["id"])
    inflight = fresh["inflight"] if fresh else None
    if not inflight or project["mode"] != "copy" or not tkey:
        return
    target = (t["target_schema"], t["target_table"])
    t_info = ops.table_info(tgt.conn, *target)
    key_types = ops.key_types(t_info, tkey)
    n = ops.delete_range(tgt.conn, target, tkey, key_types, inflight["lower"], inflight["upper"])
    if n:
        log("warn", f"removed {n:,} row(s) left by an interrupted chunk before re-copying it", t["name"])


def sync_table(project: dict, t: dict, ops: Any, src: Endpoint, tgt: Endpoint, stop: threading.Event, log: LogFn) -> None:
    name = t["name"]
    mode = project["mode"]
    source = (t["source_schema"], t["source_table"])
    target = (t["target_schema"], t["target_table"])
    key_cols: list[str] = t["key_columns"]

    pf = ops.preflight_table(src.conn, tgt.conn, mode=mode, source=source, target=target, key_cols=key_cols)
    for w in pf["warnings"]:
        log("warn", w, name)
    if pf["errors"]:
        raise TableFailed(" ".join(pf["errors"]))

    # The resolved mapping: SOURCE names for reading, TARGET names for writing. Usually identical;
    # they differ when names differ only by leading/trailing spaces (preflight warned about it).
    plan = pf["info"]["plan"]
    cols, tcols = plan["cols"], plan["tcols"]
    key, tkey, key_types = plan["key"], plan["tkey"], plan["key_types"]
    approx = pf["info"]["approx_rows"]
    store.update_table(t["id"], approx_total=approx)

    lower: Optional[list] = t["last_key"]
    fresh_start = lower is None

    # Stale in-flight marker from a cut-off run: undo before anything else.
    _cleanup_inflight(ops, tgt, project, t, log, tkey)

    if mode == "copy" and fresh_start:
        if project["truncate_target"]:
            ops.truncate_target(tgt.conn, target)
            log("warn", "target truncated (project option 'truncate target first')", name)
        elif ops.target_has_rows(tgt.conn, target):
            raise TableFailed(
                "Copy mode needs an EMPTY target table to start from the beginning, but it already has rows. "
                "Empty it yourself, enable 'truncate target first' on the project, or use upsert mode."
            )

    ops.begin_table(tgt.conn, mode=mode, target=target, cols=tcols)
    log("info", f"started — {'resuming after key ' + _key_str(lower) if lower else 'from the beginning'}"
                f" ({mode}, ~{_fmt(approx)} rows)", name)

    def check_stop() -> None:
        if stop.is_set():
            raise Stopped()

    t0 = time.monotonic()
    rows_done = t["rows_done"]
    need_reconnect = False
    cleanup_pending = False
    attempts = 0

    while True:
        check_stop()
        upper: Optional[list] = None
        res: dict[str, int] = {}
        while True:  # attempts at THIS chunk
            try:
                if need_reconnect:
                    src.reconnect()
                    tgt.reconnect()
                    ops.begin_table(tgt.conn, mode=mode, target=target, cols=tcols)
                    need_reconnect = False
                if cleanup_pending:
                    _cleanup_inflight(ops, tgt, project, t, log, tkey)
                    cleanup_pending = False
                if key_cols:
                    upper = ops.next_upper(src.conn, source, key, key_types, lower, project["batch_size"])
                    if mode == "copy":
                        store.update_table(t["id"], inflight={"lower": lower, "upper": upper})
                else:
                    upper = None  # no key: the whole table is one chunk
                res = ops.transfer_chunk(
                    src.conn, tgt.conn, mode=mode, source=source, target=target, cols=cols, tcols=tcols,
                    key_cols=key, tkey_cols=tkey, key_types=key_types, lower=lower, upper=upper, on_block=check_stop,
                )
                break
            except Stopped:
                raise
            except RETRYABLE as exc:
                attempts += 1
                if attempts > project["max_retries"]:
                    raise TableFailed(f"gave up after {project['max_retries']} retries: {_msg(exc)}") from exc
                delay = min(2 ** attempts, 30)
                log("warn", f"chunk failed ({_msg(exc)}) — retry {attempts}/{project['max_retries']} in {delay}s", name)
                need_reconnect = True
                cleanup_pending = mode == "copy"
                if stop.wait(delay):
                    raise Stopped()
            except Exception as exc:  # noqa: BLE001 — data/constraint/programming errors: no point retrying
                text = _msg(exc)
                if "cannot affect row a second time" in text:
                    text = ("The key is not unique in the source: the same key value appears more than once "
                            "within one batch, so the upsert is ambiguous. Choose a truly unique key. (" + text[:120] + ")")
                raise TableFailed(text) from exc
        attempts = 0

        last = upper
        if upper is None:  # final, open-ended chunk: record where the table really ended
            last = (ops.max_key(src.conn, source, key) if key and res["read"] else None) or lower
        store.advance(t["id"], last_key=last, rows_added=res["read"])
        rows_done += res["read"]
        elapsed = max(time.monotonic() - t0, 1e-6)
        pct = f" ({min(100, rows_done * 100 // approx)}%)" if approx and approx > 0 else ""
        changed = f", {res['written']:,} changed" if mode == "upsert" else ""
        if upper is None and res["read"] == 0 and rows_done:
            break  # row count was an exact multiple of the batch size: nothing left, nothing to report
        log("info", f"+{res['read']:,} rows{changed} → {rows_done:,} of ~{_fmt(approx)}{pct}"
                    f" · {int(rows_done / elapsed):,} rows/s · key {_key_str(last)}", name)
        if upper is None:
            break
        lower = upper

    store.update_table(t["id"], status="done", error=None, finished_at=_now(), inflight=None)
    log("ok", f"done — {rows_done:,} rows", name)


# ------------------------------------------------------------------ one run

def open_endpoints(project: dict) -> tuple[Any, Endpoint, Endpoint, dict, dict]:
    src_data = connections.resolve(project["source_conn_id"], project["source_conn_name"])
    tgt_data = connections.resolve(project["target_conn_id"], project["target_conn_name"])
    ops = get_ops(src_data.get("db_type"))
    if (tgt_data.get("db_type") or "postgres").lower() != (src_data.get("db_type") or "postgres").lower():
        raise connections.ConnectionError_("Source and target must be the same database type (cross-engine sync is not supported yet).")
    src = Endpoint(src_data, read_only=True, label="source")
    tgt = Endpoint(tgt_data, read_only=False, label="target")
    return ops, src, tgt, src_data, tgt_data


def _decorate(tables: list[dict]) -> list[dict]:
    for t in tables:
        t["name"] = f"{t['source_schema']}.{t['source_table']}"
    return tables


def run_project(project_id: str, stop: threading.Event, log: LogFn) -> dict:
    """Run (or resume) every runnable table of a project, in FK order, until
    done, stopped, or — if the project says so — the first failure. Returns a
    {done, failed, stopped} summary. Never raises for per-table problems;
    raises only if the run cannot even start (missing project/connection)."""
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    ops, src, tgt, src_data, tgt_data = open_endpoints(project)
    summary = {"done": 0, "failed": 0, "stopped": 0, "skipped": 0}
    try:
        log("info", f"source  {connections.describe(src_data)}")
        log("info", f"target  {connections.describe(tgt_data)}")
        src.open()
        tgt.open()
        tables = _decorate(store.list_tables(project_id))
        edges = ops.foreign_key_edges(tgt.conn)
        ordered, notes = order_tables(tables, edges)
        for n in notes:
            log("warn", n)
        todo = [t for t in ordered if t["status"] in store.RUNNABLE]
        log("info", f"{len(todo)} table(s) to run, {len(tables) - len(todo)} already done/skipped")
        for t in todo:
            if stop.is_set():
                break
            store.update_table(t["id"], status="running", error=None, started_at=t["started_at"] or _now())
            try:
                sync_table(project, t, ops, src, tgt, stop, log)
                summary["done"] += 1
            except Stopped:
                store.update_table(t["id"], status="stopped")
                log("warn", "stopped — position saved, Start continues from here", t["name"])
                summary["stopped"] += 1
                break
            except Exception as exc:  # noqa: BLE001 — TableFailed or anything unforeseen
                text = _msg(exc)
                store.update_table(t["id"], status="failed", error=text)
                log("error", f"FAILED — {text}", t["name"])
                summary["failed"] += 1
                if project["stop_on_failure"]:
                    log("error", "stopping the run (project option 'stop on first failure')")
                    break
        log("info", f"run finished — {summary['done']} done, {summary['failed']} failed, {summary['stopped']} stopped")
    finally:
        src.close()
        tgt.close()
    return summary


def preflight_project(project_id: str) -> dict:
    """Read-only dry check of every table (no data moved). Powers the UI's
    Preflight button — same checks the engine runs before each table."""
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    ops, src, tgt, src_data, tgt_data = open_endpoints(project)
    results: list[dict] = []
    try:
        src.open()
        tgt.open()
        tables = _decorate(store.list_tables(project_id))
        ordered, notes = order_tables(tables, ops.foreign_key_edges(tgt.conn))
        for t in ordered:
            pf = ops.preflight_table(
                src.conn, tgt.conn, mode=project["mode"],
                source=(t["source_schema"], t["source_table"]), target=(t["target_schema"], t["target_table"]),
                key_cols=t["key_columns"],
            )
            if project["mode"] == "copy" and not pf["errors"] and t["last_key"] is None and not t["inflight"]:
                if not project["truncate_target"] and ops.target_has_rows(tgt.conn, (t["target_schema"], t["target_table"])):
                    pf["errors"].append("Target already has rows (copy mode starts from an empty table).")
            results.append({"id": t["id"], "name": t["name"], **{k: pf[k] for k in ("errors", "warnings")},
                            "approx_rows": pf["info"].get("approx_rows")})
    finally:
        src.close()
        tgt.close()
    return {
        "source": connections.describe(src_data), "target": connections.describe(tgt_data),
        "mode": project["mode"], "order_notes": notes, "tables": results,
        "ok": all(not r["errors"] for r in results),
    }
