"""
schema-copy/engine.py

Copies a database's STRUCTURE (never its rows) into another, empty database:
tables (with partitions, inheritance, identity/generated columns, defaults),
every constraint and index, sequences, views, materialized views (created
unpopulated), functions, procedures, aggregates, triggers, rules, row-level
security policies, types/domains, extensions, schemas and comments.

How: the real `pg_dump --schema-only` does the heavy lifting (it is what DBAs
trust, and re-implementing dependency ordering for 15 object kinds would
silently miss something). This module wraps it with four things a bare dump
gets wrong for this job:

 1. EVERY schema is named with -n (never a bare, unfiltered dump). A bare dump
    also emits foreign servers, publications and — measured, not assumed —
    USER MAPPINGS WITH THEIR PASSWORDS IN CLEARTEXT. A script that gets
    downloaded and shared must not contain credentials.
 2. -n drops `CREATE EXTENSION` (extensions aren't schema members), so the
    extensions are re-added from the catalog, ahead of everything that needs
    them (e.g. a gin_trgm_ops index).
 3. Foreign tables are excluded (-T): their servers are not copied, so they
    would fail on the target. They are listed as warnings instead.
 4. `CREATE SCHEMA x;` becomes `CREATE SCHEMA IF NOT EXISTS x;` — a fresh
    database already has `public`, and extension schemas are pre-created.

Then: preflight (is the target empty? same-or-newer server? extensions
available? client new enough?), apply in ONE transaction stopping at the first
error (a failure leaves the target untouched), and a post-copy verification
that diffs the object NAME SETS of source and target.

Roles are server-level objects pg_dump never copies; by default owners and
GRANTs are stripped so the script runs on a server without the same roles.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:  # package import when mounted inside the toolbox (schema_copy.*)
    from schema_copy import catalog, pgtools, state_store as store
except ImportError:  # flat import when run standalone from within this folder
    import catalog
    import pgtools
    import state_store as store

try:
    from core import db_endpoint as connections
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from core import db_endpoint as connections
from core.db_endpoint import Endpoint
from core.postgres_conn import scrub_password

LogFn = Callable[..., None]  # log(level, message)
_CREATE_SCHEMA = re.compile(r"^CREATE SCHEMA (.+);$")
_CREATE_KIND = re.compile(r"^CREATE (?:OR REPLACE )?(?:UNIQUE )?(?:UNLOGGED )?(?:FOREIGN )?([A-Z]+(?: [A-Z]+)?)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _msg(exc: BaseException) -> str:
    return " ".join(scrub_password(str(exc)).split())[:800] or exc.__class__.__name__


# ------------------------------------------------------------------ preflight

def preflight(project: dict, src: Endpoint, tgt: Optional[Endpoint], log: LogFn) -> dict:
    """Read-only checks. Returns {errors, warnings, info, schemas}; any error means the
    script must not be applied. *tgt* is None for a source-only preview."""
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}

    try:
        client = pgtools.client_major("pg_dump")
        pgtools.client_major("psql")
        info["pg_dump_major"] = client
    except pgtools.PgToolError as exc:
        return {"errors": [str(exc)], "warnings": [], "info": info, "schemas": []}

    s_ver = catalog.server_info(src.conn)
    info["source_version"] = s_ver["text"]
    if client < s_ver["major"]:
        errors.append(
            f"The source is PostgreSQL {s_ver['major']} but the bundled pg_dump is {client} — it refuses to dump a "
            "newer server. Update the 'pgclient' stage in the Dockerfile and rebuild."
        )

    available = catalog.list_schemas(src.conn)
    names = [s["schema"] for s in available]
    selected = project["schemas"] or names
    unknown = [s for s in selected if s not in names]
    if unknown:
        errors.append(f"Schema(s) not found in the source: {', '.join(unknown)}.")
    selected = [s for s in selected if s in names]
    if not selected:
        errors.append("There are no user schemas to copy.")
    info["schemas"] = selected
    if project["schemas"]:
        warnings.append(
            "Only some schemas are selected. Objects that depend on a schema you did NOT select (types, functions, "
            "tables referenced by foreign keys) are not copied, and the apply will fail on the first such reference."
        )

    exts = catalog.list_extensions(src.conn)
    info["extensions"] = [f"{e['name']} {e['version']}" for e in exts]
    foreign = catalog.foreign_tables(src.conn, selected) if selected else []
    if foreign:
        sample = ", ".join(f"{s}.{t}" for s, t in foreign[:5])
        warnings.append(
            f"{len(foreign)} foreign table(s) are NOT copied (their foreign servers/user mappings carry credentials "
            f"and are never copied): {sample}{' …' if len(foreign) > 5 else ''}."
        )
    if project["keep_owner"]:
        warnings.append("Owners and GRANTs are kept: every role they name must already exist on the target, or the apply fails.")

    if tgt is not None:
        t_ver = catalog.server_info(tgt.conn)
        info["target_version"] = t_ver["text"]
        if t_ver["major"] < s_ver["major"]:
            warnings.append(
                f"The target (PostgreSQL {t_ver['major']}) is OLDER than the source ({s_ver['major']}); the script may "
                "use syntax it does not understand. If it fails, nothing is applied."
            )
        sd, td = src.data, tgt.data
        if (sd.get("host"), int(sd.get("port") or 5432), sd.get("database")) == (
            td.get("host"), int(td.get("port") or 5432), td.get("database")
        ):
            errors.append("Source and target are the same database.")
        have = catalog.available_extensions(tgt.conn)
        missing = [e["name"] for e in exts if e["name"] not in have]
        if missing:
            errors.append(
                f"Extension(s) not available on the target server: {', '.join(missing)} — install them on the "
                "target server first (the OS package, e.g. postgresql-contrib)."
            )
        n, sample = catalog.target_objects(tgt.conn)
        info["target_objects"] = n
        if n:
            errors.append(
                f"The target database is not empty — it already has {n} object(s), e.g. {'; '.join(sample[:6])}. "
                "Point this project at a new, empty database."
            )
    return {"errors": errors, "warnings": warnings, "info": info, "schemas": selected}


# ------------------------------------------------------------------ script

def build_script(project: dict, src: Endpoint, schemas: list[str], log: LogFn, cancel: threading.Event) -> dict:
    """Generate the full DDL script for *schemas* into scripts/<project>.sql.
    Returns {bytes, lines, kinds}."""
    final = store.script_path(project["id"])
    out = final.with_name(final.name + ".part")  # a failed/stopped build never replaces the previous script
    tmp = final.with_suffix(".dump.tmp")
    foreign = catalog.foreign_tables(src.conn, schemas)
    log("info", f"running pg_dump --schema-only on {len(schemas)} schema(s)…")
    pgtools.pg_dump(
        host=src.host, port=src.port, user=src.data["username"], password=src.data["password"],
        database=src.data["database"], out_path=tmp, schemas=schemas,
        exclude_tables=[pgtools.qualified_pattern(s, t) for s, t in foreign],
        keep_owner=project["keep_owner"], cancel=cancel,
    )
    exts = catalog.list_extensions(src.conn)
    kinds: Counter[str] = Counter()
    lines = 0
    try:
        with open(out, "w", encoding="utf-8") as f, open(tmp, "r", encoding="utf-8", errors="replace") as dump:
            f.write(
                f"-- Schema Copy: STRUCTURE ONLY (no table data)\n"
                f"-- source: {connections.describe(src.data)}\n-- generated: {_now()}\n"
                f"-- schemas: {', '.join(schemas)}\n\n"
            )
            ext_schemas = sorted({e["schema"] for e in exts if e["schema"] != "public"})
            for s in ext_schemas:
                f.write(f"CREATE SCHEMA IF NOT EXISTS {_qi(s)};\n")
            for e in exts:
                f.write(f"CREATE EXTENSION IF NOT EXISTS {_qi(e['name'])} WITH SCHEMA {_qi(e['schema'])};\n")
            f.write("\n")
            for line in dump:
                m = _CREATE_SCHEMA.match(line.rstrip("\n"))
                if m:
                    line = f"CREATE SCHEMA IF NOT EXISTS {m.group(1)};\n"
                k = _CREATE_KIND.match(line)
                if k:
                    kinds[k.group(1).removesuffix(" IF")] += 1
                f.write(line)
                lines += 1
            if project["copy_sequences"]:
                seqs = catalog.sequence_values(src.conn, schemas)
                if seqs:
                    f.write("\n-- current sequence values\n")
                    for s, q, v in seqs:
                        f.write(f"SELECT pg_catalog.setval('{_qi(s)}.{_qi(q)}'::regclass, {int(v)}, true);\n")
                    log("info", f"{len(seqs)} sequence value(s) included")
        out.replace(final)
    finally:
        tmp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    store.publish_script(project["id"])
    for e in exts:
        kinds["EXTENSION"] += 1
    return {"bytes": final.stat().st_size, "lines": lines, "kinds": dict(kinds.most_common())}


def _explain_failure(err: str, script_lines: list[str]) -> dict:
    """Turn psql's stderr into the first error + the script lines around it."""
    m = re.search(r"psql:[^:\n]*:(\d+): (ERROR|FATAL):\s*(.*)", err)
    line_no = int(m.group(1)) if m else None
    first = m.group(3).strip() if m else (err.strip().splitlines() or ["psql failed"])[0]
    detail = " ".join(ln.strip() for ln in err.splitlines() if re.match(r"\s*(DETAIL|HINT):", ln))
    context = ""
    if line_no:
        lo = max(1, line_no - 6)
        context = "\n".join(f"{i:>6}  {script_lines[i - 1][:200]}" for i in range(lo, min(len(script_lines), line_no) + 1))
    return {"message": first, "detail": detail[:600], "line": line_no, "context": context}


