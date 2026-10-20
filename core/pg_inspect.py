"""
core/pg_inspect.py

Small read-only Postgres catalog helpers shared by Schema Copy and Data Dumper
(moved here from schema-copy/catalog.py when the second consumer appeared).
All take an already-open psycopg connection; nothing here writes.
"""

from __future__ import annotations

from typing import Any

import psycopg

# schemas that are never copied or compared
_USER_SCHEMA = "n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'"


def _ext_member(classid: str, alias: str) -> str:
    """SQL predicate: this catalog row belongs to an extension."""
    return (
        f"EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = '{classid}'::regclass AND d.objid = {alias}.oid "
        "AND d.deptype = 'e')"
    )


def _rows(conn: psycopg.Connection, query: str, params: Any = None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    conn.rollback()  # never leave a read transaction open
    return rows


def server_info(conn: psycopg.Connection) -> dict:
    num = int(_rows(conn, "SHOW server_version_num")[0][0])
    text = _rows(conn, "SHOW server_version")[0][0]
    return {"major": num // 10000, "text": text}


def available_extensions(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in _rows(conn, "SELECT name FROM pg_available_extensions")}


def target_objects(conn: psycopg.Connection, limit: int = 15) -> tuple[int, list[str]]:
    """What already lives in the user schemas of a would-be-empty target:
    (total count, a sample of names). An empty `public` schema is normal."""
    q = f"""
        SELECT kind, name FROM (
          SELECT CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view' WHEN 'S' THEN 'sequence'
                                WHEN 'f' THEN 'foreign table' WHEN 'c' THEN 'composite type' ELSE 'table' END AS kind,
                 n.nspname || '.' || c.relname AS name
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE c.relkind IN ('r','p','v','m','S','f','c') AND {_USER_SCHEMA} AND NOT {_ext_member('pg_class', 'c')}
          UNION ALL
          SELECT 'function', n.nspname || '.' || p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE {_USER_SCHEMA} AND NOT {_ext_member('pg_proc', 'p')}
          UNION ALL
          SELECT 'type', n.nspname || '.' || t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE t.typtype IN ('e','d','r','m') AND {_USER_SCHEMA} AND NOT {_ext_member('pg_type', 't')}
        ) x ORDER BY 2
    """
    rows = _rows(conn, q)
    return len(rows), [f"{k} {n}" for k, n in rows[:limit]]
