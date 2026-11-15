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
  * Plan questions (`check: {type: plan, must_use, must_not_use}`): the learner query is also run through
    `EXPLAIN (FORMAT JSON)` (no ANALYZE, so it is never executed for the plan) under the same role/transaction rules and
    its plan tree is matched against the rules; see explain_plan() / plan_rules() and learn-sql/practice/AUTHORING.md.
  * Loading is idempotent: a dataset is rebuilt only when its schema.sql/seed.sql changed (sha256 stored in
    practice_loaded) or when a reset is asked for. A Postgres advisory lock serialises concurrent setups.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
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
    con.execute('VACUUM ANALYZE')  # outside the transaction (autocommit): fresh stats AND a visibility map, so EXPLAIN-based questions can get Index Only Scans


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


# ---------------------------------------------------------------------------------------------------- plans (EXPLAIN)

_PLAN_START = re.compile(r"^\s*(\(|select\b|with\b|values\b|table\b)", re.I)


def _walk_plan(node: dict[str, Any], depth: int, out: list[dict[str, Any]]) -> None:
    """Flatten a plan tree depth-first; "Plans" holds children and SubPlans alike."""
    out.append({"node_type": node.get("Node Type", "?"), "relation": node.get("Relation Name"), "alias": node.get("Alias"),
                "index": node.get("Index Name"), "rows": node.get("Plan Rows"), "cost": node.get("Total Cost"),
                "join_type": node.get("Join Type"), "depth": depth, "parent": node.get("Parent Relationship")})
    for ch in node.get("Plans") or []:
        _walk_plan(ch, depth + 1, out)


def _plan_text(nodes: list[dict[str, Any]]) -> str:
    lines = []
    for n in nodes:
        label = n["node_type"] + (f" on {n['relation']}" if n["relation"] else "") + (f" using {n['index']}" if n["index"] else "")
        sub = " (subplan)" if n["parent"] == "SubPlan" else ""
        lines.append("  " * n["depth"] + ("-> " if n["depth"] else "") + f"{label}{sub}  (est. rows {n['rows']})")
    return "\n".join(lines)


def explain_plan(dataset: str, sql: str) -> dict[str, Any]:
    """EXPLAIN (FORMAT JSON) of the learner's query: plan only, never executed. Same restricted role, read-only
    transaction, search_path and timeout as run_query. Returns {nodes, node_types, text}. A syntax error raises
    PracticeError (like Run), so it is never an attempt."""
    if dataset not in dataset_names():
        raise PracticeError("Unknown dataset.")
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise PracticeError("Write a query first.")
    if not _PLAN_START.match(sql):
        raise PracticeError("Only a SELECT (or WITH … SELECT) can be explained.")
    try:
        with _learner_connect() as con:
            con.autocommit = False
            con.execute(f'SET LOCAL search_path = "{dataset}"')
            con.execute("SET TRANSACTION READ ONLY")
            con.execute(f"SET LOCAL statement_timeout = '{QUERY_SECONDS}s'")
            try:
                row = con.execute("EXPLAIN (FORMAT JSON) " + sql, prepare=True).fetchone()
            finally:
                con.rollback()
    except psycopg.errors.QueryCanceled:
        raise PracticeError(f"Stopped: planning took longer than {QUERY_SECONDS} seconds.") from None
    except psycopg.Error as e:
        msg = (e.diag.message_primary or str(e)).strip()
        if "multiple commands" in msg:
            msg = "One statement at a time, please (remove the extra ; statements)."
        raise PracticeError(msg) from None
    doc = row[0]
    if isinstance(doc, str):
        doc = json.loads(doc)
    nodes: list[dict[str, Any]] = []
    _walk_plan(doc[0]["Plan"], 0, nodes)
    return {"nodes": nodes, "node_types": sorted({n["node_type"] for n in nodes}), "text": _plan_text(nodes)}


_ON_RE = re.compile(r"^(.*?)\s+on\s+(\S+)$", re.I)