def apply_script(project: dict, tgt: Endpoint, cancel: threading.Event, log: LogFn) -> Optional[dict]:
    """Apply the saved script in ONE transaction. Returns None on success, or an
    {message, detail, line, context} failure description (target untouched)."""
    path = store.fetch_script(project["id"])
    if path is None:
        raise pgtools.PgToolError("The generated script is missing — run Preview or Apply again.")
    log("info", f"applying {path.stat().st_size:,} bytes to the target in a single transaction…")
    ok, err = pgtools.psql_apply(
        host=tgt.host, port=tgt.port, user=tgt.data["username"], password=tgt.data["password"],
        database=tgt.data["database"], script_path=path, cancel=cancel,
    )
    if ok:
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        script_lines = f.read().splitlines()
    return _explain_failure(scrub_password(err), script_lines)


def verify(project: dict, src: Endpoint, tgt: Endpoint, schemas: list[str]) -> list[dict]:
    return catalog.compare(catalog.object_names(src.conn, schemas), catalog.object_names(tgt.conn, schemas))


# ------------------------------------------------------------------ one run

def run(project_id: str, action: str, cancel: threading.Event, log: LogFn) -> dict:
    """action: 'preflight' | 'preview' | 'apply' | 'verify'. Returns (and stores as the
    project's last run) a result dict; never raises for expected problems."""
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    result: dict[str, Any] = {
        "action": action, "status": "failed", "started_at": _now(), "finished_at": None,
        "errors": [], "warnings": [], "info": {}, "script": None, "report": None, "applied": False, "failure": None,
    }
    src = tgt = None
    try:
        src_data = connections.resolve(project["source_conn_id"], project["source_conn_name"])
        tgt_data = connections.resolve(project["target_conn_id"], project["target_conn_name"])
        for d, label in ((src_data, "source"), (tgt_data, "target")):
            if (d.get("db_type") or "postgres").lower() != "postgres":
                raise connections.ConnectionError_(f"{label}: only Postgres is supported.")
        src = Endpoint(src_data, read_only=True, label="source")
        log("info", f"source  {connections.describe(src_data)}")
        src.open()
        if action != "preview":
            tgt = Endpoint(tgt_data, read_only=False, label="target")
            log("info", f"target  {connections.describe(tgt_data)}")
            tgt.open()

        if action == "verify":
            schemas = project["schemas"] or [s["schema"] for s in catalog.list_schemas(src.conn)]
            result["report"] = verify(project, src, tgt, schemas)
            result["status"] = "ok" if all(r["ok"] for r in result["report"]) else "failed"
            log("ok" if result["status"] == "ok" else "error", "verification " + ("matches" if result["status"] == "ok" else "found differences"))
            return result

        log("info", "preflight checks…")
        pf = preflight(project, src, tgt, log)
        result.update(errors=pf["errors"], warnings=pf["warnings"], info=pf["info"])
        for w in pf["warnings"]:
            log("warn", w)
        for e in pf["errors"]:
            log("error", e)
        if pf["errors"]:
            log("error", "preflight found problems — nothing generated or applied")
            return result
        log("ok", "preflight passed")
        if action == "preflight":
            result["status"] = "ok"
            return result

        result["script"] = build_script(project, src, pf["schemas"], log, cancel)
        log("ok", f"script ready — {result['script']['lines']:,} lines, {result['script']['bytes']:,} bytes")
        if action == "preview":
            result["status"] = "ok"
            return result

        failure = apply_script(project, tgt, cancel, log)
        if failure:
            result["failure"] = failure
            log("error", f"apply FAILED near script line {failure['line']}: {failure['message']} — the target was left untouched")
            return result
        result["applied"] = True
        log("ok", "applied — verifying…")
        result["report"] = verify(project, src, tgt, pf["schemas"])
        bad = [r for r in result["report"] if not r["ok"]]
        result["status"] = "ok" if not bad else "failed"
        log("ok" if not bad else "error",
            "everything matches the source" if not bad else f"{len(bad)} categor(ies) differ from the source")
        return result
    except InterruptedError:
        result["status"] = "cancelled"
        result["errors"].append("Stopped by you." + (" The target was rolled back." if action == "apply" else ""))
        log("warn", "stopped")
        return result
    except (connections.ConnectionError_, pgtools.PgToolError) as exc:
        result["errors"].append(str(exc))
        log("error", str(exc))
        return result
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(_msg(exc))
        log("error", _msg(exc))
        return result
    finally:
        for ep in (src, tgt):
            if ep is not None:
                ep.close()
        result["finished_at"] = _now()
        store.set_last_run(project_id, result)
