"""
data-syncer/sync_ops.py

Everything database-specific the syncer needs, behind one small class per
database (`PostgresSyncOps` today) and a `get_ops(db_type)` lookup — the
same shape as core/db's `Dialect` registry, kept separate because
`Dialect` is about connecting/introspecting/read-capping and has no notion
of writing at all. A future MSSQL/Oracle implementation adds a class here
(`MERGE` instead of `ON CONFLICT`, bcp/SQL*Loader instead of `COPY`); the
engine (engine.py) never changes.

THE ONE TRICK EVERYTHING HERE RESTS ON — a "chunk" is a key range
`(lower, upper]`, and it moves as raw bytes, never as Python rows:

    source:  COPY (SELECT cols FROM src WHERE key > lower AND key <= upper) TO STDOUT
    target:  COPY <destination> FROM STDIN

 * copy mode   — destination is the real target table. Pure bulk load.
 * upsert mode — destination is a TEMP staging table, then one
                 `INSERT ... SELECT ... ON CONFLICT DO UPDATE` merges it.

Why this shape (decided, not defaulted):
 * Postgres's text COPY format round-trips EVERY type (numeric precision,
   timestamps, json, arrays, enums, bytea) without Python ever parsing a
   value — so "same data, same types" is exact by construction, and memory
   per chunk is a few KiB of stream buffer regardless of batch size.
 * Chunks are key RANGES found via one cheap boundary query (below), not
   `LIMIT n`: a LIMIT cut can split rows sharing the same key value across
   two batches and silently lose some; a range never does. It also makes
   every chunk re-runnable (same range -> same rows) which is what makes
   resume safe.
 * Keys are stored/compared as TEXT and cast back (`%s::<column type>`)
   inside SQL, so any key type (int, uuid, timestamptz, text, composite)
   survives the SQLite state store with no per-type serialization code.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import psycopg
from psycopg import sql

Key = Optional[list]  # list[str] of key values as text; None = "from the very beginning"


def _ident(schema: str, table: str) -> sql.Composable:
    return sql.Identifier(schema, table)


def _safe_rollback(conn: psycopg.Connection) -> None:
    """Rollback that can't mask the error being handled: on a dead connection
    rollback() itself raises, and that must not replace the real failure."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def _cols(names: list[str]) -> sql.Composable:
    return sql.SQL(", ").join(sql.Identifier(n) for n in names)


