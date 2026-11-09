"""
mcp_server/scriptgen.py — turn rows into an INSERT script (ADR D8, roadmap K3).

PURE: text in, text out. This module imports no database driver, opens no connection and runs nothing — "generate_insert_script
never executes the script" is true by construction (and a test asserts the module has no I/O imports). Running the script is the
owner's job, in SQL Studio or their own client.

Accuracy rules (ADR D14): every value is rendered from its real Python type (Decimal stays exact, dates stay dates, bytes stay
bytes), strings are escaped for the target dialect, a value that cannot be represented exactly is REFUSED (never silently changed),
and the caller refuses to build a script for a partial result.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

DIALECTS = ("postgres", "mssql", "oracle")
BATCH = {"postgres": 500, "mssql": 500, "oracle": 1}   # rows per INSERT statement (SQL Server caps VALUES at 1000; Oracle: one per row)
_IDENT_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]{0,127}$")


class ScriptError(ValueError):
    """A value or name that cannot be turned into SQL exactly."""


def quote_ident(name: str, dialect: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name or len(name) > 128:
        raise ScriptError(f"Invalid column name {name!r}.")
    if dialect == "mssql":
        return "[" + name.replace("]", "]]") + "]"
    return '"' + name.replace('"', '""') + '"'


def target_name(raw: str, dialect: str) -> str:
    """'schema.table' (1–3 parts) → quoted, only plain identifiers accepted (no quotes, spaces or punctuation to smuggle SQL in)."""
    parts = (raw or "").strip().split(".")
    if not 1 <= len(parts) <= 3 or not all(_IDENT_PART.match(p) for p in parts):
        raise ScriptError("target_table must be a plain name like orders or sales.orders (letters, digits, _ $ # only).")
    return ".".join(quote_ident(p, dialect) for p in parts)


def _str_lit(s: str, dialect: str) -> str:
    if "\x00" in s:
        raise ScriptError("A text value contains a NUL character, which SQL text cannot hold; clean it in the query first.")
    q = s.replace("'", "''")
    if dialect == "mssql":
        return "N'" + q + "'"
    if dialect == "postgres" and "\\" in q:
        return "E'" + q.replace("\\", "\\\\") + "'"   # correct whether or not standard_conforming_strings is on
    return "'" + q + "'"


def literal(v: Any, dialect: str) -> str:
    """One value as a SQL literal for *dialect*; raises ScriptError rather than approximate."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return ("TRUE" if v else "FALSE") if dialect == "postgres" else ("1" if v else "0")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, decimal.Decimal):
        if not v.is_finite():
            raise ScriptError(f"Non-finite decimal {v} cannot be written exactly for {dialect}.")
        return format(v, "f")
    if isinstance(v, float):
        if not math.isfinite(v):
            if dialect == "postgres":
                return {"nan": "'NaN'::float8", "inf": "'Infinity'::float8", "-inf": "'-Infinity'::float8"}[
                    "nan" if v != v else ("inf" if v > 0 else "-inf")]
            raise ScriptError(f"A float value ({v}) has no exact {dialect} literal; filter or convert it in the query.")
        return repr(v)
    if isinstance(v, dt.datetime):
        aware = v.tzinfo is not None
        iso = v.isoformat(sep=" ")
        if dialect == "postgres":
            return f"'{iso}'::{'timestamptz' if aware else 'timestamp'}"
        if dialect == "mssql":
            return f"CAST('{iso}' AS {'datetimeoffset' if aware else 'datetime2'})"
        naive = v.replace(tzinfo=None).isoformat(sep=" ")
        if not aware:
            return f"TIMESTAMP '{naive}'"
        off = v.strftime("%z")  # +0530 → +05:30
        return f"TIMESTAMP '{naive} {off[:3]}:{off[3:]}'"
    if isinstance(v, dt.date):
        return {"postgres": f"'{v.isoformat()}'::date", "mssql": f"CAST('{v.isoformat()}' AS date)", "oracle": f"DATE '{v.isoformat()}'"}[dialect]
    if isinstance(v, dt.time):
        if dialect == "oracle":
            raise ScriptError("Oracle has no TIME type; convert the column to text or a timestamp in the query.")
        return f"'{v.isoformat()}'::time" if dialect == "postgres" else f"CAST('{v.isoformat()}' AS time)"
    if isinstance(v, dt.timedelta):
        if dialect != "postgres":
            raise ScriptError(f"Intervals have no portable {dialect} literal; convert them to a number or text in the query.")
        return f"'{v.days} days {v.seconds} seconds {v.microseconds} microseconds'::interval"
    if isinstance(v, (bytes, bytearray, memoryview)):
        h = bytes(v).hex()
        return {"postgres": f"'\\x{h}'::bytea", "mssql": "0x" + h if h else "0x", "oracle": f"HEXTORAW('{h}')"}[dialect]
    if isinstance(v, uuid.UUID):
        return _str_lit(str(v), dialect)
    if isinstance(v, (dict, list, tuple)):
        return _str_lit(json.dumps(v, ensure_ascii=False, default=str), dialect)
    return _str_lit(str(v), dialect)


@dataclass
class Script:
    sql: str
    rows: int
    statements: int
    warnings: list[str]


def build_script(columns: Sequence[str], rows: Sequence[Sequence[Any]], *, table: str, dialect: str = "postgres",
                 transaction: bool = True, header: Sequence[str] = ()) -> Script:
    """The whole script as text. Deterministic: the same input always gives the same output."""
    if dialect not in DIALECTS:
        raise ScriptError(f"dialect must be one of {', '.join(DIALECTS)}.")
    if not columns:
        raise ScriptError("The source has no columns.")
    if len(set(columns)) != len(columns):
        raise ScriptError("Two columns have the same name; alias them in the query.")
    tbl = target_name(table, dialect)
    cols = ", ".join(quote_ident(c, dialect) for c in columns)
    warnings: list[str] = []
    if dialect == "oracle" and any(v == "" for r in rows for v in r):
        warnings.append("Oracle stores an empty string as NULL, so empty strings in this script will arrive as NULL.")
    lines: list[str] = [f"-- {h}" for h in header]
    begin, end = {"postgres": ("BEGIN;", "COMMIT;"), "mssql": ("BEGIN TRANSACTION;", "COMMIT TRANSACTION;"), "oracle": (None, "COMMIT;")}[dialect]
    if transaction and begin:
        lines.append(begin)
    batch = BATCH[dialect]
    statements = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        for r in chunk:
            if len(r) != len(columns):
                raise ScriptError("A row has a different number of values than there are columns.")
        values = ",\n  ".join("(" + ", ".join(literal(v, dialect) for v in r) + ")" for r in chunk)
        lines.append(f"INSERT INTO {tbl} ({cols}) VALUES\n  {values};")
        statements += 1
    if transaction:
        lines.append(end)
    return Script("\n".join(lines) + "\n", len(rows), statements, warnings)
