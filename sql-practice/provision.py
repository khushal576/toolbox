"""
sql-practice/provision.py — the `practice` database: create it, load the datasets, run learners' queries safely.

Layout (content lives OUTSIDE the toolbox repo, in learn-sql/practice/, mounted read-only at /practice):
    datasets/<name>/{meta.yaml, schema.sql, seed.sql, schema.html?}   one Postgres SCHEMA per dataset
    questions/<topic>/<id>.yaml                                       one question per file

Safety model (why this is not just "run it with the toolbox login"):
  * Toolbox's own database also holds the Vault and every tool's records. Learner SQL therefore never runs as the
    `toolbox` user: it runs as `practice_user`, a role that has NO access to the toolbox database (CONNECT is revoked
    from PUBLIC there) and only SELECT on the practice schemas. Setup itself uses the `toolbox` login (a superuser on the
    bundled Postgres) and is the only thing that does.
  * Every learner statement runs in a READ ONLY transaction that is always rolled back, with a statement timeout and a
    row cap, and with search_path pinned to the one dataset schema of the question.
  * Loading is idempotent: a dataset is rebuilt only when its schema.sql/seed.sql changed (sha256 stored in
    practice_loaded) or when a reset is asked for. A Postgres advisory lock serialises concurrent setups.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg import sql as pgsql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

PRACTICE_DIR = Path(os.environ.get("TOOLBOX_PRACTICE_DIR_IN_CONTAINER", "/practice"))
PRACTICE_DB = "practice"
PRACTICE_USER = "practice_user"
LOCK_KEY = 7_424_001          # arbitrary app-wide advisory-lock id for "practice setup"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
QUERY_SECONDS = 10
MAX_ROWS = 500


class PracticeError(Exception):
    """A problem to show the learner (bad dataset name, setup not done, query refused)."""


# ---------------------------------------------------------------------------------------------------- connections

def _practice_password() -> str:
    return os.environ.get("TOOLBOX_PRACTICE_PASSWORD") or "practice-local-only"


def _admin_url() -> str:
    url = os.environ.get("TOOLBOX_DATABASE_URL", "")
    if not url:
        raise PracticeError("TOOLBOX_DATABASE_URL is not set — Toolbox's state Postgres is required.")
    return url


def _admin_connect(dbname: str | None = None, autocommit: bool = True) -> psycopg.Connection:
    """The `toolbox` login (setup only). dbname=None = the toolbox database itself."""
    kw = {"dbname": dbname} if dbname else {}
    return psycopg.connect(make_conninfo(_admin_url(), **kw), autocommit=autocommit, connect_timeout=10)


def _learner_connect() -> psycopg.Connection:
    """The restricted `practice_user` login on the practice database (what learner SQL runs as)."""
    return psycopg.connect(make_conninfo(_admin_url(), dbname=PRACTICE_DB, user=PRACTICE_USER,
                                         password=_practice_password()), autocommit=True, connect_timeout=10)


def _toolbox_dbname() -> str:
    return conninfo_to_dict(_admin_url()).get("dbname") or "toolbox"


# ---------------------------------------------------------------------------------------------------- content files

def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def dataset_names() -> list[str]:
    root = PRACTICE_DIR / "datasets"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and NAME_RE.match(d.name) and (d / "schema.sql").is_file())


def _dataset_sha(name: str) -> str:
    d = PRACTICE_DIR / "datasets" / name
    h = hashlib.sha256()
    for f in ("schema.sql", "seed.sql"):
        if (d / f).is_file():
            h.update(_read(d / f).encode("utf-8"))
    return h.hexdigest()


def dataset_meta(name: str) -> dict[str, Any]:
    d = PRACTICE_DIR / "datasets" / name
    meta = {}
    if (d / "meta.yaml").is_file():
        meta = yaml.safe_load(_read(d / "meta.yaml")) or {}
    return {"name": name, "title": meta.get("title", name), "description": meta.get("description", ""),
            "has_schema_html": (d / "schema.html").is_file(), "stored_schema_html": (d / "schema.html").is_file()}


def schema_html_path(name: str) -> Path:
    if not NAME_RE.match(name):
        raise PracticeError("Invalid dataset name.")
    p = PRACTICE_DIR / "datasets" / name / "schema.html"
    if not p.is_file():
        raise PracticeError("No schema.html stored for this dataset.")
    return p


# ---------------------------------------------------------------------------------------------------- setup

def _loaded_map() -> dict[str, str]:
    """dataset -> sha currently loaded ({} if the practice database or its bookkeeping table does not exist yet)."""
    try:
        with _admin_connect(PRACTICE_DB) as con:
            return dict(con.execute("SELECT dataset, sha FROM public.practice_loaded").fetchall())
    except psycopg.Error:
        return {}


def status() -> dict[str, Any]:
    names = dataset_names()
    loaded = _loaded_map()
    return {
        "content_dir": str(PRACTICE_DIR), "content_found": PRACTICE_DIR.is_dir(),
        "database": PRACTICE_DB,
        "datasets": [{**dataset_meta(n), "loaded": n in loaded, "up_to_date": loaded.get(n) == _dataset_sha(n)} for n in names],
        "ready": bool(names) and all(loaded.get(n) == _dataset_sha(n) for n in names),
    }


def _ensure_role_and_database() -> None:
    with _admin_connect() as con:
        pw = _practice_password()
        exists = con.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (PRACTICE_USER,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        # the password is a statement literal (utility statements take no bind parameters), so quote it properly
        con.execute(f"{verb} ROLE {PRACTICE_USER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20 "
                    f"PASSWORD {pgsql.Literal(pw).as_string(con)}")
        con.execute(f"ALTER ROLE {PRACTICE_USER} SET default_transaction_read_only = on")
        con.execute(f"ALTER ROLE {PRACTICE_USER} SET statement_timeout = '{QUERY_SECONDS}s'")
        if not con.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PRACTICE_DB,)).fetchone():
            con.execute(f'CREATE DATABASE "{PRACTICE_DB}"')
        # The learner role must never reach Toolbox's own records (Vault, tool tables).
        con.execute(f'REVOKE CONNECT ON DATABASE "{_toolbox_dbname()}" FROM PUBLIC')
        con.execute(f'REVOKE CONNECT ON DATABASE "{PRACTICE_DB}" FROM PUBLIC')
        con.execute(f'GRANT CONNECT ON DATABASE "{PRACTICE_DB}" TO {PRACTICE_USER}')


def _load_dataset(con: psycopg.Connection, name: str, sha: str) -> None:
    d = PRACTICE_DIR / "datasets" / name
    with con.transaction():
        con.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        con.execute(f'CREATE SCHEMA "{name}"')
        con.execute(f'SET LOCAL search_path = "{name}"')
        con.execute(_read(d / "schema.sql"))
        if (d / "seed.sql").is_file():
            con.execute(_read(d / "seed.sql"))
        con.execute(f'GRANT USAGE ON SCHEMA "{name}" TO {PRACTICE_USER}')
        con.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{name}" TO {PRACTICE_USER}')
        con.execute("INSERT INTO public.practice_loaded (dataset, sha, loaded_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (dataset) DO UPDATE SET sha = EXCLUDED.sha, loaded_at = EXCLUDED.loaded_at", (name, sha))
    con.execute(f'ANALYZE')  # outside the transaction: refresh planner stats so EXPLAIN-based questions behave


def setup(reset: bool = False) -> dict[str, Any]:
    """Create role + database if missing and (re)load every dataset whose files changed (or all, with reset)."""
    names = dataset_names()
    if not names:
        raise PracticeError(f"No datasets found under {PRACTICE_DIR}/datasets — is the learn-sql/practice folder mounted?")
    _ensure_role_and_database()
    done: list[str] = []
    started = time.time()
    with _admin_connect(PRACTICE_DB) as con:
        con.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            con.execute("CREATE TABLE IF NOT EXISTS public.practice_loaded "
                        "(dataset text PRIMARY KEY, sha text NOT NULL, loaded_at timestamptz NOT NULL)")
            con.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")   # learner role: no objects in public, no creating anything
            current = dict(con.execute("SELECT dataset, sha FROM public.practice_loaded").fetchall())
            for name in names:
                sha = _dataset_sha(name)
                if reset or current.get(name) != sha:
                    _load_dataset(con, name, sha)
                    done.append(name)
        finally:
            con.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return {"loaded": done, "skipped": [n for n in names if n not in done], "seconds": round(time.time() - started, 1)}


# ---------------------------------------------------------------------------------------------------- schema (for autocomplete + preview)

_SCHEMA_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnum
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r','p') AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""


def schema_json(dataset: str) -> dict[str, dict[str, str]]:
    """{table: {column: type}} — the exact shape SQL Studio's editor feeds its autocomplete with."""
    if dataset not in dataset_names():
        raise PracticeError("Unknown dataset.")
    out: dict[str, dict[str, str]] = {}
    with _learner_connect() as con:
        for table, col, typ, _ in con.execute(_SCHEMA_SQL, (dataset,)).fetchall():
            out.setdefault(table, {})[col] = typ
    return out


