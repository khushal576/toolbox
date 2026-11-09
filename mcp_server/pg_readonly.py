"""
mcp_server/pg_readonly.py — SELECT-only access to a saved Postgres connection (ADR D6, D10).

Two independent guards, both required:
  1. sql-studio's query_guard decides what the statement IS (exactly one statement, SELECT / WITH / VALUES / TABLE — no COPY,
     no DML, no DDL);
  2. the SESSION is read-only (`default_transaction_read_only`, psycopg `read_only=True`), with a statement timeout — so even a
     `SELECT … INTO`, a data-modifying CTE or a function that writes is refused by the database itself.
Rows are read through a server-side cursor and never more than max_rows+1 are pulled, whatever the query returns.
The database user should ALSO be read-only (docs/runbook.md) — a third, outside guard.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .safety import ToolError

REPO = Path(__file__).resolve().parent.parent
ALLOWED_KEYWORDS = {"SELECT", "WITH", "VALUES", "TABLE"}


def guard_module():
    """sql_studio.query_guard (the image's name for sql-studio/) — or the file itself in a source checkout."""
    try:
        from sql_studio import query_guard as g  # type: ignore
        return g
    except ImportError:
        spec = importlib.util.spec_from_file_location("sql_studio_query_guard", REPO / "sql-studio" / "query_guard.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


def check_select(sql: str) -> str:
    """The single statement to run, or ToolError (refused). Only Postgres is supported in this version."""
    from core.db.registry import get_dialect

    g = guard_module()
    try:
        statements = g.split_statements(sql)
        if not statements:
            raise ToolError("The query is empty.")
        if len(statements) > 1:
            raise ToolError("Run exactly one statement at a time.", refused=True)
        stmt = statements[0]
        cls = g.classify(stmt, get_dialect("postgres"))
    except g.GuardError as exc:
        raise ToolError(str(exc), refused=True) from None
    if cls.keyword not in ALLOWED_KEYWORDS:
        raise ToolError(f"Only SELECT queries run here (this one starts with {cls.keyword or 'something else'}).",
                        hint="Reading is allowed; changing data needs an owner grant (planned roadmap session K4).",
                        refused=True)
    return stmt


def run_select(data: dict, sql: str, *, max_rows: int, seconds: int) -> dict[str, Any]:
    """{columns: [{name, type}], rows: [[…]], more: bool}. `data` is the decrypted connection (stays in this function)."""
    import psycopg

    from core.postgres_conn import build_conninfo, open_ssh_tunnel, scrub_password, ssh_tunnel_from_dict

    if (data.get("db_type") or "postgres") != "postgres":
        raise ToolError(f"This version of run_query supports PostgreSQL connections only (this one is {data.get('db_type')}).",
                        hint="SQL Server / Oracle are available in SQL Studio; stage the table into Vault Data to query it here.")
    stmt = check_select(sql)
    tunnel = None
    host, port = data["host"], int(data.get("port") or 5432)
    try:
        tcfg = ssh_tunnel_from_dict(data.get("ssh_tunnel"))
        if tcfg is not None:
            tunnel = open_ssh_tunnel(tcfg, remote_host=host, remote_port=port)
            host, port = "127.0.0.1", tunnel.local_bind_port
        conninfo = build_conninfo(host, port, data["database"], data["username"], data["password"],
                                  statement_timeout_ms=seconds * 1000)
        with psycopg.connect(conninfo, connect_timeout=10,
                             options=f"-c statement_timeout={seconds * 1000} -c default_transaction_read_only=on "
                                     f"-c idle_in_transaction_session_timeout={(seconds + 10) * 1000}") as con:
            con.read_only = True
            with con.cursor(name="mcp_readonly") as cur:  # server-side: the server streams, we pull a few rows
                cur.itersize = max_rows + 1
                cur.execute(stmt)
                rows = cur.fetchmany(max_rows + 1)
                desc = cur.description or []
                types = con.adapters.types
                cols = []
                for d in desc:
                    t = types.get(d.type_code)
                    cols.append({"name": d.name, "type": t.name if t else str(d.type_code)})
            con.rollback()
        more = len(rows) > max_rows
        return {"columns": cols, "rows": [list(r) for r in rows[:max_rows]], "more": more}
    except psycopg.errors.QueryCanceled:
        raise ToolError(f"The query ran longer than {seconds} s and was cancelled by the database.",
                        hint="Add a WHERE/LIMIT or an index-friendly filter.") from None
    except psycopg.errors.ReadOnlySqlTransaction:
        raise ToolError("The database refused it: this session is read-only.", refused=True) from None
    except psycopg.Error as exc:
        msg = scrub_password(str(exc)).strip().splitlines()[0][:400] if str(exc).strip() else type(exc).__name__
        # the database itself said "that is a write / not allowed here": a refusal, not a failure
        blocked = isinstance(exc, (psycopg.errors.FeatureNotSupported, psycopg.errors.ActiveSqlTransaction,
                                   psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)) \
            or "not allowed" in msg.lower()
        raise ToolError(msg, refused=blocked) from None
    except OSError as exc:  # tunnel / socket problems
        raise ToolError(f"Could not reach the database: {scrub_password(str(exc))[:200]}") from None
    finally:
        if tunnel is not None:
            try:
                tunnel.stop()
            except Exception:  # noqa: BLE001
                pass
