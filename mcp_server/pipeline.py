"""
mcp_server/pipeline.py — the gap actions of roadmap H5 (ADR-AI-HELPER D9): query → Vault Data table, and Vault Data table → database.

  stage_query  SELECT (Vault Data or a saved Postgres connection) → a NEW / replaced Vault Data table.   needs a workspace grant (create_table / replace_table)
  load_table   Vault Data table → INSERT into an EXISTING Postgres table.                                  needs a connection grant (insert_rows)

Both follow ADR-MCP D7 exactly like table_transform: control.require FIRST (a refusal becomes a plan card, approvals.py) → DRY-RUN that shows the plan
and issues a single-use confirm_code bound to a digest of the exact data → the same call with the code writes → READ-BACK is checked, a failed read-back is an error.
Never partial: a source over the row cap (5,000; 500 for prod / unlabelled) is refused. Nothing is ever deleted; the load only appends in ONE transaction (all or nothing).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from core import lake as lake_store

from . import access, approvals, control, frame, lake_sql, pg_readonly
from .safety import Limits, ToolError, jsonable

def _digest(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _rows_hash(columns: list, rows: list) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(columns, default=str).encode())
    for r in rows:
        h.update(json.dumps(r, default=str).encode())
    return h.hexdigest()


def _refusal_to_card(refusal: ToolError, tool: str, kind: str, target: str, action: str, plan: dict, digest: str) -> ToolError:
    card = approvals.ask_owner(tool, kind, target, action, plan, digest)
    if card is None:
        return refusal
    if card["status"] == "rejected":
        return ToolError("The owner said no to this.", hint="Do not ask again unless the owner asks you to.", refused=True)
    return ToolError(refusal.args[0], refused=True,
                     hint="I have shown the owner an approval card in the Ask Claude panel (request " + card["id"] + "). Tell the owner to click Approve "
                          "(it needs their PIN), then repeat this same call. You cannot grant this yourself.")


# ---------------------------------------------------------------------------------------------------- stage_query

def stage_query(args: dict, Result: Any) -> Any:
    import pandas as pd

    from . import tools

    save_as = str(args.get("save_as") or "").strip().lower()
    mode = str(args.get("mode") or "create").strip().lower()
    token = str(args.get("confirm_code") or "").strip()
    conn = (args.get("connection") or "").strip()
    sql = str(args.get("sql") or "").strip()
    if mode not in ("create", "replace"):
        raise ToolError("'mode' must be create (a new table) or replace (the old table is kept as a backup table).")
    if not save_as:
        raise ToolError("Give 'save_as' (workspace.table): the Vault Data table to create from the query result.",
                        hint="To only look at rows without storing them, use run_query.")
    tws, tname = frame.split_table(save_as)
    try:
        lake_store.check_name(tws, "workspace name")
        lake_store.check_name(tname, "table name")
    except lake_store.LakeError as exc:
        raise ToolError(str(exc)) from None
    res, meta, lim, conns = tools._run_sql(sql, conn, None, cap="script_rows")
    if res.get("more"):
        _too_big(meta["n"], conns)
    names = [c["name"] for c in res["columns"]]
    if len(set(names)) != len(names) or any(not n for n in names):
        raise ToolError("The result has duplicate or empty column names.", hint="Give every column a unique alias (SELECT a AS a1, b AS b1).")
    df = pd.DataFrame([list(r) for r in res["rows"]], columns=names, dtype=object)
    lake = lake_store.scoped(access.PLUGIN)
    try:
        existing = lake.get_table(tws, tname)
    except lake_store.NotFound:
        existing = None
    if existing and mode == "create":
        raise ToolError(f"{tws}.{tname} already exists.", hint='Choose another name, or use mode "replace" (the old table is kept as a backup table).')
    if not existing and mode == "replace":
        raise ToolError(f"There is no table {tws}.{tname} to replace; use mode \"create\".")
    action = "replace_table" if mode == "replace" else "create_table"
    src_label = f"connection '{conns[0]['name']}' ({conns[0]['environment']})" if conns else "Vault Data"
    digest = _digest({"sql": sql, "connection": conn, "save_as": f"{tws}.{tname}", "mode": mode, "data": _rows_hash(names, res["rows"])})
    plan = {"what": ("Replace" if mode == "replace" else "Create") + f" the Vault Data table {tws}.{tname} from a query", "target": f"{tws}.{tname}", "environment": "non-prod",
            "rows": len(df), "columns": names[:30], "source": src_label, "source_environment": conns[0]["environment"] if conns else "non-prod", "sql": sql[:300],
            "replaces": ({"rows": existing.get("row_count"), "kept_as": f"{tws}.{tname}_backup_<time>"} if existing else None)}
    try:
        grant = control.require("workspace", tws, action, rows=len(df))
    except ToolError as refusal:
        raise _refusal_to_card(refusal, "stage_query", "workspace", tws, action, plan, digest) from None
    if not token:
        issued = control.issue_confirmation("stage_query", digest)
        return Result({"saved": False, "dry_run": True, "plan": plan, **issued, "sample": jsonable([list(r) for r in res["rows"][:5]]),
                       "how_to_confirm": "If this is what you want, call stage_query again with EXACTLY the same arguments plus this confirm_code. It works once, for 10 minutes, and only for this data."},
                      connections=conns, rows=len(df), grant_id=grant["id"])
    control.consume_confirmation(token, "stage_query", digest)
    try:
        out = frame.write_result(df, tws, tname, mode=mode, source={"kind": "mcp-stage-query", "connection": conn or None, "sql": sql[:2000]},
                                 description=f"Staged via Toolbox MCP from {src_label}; the query is stored in this table's source.")
    finally:
        approvals.spend(grant)
    rb = out["read_back"]
    if not rb["ok"]:
        raise ToolError(f"The table was written but the read-back check FAILED (rows match: {rb['rows_match']}, columns match: {rb['columns_match']}). Do not trust {tws}.{tname}; tell the owner."
                        + (f" The previous table is kept as {out['backup']}." if out["backup"] else ""))
    return Result({"saved": True, "table": f"{tws}.{tname}", "rows": rb["rows"], "columns": names, "backup_of_previous": out["backup"], "read_back": rb,
                   "note": "Written with the owner's permission; recorded in the audit log and in the table's history."}, connections=conns, rows=rb["rows"], grant_id=grant["id"])


def _too_big(n: int, conns: list) -> ToolError:
    e = ToolError(f"The query returns more than {n:,} rows, the most that can be staged here (prod / unlabelled connections allow fewer).",
                  hint="Add a WHERE / LIMIT, or aggregate first. A partial copy would be wrong, so nothing is staged.")
    e.connections = conns
    raise e


# ---------------------------------------------------------------------------------------------------- load_table

def _split_pg(ref: str) -> tuple[str, str]:
    ref = (ref or "").strip()
    schema, _, name = ref.rpartition(".")
    schema = schema or "public"
    for part in (schema, name):
        if not part or len(part) > 63 or not all(ch.isalnum() or ch in "_$" for ch in part):
            raise ToolError("'target_table' must be schema.table (letters, digits and underscores only), for example sales.orders.")
    return schema, name


def _pg(data: dict, *, seconds: int, read_only: bool):
    """Open a psycopg connection to a saved connection (with its SSH tunnel). Returns (connection, tunnel-or-None). Caller closes both."""
    import psycopg

    from core.postgres_conn import build_conninfo, open_ssh_tunnel, ssh_tunnel_from_dict

    if (data.get("db_type") or "postgres") != "postgres":
        raise ToolError(f"Loading supports PostgreSQL connections only (this one is {data.get('db_type')}).", hint="generate_insert_script writes an INSERT script for other databases.")
    host, port = data["host"], int(data.get("port") or 5432)
    tunnel = None
    tcfg = ssh_tunnel_from_dict(data.get("ssh_tunnel"))
    if tcfg is not None:
        tunnel = open_ssh_tunnel(tcfg, remote_host=host, remote_port=port)
        host, port = "127.0.0.1", tunnel.local_bind_port
    conninfo = build_conninfo(host, port, data["database"], data["username"], data["password"], statement_timeout_ms=seconds * 1000)
    try:
        con = psycopg.connect(conninfo, connect_timeout=10, options=f"-c statement_timeout={seconds * 1000}" + (" -c default_transaction_read_only=on" if read_only else ""))
    except Exception:
        if tunnel is not None:
            tunnel.stop()
        raise
    return con, tunnel


def _target_columns(data: dict, schema: str, name: str, seconds: int) -> list[dict]:
    from core.postgres_conn import scrub_password
    import psycopg

    con = tunnel = None
    try:
        con, tunnel = _pg(data, seconds=seconds, read_only=True)
        cur = con.execute("SELECT column_name, data_type, is_nullable, column_default IS NOT NULL AS has_default FROM information_schema.columns "
                          "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, name))
        rows = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES", "has_default": bool(r[3])} for r in cur.fetchall()]
        con.rollback()
        return rows
    except psycopg.Error as exc:
        raise ToolError(scrub_password(str(exc)).strip().splitlines()[0][:300] if str(exc).strip() else "Could not read the target table.") from None
    except OSError as exc:
        raise ToolError(f"Could not reach the database: {scrub_password(str(exc))[:200]}") from None
    finally:
        if con is not None:
            con.close()
        if tunnel is not None:
            try:
                tunnel.stop()
            except Exception:  # noqa: BLE001
                pass


def _insert(data: dict, schema: str, name: str, columns: list[str], rows: list[list], seconds: int) -> dict:
    """ONE transaction: count, insert, count again; commit only if exactly len(rows) rows were added. Returns the read-back."""
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    from core.postgres_conn import scrub_password

    def adapt(v: Any) -> Any:
        return Jsonb(v) if isinstance(v, (dict, list)) else v

    con = tunnel = None
    try:
        con, tunnel = _pg(data, seconds=seconds, read_only=False)
        tbl = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(name))
        with con.transaction():
            before = con.execute(sql.SQL("SELECT count(*) FROM {}").format(tbl)).fetchone()[0]
            q = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(tbl, sql.SQL(", ").join(map(sql.Identifier, columns)), sql.SQL(", ").join([sql.Placeholder()] * len(columns)))
            with con.cursor() as cur:
                cur.executemany(q, [[adapt(v) for v in r] for r in rows])
            after = con.execute(sql.SQL("SELECT count(*) FROM {}").format(tbl)).fetchone()[0]
            if after - before != len(rows):
                raise ToolError(f"Read-back failed inside the transaction (expected +{len(rows)} rows, saw +{after - before}); nothing was committed.")
        again = con.execute(sql.SQL("SELECT count(*) FROM {}").format(tbl)).fetchone()[0]
        con.rollback()
        return {"ok": again == after, "rows_added": len(rows), "count_before": before, "count_after": again}
    except psycopg.Error as exc:
        msg = scrub_password(str(exc)).strip().splitlines()[0][:400] if str(exc).strip() else type(exc).__name__
        raise ToolError(f"The database refused the load, so NOTHING was inserted: {msg}") from None
    except OSError as exc:
        raise ToolError(f"Could not reach the database: {scrub_password(str(exc))[:200]}") from None
    finally:
        if con is not None:
            con.close()
        if tunnel is not None:
            try:
                tunnel.stop()
            except Exception:  # noqa: BLE001
                pass


def load_table(args: dict, Result: Any) -> Any:
    conn = (args.get("connection") or "").strip()
    target = str(args.get("target_table") or "").strip()
    token = str(args.get("confirm_code") or "").strip()
    if not conn or not target or not args.get("table"):
        raise ToolError("Give 'table' (Vault Data workspace.table), 'connection' (a saved PostgreSQL connection) and 'target_table' (schema.table that already exists).")
    schema, name = _split_pg(target)
    data, pub = access.resolve_connection(conn)
    lim = Limits.for_environment(pub["environment"])
    df, t = frame.load(args["table"])
    if len(df) > lim.script_rows:
        e = ToolError(f"{t['full_name']} has {len(df):,} rows — more than the {lim.script_rows:,} that can be loaded in one go into a {pub['environment']} connection.",
                      hint="Load a smaller table, or ask the owner to raise MCP_SCRIPT_MAX_ROWS (prod: MCP_PROD_SCRIPT_MAX_ROWS).")
        e.connections = [pub]
        raise e
    only = args.get("columns")
    cols = list(df.columns) if not only else list(only)
    if only and (not isinstance(only, list) or [c for c in cols if c not in df.columns]):
        raise ToolError("'columns' must be a list of columns of the source table.", hint="Columns: " + ", ".join(map(str, df.columns)))
    tcols = _target_columns(data, schema, name, lim.seconds)
    if not tcols:
        e = ToolError(f"There is no table {schema}.{name} on connection '{conn}'.", hint="Loading only adds rows to an existing table; the owner creates the table first.")
        e.connections = [pub]
        raise e
    tnames = {c["name"] for c in tcols}
    unknown = [c for c in cols if c not in tnames]
    if unknown:
        e = ToolError(f"These source columns do not exist in {schema}.{name}: {', '.join(map(str, unknown))}.",
                      hint="Rename them with table_transform (rename step) or pass 'columns' to load only some. Target columns: " + ", ".join(sorted(tnames)))
        e.connections = [pub]
        raise e
    required = [c["name"] for c in tcols if not c["nullable"] and not c["has_default"] and c["name"] not in cols]
    if required:
        e = ToolError(f"{schema}.{name} needs a value for: {', '.join(required)} (not null, no default), which the source does not provide.")
        e.connections = [pub]
        raise e
    sub = df[cols].astype(object)
    rows = [[None if (v is None or (isinstance(v, float) and v != v) or (hasattr(v, "isoformat") and str(v) == "NaT")) else v for v in r] for r in sub.values.tolist()]
    digest = _digest({"table": t["full_name"], "version": t.get("version"), "rows": len(rows), "connection": conn, "target": f"{schema}.{name}", "columns": cols,
                      "data": _rows_hash(cols, rows)})
    plan = {"what": f"Add {len(rows):,} rows to {schema}.{name} on '{conn}'", "target": f"{schema}.{name} on {conn}", "environment": pub["environment"], "rows": len(rows),
            "columns": [str(c) for c in cols][:30], "source": t["full_name"], "not_loaded_target_columns": sorted(tnames - set(cols))[:20],
            "how": "INSERT only, in one transaction (all or nothing); nothing is updated or deleted"}
    try:
        grant = control.require("connection", conn, "insert_rows", rows=len(rows))
    except ToolError as refusal:
        refusal.connections = [pub]
        raise _refusal_to_card(refusal, "load_table", "connection", conn, "insert_rows", plan, digest) from None
    if not token:
        issued = control.issue_confirmation("load_table", digest)
        return Result({"saved": False, "dry_run": True, "plan": plan, **issued,
                       "sample": jsonable(rows[:5]), "how_to_confirm": "If this is what you want, call load_table again with EXACTLY the same arguments plus this confirm_code. "
                                                                    "It works once, for 10 minutes, and only for this data."}, connections=[pub], rows=len(rows), grant_id=grant["id"])
    control.consume_confirmation(token, "load_table", digest)
    try:
        rb = _insert(data, schema, name, [str(c) for c in cols], rows, lim.seconds)
    finally:
        approvals.spend(grant)
    if not rb["ok"]:
        raise ToolError(f"The rows were inserted but the final count check FAILED; tell the owner to check {schema}.{name} on '{conn}'.")
    return Result({"saved": True, "inserted": rb["rows_added"], "target": f"{schema}.{name}", "connection": conn, "count_before": rb["count_before"], "count_after": rb["count_after"],
                   "read_back": rb, "note": "Inserted in one transaction with the owner's permission; recorded in the audit log."}, connections=[pub], rows=rb["rows_added"], grant_id=grant["id"])