_GRAPH_TABLES_SQL = """
SELECT c.relname, greatest(c.reltuples, 0)::bigint
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r','p') ORDER BY c.relname
"""
_GRAPH_COLUMNS_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
       EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p' AND a.attnum = ANY (k.conkey))
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r','p') AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""
_GRAPH_FKS_SQL = """
SELECT ft.relname, fa.attname, tt.relname, ta.attname
FROM pg_constraint k
JOIN pg_class ft ON ft.oid = k.conrelid JOIN pg_class tt ON tt.oid = k.confrelid
JOIN pg_namespace n ON n.oid = ft.relnamespace
CROSS JOIN LATERAL unnest(k.conkey, k.confkey) AS u(fcol, tcol)
JOIN pg_attribute fa ON fa.attrelid = k.conrelid AND fa.attnum = u.fcol
JOIN pg_attribute ta ON ta.attrelid = k.confrelid AND ta.attnum = u.tcol
WHERE k.contype = 'f' AND n.nspname = %s ORDER BY ft.relname, fa.attname
"""


def schema_graph(dataset: str) -> dict[str, Any]:
    """Tables (with row estimates), columns (type, NOT NULL, PK) and foreign keys of one dataset, read live."""
    if dataset not in dataset_names():
        raise PracticeError("Unknown dataset.")
    with _learner_connect() as con:
        tables = [{"name": n, "rows": int(r)} for n, r in con.execute(_GRAPH_TABLES_SQL, (dataset,)).fetchall()]
        columns = [{"table": t, "name": c, "type": ty, "nullable": nl, "pk": pk}
                   for t, c, ty, nl, pk in con.execute(_GRAPH_COLUMNS_SQL, (dataset,)).fetchall()]
        fks = [{"from_table": a, "from_column": b, "to_table": c, "to_column": d}
               for a, b, c, d in con.execute(_GRAPH_FKS_SQL, (dataset,)).fetchall()]
    return {"title": dataset_meta(dataset)["title"], "tables": tables, "columns": columns, "foreign_keys": fks}


