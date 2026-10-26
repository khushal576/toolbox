"""
data-lake/staging.py — stage database tables into a Vault Data workspace (roadmap L4, "migration staging").

A saved Vault connection (kind `postgres_connection`, `db_type` postgres | mssql | oracle, SSH tunnel aware) is
opened read-only, each chosen table (or one SELECT) is streamed out in batches of BATCH_ROWS with the dialect's
export cursor (server-side cursor on Postgres — bounded memory), every batch becomes a small Parquet file (pyarrow;
a column pyarrow can't type is stored as text; json/arrays as JSON text), and DuckDB merges the batches into the table's Parquet parts
(`union_by_name`, so a column that was NULL in the first batch still gets its real type). The source database is
only read: SELECTs only, and Postgres sessions are set read-only.

    spec = {"connection_id": "...", "workspace": "migration_staging", "mode": "create|overwrite|append",
            "tables": ["public.orders", "public.customers"]}            # each → table `orders`, `customers`
         | {..., "sql": "SELECT ... FROM ...", "table": "open_orders"}   # one query → one table
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

from core import lake as lake_store
from core import vault as vault_store

BATCH_ROWS = int(os.environ.get("DATA_LAKE_STAGE_BATCH", "50000"))
MEMORY_LIMIT = os.environ.get("DATA_LAKE_MEMORY_LIMIT", "1GB")
PART_BYTES = os.environ.get("DATA_LAKE_PART_SIZE", "256MB")
CONNECTION_KIND = "postgres_connection"   # what the Vault / SQL Studio save, for every db_type


class StageError(ValueError):
    pass


def _vault():
    return vault_store.scoped("data-lake")


def list_connections() -> list[dict[str, Any]]:
    """Saved database connections (metadata only — nothing decrypted)."""
    return [{"id": s["id"], "name": s["name"]} for s in _vault().list_secrets(CONNECTION_KIND)]


def _quote(db_type: str, ident: str) -> str:
    if db_type == "mssql":
        return "[" + ident.replace("]", "]]") + "]"
    return '"' + ident.replace('"', '""') + '"'


@contextlib.contextmanager
def connect(connection_id: str) -> Iterator[tuple[Any, Any, dict]]:
    """(connection, dialect, saved data) for a Vault connection — SSH tunnel opened first when the entry has one."""
    from core.db.registry import get_dialect
    from core.postgres_conn import open_ssh_tunnel, scrub_password, ssh_tunnel_from_dict

    vault = _vault()
    try:
        d = {**vault.get_secret(connection_id),
             "name": next((c["name"] for c in list_connections() if c["id"] == connection_id), "connection")}
    except (vault.SecretNotFound, vault.ScopeError):  # (a dataset id or another kind looks like a missing one)
        raise StageError("That Vault connection doesn't exist any more.") from None
    db_type = (d.get("db_type") or "postgres").lower()
    dialect = get_dialect(db_type)
    tunnel = pool = None
    try:
        host, port = d["host"], int(d.get("port") or dialect.default_port)
        cfg = ssh_tunnel_from_dict(d.get("ssh_tunnel"))
        if cfg is not None:
            tunnel = open_ssh_tunnel(cfg, remote_host=host, remote_port=port)
            host, port = "127.0.0.1", tunnel.local_bind_port
        conninfo = dialect.build_conninfo(host, port, d["database"], d["username"], d["password"])
        dialect.verify_connection(conninfo, connect_timeout=15)
        pool = dialect.open_pool(conninfo, max_size=1, timeout=15)
        with dialect.checkout(pool) as conn:
            if db_type == "postgres":
                conn.read_only = True  # staging never writes to the source
            yield conn, dialect, d
    except StageError:
        raise
    except Exception as exc:  # noqa: BLE001 — one clean, password-free message
        raise StageError(f"{d.get('name') or 'connection'}: {scrub_password(str(exc)).splitlines()[0][:400]}") from None
    finally:
        if pool is not None:
            with contextlib.suppress(Exception):
                dialect.close_pool(pool)
        if tunnel is not None:
            with contextlib.suppress(Exception):
                tunnel.stop()


def list_tables(connection_id: str) -> list[dict[str, Any]]:
    """The connection's user tables: [{schema, table, full_name, columns}] (system schemas filtered by the dialect)."""
    with connect(connection_id) as (conn, dialect, _d):
        cur = conn.cursor()
        cur.execute(dialect.list_tables_sql())
        rows = cur.fetchall()
        with contextlib.suppress(Exception):
            conn.commit()
    out: dict[tuple[str, str], dict] = {}
    for schema, table, _col, _type in rows:
        t = out.setdefault((schema, table), {"schema": schema, "table": table, "full_name": f"{schema}.{table}",
                                             "columns": 0})
        t["columns"] += 1
    return list(out.values())


def target_names(tables: list[str]) -> dict[str, str]:
    """'public.orders' → 'orders'; when two schemas share a table name both get the schema prefix."""
    bare = [t.split(".")[-1] for t in tables]
    return {t: lake_store.safe_name(t.replace(".", "_") if bare.count(t.split(".")[-1]) > 1 else t.split(".")[-1])
            for t in tables}


def _check_select(sql: str) -> str:
    sql = re.sub(r"[\s;]+$", "", sql or "").strip()
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip()
    if not re.match(r"(?is)^(select|with)\b", body):
        raise StageError("Only a SELECT (or WITH … SELECT) can be staged.")
    if ";" in re.sub(r"'(?:[^']|'')*'", "''", body):
        raise StageError("Stage one statement at a time.")
    return sql


