"""
core/db/loader.py

Loads a CSV/JSON/Parquet file (e.g. a decrypted Vault dataset) INTO a
database table, for any Dialect (Postgres / SQL Server / Oracle) — the
reverse of "Export FULL result → Vault". Streams: DuckDB reads the file
and hands rows over in `batch_size` chunks, each inserted with
executemany(), so memory is bounded by one batch, not the dataset.

Column types come from DuckDB's own inference of the file (a CSV carries
no types), mapped to a sensible native type per dialect. Anything unusual
falls back to a large text type rather than failing.

Everything runs in ONE transaction on the caller's connection: any error
rolls the whole load back. Exception: Oracle auto-commits DDL, so on a
failed load into a NEW table there the (empty/partial) table is dropped
explicitly instead.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import json
import re
from typing import Any

import duckdb

from core.file_source import build_read_expr

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# DuckDB base type -> (postgres, mssql, oracle). DECIMAL(p,s) is handled
# separately below because it carries its own precision.
_TYPE_MAP: dict[str, tuple[str, str, str]] = {
    "TINYINT": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "SMALLINT": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "INTEGER": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "BIGINT": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "UTINYINT": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "USMALLINT": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "UINTEGER": ("BIGINT", "BIGINT", "NUMBER(19)"),
    "UBIGINT": ("NUMERIC(38,0)", "DECIMAL(38,0)", "NUMBER(38)"),
    "HUGEINT": ("NUMERIC(38,0)", "DECIMAL(38,0)", "NUMBER(38)"),
    "FLOAT": ("DOUBLE PRECISION", "FLOAT", "BINARY_DOUBLE"),
    "DOUBLE": ("DOUBLE PRECISION", "FLOAT", "BINARY_DOUBLE"),
    "BOOLEAN": ("BOOLEAN", "BIT", "NUMBER(1)"),
    "DATE": ("DATE", "DATE", "DATE"),
    "TIME": ("TIME", "TIME", "VARCHAR2(20)"),
    "TIMESTAMP": ("TIMESTAMP", "DATETIME2", "TIMESTAMP"),
    "TIMESTAMP WITH TIME ZONE": ("TIMESTAMPTZ", "DATETIMEOFFSET", "TIMESTAMP WITH TIME ZONE"),
    "BLOB": ("BYTEA", "VARBINARY(MAX)", "BLOB"),
}
_TEXT_FALLBACK = ("TEXT", "NVARCHAR(MAX)", "CLOB")
_DIALECT_INDEX = {"postgres": 0, "mssql": 1, "oracle": 2}


class LoadError(Exception):
    """A problem with the request itself (bad table name, table already
    exists, ...) — safe to show to the user as-is."""


def _quote(dialect_name: str, ident: str) -> str:
    if dialect_name == "mssql":
        return "[" + ident.replace("]", "]]") + "]"
    return '"' + ident.replace('"', '""') + '"'


def _fold(dialect_name: str, ident: str) -> str:
    # Oracle folds unquoted names to UPPERCASE; since every name here is
    # quoted (exact case), uppercase them so plain `SELECT * FROM mytable`
    # works afterwards, the way an Oracle user expects.
    return ident.upper() if dialect_name == "oracle" else ident


def qualified_table_name(dialect_name: str, table: str) -> str:
    parts = [p for p in table.strip().split(".")]
    if not 1 <= len(parts) <= 2 or not all(_IDENT_RE.match(p) for p in parts):
        raise LoadError(
            "Table name must be `table` or `schema.table`, using only letters, digits, _ and $ "
            "(not starting with a digit)."
        )
    return ".".join(_quote(dialect_name, _fold(dialect_name, p)) for p in parts)


def native_type(dialect_name: str, duckdb_type: str) -> str:
    idx = _DIALECT_INDEX[dialect_name]
    t = duckdb_type.upper().strip()
    m = re.match(r"^DECIMAL\((\d+),\s*(\d+)\)$", t)
    if m:
        p, s = m.groups()
        return (f"NUMERIC({p},{s})", f"DECIMAL({p},{s})", f"NUMBER({p},{s})")[idx]
    return _TYPE_MAP.get(t, _TEXT_FALLBACK)[idx]


def _convert(value: Any, dialect_name: str) -> Any:
    if value is None or isinstance(value, (str, bytes, int, float, _decimal.Decimal, _dt.date, _dt.datetime)):
        if isinstance(value, bool) and dialect_name == "oracle":
            return int(value)
        return value
    if isinstance(value, _dt.time):
        return value.isoformat() if dialect_name == "oracle" else value
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    return str(value)  # UUID, intervals, anything else DuckDB hands back


def _placeholders(dialect_name: str, n: int) -> str:
    if dialect_name == "oracle":
        return ", ".join(f":{i}" for i in range(1, n + 1))
    return ", ".join(["%s"] * n)


def load_file_into_table(
    conn: Any, dialect_name: str, file_path: str, table: str,
    *, mode: str = "create", batch_size: int = 1000,
) -> dict[str, Any]:
    """Load *file_path* into *table* on *conn* (a raw driver connection).
    mode="create": create the table (error if it exists). mode="append":
    insert into an existing table, matching columns by name. Commits on
    success, rolls back on failure. Returns {"table", "columns", "row_count"}."""
    if dialect_name not in _DIALECT_INDEX:
        raise LoadError(f"Loading data isn't supported for '{dialect_name}'.")
    if mode not in ("create", "append"):
        raise LoadError("mode must be 'create' or 'append'.")
    qtable = qualified_table_name(dialect_name, table)

    con = duckdb.connect(":memory:")
    created = False
    try:
        source = build_read_expr(file_path)
        described = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
        col_names = [row[0] for row in described]
        col_types = [row[1] for row in described]
        if not col_names:
            raise LoadError("The dataset has no columns.")
        qcols = [_quote(dialect_name, _fold(dialect_name, c)) for c in col_names]
        if len(set(qcols)) != len(qcols):
            raise LoadError("The dataset has duplicate column names (case-insensitively for this database).")

        cur = conn.cursor()
        try:
            if mode == "create":
                cols_sql = ", ".join(
                    f"{q} {native_type(dialect_name, t)}" for q, t in zip(qcols, col_types)
                )
                try:
                    cur.execute(f"CREATE TABLE {qtable} ({cols_sql})")
                except Exception as exc:  # noqa: BLE001 - driver-specific "already exists" errors
                    raise LoadError(f"Couldn't create table {table}: {exc}") from exc
                created = True
            insert_sql = (
                f"INSERT INTO {qtable} ({', '.join(qcols)}) VALUES ({_placeholders(dialect_name, len(qcols))})"
            )
            result = con.execute(f"SELECT * FROM {source}")
            row_count = 0
            while True:
                batch = result.fetchmany(batch_size)
                if not batch:
                    break
                cur.executemany(insert_sql, [[_convert(v, dialect_name) for v in row] for row in batch])
                row_count += len(batch)
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            if created and dialect_name == "oracle":  # Oracle DDL isn't transactional
                try:
                    cur.execute(f"DROP TABLE {qtable}")
                    conn.commit()
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        return {"table": table, "columns": col_names, "row_count": row_count}
    finally:
        con.close()