def schema_page(dataset: str, template: str) -> str:
    """The self-contained schema page (Schema Map look: graph + a left column list), built from the live database,
    so it can never drift from the data. `template` is ui/schema_template.html with a /*__DATA__*/null placeholder."""
    import json
    data = json.dumps(schema_graph(dataset)).replace("<", "\\u003c")     # no </script> can ever break out of the page
    return template.replace("/*__DATA__*/null", data, 1)


# ---------------------------------------------------------------------------------------------------- running learner SQL

def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    return str(v)       # Decimal, date, datetime, UUID, interval ... keep exact text (DataDiff compares text/number later)


def run_query(dataset: str, sql: str, limit: int = MAX_ROWS, cap: int = MAX_ROWS) -> dict[str, Any]:
    """One statement, read-only, rolled back, time- and row-limited. Returns {columns, types, rows, row_count, truncated, ms}.
    `cap` is the hard row ceiling (Check raises it so a long answer is compared whole instead of cut at 500)."""
    if dataset not in dataset_names():
        raise PracticeError("Unknown dataset.")
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise PracticeError("Write a query first.")
    limit = max(1, min(int(limit), cap))
    started = time.time()
    try:
        with _learner_connect() as con:
            con.autocommit = False
            con.execute(f'SET LOCAL search_path = "{dataset}"')
            con.execute("SET TRANSACTION READ ONLY")
            con.execute(f"SET LOCAL statement_timeout = '{QUERY_SECONDS}s'")
            try:
                # prepare=True uses the extended protocol, which refuses several statements in one string (so the
                # learner gets exactly one result set to compare), and leaves a literal % (LIKE '50%') untouched.
                cur = con.execute(sql, prepare=True)
                if cur.description is None:
                    raise PracticeError("That statement returns no rows — write a SELECT (or WITH … SELECT).")
                cols = [c.name for c in cur.description]
                types = [c.type_code for c in cur.description]
                rows = cur.fetchmany(limit + 1)
            finally:
                con.rollback()
    except PracticeError:
        raise
    except psycopg.errors.QueryCanceled:
        raise PracticeError(f"Stopped: the query ran longer than {QUERY_SECONDS} seconds.") from None
    except psycopg.Error as e:
        msg = (e.diag.message_primary or str(e)).strip()
        if "multiple commands" in msg:
            msg = "One statement at a time, please (remove the extra ; statements)."
        raise PracticeError(msg) from None
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {"columns": cols, "types": types, "rows": [[_json_safe(v) for v in r] for r in rows], "row_count": len(rows),
            "truncated": truncated, "ms": int((time.time() - started) * 1000)}