def _entry_matches(entry: str, nodes: list[dict[str, Any]]) -> bool:
    """One rule entry: alternatives split by '|'; each is "Node Type" or "Node Type on relation" (case-insensitive)."""
    for alt in str(entry).split("|"):
        alt = alt.strip()
        if not alt:
            continue
        if alt.lower() in ("anti join", "semi join"):          # any join node whose Join Type is Anti / Semi / Right Anti ...
            if any(alt.lower().split()[0] in (n.get("join_type") or "").lower() for n in nodes):
                return True
            continue
        m = _ON_RE.match(alt)
        want_type, want_rel = (m.group(1).strip().lower(), m.group(2).strip().lower()) if m else (alt.lower(), None)
        for n in nodes:
            if n["node_type"].lower() == want_type and (want_rel is None or (n["relation"] or "").lower() == want_rel):
                return True
    return False


def _fail_message(kind: str, entry: str) -> str:
    alts = [a.strip() for a in str(entry).split("|") if a.strip()]
    first = alts[0] if alts else str(entry)
    m = _ON_RE.match(first)
    if kind == "not":
        if m and m.group(1).strip().lower() == "seq scan":
            return f"Your plan scans {m.group(2)} sequentially (Seq Scan on {m.group(2)}) — this question expects the table not to be read in full."
        return f"Your plan contains {', '.join(alts)}, which this question does not allow."
    if all("index" in a.lower() for a in alts):
        return f"Your plan uses no index scan (none of: {', '.join(alts)}) — expected the query to be answered through an index."
    return f"Your plan has no {' / '.join(alts)} step, which this question expects."