class PostgresSyncOps:
    name = "postgres"

    # ------------------------------------------------------------------ discovery

    def list_tables(self, conn: psycopg.Connection) -> list[dict]:
        """Every ordinary/partitioned table outside system schemas (partitions
        themselves are hidden — selecting the parent reads them all, and
        selecting both would copy the data twice), with its primary key (in
        key order) and the planner's row estimate (-1 if never analyzed)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname, c.relname, c.reltuples::bigint,
                  (SELECT array_agg(a.attname::text ORDER BY k.ord)
                     FROM pg_constraint con
                     CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                    WHERE con.conrelid = c.oid AND con.contype = 'p') AS pk
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'
                ORDER BY 1, 2
                """
            )
            rows = cur.fetchall()
        conn.rollback()
        return [
            {"schema": r[0], "table": r[1], "approx_rows": (r[2] if r[2] is not None and r[2] >= 0 else None),
             "primary_key": list(r[3]) if r[3] else []}
            for r in rows
        ]

    def foreign_key_edges(self, conn: psycopg.Connection) -> list[tuple[tuple[str, str], tuple[str, str]]]:
        """(child, parent) pairs — child must be loaded AFTER parent."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cn.nspname, c.relname, pn.nspname, p.relname
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace cn ON cn.oid = c.relnamespace
                JOIN pg_class p ON p.oid = con.confrelid JOIN pg_namespace pn ON pn.oid = p.relnamespace
                WHERE con.contype = 'f'
                """
            )
            rows = cur.fetchall()
        conn.rollback()
        return [((r[0], r[1]), (r[2], r[3])) for r in rows]

    def table_info(self, conn: psycopg.Connection, schema: str, table: str) -> Optional[dict]:
        """None if the table doesn't exist. Otherwise columns (generated ones
        flagged — they can't be written, so they're never copied), the row
        estimate, and the table's catalog oid."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.oid, c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'p')
                """,
                (schema, table),
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return None
            oid, approx = row
            cur.execute(
                """
                SELECT a.attnum, a.attname::text, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       a.attgenerated <> ''
                FROM pg_attribute a WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (oid,),
            )
            cols = [{"attnum": r[0], "name": r[1], "type": r[2], "notnull": r[3], "generated": r[4]} for r in cur.fetchall()]
        conn.rollback()
        return {"oid": oid, "approx_rows": approx if approx is not None and approx >= 0 else None, "columns": cols}

    def _has_unique_index(self, conn: psycopg.Connection, oid: int, key_cols: list[str]) -> bool:
        """Is there a non-partial, non-expression unique index on EXACTLY
        these columns? That's what `ON CONFLICT (cols)` needs to infer."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM pg_index i
                WHERE i.indrelid = %s AND i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL
                  AND i.indnatts = i.indnkeyatts
                  AND (SELECT array_agg(a.attname::text ORDER BY a.attname::text) FROM pg_attribute a
                        WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)) = %s::text[]
                LIMIT 1
                """,
                (oid, sorted(key_cols)),
            )
            found = cur.fetchone() is not None
        conn.rollback()
        return found

    def _has_leading_index(self, conn: psycopg.Connection, info: dict, key_cols: list[str]) -> bool:
        """Is there an index whose LEADING columns are exactly the key (in
        order)? Chunk-boundary and range queries are only cheap with one."""
        attnums = {c["name"]: c["attnum"] for c in info["columns"]}
        prefix = " ".join(str(attnums[k]) for k in key_cols) + " "
        with conn.cursor() as cur:
            cur.execute(
                # int2vector::text is space-separated ('1 2 3'); append a space so '1 2' doesn't match '1 23'
                "SELECT 1 FROM pg_index i WHERE i.indrelid = %s AND i.indpred IS NULL "
                "AND (i.indkey::text || ' ') LIKE %s LIMIT 1",
                (info["oid"], prefix + "%"),
            )
            found = cur.fetchone() is not None
        conn.rollback()
        return found

    # ------------------------------------------------------------------ preflight

    def preflight_table(
        self, src: psycopg.Connection, tgt: psycopg.Connection, *, mode: str,
        source: tuple[str, str], target: tuple[str, str], key_cols: list[str],
    ) -> dict:
        """Cheap, read-only checks for one table. Returns
        {errors, warnings, info}; any error means the table must not run.
        Used both by the API's Preflight button and by the engine itself
        before a table starts, so what the UI promised is what runs."""
        errors: list[str] = []
        warnings: list[str] = []
        s_info = self.table_info(src, *source)
        t_info = self.table_info(tgt, *target)
        info: dict[str, Any] = {"approx_rows": s_info["approx_rows"] if s_info else None}
        if s_info is None:
            errors.append(f"Source table {source[0]}.{source[1]} does not exist.")
        if t_info is None:
            errors.append(f"Target table {target[0]}.{target[1]} does not exist (the syncer never creates tables).")
        if s_info is None or t_info is None:
            return {"errors": errors, "warnings": warnings, "info": info}

        copy_cols = [c["name"] for c in s_info["columns"] if not c["generated"]]
        t_cols = {c["name"]: c for c in t_info["columns"]}
        missing = [c for c in copy_cols if c not in t_cols]
        if missing:
            errors.append(f"Target is missing column(s): {', '.join(missing)}.")
        not_writable = [c for c in copy_cols if c in t_cols and t_cols[c]["generated"]]
        if not_writable:
            errors.append(f"Target column(s) are GENERATED and cannot be written: {', '.join(not_writable)}.")
        for c in s_info["columns"]:
            tc = t_cols.get(c["name"])
            if tc and not c["generated"] and tc["type"] != c["type"]:
                warnings.append(f"Column '{c['name']}' type differs: source {c['type']} vs target {tc['type']}.")
        info["columns"] = copy_cols

        if key_cols:
            s_cols = {c["name"]: c for c in s_info["columns"]}
            bad = [k for k in key_cols if k not in s_cols]
            if bad:
                errors.append(f"Key column(s) not in source table: {', '.join(bad)}.")
            else:
                nullable = [k for k in key_cols if not s_cols[k]["notnull"]]
                if nullable:
                    # A NULL key is invisible to `key > x` range reads: those rows would be
                    # skipped SILENTLY. A NOT NULL constraint is proof enough; otherwise look.
                    with src.cursor() as cur:
                        cur.execute(
                            sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE {})").format(
                                _ident(*source),
                                sql.SQL(" OR ").join(sql.SQL("{} IS NULL").format(sql.Identifier(k)) for k in nullable),
                            )
                        )
                        has_null = cur.fetchone()[0]
                    src.rollback()
                    if has_null:
                        errors.append(
                            f"Key column(s) {', '.join(nullable)} contain NULLs in the source — those rows "
                            "would be silently skipped. Pick a different key or fix the data."
                        )
                if not self._has_leading_index(src, s_info, key_cols):
                    warnings.append(
                        f"Source has no index starting with ({', '.join(key_cols)}) — every batch will sort/scan "
                        "the table, which gets very slow on big tables."
                    )
        elif mode == "upsert":
            errors.append("Upsert mode needs a key (one or more columns).")
        else:
            warnings.append("No key: this table is copied in ONE transaction — not resumable mid-table, restarts from zero.")

        if mode == "upsert" and key_cols and not missing:
            if not self._has_unique_index(tgt, t_info["oid"], key_cols):
                errors.append(
                    f"Target has no unique index/constraint on exactly ({', '.join(key_cols)}) — "
                    "ON CONFLICT needs one. Create it on the target (the syncer won't)."
                )
        return {"errors": errors, "warnings": warnings, "info": info}

    def target_has_rows(self, tgt: psycopg.Connection, target: tuple[str, str]) -> bool:
        with tgt.cursor() as cur:
            cur.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(_ident(*target)))
            found = cur.fetchone()[0]
        tgt.rollback()
        return found

    def truncate_target(self, tgt: psycopg.Connection, target: tuple[str, str]) -> None:
        with tgt.cursor() as cur:
            cur.execute(sql.SQL("TRUNCATE TABLE {}").format(_ident(*target)))
        tgt.commit()

    # ------------------------------------------------------------------ chunking

    def _range_where(
        self, key_cols: list[str], key_types: list[str], lower: Key, upper: Key
    ) -> tuple[Optional[sql.Composable], list[str]]:
        row = sql.SQL("({})").format(_cols(key_cols))

        def casts() -> sql.Composable:
            return sql.SQL("({})").format(
                sql.SQL(", ").join(sql.SQL("%s::") + sql.SQL(t) for t in key_types)
            )

        parts: list[sql.Composable] = []
        params: list[str] = []
        if lower is not None:
            parts.append(sql.SQL("{} > {}").format(row, casts()))
            params += list(lower)
        if upper is not None:
            parts.append(sql.SQL("{} <= {}").format(row, casts()))
            params += list(upper)
        if not parts:
            return None, []
        return sql.SQL(" AND ").join(parts), params

    def next_upper(
        self, src: psycopg.Connection, source: tuple[str, str], key_cols: list[str], key_types: list[str],
        lower: Key, batch_size: int,
    ) -> Key:
        """The key of the batch_size-th row after *lower*, i.e. the chunk's
        inclusive upper bound — or None if fewer than batch_size rows remain
        (the final chunk, which then has no upper bound). One ordered index
        walk of at most batch_size entries; no rows are transferred."""
        where, params = self._range_where(key_cols, key_types, lower, None)
        # Output columns are ALIASED: `SELECT "id"::text ... ORDER BY "id"` would sort by the
        # text OUTPUT column (Postgres resolves ORDER BY names against the select list first),
        # i.e. '10' < '9' — chunks of arbitrary size. Found by a test, not by thought.
        q = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(
                sql.SQL("{}::text AS {}").format(sql.Identifier(k), sql.Identifier(f"_k{i}"))
                for i, k in enumerate(key_cols)
            ),
            _ident(*source),
        )
        if where is not None:
            q += sql.SQL(" WHERE ") + where
        q += sql.SQL(" ORDER BY {} OFFSET %s LIMIT 1").format(_cols(key_cols))
        with src.cursor() as cur:
            cur.execute(q, params + [batch_size - 1])
            row = cur.fetchone()
        src.rollback()  # never leave the source transaction open between batches
        if row is None:
            return None
        if any(v is None for v in row):
            raise ValueError("NULL key value met while chunking — the key column(s) are not NULL-free.")
        return list(row)

    def max_key(self, src: psycopg.Connection, source: tuple[str, str], key_cols: list[str]) -> Key:
        """The table's current highest key (an index walk of one entry). Used
        only to record an honest final position after the last chunk, whose
        upper bound is open-ended."""
        q = sql.SQL("SELECT {} FROM {} ORDER BY {} LIMIT 1").format(
            sql.SQL(", ").join(
                sql.SQL("{}::text AS {}").format(sql.Identifier(k), sql.Identifier(f"_k{i}"))
                for i, k in enumerate(key_cols)
            ),
            _ident(*source),
            sql.SQL(", ").join(sql.SQL("{} DESC").format(sql.Identifier(k)) for k in key_cols),
        )
        with src.cursor() as cur:
            cur.execute(q)
            row = cur.fetchone()
        src.rollback()
        return list(row) if row else None

    def key_types(self, info: dict, key_cols: list[str]) -> list[str]:
        by_name = {c["name"]: c["type"] for c in info["columns"]}
        return [by_name[k] for k in key_cols]

    def begin_table(self, tgt: psycopg.Connection, *, mode: str, target: tuple[str, str], cols: list[str]) -> None:
        """Per-connection setup. Upsert mode needs a TEMP staging table with the
        copied columns (no constraints, so a half-bad chunk can't fail on COPY
        and the real constraints are enforced once, at merge time). Idempotent
        — called again after every reconnect, since temp tables die with the
        session."""
        if mode != "upsert":
            return
        with tgt.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS pg_temp._sync_stage")
            cur.execute(
                sql.SQL(
                    "CREATE TEMP TABLE _sync_stage ON COMMIT DELETE ROWS AS SELECT {} FROM {} WITH NO DATA"
                ).format(_cols(cols), _ident(*target))
            )
        tgt.commit()

    def delete_range(
        self, tgt: psycopg.Connection, target: tuple[str, str], key_cols: list[str], key_types: list[str],
        lower: Key, upper: Key,
    ) -> int:
        """Copy mode crash recovery: remove whatever a half-finished chunk may
        have left (the target commit and the state save are in two different
        databases, so a crash between them is possible) so the chunk can be
        re-copied without duplicate-key errors."""
        where, params = self._range_where(key_cols, key_types, lower, upper)
        q = sql.SQL("DELETE FROM {}").format(_ident(*target))
        if where is not None:
            q += sql.SQL(" WHERE ") + where
        with tgt.cursor() as cur:
            cur.execute(q, params)
            n = cur.rowcount
        tgt.commit()
        return n

    def transfer_chunk(
        self, src: psycopg.Connection, tgt: psycopg.Connection, *, mode: str,
        source: tuple[str, str], target: tuple[str, str], cols: list[str],
        key_cols: list[str], key_types: list[str], lower: Key, upper: Key,
        on_block: Optional[Callable[[], None]] = None,
    ) -> dict:
        """Move one chunk. Target side is ONE transaction: it commits only after
        the whole chunk is in. Returns {read, written} — `written` differs
        from `read` only in upsert mode (rows that already matched exactly
        are skipped by the WHERE ... IS DISTINCT FROM guard)."""
        where, params = self._range_where(key_cols, key_types, lower, upper) if key_cols else (None, [])
        select = sql.SQL("SELECT {} FROM {}").format(_cols(cols), _ident(*source))
        if where is not None:
            select += sql.SQL(" WHERE ") + where
        copy_out = sql.SQL("COPY ({}) TO STDOUT").format(select)
        dest = sql.SQL("_sync_stage") if mode == "upsert" else _ident(*target)
        copy_in = sql.SQL("COPY {} ({}) FROM STDIN").format(dest, _cols(cols))

        try:
            with src.cursor() as scur, tgt.cursor() as tcur:
                with scur.copy(copy_out, params) as out:
                    with tcur.copy(copy_in) as inn:
                        for block in out:
                            inn.write(block)
                            if on_block:
                                on_block()
                read = tcur.rowcount
                written = read
                if mode == "upsert":
                    written = self._merge_stage(tcur, target, cols, key_cols)
            tgt.commit()
        except BaseException:
            _safe_rollback(tgt)
            raise
        finally:
            _safe_rollback(src)
        return {"read": read, "written": written}

    def _merge_stage(self, tcur: psycopg.Cursor, target: tuple[str, str], cols: list[str], key_cols: list[str]) -> int:
        non_key = [c for c in cols if c not in key_cols]
        base = sql.SQL(
            "INSERT INTO {t} ({cols}) OVERRIDING SYSTEM VALUE SELECT {cols} FROM _sync_stage ON CONFLICT ({keys}) "
        ).format(t=_ident(*target), cols=_cols(cols), keys=_cols(key_cols))
        if not non_key:
            q = base + sql.SQL("DO NOTHING")
        else:
            # Compared as text: json (no equality operator) and other exotic types still work, at the
            # cost of an occasional pointless update when two equal values print differently (1.0 vs 1.00).
            tgt_row = sql.SQL("ROW({})").format(
                sql.SQL(", ").join(sql.SQL("{}.{}::text").format(_ident(*target), sql.Identifier(c)) for c in non_key)
            )
            new_row = sql.SQL("ROW({})").format(
                sql.SQL(", ").join(sql.SQL("EXCLUDED.{}::text").format(sql.Identifier(c)) for c in non_key)
            )
            sets = sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in non_key)
            q = base + sql.SQL("DO UPDATE SET {} WHERE {} IS DISTINCT FROM {}").format(sets, tgt_row, new_row)
        tcur.execute(q)
        return tcur.rowcount


_OPS = {"postgres": PostgresSyncOps}


def get_ops(db_type: str) -> PostgresSyncOps:
    try:
        return _OPS[(db_type or "postgres").lower()]()
    except KeyError:
        raise ValueError(f"database type '{db_type}' is not supported by the syncer yet (Postgres only)") from None