# ---------------------------------------------------------------------------------------------------- questions

HIDDEN_FIELDS = ("solution_sql", "trap", "followup", "alternatives")   # shown only after the question is completed
DONE = ("solved", "revealed")          # "revealed" = gave up and looked: counts for moving on, not for the ✓ mark
REVEAL_AFTER = 3                        # wrong Checks before "reveal the solution" unlocks
CHECK_ROWS = 2000
SAMPLE_ROWS = 5
NUMERIC_OIDS = {20, 21, 23, 700, 701, 1700}      # int8 int2 int4 float4 float8 numeric — compared after rounding
PROGRESS_SCHEMA = "sql_practice"


def _load_questions() -> list[dict[str, Any]]:
    root = PRACTICE_DIR / "questions"
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for f in sorted(root.glob("*/*.yaml")):
        try:
            q = yaml.safe_load(_read(f)) or {}
        except yaml.YAMLError:
            continue
        if not all(k in q for k in ("id", "title", "topic", "difficulty", "dataset", "prompt", "solution_sql")):
            continue
        out.append(q)
    return out


def _topic_order() -> list[str]:
    f = PRACTICE_DIR / "questions" / "_path.yaml"
    if not f.is_file():
        return []
    try:
        return list((yaml.safe_load(_read(f)) or {}).get("topics") or [])
    except yaml.YAMLError:
        return []


def ordered_questions() -> list[dict[str, Any]]:
    """Every question in PATH order (topic order from questions/_path.yaml, then id), each with a 1-based `seq`."""
    topics = _topic_order()
    rank = {t: i for i, t in enumerate(topics)}
    qs = sorted(_load_questions(), key=lambda q: (rank.get(q["topic"], len(topics)), q["id"]))
    for i, q in enumerate(qs, 1):
        q["seq"] = i
    return qs


# ---- progress (Toolbox's own Postgres, schema sql_practice — so its backups cover it; never the learner role)

_progress_ready = False


def _progress_con():
    global _progress_ready
    from core.state import db as state_db      # lazy: only needed once someone checks an answer
    if not _progress_ready:
        state_db.ensure_schema(PROGRESS_SCHEMA)
        with state_db.connection() as con:
            con.execute(f"""CREATE TABLE IF NOT EXISTS {PROGRESS_SCHEMA}.progress (
                question_id text PRIMARY KEY, status text NOT NULL, attempts int NOT NULL DEFAULT 0,
                failed int NOT NULL DEFAULT 0, solved_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now(),
                last_sql text)""")
        _progress_ready = True
    return state_db.connection()