def plan_rules(check: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    c = check if isinstance(check, dict) and check.get("type") == "plan" else {}
    return [str(x) for x in (c.get("must_use") or [])], [str(x) for x in (c.get("must_not_use") or [])]


def evaluate_plan(check: dict[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    """Messages for every broken rule ([] = the plan satisfies the rules)."""
    must, must_not = plan_rules(check)
    fails = [_fail_message("not", e) for e in must_not if _entry_matches(e, nodes)]
    fails += [_fail_message("use", e) for e in must if not _entry_matches(e, nodes)]
    return fails


def check_hint(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the page may say about a plan check: general words only (never the exact node names). `check.note` overrides."""
    must, must_not = plan_rules(check)
    if not (must or must_not):
        return None
    if (check or {}).get("note"):
        return {"type": "plan", "note": str(check["note"])}
    parts = []
    for e in must:
        parts.append("must be answered through an index" if all("index" in a.lower() for a in e.split("|")) else "must have a particular plan shape")
    for e in must_not:
        m = _ON_RE.match(e.split("|")[0].strip())
        parts.append(f"must avoid a sequential scan of {m.group(2)}" if m and m.group(1).strip().lower() == "seq scan" else "must avoid some plan steps")
    return {"type": "plan", "note": "This question also checks your query plan: it " + "; it ".join(dict.fromkeys(parts)) + "."}


# ---------------------------------------------------------------------------------------------------- questions

HIDDEN_FIELDS = ("solution_sql", "trap", "followup", "alternatives", "check")   # shown only after the question is completed
DONE = ("solved", "revealed")          # "revealed" = gave up and looked: counts for moving on, not for the ✓ mark
REVEAL_AFTER = 3                        # wrong Checks before "reveal the solution" unlocks
CHECK_ROWS = 2000
SAMPLE_ROWS = 5
NUMERIC_OIDS = {20, 21, 23, 700, 701, 1700}      # int8 int2 int4 float4 float8 numeric — compared after rounding
PROGRESS_SCHEMA = "sql_practice"
MOCK_TOPIC = "mock-interviews"          # questions of this topic belong to mock sets, never to the normal path


_q_cache: tuple[Any, list[dict[str, Any]]] | None = None


def _load_questions() -> list[dict[str, Any]]:
    """All question files (cached until a file changes; callers get their own shallow copies — they add seq/status)."""
    global _q_cache
    root = PRACTICE_DIR / "questions"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*/*.yaml"))
    stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files)
    if _q_cache is None or _q_cache[0] != stamp:
        out: list[dict[str, Any]] = []
        for f in files:
            try:
                q = yaml.safe_load(_read(f)) or {}
            except yaml.YAMLError:
                continue
            if isinstance(q, dict) and all(k in q for k in ("id", "title", "topic", "difficulty", "dataset", "prompt", "solution_sql")):
                out.append(q)
        _q_cache = (stamp, out)
    return [dict(q) for q in _q_cache[1]]


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
    mock_ids = _mock_question_ids()
    qs = sorted((q for q in _load_questions() if q["topic"] != MOCK_TOPIC and q["id"] not in mock_ids), key=lambda q: (rank.get(q["topic"], len(topics)), q["id"]))
    for i, q in enumerate(qs, 1):
        q["seq"] = i
    return qs


# ---- revisit queue: pure date rules (injectable clock `now`, so tests need not wait days)

HARD_WON_FAILS = 3                       # solved after this many wrong Checks = "hard-won" (needed help, like a reveal)
REVISIT_DELAY_DAYS = {1: 3, 2: 10}       # stage 1 is due 3 days after reveal / hard-won; stage 2 is due 10 days after stage 1 succeeded


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def revisit_due_at(stage: int, moment: datetime) -> datetime:
    """When the given stage (1 or 2) becomes due, counted from `moment`."""
    return moment + timedelta(days=REVISIT_DELAY_DAYS[stage])


def revisit_is_open(due: datetime | None, now: datetime) -> bool:
    """A revisit is OPEN (the question must be solved again, solution hidden) once its due moment has passed."""
    return due is not None and due <= now


def revisit_plan(prev: dict[str, Any] | None, ok: bool, now: datetime) -> dict[str, Any] | None:
    """What a Check does to the revisit columns. `prev` = the progress row BEFORE this Check (None = first try).
    Returns None (no change) or {stage, due, done_at}:
      - wrong Check: never changes anything (an open revisit stays due);
      - correct Check while a revisit is open: stage 1 -> stage 2 due +10 days; stage 2 -> mastered (due NULL, done_at set);
      - correct Check on a question that was neither solved nor revealed and had >= 3 failed Checks: hard-won -> stage 1 due +3 days."""
    if not ok or prev is None:
        return None
    stage, due = int(prev.get("revisit_stage") or 0), prev.get("revisit_due")
    if revisit_is_open(due, now):
        if stage <= 1:
            return {"stage": 2, "due": revisit_due_at(2, now), "done_at": None}
        return {"stage": 2, "due": None, "done_at": now}
    if prev.get("status") not in DONE and int(prev.get("failed") or 0) >= HARD_WON_FAILS and stage == 0:
        return {"stage": 1, "due": revisit_due_at(1, now), "done_at": None}
    return None


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
            for ddl in ("revisit_stage int NOT NULL DEFAULT 0", "revisit_due timestamptz", "revisit_done_at timestamptz"):
                con.execute(f"ALTER TABLE {PROGRESS_SCHEMA}.progress ADD COLUMN IF NOT EXISTS {ddl}")
            con.execute(f"""CREATE TABLE IF NOT EXISTS {PROGRESS_SCHEMA}.mock_runs (
                id bigserial PRIMARY KEY, set_id text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
                ends_at timestamptz NOT NULL, finished_at timestamptz, results jsonb)""")
        _progress_ready = True
    return state_db.connection()


def progress_map() -> dict[str, dict[str, Any]]:
    with _progress_con() as con:
        rows = con.execute(f"SELECT question_id, status, attempts, failed, revisit_stage, revisit_due, revisit_done_at "
                           f"FROM {PROGRESS_SCHEMA}.progress").fetchall()
    return {r[0]: {"status": r[1], "attempts": r[2], "failed": r[3], "revisit_stage": r[4], "revisit_due": r[5],
                   "revisit_done_at": r[6]} for r in rows}


def _record_attempt(qid: str, sql: str, ok: bool, track_revisit: bool = True, now: datetime | None = None) -> None:
    now = now or _utcnow()
    with _progress_con() as con:
        row = con.execute(f"SELECT status, failed, revisit_stage, revisit_due FROM {PROGRESS_SCHEMA}.progress "
                          f"WHERE question_id = %s FOR UPDATE", (qid,)).fetchone()
        prev = None if row is None else {"status": row[0], "failed": row[1], "revisit_stage": row[2], "revisit_due": row[3]}
        plan = revisit_plan(prev, ok, now) if track_revisit else None
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
        if plan:
            con.execute(f"UPDATE {PROGRESS_SCHEMA}.progress SET revisit_stage = %s, revisit_due = %s, revisit_done_at = %s "
                        f"WHERE question_id = %s", (plan["stage"], plan["due"], plan["done_at"], qid))


def reveal(qid: str) -> dict[str, Any]:
    get_question(qid)                                     # 404 for an unknown id
    if qid in _mock_question_ids():
        raise PracticeError("Mock interview questions have no 'give up': finish the set to see every solution.")
    row = progress_map().get(qid) or {}
    if row.get("status") in DONE:
        return get_question(qid)
    if row.get("failed", 0) < REVEAL_AFTER:
        raise PracticeError(f"The solution unlocks after {REVEAL_AFTER} wrong Checks (you have {row.get('failed', 0)}).")
    with _progress_con() as con:
        con.execute(f"UPDATE {PROGRESS_SCHEMA}.progress SET status = 'revealed', updated_at = now(), "
                    f"revisit_stage = 1, revisit_due = %s WHERE question_id = %s", (revisit_due_at(1, _utcnow()), qid))
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
    prog = progress_map()
    _decorate(qs, prog)
    now = _utcnow()
    for x in qs:
        x["revisit_due"] = revisit_is_open((prog.get(x["id"]) or {}).get("revisit_due"), now)
    summary = {"total": len(qs), "solved": sum(1 for x in qs if x["status"] == "solved"),
               "revealed": sum(1 for x in qs if x["status"] == "revealed"),
               "revisits_due": sum(1 for x in qs if x["revisit_due"]),
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
        result.append({k: item.get(k) for k in ("id", "title", "topic", "difficulty", "dataset", "tags", "seq", "status", "locked", "next", "revisit_due")})
    return {"questions": result, "summary": summary}


def _sample(item: dict[str, Any]) -> dict[str, Any] | None:
    """What a correct answer looks like — first rows of the reference result — so column names are never a guess."""
    try:
        r = run_query(item["dataset"], item["solution_sql"], MAX_ROWS)
    except PracticeError:
        return None
    return {"columns": r["columns"], "rows": r["rows"][:SAMPLE_ROWS], "total_rows": r["row_count"], "truncated": r["truncated"]}


def get_question(qid: str) -> dict[str, Any]:
    """The question with its sample output; the reference SQL, trap and follow-up only once it is completed.
    A mock-interview question is not in the PATH (no lock / seq / next); its solution is also shown once its set's
    latest run is finished (the whole point of the debrief)."""
    prog = progress_map()
    mock_set = _mock_set_of(qid)
    raw = _load_questions()
    item = next((q for q in raw if q["id"] == qid), None)
    if mock_set is not None or (item is not None and item["topic"] == MOCK_TOPIC):
        if item is None:
            raise PracticeError("Unknown question.")
        item = dict(item, seq=None, locked=False, next=False, status=(prog.get(qid) or {}).get("status", "new"))
        debrief = mock_set is not None and _latest_run_finished(mock_set["id"])
    else:
        qs = ordered_questions()
        _decorate(qs, prog)
        item = next((x for x in qs if x["id"] == qid), None)
        if item is None:
            raise PracticeError("Unknown question.")
        debrief = False
    out = {k: v for k, v in item.items() if k not in HIDDEN_FIELDS}
    p = prog.get(qid) or {}
    is_mock = mock_set is not None or item["topic"] == MOCK_TOPIC
    out.update({"attempts": p.get("attempts", 0), "failed": p.get("failed", 0),
                "ordered": bool((item.get("compare") or {}).get("order_matters")),
                "can_reveal": (not is_mock) and p.get("failed", 0) >= REVEAL_AFTER and item["status"] not in DONE,
                "reveal_after": REVEAL_AFTER, "sample": _sample(item), "check": check_hint(item.get("check")),
                "mock": mock_set["id"] if mock_set else None})
    due = p.get("revisit_due")
    open_rev = (not is_mock) and revisit_is_open(due, _utcnow())
    out["revisit"] = None if is_mock or due is None else {"stage": p.get("revisit_stage", 1), "open": open_rev, "due_at": due.isoformat()}
    if (item["status"] in DONE or debrief) and not open_rev:      # an open revisit hides the solution: solve it again without help
        out["solution"] = {"sql": item["solution_sql"].strip(), "trap": item.get("trap"),
                           "followup": item.get("followup"), "alternatives": item.get("alternatives") or []}
    return out


def facets() -> dict[str, Any]:
    qs = ordered_questions()
    topics: list[str] = []
    for x in qs:
        if x["topic"] not in topics:
            topics.append(x["topic"])
    return {"topics": topics, "difficulties": ["easy", "medium", "hard", "brutal"],
            "datasets": sorted({x["dataset"] for x in qs}), "total": len(qs)}


def revisits(now: datetime | None = None) -> dict[str, Any]:
    """The revisit queue: {due: [...], upcoming: [...], counts}. Mock questions are never in it."""
    now = now or _utcnow()
    prog = progress_map()
    due, upcoming, mastered = [], [], 0
    for q in ordered_questions():
        p = prog.get(q["id"])
        if not p:
            continue
        if p.get("revisit_due") is None:
            mastered += 1 if p.get("revisit_done_at") else 0
            continue
        item = {"id": q["id"], "title": q["title"], "topic": q["topic"], "stage": p["revisit_stage"], "due_at": p["revisit_due"].isoformat()}
        (due if revisit_is_open(p["revisit_due"], now) else upcoming).append(item)
    due.sort(key=lambda x: x["due_at"])
    upcoming.sort(key=lambda x: x["due_at"])
    return {"due": due, "upcoming": upcoming, "counts": {"due": len(due), "upcoming": len(upcoming), "mastered": mastered}}


def weak_topics() -> dict[str, Any]:
    """Per topic (mock topics excluded). Sorted weakest first: lowest solved share among STARTED questions (status != new;
    a topic with nothing started goes last), then most failed Checks per started question, then PATH order."""
    prog = progress_map()
    rows: dict[str, dict[str, Any]] = {}
    for q in ordered_questions():
        t = rows.setdefault(q["topic"], {"topic": q["topic"], "total": 0, "solved": 0, "revealed": 0, "attempted": 0,
                                         "hard_won": 0, "failed_checks": 0, "attempts": 0})
        p = prog.get(q["id"]) or {}
        st = p.get("status", "new")
        t["total"] += 1
        if st in ("solved", "revealed", "attempted"):
            t[st] += 1
        t["failed_checks"] += p.get("failed", 0)
        t["attempts"] += p.get("attempts", 0)
        if st == "solved" and p.get("failed", 0) >= HARD_WON_FAILS:
            t["hard_won"] += 1
    order = {t: i for i, t in enumerate(rows)}

    def key(t: dict[str, Any]):
        started = t["solved"] + t["revealed"] + t["attempted"]
        t["started"] = started
        t["accuracy"] = round(t["solved"] / t["attempts"], 3) if t["attempts"] else None
        if not started:
            return (1, 0.0, 0.0, order[t["topic"]])
        return (0, t["solved"] / started, -t["failed_checks"] / started, order[t["topic"]])

    out = sorted(rows.values(), key=key)
    return {"topics": out}


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
    if item["topic"] == MOCK_TOPIC or _mock_set_of(qid) is not None:
        mset = _mock_set_of(qid)
        if mset is None or _active_run(mset["id"]) is None:
            raise PracticeError("This question belongs to a mock interview and its clock is not running "
                                "(time is up or the set was finished). Start the set again from Mock interviews.")
    cmp_opts = item.get("compare") or {}
    ordered = bool(cmp_opts.get("order_matters"))
    decimals = int(cmp_opts.get("decimals", 2))
    mine = run_query(item["dataset"], sql, CHECK_ROWS, cap=CHECK_ROWS)       # a syntax error is not a wrong answer: it raises, nothing is recorded
    ref = run_query(item["dataset"], item["solution_sql"], CHECK_ROWS, cap=CHECK_ROWS)
    plan = plan_fails = None
    if plan_rules(item.get("check")) != ([], []):
        plan = explain_plan(item["dataset"], sql)                              # raises on a planning error: nothing recorded
        plan_fails = evaluate_plan(item["check"], plan["nodes"])
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
    if plan is not None:
        result.update(plan_checked=True, plan_ok=not plan_fails, plan_failures=plan_fails, plan_text=plan["text"])
        ok = ok and not plan_fails
    result["correct"] = ok
    _record_attempt(qid, sql, ok, track_revisit=item["topic"] != MOCK_TOPIC and _mock_set_of(qid) is None)
    full = get_question(qid)
    result.update(status=full["status"], attempts=full["attempts"], failed=full["failed"], can_reveal=full["can_reveal"],
                  solution=full.get("solution"), revisit=full.get("revisit"))
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
            c = q.get("check")
            if c is not None:
                if not (isinstance(c, dict) and c.get("type") == "plan"):
                    problems.append("check: only {type: plan, must_use: [...], must_not_use: [...]} is supported")
                else:
                    must, must_not = plan_rules(c)
                    if not (must or must_not):
                        problems.append("check: type plan needs must_use and/or must_not_use")
                    for k in ("must_use", "must_not_use"):
                        if not isinstance(c.get(k, []) or [], list):
                            problems.append(f"check.{k} must be a list of strings")
        except PracticeError as e:
            problems.append(str(e))
            rows = 0
        report.append({"id": q["id"], "ok": not problems, "rows": rows, "problems": problems})
    return report


def validate_mocks() -> list[dict[str, Any]]:
    """Check the sets of questions/_mocks*.yaml: per set (and one 'orphans' entry): 3 existing distinct ids, minutes > 0, unique ids."""
    ids = {q["id"] for q in _load_questions()}
    report, seen_sets, owner = [], set(), {}
    for i, st in enumerate(_load_mock_sets()):
        sid = st.get("id") if isinstance(st, dict) else None
        problems: list[str] = []
        if not isinstance(st, dict):
            report.append({"id": f"#{i + 1}", "ok": False, "problems": ["a set must be a mapping"]}); continue
        if not isinstance(sid, str) or not re.match(r"^[a-z0-9][a-z0-9-]*$", sid):
            problems.append("id must be lowercase letters, digits and dashes")
        elif sid in seen_sets:
            problems.append("duplicate set id")
        seen_sets.add(sid)
        if not str(st.get("title") or "").strip():
            problems.append("title is missing")
        if not str(st.get("intro") or "").strip():
            problems.append("intro is missing")
        m = st.get("minutes")
        if isinstance(m, bool) or not isinstance(m, int) or m <= 0:
            problems.append("minutes must be a whole number > 0")
        qs = st.get("questions")
        if not isinstance(qs, list) or len(qs) != 3:
            problems.append("questions must be a list of exactly 3 ids")
        else:
            if len(set(qs)) != 3:
                problems.append("the 3 question ids must be different")
            for q in qs:
                if q not in ids:
                    problems.append(f"question {q} does not exist")
                elif owner.setdefault(q, sid) != sid:
                    problems.append(f"question {q} is already in set {owner[q]}")
        report.append({"id": sid or f"#{i + 1}", "ok": not problems, "problems": problems})
    orphans = sorted(q["id"] for q in _load_questions() if q["topic"] == MOCK_TOPIC and q["id"] not in owner)
    if orphans:
        report.append({"id": "(not in any set)", "ok": False, "problems": [f"mock question(s) without a set: {', '.join(orphans)}"]})
    return report


# ---------------------------------------------------------------------------------------------------- mock interviews
# A SET (questions/_mocks.yaml) chains 3 ordinary question files (topic `mock-interviews`) under a server-side clock.
# Runs live in sql_practice.mock_runs. Starting a run forgets the progress of the set's 3 questions (a run is a clean
# attempt); finishing / time-up snapshots status + attempts into the run's `results`. Mock questions never appear in the
# normal list, path, locks or counts.

class MockError(PracticeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _load_mock_sets() -> list[Any]:
    """Sets from every questions/_mocks*.yaml (so several authors can each own a file: _mocks.yaml, _mocks_part1.yaml ...)."""
    out: list[Any] = []
    root = PRACTICE_DIR / "questions"
    if not root.is_dir():
        return out
    for f in sorted(root.glob("_mocks*.yaml")):
        try:
            sets = (yaml.safe_load(_read(f)) or {}).get("sets") or []
        except (yaml.YAMLError, AttributeError):
            continue
        if isinstance(sets, list):
            out.extend(sets)
    return out


def _sets() -> list[dict[str, Any]]:
    """Only well-formed sets (validate_mocks reports the rest)."""
    out = []
    for s in _load_mock_sets():
        if (isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("questions"), list)
                and isinstance(s.get("minutes"), int) and s["minutes"] > 0):
            out.append(s)
    return out


def _mock_question_ids() -> set[str]:
    return {q for s in _sets() for q in s["questions"] if isinstance(q, str)}


def _mock_set_of(qid: str) -> dict[str, Any] | None:
    return next((s for s in _sets() if qid in s["questions"]), None)


def _set_by_id(set_id: str) -> dict[str, Any]:
    s = next((x for x in _sets() if x["id"] == set_id), None)
    if s is None:
        raise MockError("Unknown mock interview set.", 404)
    return s


_RUN_COLS = ("id, set_id, started_at, ends_at, finished_at, results, "
             "greatest(0, extract(epoch from ends_at - now()))::int, "
             "extract(epoch from least(coalesce(finished_at, now()), ends_at) - started_at)::int")


def _run_row(r: tuple) -> dict[str, Any]:
    results = r[5] or {}
    return {"id": r[0], "set_id": r[1], "started_at": r[2].isoformat(), "ends_at": r[3].isoformat(),
            "finished_at": r[4].isoformat() if r[4] else None, "finished": r[4] is not None,
            "remaining_seconds": 0 if r[4] else r[6], "used_seconds": max(0, r[7]), "results": results,
            "score": sum(1 for v in results.values() if v.get("status") == "solved")}


def _snapshot(st: dict[str, Any], prog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {q: {"status": (prog.get(q) or {}).get("status", "new"), "attempts": (prog.get(q) or {}).get("attempts", 0),
                "failed": (prog.get(q) or {}).get("failed", 0)} for q in st["questions"]}


def _expire_runs(con) -> None:
    """Time is up -> finish the run at ends_at (lazily, whenever anyone reads)."""
    rows = con.execute(f"SELECT id, set_id FROM {PROGRESS_SCHEMA}.mock_runs WHERE finished_at IS NULL AND ends_at <= now()").fetchall()
    if not rows:
        return
    prog = {r[0]: {"status": r[1], "attempts": r[2], "failed": r[3]} for r in
            con.execute(f"SELECT question_id, status, attempts, failed FROM {PROGRESS_SCHEMA}.progress").fetchall()}
    for rid, set_id in rows:
        st = next((x for x in _sets() if x["id"] == set_id), None)
        con.execute(f"UPDATE {PROGRESS_SCHEMA}.mock_runs SET finished_at = ends_at, results = %s::jsonb WHERE id = %s",
                    (json.dumps(_snapshot(st, prog) if st else {}), rid))


def _latest_run(set_id: str) -> dict[str, Any] | None:
    with _progress_con() as con:
        _expire_runs(con)
        r = con.execute(f"SELECT {_RUN_COLS} FROM {PROGRESS_SCHEMA}.mock_runs WHERE set_id = %s ORDER BY id DESC LIMIT 1", (set_id,)).fetchone()
    return _run_row(r) if r else None


def _active_run(set_id: str) -> dict[str, Any] | None:
    run = _latest_run(set_id)
    return run if run and not run["finished"] else None


def _latest_run_finished(set_id: str) -> bool:
    run = _latest_run(set_id)
    return bool(run and run["finished"])


def _set_card(st: dict[str, Any]) -> dict[str, Any]:
    return {"id": st["id"], "title": st.get("title") or st["id"], "domain": st.get("domain") or "", "minutes": st["minutes"],
            "intro": st.get("intro") or "", "questions": list(st["questions"])}


def mock_list() -> dict[str, Any]:
    with _progress_con() as con:
        _expire_runs(con)
        rows = con.execute(f"SELECT {_RUN_COLS} FROM {PROGRESS_SCHEMA}.mock_runs ORDER BY id DESC").fetchall()
    runs = [_run_row(r) for r in rows]
    out = []
    for st in _sets():
        mine = [r for r in runs if r["set_id"] == st["id"]]
        latest = mine[0] if mine else None
        done = [r for r in mine if r["finished"]]
        card = {k: v for k, v in _set_card(st).items() if k != "intro"}
        card.update(status="in_progress" if latest and not latest["finished"] else "finished" if latest else "not_started",
                    remaining_seconds=latest["remaining_seconds"] if latest and not latest["finished"] else None,
                    last_score=done[0]["score"] if done else None, last_used_seconds=done[0]["used_seconds"] if done else None,
                    best_score=max((r["score"] for r in done), default=None), runs=len(done))
        out.append(card)
    return {"sets": out}


def mock_questions() -> list[dict[str, Any]]:
    """For the authoring harness (tools/check_traps.py): every mock question with its status and set."""
    prog = progress_map()
    return [{"id": q, "set_id": s["id"], "status": (prog.get(q) or {}).get("status", "new")} for s in _sets() for q in s["questions"]]


def mock_get(set_id: str) -> dict[str, Any]:
    st = _set_by_id(set_id)
    run = _latest_run(set_id)
    if run is None:
        raise MockError("Start the set first.", 409)
    return {"set": _set_card(st), "run": run, "questions": [get_question(q) for q in st["questions"]]}


def mock_start(set_id: str) -> dict[str, Any]:
    st = _set_by_id(set_id)
    if _active_run(set_id) is None:
        with _progress_con() as con:
            con.execute(f"DELETE FROM {PROGRESS_SCHEMA}.progress WHERE question_id = ANY(%s)", (list(st["questions"]),))
            con.execute(f"INSERT INTO {PROGRESS_SCHEMA}.mock_runs (set_id, ends_at) VALUES (%s, now() + make_interval(mins => %s))",
                        (set_id, st["minutes"]))
    return mock_get(set_id)


def mock_finish(set_id: str) -> dict[str, Any]:
    st = _set_by_id(set_id)
    run = _active_run(set_id)
    if run is not None:
        snap = _snapshot(st, progress_map())
        with _progress_con() as con:
            con.execute(f"UPDATE {PROGRESS_SCHEMA}.mock_runs SET finished_at = now(), results = %s::jsonb WHERE id = %s AND finished_at IS NULL",
                        (json.dumps(snap), run["id"]))
    return mock_get(set_id)


def mock_discard(run_id: int) -> None:
    """Delete one run (history entry) — used by the harness so its test runs leave no trace."""
    with _progress_con() as con:
        con.execute(f"DELETE FROM {PROGRESS_SCHEMA}.mock_runs WHERE id = %s", (run_id,))