def _cell(v: Any) -> Any:
    if hasattr(v, "read"):  # Oracle LOBs → str/bytes
        return v.read()
    if isinstance(v, (dict, list)):  # json/jsonb, arrays: JSON text (query with json_extract) — same type every batch
        return json.dumps(v, default=str)
    return v


def _batch_to_parquet(rows: list, cols: list[str], dest: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    arrays = []
    for i in range(len(cols)):
        values = [_cell(r[i]) for r in rows]
        try:
            arrays.append(pa.array(values))
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError, OverflowError):
            arrays.append(pa.array([None if v is None else str(v) for v in values], type=pa.string()))
    pq.write_table(pa.Table.from_arrays(arrays, names=cols), dest)


def _dump(conn: Any, dialect: Any, sql: str, work: Path, ctx: Any, label: str) -> tuple[list[Path], list[str], int]:
    """Stream one SELECT into batch Parquet files. Returns (files, columns, rows)."""
    cur = dialect.open_export_cursor(conn, f"stage_{os.urandom(4).hex()}", batch_size=BATCH_ROWS)
    files, rows_total = [], 0
    with cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        if len(set(cols)) != len(cols):
            raise StageError(f"{label}: the result has duplicate column names — give them aliases.")
        while True:
            if ctx.cancel.is_set():
                raise StageError("Stopped.")
            batch = cur.fetchmany(BATCH_ROWS)
            if not batch:
                break
            dest = work / f"b{len(files):06d}.parquet"
            _batch_to_parquet(batch, cols, dest)
            files.append(dest)
            rows_total += len(batch)
            ctx.progress["rows"] = ctx.progress.get("rows_done", 0) + rows_total
    with contextlib.suppress(Exception):
        conn.commit()
    return files, cols, rows_total


def _merge(batches: list[Path], cols: list[str], out_dir: Path, work: Path) -> list[Path]:
    """Batches → the table's Parquet parts (one schema for all; an empty result keeps its columns)."""
    import duckdb

    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
        con.execute(f"SET temp_directory = '{work / 'spill'}'")
        if batches:
            files = ", ".join("'" + str(b).replace("'", "''") + "'" for b in batches)
            src = f"SELECT * FROM read_parquet([{files}], union_by_name = true)"
        else:
            src = "SELECT " + ", ".join(f"NULL::VARCHAR AS {_quote('postgres', c)}" for c in cols) + " WHERE false"
        con.execute(f"COPY ({src}) TO '{out_dir}' (FORMAT PARQUET, FILE_SIZE_BYTES '{PART_BYTES}')")
    finally:
        con.close()
    parts = sorted(out_dir.rglob("*.parquet"))
    if not parts:  # DuckDB writes nothing for zero rows into a directory: write one empty file
        con = duckdb.connect(":memory:")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            cols_sql = ", ".join(f"NULL::VARCHAR AS {_quote('postgres', c)}" for c in cols) or "NULL AS x"
            con.execute(f"COPY (SELECT {cols_sql} WHERE false) TO '{out_dir / 'empty.parquet'}' (FORMAT PARQUET)")
        finally:
            con.close()
        parts = [out_dir / "empty.parquet"]
    return parts


def run_stage(ctx: Any, spec: dict[str, Any]) -> None:
    """Worker job body (JobRunner): stage tables or one query into a workspace."""
    log, p = ctx.log, ctx.progress
    t0 = time.monotonic()
    lake = lake_store.scoped("data-lake")
    ws, mode = spec["workspace"], spec.get("mode") or "create"
    work_root = Path(tempfile.mkdtemp(prefix="lake_stage_", dir=os.environ.get("DATA_LAKE_TMP")))
    done: list[dict] = []
    try:
        if spec.get("sql"):
            jobs = [(lake_store.check_name(spec["table"], "table name"), _check_select(spec["sql"]), "query")]
        else:
            tables = spec.get("tables") or []
            if not tables:
                raise StageError("Choose at least one table.")
            names = target_names(tables)
            jobs = [(names[full], None, full) for full in tables]
        p.update(phase="connecting", tables_total=len(jobs), tables_done=0, rows=0, rows_done=0)
        with connect(spec["connection_id"]) as (conn, dialect, d):
            db_type = (d.get("db_type") or "postgres").lower()
            log("info", f"connected to {d.get('name') or 'database'} ({db_type}) — read-only")
            for i, (target, sql, label) in enumerate(jobs):
                if sql is None:
                    schema, _, table = label.rpartition(".")
                    sql = f"SELECT * FROM {_quote(db_type, schema) + '.' if schema else ''}{_quote(db_type, table)}"
                p.update(phase=f"reading {label}", current=label)
                work = work_root / f"t{i}"
                work.mkdir()
                batches, cols, rows = _dump(conn, dialect, sql, work, ctx, label)
                p["phase"] = f"storing {ws}.{target}"
                parts = _merge(batches, cols, work / "parts", work)
                t = lake.write_table(ws, target, parts, mode=mode, create_workspace_if_missing=True, source={
                    "kind": "database", "connection": d.get("name"), "db_type": db_type,
                    **({"table": label} if label != "query" else {"sql": sql[:4000]})})
                shutil.rmtree(work, ignore_errors=True)
                p.update(tables_done=i + 1, rows_done=p.get("rows_done", 0) + rows)
                done.append({"table": t["full_name"], "rows": rows, "source": label})
                log("ok", f"{label} → {t['full_name']}: {rows:,} rows")
        p.update(phase="done", tables=done, seconds=round(time.monotonic() - t0, 1), rows=p.get("rows_done", 0))
        log("ok", f"staged {len(done)} table(s), {p['rows']:,} rows in {p['seconds']} s")
    except (StageError, lake_store.LakeError, ValueError) as exc:
        p.update(phase="failed", error=str(exc), tables=done)
        log("error", str(exc))
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