def progress_map() -> dict[str, dict[str, Any]]:
    with _progress_con() as con:
        rows = con.execute(f"SELECT question_id, status, attempts, failed FROM {PROGRESS_SCHEMA}.progress").fetchall()
    return {r[0]: {"status": r[1], "attempts": r[2], "failed": r[3]} for r in rows}


def _record_attempt(qid: str, sql: str, ok: bool) -> None:
    with _progress_con() as con:
        con.execute(f"""
            INSERT INTO {PROGRESS_SCHEMA}.progress AS p (question_id, status, attempts, failed, solved_at, last_sql)
            VALUES (%(q)s, CASE WHEN %(ok)s THEN 'solved' ELSE 'attempted' END, 1, CASE WHEN %(ok)s THEN 0 ELSE 1 END,
                    CASE WHEN %(ok)s THEN now() END, %(sql)s)
            ON CONFLICT (question_id) DO UPDATE SET
                attempts = p.attempts + 1,
                failed = p.failed + CASE WHEN %(ok)s THEN 0 ELSE 1 END,
                status = CASE WHEN %(ok)s THEN 'solved' WHEN p.status IN ('solved', 'revealed') THEN p.status ELSE 'attempted' END,
                solved_at = CASE WHEN %(ok)s AND p.solved_at IS NULL THEN now() ELSE p.solved_at END,
                last_sql = %(sql)s, updated_at = now()""", {"q": qid, "ok": ok, "sql": sql})


def reveal(qid: str) -> dict[str, Any]:
    get_question(qid)                                     # 404 for an unknown id
    row = progress_map().get(qid) or {}
    if row.get("status") in DONE:
        return get_question(qid)
    if row.get("failed", 0) < REVEAL_AFTER:
        raise PracticeError(f"The solution unlocks after {REVEAL_AFTER} wrong Checks (you have {row.get('failed', 0)}).")
    with _progress_con() as con:
        con.execute(f"UPDATE {PROGRESS_SCHEMA}.progress SET status = 'revealed', updated_at = now() WHERE question_id = %s", (qid,))
    return get_question(qid)


def reset(qid: str) -> None:
    """Forget the progress of ONE question (Redo)."""
    get_question(qid)
    with _progress_con() as con:
        con.execute(f"DELETE FROM {PROGRESS_SCHEMA}.progress WHERE question_id = %s", (qid,))


# ---- listing / one question

def _decorate(qs: list[dict[str, Any]], prog: dict[str, dict[str, Any]]) -> None:
    """status (new|attempted|solved|revealed), locked (previous question not done yet), next (the one to do now)."""
    nxt = None
    for i, q in enumerate(qs):
        st = (prog.get(q["id"]) or {}).get("status", "new")
        q["status"] = st
        q["locked"] = i > 0 and qs[i - 1]["status"] not in DONE
        if nxt is None and st not in DONE:
            nxt = q["id"]
    for q in qs:
        q["next"] = q["id"] == nxt


def list_questions(q: str = "", topic: str = "", difficulty: str = "", dataset: str = "") -> dict[str, Any]:
    qs = ordered_questions()
    _decorate(qs, progress_map())
    summary = {"total": len(qs), "solved": sum(1 for x in qs if x["status"] == "solved"),
               "revealed": sum(1 for x in qs if x["status"] == "revealed"),
               "next_id": next((x["id"] for x in qs if x["next"]), None)}
    needle = q.strip().lower()
    result = []
    for item in qs:
        if topic and item["topic"] != topic:
            continue
        if difficulty and item["difficulty"] != difficulty:
            continue
        if dataset and item["dataset"] != dataset:
            continue
        hay = " ".join([item["id"], item["title"], item["topic"], " ".join(map(str, item.get("tags") or [])), item["prompt"]]).lower()
        if needle and not all(w in hay for w in needle.split()):
            continue
        result.append({k: item.get(k) for k in ("id", "title", "topic", "difficulty", "dataset", "tags", "seq", "status", "locked", "next")})
    return {"questions": result, "summary": summary}


def _sample(item: dict[str, Any]) -> dict[str, Any] | None:
    """What a correct answer looks like — first rows of the reference result — so column names are never a guess."""
    try:
        r = run_query(item["dataset"], item["solution_sql"], MAX_ROWS)
    except PracticeError:
        return None
    return {"columns": r["columns"], "rows": r["rows"][:SAMPLE_ROWS], "total_rows": r["row_count"], "truncated": r["truncated"]}


