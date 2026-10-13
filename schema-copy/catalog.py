"""
schema-copy/catalog.py

Read-only catalog queries (psycopg, via an already-open core.db_endpoint
Endpoint connection). Nothing here writes to a database.

`object_names()` is the heart of the post-copy report: it returns, per
category, the SET of object identifiers (e.g. every index as
`schema.index_name`, every function as `schema.name(arg types)`). Running it
on source and target and diffing the sets proves "everything was copied"
better than comparing counts — a missing index and an extra one would cancel
out in a count. Objects that belong to an extension are excluded everywhere
(their existence follows `CREATE EXTENSION`, and their versions can differ
legitimately between servers).
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


def list_schemas(conn: psycopg.Connection) -> list[dict]:
    """Every user schema with how much is in it — what the project editor lists."""
    schemas: dict[str, dict[str, Any]] = {
        r[0]: {"schema": r[0], "tables": 0, "views": 0, "matviews": 0, "sequences": 0, "foreign_tables": 0, "functions": 0}
        for r in _rows(conn, f"SELECT n.nspname FROM pg_namespace n WHERE {_USER_SCHEMA} ORDER BY 1")
    }
    kinds = {"r": "tables", "p": "tables", "v": "views", "m": "matviews", "S": "sequences", "f": "foreign_tables"}
    for schema, kind, n in _rows(
        conn,
        f"SELECT n.nspname, c.relkind, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE c.relkind IN ('r','p','v','m','S','f') AND NOT c.relispartition AND {_USER_SCHEMA} "
        f"AND NOT {_ext_member('pg_class', 'c')} GROUP BY 1, 2",
    ):
        if schema in schemas:
            schemas[schema][kinds[kind]] += n
    for schema, n in _rows(
        conn,
        f"SELECT n.nspname, count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        f"WHERE {_USER_SCHEMA} AND NOT {_ext_member('pg_proc', 'p')} GROUP BY 1",
    ):
        if schema in schemas:
            schemas[schema]["functions"] = n
    return list(schemas.values())


def list_extensions(conn: psycopg.Connection) -> list[dict]:
    return [
        {"name": r[0], "schema": r[1], "version": r[2]}
        for r in _rows(
            conn,
            "SELECT e.extname, n.nspname, e.extversion FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE e.extname <> 'plpgsql' ORDER BY 1",
        )
    ]


def available_extensions(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in _rows(conn, "SELECT name FROM pg_available_extensions")}


def foreign_tables(conn: psycopg.Connection, schemas: list[str]) -> list[tuple[str, str]]:
    return [
        (r[0], r[1])
        for r in _rows(
            conn,
            "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'f' AND n.nspname = ANY(%s) ORDER BY 1, 2",
            (schemas,),
        )
    ]


def sequence_values(conn: psycopg.Connection, schemas: list[str]) -> list[tuple[str, str, int]]:
    """(schema, sequence, last_value) for sequences that have been used and whose
    value this role may read (pg_sequences shows NULL otherwise)."""
    return [
        (r[0], r[1], r[2])
        for r in _rows(
            conn,
            "SELECT schemaname, sequencename, last_value FROM pg_sequences "
            "WHERE schemaname = ANY(%s) AND last_value IS NOT NULL ORDER BY 1, 2",
            (schemas,),
        )
    ]


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


# category -> SQL returning one identifier column; %(schemas)s is the selected schema list
_NAME_QUERIES: dict[str, str] = {
    "tables": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r','p') AND NOT c.relispartition AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "partitions": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r','p') AND c.relispartition AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "columns": f"""SELECT n.nspname || '.' || c.relname || '.' || a.attname FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m') AND n.nspname = ANY(%(s)s)
          AND NOT {_ext_member('pg_class', 'c')}""",
    "indexes": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('i','I') AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "primary keys": """SELECT n.nspname || '.' || c.relname || '.' || k.conname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE k.contype = 'p' AND n.nspname = ANY(%(s)s)""",
    "unique constraints": """SELECT n.nspname || '.' || c.relname || '.' || k.conname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE k.contype = 'u' AND n.nspname = ANY(%(s)s)""",
    "foreign keys": """SELECT n.nspname || '.' || c.relname || '.' || k.conname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE k.contype = 'f' AND n.nspname = ANY(%(s)s)""",
    "check constraints": """SELECT n.nspname || '.' || c.relname || '.' || k.conname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE k.contype = 'c' AND n.nspname = ANY(%(s)s)""",
    "exclusion constraints": """SELECT n.nspname || '.' || c.relname || '.' || k.conname FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE k.contype = 'x' AND n.nspname = ANY(%(s)s)""",
    "views": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'v' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "materialized views": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'm' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "sequences": f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'S' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_class', 'c')}""",
    "functions": f"""SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prokind = 'f' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_proc', 'p')}""",
    "procedures": f"""SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prokind = 'p' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_proc', 'p')}""",
    "aggregates": f"""SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prokind = 'a' AND n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_proc', 'p')}""",
    "triggers": """SELECT n.nspname || '.' || c.relname || '.' || t.tgname FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal AND n.nspname = ANY(%(s)s)""",
    "types": f"""SELECT n.nspname || '.' || t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        LEFT JOIN pg_class c ON c.oid = t.typrelid
        WHERE n.nspname = ANY(%(s)s) AND NOT {_ext_member('pg_type', 't')}
          AND (t.typtype IN ('e','d','r','m') OR (t.typtype = 'c' AND c.relkind = 'c'))""",
    "policies": """SELECT n.nspname || '.' || c.relname || '.' || p.polname FROM pg_policy p
        JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%(s)s)""",
    "rules": """SELECT n.nspname || '.' || c.relname || '.' || r.rulename FROM pg_rewrite r
        JOIN pg_class c ON c.oid = r.ev_class JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE r.rulename <> '_RETURN' AND n.nspname = ANY(%(s)s)""",
}

CATEGORIES = list(_NAME_QUERIES)


def object_names(conn: psycopg.Connection, schemas: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for cat, q in _NAME_QUERIES.items():
        out[cat] = {r[0] for r in _rows(conn, q, {"s": schemas})}
    out["extensions"] = {e["name"] for e in list_extensions(conn)}
    return out


def compare(src: dict[str, set[str]], tgt: dict[str, set[str]], sample: int = 20) -> list[dict]:
    """One row per category: counts on both sides, and (a sample of) what is
    missing from / extra in the target."""
    rows = []
    for cat in [*CATEGORIES, "extensions"]:
        s, t = src.get(cat, set()), tgt.get(cat, set())
        missing, extra = sorted(s - t), sorted(t - s)
        if not s and not t:
            continue  # nothing of this kind on either side: not worth a row
        rows.append({
            "category": cat, "source": len(s), "target": len(t), "ok": not missing and not extra,
            "missing": missing[:sample], "missing_total": len(missing),
            "extra": extra[:sample], "extra_total": len(extra),
        })
    return rows
