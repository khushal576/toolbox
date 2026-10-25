"""
data-dumper/engine.py

Takes a Postgres dump (consistent snapshot, via the bundled pg_dump) and restores one
into any database (via pg_restore for the custom format, psql for plain SQL), with a
SELECTIVE restore: everything / structure only / data only / by phase / chosen
schemas / chosen tables / individual objects. Dumps live as files on the volume and
are downloadable; a dump also remembers how it was taken so a scheduler can later
repeat it (see state_store.py).

Safety rules that matter:
 * Restores run in ONE transaction and stop at the first error, so a failed restore
   leaves the target untouched (a stopped one is rolled back too).
 * A whole-database restore needs an EMPTY target (preflight refuses otherwise)
   unless "replace existing" is chosen — the one destructive option, off by default.
 * Dumps are written to `<id>.<ext>.part` and renamed only when pg_dump exits 0, so
   a half-written file can never be mistaken for a dump.
 * Owners and GRANTs are stripped by default so a dump restores on any server; roles
   themselves are never part of a pg_dump.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:  # package import when mounted inside the toolbox (data_dumper.*)
    from data_dumper import state_store as store, toc as tocmod
except ImportError:  # flat import when run standalone from within this folder
    import state_store as store
    import toc as tocmod

try:
    from core import db_endpoint as connections, pgclient, pg_inspect
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import db_endpoint as connections, pgclient, pg_inspect
from core.db_endpoint import Endpoint
from core.postgres_conn import scrub_password

LogFn = Callable[[str, str], None]  # log(level, message)
EXT = {"custom": "dump", "plain": "sql.gz"}
MIN_FREE_BYTES = 200 * 1024 * 1024
DUMP_ATTEMPTS = 3
PRESETS = {
    "all": [], "schema_only": ["--schema-only"], "data_only": ["--data-only"],
    "pre_data": ["--section=pre-data"], "data": ["--section=data"], "post_data": ["--section=post-data"],
}
LIST_MODES = ("schemas", "tables", "objects")
NEEDS_EMPTY = ("all", "schema_only", "pre_data")          # create objects from scratch
NEEDS_STRUCTURE = ("data_only", "data", "post_data")      # act on tables that must already exist


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg(exc: BaseException) -> str:
    return " ".join(scrub_password(str(exc)).split())[:900] or exc.__class__.__name__


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


# ====================================================================== dump

def run_dump(dump_id: str, cancel: threading.Event, log: LogFn, progress: dict) -> None:
    """Take the dump described by the `dumps` row *dump_id* (already created, status 'running')."""
    dump = store.get_dump(dump_id)
    run_id = store.add_run("dump", dump_id)
    ext = EXT[dump["fmt"]]
    part = store.part_path(dump_id, ext)
    ep: Optional[Endpoint] = None
    stop_watch = threading.Event()
    result: dict[str, Any] = {"label": dump["label"]}
    status = "failed"
    try:
        data = connections.resolve(dump["source_conn_id"], dump["source_conn_name"])
        if (data.get("db_type") or "postgres").lower() != "postgres":
            raise connections.ConnectionError_("Only Postgres is supported.")
        ep = Endpoint(data, read_only=True, label="source")
        log("info", f"source  {connections.describe(data)}")
        ep.open()
        server = pg_inspect.server_info(ep.conn)
        client = pgclient.client_major("pg_dump")
        if client < server["major"]:
            raise pgclient.PgToolError(
                f"The source is PostgreSQL {server['major']} but the bundled pg_dump is {client} — it cannot dump a "
                "newer server. Bump PG_CLIENT_MAJOR in the Dockerfile and rebuild."
            )
        db_size = pg_inspect._rows(ep.conn, "SELECT pg_database_size(current_database())")[0][0]
        usage = store.disk_usage()
        progress.update(db_size=db_size, bytes=0, tables=0)
        log("info", f"database size {_fmt_bytes(db_size)} · free disk {_fmt_bytes(usage['free_bytes'])} · PostgreSQL {server['text']}")
        if usage["free_bytes"] < MIN_FREE_BYTES:
            raise pgclient.PgToolError(f"Only {_fmt_bytes(usage['free_bytes'])} of disk is free — free up space first.")
        if usage["free_bytes"] < db_size:
            log("warn", "free disk is less than the database size; a compressed dump is usually smaller, but it may not fit")

        def watch() -> None:  # the growing file is the only honest progress pg_dump gives
            while not stop_watch.wait(1.0):
                try:
                    progress["bytes"] = part.stat().st_size
                except OSError:
                    pass
        threading.Thread(target=watch, daemon=True).start()

        def on_line(line: str) -> None:
            if "dumping contents of table" in line:
                progress["tables"] = progress.get("tables", 0) + 1
                log("info", line.split("pg_dump: ", 1)[-1])
            elif re.search(r"\b(error|fatal|warning)\b", line, re.I):
                log("error" if re.search(r"error|fatal", line, re.I) else "warn", line)

        log("info", f"pg_dump started: {dump['fmt']} format, scope {dump['scope']}")
        t0 = time.monotonic()
        for attempt in range(1, DUMP_ATTEMPTS + 1):
            try:
                pgclient.dump_database(
                    host=ep.host, port=ep.port, user=data["username"], password=data["password"], database=data["database"],
                    out_path=part, fmt=dump["fmt"], scope=dump["scope"], keep_owner=dump["keep_owner"], cancel=cancel, on_line=on_line,
                )
                break
            except pgclient.PgToolError as exc:
                # A dump has no state to resume — a retry simply starts again, so it is always safe. Only
                # connection-type failures are retried; a permission or version error would just repeat.
                if attempt < DUMP_ATTEMPTS and pgclient.is_transient(str(exc)):
                    delay = 4 * attempt
                    part.unlink(missing_ok=True)
                    progress["tables"] = 0
                    log("warn", f"the connection dropped ({str(exc)[:200]}) — retrying in {delay}s (attempt {attempt + 1}/{DUMP_ATTEMPTS})")
                    if cancel.wait(delay):
                        raise InterruptedError()
                    continue
                raise
        final = store.final_path(dump_id, ext)
        part.replace(final)
        size = final.stat().st_size
        progress["bytes"] = size
        log("info", f"storing the dump file ({_fmt_bytes(size)})…")
        try:
            store.publish_file(dump_id, final)
        except Exception:
            final.unlink(missing_ok=True)  # a dump that isn't in storage would vanish with this machine
            raise
        store.update_dump(
            dump_id, status="ready", error=None, file_name=final.name, size_bytes=size, server_version=server["text"],
            client_version=str(client), source_db=data["database"], source_desc=connections.describe(data), finished_at=_now(),
        )
        status = "ok"
        result.update(size_bytes=size, seconds=round(time.monotonic() - t0, 1))
        log("ok", f"dump ready — {_fmt_bytes(size)} in {result['seconds']}s (database was {_fmt_bytes(db_size)})")
    except InterruptedError:
        status = "cancelled"
        store.update_dump(dump_id, status="failed", error="Stopped by you.", finished_at=_now())
        log("warn", "stopped — the partial file was discarded")
    except Exception as exc:  # noqa: BLE001 — every failure ends as a visible, scrubbed message
        text = _msg(exc)
        result["error"] = text
        store.update_dump(dump_id, status="failed", error=text, finished_at=_now())
        log("error", text)
    finally:
        stop_watch.set()
        part.unlink(missing_ok=True)
        if ep is not None:
            ep.close()
        store.finish_run(run_id, status, result)


# ====================================================================== upload

def finalize_upload(dump_id: str, tmp: Path) -> None:
    """Validate an uploaded file and make it a normal dump. Raises pgclient.PgToolError (message is
    user-facing) if it is not a readable Postgres dump."""
    with open(tmp, "rb") as f:
        head = f.read(8192)
    if head.startswith(b"PGDMP"):
        fmt, ext = "custom", "dump"
    elif head[:2] == b"\x1f\x8b":
        fmt, ext = "plain", "sql.gz"
    elif b"\x00" not in head and head:
        fmt, ext = "plain", "sql"
    else:
        raise pgclient.PgToolError("This is not a Postgres dump (expected a custom-format .dump, a .sql file or a .sql.gz).")
    final = store.final_path(dump_id, ext)
    tmp.replace(final)
    fields: dict[str, Any] = {"fmt": fmt, "file_name": final.name, "size_bytes": final.stat().st_size, "status": "ready", "finished_at": _now()}
    if fmt == "custom":
        try:
            text = pgclient.restore_list(final)
        except pgclient.PgToolError as exc:
            final.unlink(missing_ok=True)
            raise pgclient.PgToolError(f"{exc} (a dump made by a NEWER PostgreSQL than the bundled client cannot be read)") from exc
        m = re.search(r"^;\s+dbname: (.+)$", text, re.M)
        v = re.search(r"^;\s+Dumped from database version: (.+)$", text, re.M)
        if m:
            fields["source_db"] = m.group(1).strip()
        if v:
            fields["server_version"] = v.group(1).strip()
    try:
        store.publish_file(dump_id, final)
    except Exception:
        final.unlink(missing_ok=True)
        raise
    store.update_dump(dump_id, **fields)


# ====================================================================== contents (custom format)

def _toc_to_json(toc: tocmod.Toc) -> dict:
    r = toc.rel
    return {
        "entries": [{k: e[k] for k in ("id", "type", "schema", "tag", "raw")} for e in toc.entries],
        "relations": {
            "index_table": [[list(k), list(v)] for k, v in r["index_table"].items()],
            "seq_table": [[list(k), list(v)] for k, v in r["seq_table"].items()],
            "partitions": [[list(k), [list(x) for x in v]] for k, v in r["partitions"].items()],
            "fks": [[list(k), list(v)] for k, v in r["fks"].items()],
        },
    }


def _toc_from_json(d: dict) -> tocmod.Toc:
    r = d["relations"]
    rel = {
        "index_table": {tuple(k): tuple(v) for k, v in r["index_table"]},
        "seq_table": {tuple(k): tuple(v) for k, v in r["seq_table"]},
        "partitions": {tuple(k): [tuple(x) for x in v] for k, v in r["partitions"]},
        "fks": {tuple(k): tuple(v) for k, v in r["fks"]},
    }
    entries = [{**e, "name": e["tag"]} for e in d["entries"]]
    return tocmod.Toc(entries, rel)


def load_toc(dump: dict[str, Any]) -> tocmod.Toc:
    """The parsed contents of a custom-format dump (cached next to it: reading the TOC and the
    pre/post-data SQL is cheap but not free on a schema with thousands of objects)."""
    if dump["fmt"] != "custom":
        raise pgclient.PgToolError("Only custom-format dumps have browsable contents; a plain SQL dump restores whole.")
    cache = store.FILES.fetch(dump["id"], store.toc_cache_path(dump["id"]).name)
    if cache is not None:
        try:
            return _toc_from_json(json.loads(cache.read_text()))
        except (ValueError, KeyError):
            store.FILES.remove(dump["id"], cache.name)
    cache = store.toc_cache_path(dump["id"])
    path = store.fetch_file(dump)
    if path is None:
        raise pgclient.PgToolError("The dump file is missing.")
    entries = tocmod.parse_toc(pgclient.restore_list(path))
    rel = tocmod.parse_relations(
        pgclient.restore_script(path, ["--section=pre-data"]), pgclient.restore_script(path, ["--section=post-data"])
    )
    toc = tocmod.Toc(entries, rel)
    cache.write_text(json.dumps(_toc_to_json(toc)))
    try:
        store.FILES.publish(dump["id"], cache)
    except Exception:  # noqa: BLE001 - only a cache; rebuilt next time if missing
        pass
    return toc


def contents(dump_id: str) -> dict[str, Any]:
    dump = store.get_dump(dump_id)
    toc = load_toc(dump)
    return {
        **toc.summary(),
        "objects": [{"id": e["id"], "type": e["type"], "schema": e["schema"], "name": e["tag"]} for e in toc.entries],
    }


# ====================================================================== restore

def _plan(dump: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    """Translate the user's choices into pg_restore arguments (+ a list file) and a preview.
    Raises pgclient.PgToolError for impossible combinations."""
    sel = opts.get("selection") or {"mode": "all"}
    mode = sel.get("mode", "all")
    replace = bool(opts.get("replace_existing"))
    plan: dict[str, Any] = {"mode": mode, "args": [], "list_text": None, "preview": None, "entries_total": None, "replace_sql": None, "replace_note": None}
    if dump["fmt"] == "plain":
        if replace:
            raise pgclient.PgToolError("'Replace existing' needs a custom-format dump (a plain SQL dump cannot be cleaned up selectively).")
        if mode != "all":
            raise pgclient.PgToolError("A plain-SQL dump can only be restored whole. Take (or upload) a custom-format dump for selective restores.")
        return plan
    if mode not in PRESETS and mode not in LIST_MODES:
        raise pgclient.PgToolError(f"Unknown restore mode '{mode}'.")
    toc = load_toc(dump)
    plan["toc"] = toc
    plan["entries_total"] = len(toc.entries)
    if replace and mode in NEEDS_STRUCTURE:
        raise pgclient.PgToolError("'Replace existing' does not apply when restoring only data, or only indexes/constraints.")
    if mode in PRESETS:
        if replace:
            schemas = [x["name"] for x in toc.summary()["schemas"]]
            plan["replace_sql"] = toc.schema_wipe_sql(schemas)
            plan["replace_note"] = "DROP SCHEMA … CASCADE for: " + ", ".join(schemas) + " (everything inside them, including objects that are not in this dump)"
        plan["args"] = list(PRESETS[mode])
        if mode == "all":
            plan["preview"] = toc.preview([e["id"] for e in toc.entries])
        elif mode == "schema_only":
            plan["preview"] = toc.preview([e["id"] for e in toc.entries if e["type"] not in tocmod.DATA_TYPES])
        elif mode == "data_only":
            plan["preview"] = toc.preview([e["id"] for e in toc.entries if e["type"] in tocmod.DATA_TYPES])
        return plan
    ids = toc.select(sel)
    if not ids:
        raise pgclient.PgToolError("Nothing is selected.")
    plan["ids"] = ids
    if replace:
        if mode == "schemas":
            picked = list(sel.get("schemas", []))
            plan["replace_sql"] = toc.schema_wipe_sql(picked)
            plan["replace_note"] = "DROP SCHEMA … CASCADE for: " + ", ".join(picked) + " (everything inside them, including objects that are not in this dump)"
        else:
            plan["replace_sql"] = toc.object_drop_sql(ids)
            plan["replace_note"] = f"DROP … IF EXISTS … CASCADE for the {len(ids):,} selected objects (and anything that depends on them)"
    plan["list_text"] = toc.list_file(ids)
    plan["preview"] = toc.preview(ids)
    plan["entries_total"] = len(ids)
    return plan


def preflight_restore(dump_id: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Read-only checks of a planned restore against the target. Returns {errors, warnings, info, preview}."""
    dump = store.get_dump(dump_id)
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}
    if dump is None:
        return {"errors": ["Dump not found."], "warnings": [], "info": {}, "preview": None}
    if dump["status"] != "ready":
        errors.append("This dump is not ready (it failed or is still running).")
    path = store.fetch_file(dump) if dump["status"] == "ready" else None
    if dump["status"] == "ready" and path is None:
        errors.append("The dump file is missing (not in storage).")
    if errors:
        return {"errors": errors, "warnings": warnings, "info": info, "preview": None}
    try:
        plan = _plan(dump, opts)
    except pgclient.PgToolError as exc:
        return {"errors": [str(exc)], "warnings": warnings, "info": info, "preview": None}
    mode, replace = plan["mode"], bool(opts.get("replace_existing"))
    info["mode"] = mode
    try:
        pgclient.client_major("pg_restore")
        pgclient.client_major("psql")
    except pgclient.PgToolError as exc:
        return {"errors": [str(exc)], "warnings": warnings, "info": info, "preview": plan["preview"]}

    ep: Optional[Endpoint] = None
    try:
        data = connections.resolve(opts["target_conn_id"], opts.get("target_conn_name"))
        if (data.get("db_type") or "postgres").lower() != "postgres":
            return {"errors": ["Only Postgres targets are supported."], "warnings": warnings, "info": info, "preview": plan["preview"]}
        info["target"] = connections.describe(data)
        ep = Endpoint(data, read_only=False, label="target")
        ep.open()
        t_ver = pg_inspect.server_info(ep.conn)
        info["target_version"] = t_ver["text"]
        m = re.match(r"(\d+)", dump.get("server_version") or "")
        if m and t_ver["major"] < int(m.group(1)):
            warnings.append(
                f"The dump comes from PostgreSQL {m.group(1)} but the target is {t_ver['major']}; the script may use syntax "
                "the older server does not know. If it fails, nothing is applied."
            )
        n, sample = pg_inspect.target_objects(ep.conn)
        info["target_objects"] = n
        if mode in NEEDS_EMPTY and not replace and n:
            errors.append(
                f"The target database is not empty — it already has {n} object(s), e.g. {'; '.join(sample[:6])}. Use a new, empty "
                "database, restore only the parts you need, or choose 'replace existing' (drops what is in the way)."
            )
        if (mode in NEEDS_STRUCTURE or (mode in LIST_MODES and not (opts.get("selection") or {}).get("structure", True))) and not n:
            errors.append("The target has no tables yet, but this restore only loads data / indexes / constraints. Restore the structure first (e.g. 'Before data').")
        if mode in LIST_MODES and n and not replace:
            warnings.append(
                "The target already has objects. Anything in your selection that already exists will make the restore stop "
                "(and roll back). Choose 'replace existing' to drop and recreate those objects."
            )
        if replace:
            warnings.append("REPLACE EXISTING is on — " + (plan.get("replace_note") or "objects in the way are dropped first") + ". This destroys data. It all runs in one transaction, so a failure rolls the drops back too.")
        toc = plan.get("toc")
        if toc is not None:
            ids = plan.get("ids")
            wanted_ext = {e["tag"] for e in toc.entries if e["type"] == "EXTENSION" and (ids is None or e["id"] in ids)}
            if mode in PRESETS and mode in ("data_only", "data", "post_data"):
                wanted_ext = set()
            missing = sorted(wanted_ext - pg_inspect.available_extensions(ep.conn))
            if missing:
                errors.append(f"Extension(s) not available on the target server: {', '.join(missing)} — install them there first (postgresql-contrib).")
        if dump["fmt"] == "plain":
            warnings.append("Plain-SQL dump: restored whole through psql; owners/privileges are whatever the dump contains.")
    except (connections.ConnectionError_, pgclient.PgToolError) as exc:
        errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001
        errors.append(_msg(exc))
    finally:
        if ep is not None:
            ep.close()
    return {"errors": errors, "warnings": warnings, "info": info, "preview": plan["preview"]}