def get_question(qid: str) -> dict[str, Any]:
    """The question with its sample output; the reference SQL, trap and follow-up only once it is completed."""
    qs = ordered_questions()
    prog = progress_map()
    _decorate(qs, prog)
    for item in qs:
        if item["id"] != qid:
            continue
        out = {k: v for k, v in item.items() if k not in HIDDEN_FIELDS}
        p = prog.get(qid) or {}
        out.update({"attempts": p.get("attempts", 0), "failed": p.get("failed", 0),
                    "ordered": bool((item.get("compare") or {}).get("order_matters")),
                    "can_reveal": p.get("failed", 0) >= REVEAL_AFTER and item["status"] not in DONE,
                    "reveal_after": REVEAL_AFTER, "sample": _sample(item)})
        if item["status"] in DONE:
            out["solution"] = {"sql": item["solution_sql"].strip(), "trap": item.get("trap"),
                               "followup": item.get("followup"), "alternatives": item.get("alternatives") or []}
        return out
    raise PracticeError("Unknown question.")


def facets() -> dict[str, Any]:
    qs = ordered_questions()
    topics: list[str] = []
    for x in qs:
        if x["topic"] not in topics:
            topics.append(x["topic"])
    return {"topics": topics, "difficulties": ["easy", "medium", "hard", "brutal"],
            "datasets": sorted({x["dataset"] for x in qs}), "total": len(qs)}


# ---- Check: run yours + the reference, compare the two result sets with DataDiff

ENV_YAML = "list_keys:\n  rows: [__k]\n"      # rows are matched by the synthetic key __k


def _normalise(res: dict[str, Any], decimals: int) -> list[list[Any]]:
    num = [t in NUMERIC_OIDS for t in res["types"]]
    q = Decimal(1).scaleb(-decimals)
    out = []
    for row in res["rows"]:
        cells = []
        for v, is_num in zip(row, num):
            if is_num and v is not None:
                try:
                    v = format(Decimal(str(v)).quantize(q), "f")     # 3.3333 / 3.33 / 3.330 all compare as 3.33
                except (InvalidOperation, ValueError):
                    pass                                              # NaN / Infinity stay as they are
            cells.append(v)
        out.append(cells)
    return out


def _keyed(cols: list[str], rows: list[list[Any]], ordered: bool) -> list[dict[str, Any]]:
    """Row identity for DataDiff: the position (order matters) or the row's own content (+ a counter so duplicates stay visible)."""
    seen: dict[str, int] = {}
    out = []
    for i, r in enumerate(rows, 1):
        if ordered:
            key = str(i)
        else:
            base = json.dumps(r, default=str)
            seen[base] = seen.get(base, 0) + 1
            key = f"{base}#{seen[base]}"
        out.append({"__k": key, **dict(zip(cols, r))})
    return out


