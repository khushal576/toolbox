"""
mcp_server/lake_sql.py — read-only SQL over Vault Data (ADR D6).

Reuses data-lake/query.py's `analyse()` (the parse-tree check: exactly one SELECT, only workspace tables, no file-reading
functions) and its way of mounting only the named tables into a fresh in-memory DuckDB. Unlike the Data Lake runner this one
stores nothing: no result file, no history row — the MCP audit log is the record.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from core import lake as lake_store

from .access import PLUGIN
from .safety import ToolError

REPO = Path(__file__).resolve().parent.parent
MEMORY = os.environ.get("MCP_QUERY_MEMORY", "384MB")


def query_module():
    """data_lake.query (the image's name for data-lake/) — or the file itself when run from a source checkout."""
    try:
        from data_lake import query as q  # type: ignore
        return q
    except ImportError:
        spec = importlib.util.spec_from_file_location("data_lake_query", REPO / "data-lake" / "query.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def run_select(sql: str, *, max_rows: int, seconds: int) -> dict[str, Any]:
    """{columns: [{name, type}], rows: [[…]], more: bool, tables: [...]}. Raises ToolError for anything not allowed."""
    import duckdb

    q = query_module()
    try:
        plan = q.analyse(sql)
    except q.QueryError as exc:
        raise ToolError(str(exc), hint="Only one SELECT over workspace.table names is allowed here.", refused=True) from None
    except lake_store.LakeError as exc:
        raise ToolError(str(exc), refused=True) from None
    if plan.target:
        raise ToolError("CREATE TABLE … AS is a write, and writes are off for the AI by default.",
                        hint="Run a SELECT. Saving results needs an owner grant (planned roadmap session K4).", refused=True)
    lake = lake_store.scoped(PLUGIN)
    work = Path(tempfile.mkdtemp(prefix="mcp_query_", dir=os.environ.get("DATA_LAKE_TMP")))
    con = duckdb.connect(":memory:")
    done = threading.Event()
    stop = {"why": None}
    try:
        con.execute(f"SET memory_limit = '{MEMORY}'")
        con.execute(f"SET temp_directory = '{work / 'spill'}'")
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("SET autoload_known_extensions = false")
        con.execute("SET threads = 2")
        try:
            for (schema, name), t in plan.tables.items():
                lake.prepare(con, t)
                expr = lake.read_expr(t["workspace"], t["name"])
                con.execute(f"CREATE SCHEMA IF NOT EXISTS {_q(schema)}")
                con.execute(f"CREATE VIEW {_q(schema)}.{_q(name)} AS SELECT * FROM {expr}")
        except lake_store.LakeError as exc:
            raise ToolError(str(exc)) from None
        con.execute("SET lock_configuration = true")
        t0 = time.monotonic()

        def watch() -> None:
            while not done.wait(0.25):
                if time.monotonic() - t0 > seconds:
                    stop["why"] = f"The query ran longer than {seconds} s and was stopped."
                    try:
                        con.interrupt()
                    except Exception:  # noqa: BLE001
                        pass
                    return

        threading.Thread(target=watch, daemon=True).start()
        try:
            types = None
            if not plan.explain:  # exact SQL types (DECIMAL(12,2), TIMESTAMP …); the DB-API cursor only says NUMBER / STRING
                types = [r[1] for r in con.execute(f"DESCRIBE {plan.select}").fetchall()]
            cur = con.execute(plan.sql if plan.explain else plan.select)
            cols = [{"name": d[0], "type": (types[i] if types and i < len(types) else str(d[1]))}
                    for i, d in enumerate(cur.description)]
            rows = cur.fetchmany(max_rows + 1)
        except duckdb.InterruptException:
            raise ToolError(stop["why"] or "The query was stopped.", hint="Add a WHERE/LIMIT or aggregate first.") from None
        except duckdb.Error as exc:
            if stop["why"]:
                raise ToolError(stop["why"]) from None
            msg = str(exc).strip().splitlines()[0][:400] if str(exc).strip() else type(exc).__name__
            raise ToolError(msg, hint="Check column names with vault_list / vault_dataset_preview.") from None
        more = len(rows) > max_rows
        return {"columns": cols, "rows": [list(r) for r in rows[:max_rows]], "more": more,
                "tables": sorted({t["full_name"] for t in plan.tables.values()})}
    finally:
        done.set()
        con.close()
        shutil.rmtree(work, ignore_errors=True)