def _explain(err: str) -> dict[str, Any]:
    """The failing statement/message out of pg_restore's or psql's stderr."""
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    first = next((ln for ln in lines if re.search(r"\berror\b|\bfatal\b", ln, re.I) and "processing" not in ln), "")
    message = re.sub(r"^psql:.*?:\d+: (ERROR:\s*)?", "", first)          # psql:<file>:LINE: ERROR: msg
    message = re.sub(r"^pg_restore: (error: )?", "", message) or (lines[-1] if lines else "restore failed")
    cmd = ""
    for i, ln in enumerate(lines):
        if ln.startswith("Command was:"):
            cmd = " ".join(lines[i:])[:900]
            break
    mline = re.search(r"psql:[^:\n]*:(\d+):", err)
    return {"message": message[:600], "command": cmd, "line": int(mline.group(1)) if mline else None}


def run_restore(dump_id: str, opts: dict[str, Any], cancel: threading.Event, log: LogFn, progress: dict) -> None:
    dump = store.get_dump(dump_id)
    run_id = store.add_run("restore", dump_id)
    result: dict[str, Any] = {"options": {k: opts.get(k) for k in ("selection", "replace_existing", "single_transaction", "keep_owner")}}
    status = "failed"
    ep: Optional[Endpoint] = None
    list_file: Optional[Path] = None
    try:
        log("info", "preflight…")
        pf = preflight_restore(dump_id, opts)
        result.update(errors=pf["errors"], warnings=pf["warnings"], info=pf["info"], preview=pf["preview"])
        for w in pf["warnings"]:
            log("warn", w)
        for e in pf["errors"]:
            log("error", e)
        if pf["errors"]:
            log("error", "preflight found problems — nothing was restored")
            return
        log("ok", "preflight passed")
        plan = _plan(dump, opts)
        data = connections.resolve(opts["target_conn_id"], opts.get("target_conn_name"))
        ep = Endpoint(data, read_only=False, label="target")
        log("info", f"target  {connections.describe(data)}")
        ep.open()
        path = store.fetch_file(dump)
        if path is None:
            raise pgclient.PgToolError("The dump file is missing.")
        single = bool(opts.get("single_transaction", True))
        replace = bool(opts.get("replace_existing"))
        total = plan["entries_total"] or 0
        progress.update(done=0, total=total)

        def on_line(line: str) -> None:
            if re.search(r"pg_restore: (creating|processing)", line):
                progress["done"] = progress.get("done", 0) + 1
                if "processing data" in line or "creating TABLE " in line or "creating SCHEMA" in line or progress["done"] % 25 == 0:
                    log("info", line.split("pg_restore: ", 1)[-1])
            elif re.search(r"\b(error|fatal)\b", line, re.I):
                log("error", line)

        t0 = time.monotonic()
        if dump["fmt"] == "plain":
            log("info", "applying the SQL dump through psql" + (" in one transaction" if single else ""))
            ok, err = pgclient.psql_apply(
                host=ep.host, port=ep.port, user=data["username"], password=data["password"], database=data["database"],
                script_path=path, cancel=cancel, app_name="toolbox-data-dumper",
            )
        else:
            args = list(plan["args"])
            if plan["list_text"] is not None:
                list_file = store.FILES_DIR / f"{dump_id}.{run_id}.list"
                list_file.write_text(plan["list_text"])
                args += ["-L", str(list_file)]
            log("info", f"pg_restore ({plan['mode']}) — {total:,} entr{'y' if total == 1 else 'ies'}"
                        + (", one transaction" if single else "") + (", replacing existing objects" if replace else ""))
            if replace and plan["replace_sql"] is not None:
                log("info", "replace: clearing the way and restoring in ONE transaction — " + (plan["replace_note"] or ""))
                ok, err = pgclient.pg_restore_replace(
                    host=ep.host, port=ep.port, user=data["username"], password=data["password"], database=data["database"],
                    dump_path=path, extra_args=args, pre_sql=plan["replace_sql"], keep_owner=bool(opts.get("keep_owner")),
                    cancel=cancel, on_line=on_line,
                )
            else:
                ok, err = pgclient.pg_restore(
                    host=ep.host, port=ep.port, user=data["username"], password=data["password"], database=data["database"],
                    dump_path=path, extra_args=args, single_transaction=single, replace_existing=False,
                    keep_owner=bool(opts.get("keep_owner")), cancel=cancel, on_line=on_line,
                )
        result["seconds"] = round(time.monotonic() - t0, 1)
        if ok:
            status = "ok"
            log("ok", f"restore finished in {result['seconds']}s")
        else:
            result["failure"] = _explain(scrub_password(err))
            f = result["failure"]
            log("error", f"restore FAILED: {f['message']}" + (" — the target was left untouched" if single else ""))
            if f["command"]:
                log("error", f["command"][:300])
    except InterruptedError:
        status = "cancelled"
        result["errors"] = (result.get("errors") or []) + ["Stopped by you." + (" The target was rolled back." if opts.get("single_transaction", True) else "")]
        log("warn", "stopped")
    except Exception as exc:  # noqa: BLE001
        result["errors"] = (result.get("errors") or []) + [_msg(exc)]
        log("error", _msg(exc))
    finally:
        if list_file is not None:
            list_file.unlink(missing_ok=True)
        if ep is not None:
            ep.close()
        store.finish_run(run_id, status, result)