def _strip(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else {k: v for k, v in row.items() if k != "__k"}


def check(qid: str, sql: str) -> dict[str, Any]:
    from core.clients.datadiff import DataDiffClient, DataDiffError
    item = next((x for x in _load_questions() if x["id"] == qid), None)
    if item is None:
        raise PracticeError("Unknown question.")
    cmp_opts = item.get("compare") or {}
    ordered = bool(cmp_opts.get("order_matters"))
    decimals = int(cmp_opts.get("decimals", 2))
    mine = run_query(item["dataset"], sql, CHECK_ROWS, cap=CHECK_ROWS)       # a syntax error is not a wrong answer: it raises, nothing is recorded
    ref = run_query(item["dataset"], item["solution_sql"], CHECK_ROWS, cap=CHECK_ROWS)
    result: dict[str, Any] = {"expected_columns": ref["columns"], "your_columns": mine["columns"],
                              "rows_expected": ref["row_count"], "rows_yours": mine["row_count"] + (1 if mine["truncated"] else 0),
                              "ordered": ordered, "missing": [], "unexpected": [], "cell_diffs": [],
                              "missing_total": 0, "unexpected_total": 0, "cell_diffs_total": 0,
                              "columns_ok": True, "order_only": False}
    if len(set(mine["columns"])) != len(mine["columns"]):
        result.update(columns_ok=False, reason="Two output columns share a name — give each column its own alias.")
    elif mine["columns"] != ref["columns"]:
        result.update(columns_ok=False, reason="The output columns differ from the expected ones (names and order matter).")
    elif mine["truncated"]:
        result["reason"] = f"Your query returns more than {CHECK_ROWS} rows; the expected answer has {ref['row_count']}."
        result["unexpected_total"] = 1
    else:
        nm, nr = _normalise(mine, decimals), _normalise(ref, decimals)
        # Order is only worth comparing once the ROWS are right: with extra/missing rows every later row shifts position
        # and a positional diff reports dozens of "different values" that are just displacement.
        same_rows = sorted(json.dumps(x, default=str) for x in nm) == sorted(json.dumps(x, default=str) for x in nr)
        positional = ordered and same_rows
        result["rows_first"] = ordered and not same_rows
        left = _keyed(mine["columns"], nm, positional)
        right = _keyed(ref["columns"], nr, positional)
        try:
            diff = DataDiffClient().compare_data({"rows": left}, {"rows": right}, environment_yaml=ENV_YAML)
        except DataDiffError as e:
            raise PracticeError(f"DataDiff could not compare the results: {e}") from None
        for r in diff["records"]:
            st = r["status"]
            if st == "MATCH":
                continue                                    # anything but an exact MATCH is a difference (DataDiff calls 'y' vs 'Y' EQUIVALENT)
            if st == "EXTRA_LEFT":
                result["unexpected_total"] += 1
                result["unexpected"].append(_strip(r["left_value"])) if len(result["unexpected"]) < 10 else None
            elif st == "EXTRA_RIGHT":
                result["missing_total"] += 1
                result["missing"].append(_strip(r["right_value"])) if len(result["missing"]) < 10 else None
            else:
                result["cell_diffs_total"] += 1
                if len(result["cell_diffs"]) < 15:
                    key = (r.get("trace") or {}).get("list_key_values", {}).get("__k")
                    result["cell_diffs"].append({"row": int(key) if ordered and str(key).isdigit() else None,
                                                 "column": r["path"].rsplit("].", 1)[-1], "yours": r["left_value"], "expected": r["right_value"]})
        result["summary"] = diff["summary"]
        if positional and (result["cell_diffs_total"] or result["missing_total"] or result["unexpected_total"]):
            result["order_only"] = True           # the same rows, just not in the required order
    ok = (result["columns_ok"] and not (result["missing_total"] or result["unexpected_total"] or result["cell_diffs_total"])
          and mine["row_count"] == ref["row_count"])
    result["correct"] = ok
    _record_attempt(qid, sql, ok)
    full = get_question(qid)
    result.update(status=full["status"], attempts=full["attempts"], failed=full["failed"], can_reveal=full["can_reveal"],
                  solution=full.get("solution"))
    return result


def validate_questions() -> list[dict[str, Any]]:
    """Run every question's reference SQL: it must execute, return rows, give the same rows twice, and (when
    order_matters is false) not be cut by the row cap. The authoring check for new questions."""
    report = []
    for q in _load_questions():
        problems: list[str] = []
        try:
            a = run_query(q["dataset"], q["solution_sql"], MAX_ROWS)
            b = run_query(q["dataset"], q["solution_sql"], MAX_ROWS)
            if a["row_count"] == 0:
                problems.append("returns no rows")
            if a["truncated"]:
                problems.append(f"more than {MAX_ROWS} rows — ask for a smaller result")
            same = a["rows"] == b["rows"] if (q.get("compare") or {}).get("order_matters") else \
                sorted(map(repr, a["rows"])) == sorted(map(repr, b["rows"]))
            if not same:
                problems.append("not deterministic (two runs differ) — add a full ORDER BY or a tie-breaker")
            rows = a["row_count"]
        except PracticeError as e:
            problems.append(str(e))
            rows = 0
        report.append({"id": q["id"], "ok": not problems, "rows": rows, "problems": problems})
    return report
