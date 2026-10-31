"""
data-lake/loader.py — load files into a Vault Data table (roadmap L2, "Redshift COPY" style).

`run_load(ctx, spec)` is a job body (core/jobs/runner.JobRunner → runs in the `worker` container): it gathers the
input files (a staged browser upload, a pattern in the shared data folder, or a downloaded link), works out their
format (by extension, else by sniffing), converts XML/Excel to a readable form first, and lets DuckDB stream
everything into Parquet files (bounded memory — `memory_limit` + spilling to a temp directory, never the whole file in
Python). The Parquet files then become a managed table via core.lake (create / append / overwrite). With
`external: true` and a data-folder source nothing is copied: the pattern is registered as an external table.

spec = {"source": {"kind": "upload", "upload_id": ..., "files": [names]} | {"kind": "folder", "pattern": "sales/*.csv"}
                  | {"kind": "url", "url": "https://..."},
        "workspace": "sales", "table": "orders", "mode": "create|append|overwrite", "format": "auto|csv|json|...",
        "header": null|true|false, "delimiter": null|",", "add_filename": bool, "sheet": null|"Sheet1", "external": bool,
        "columns": null | [column map, see colmap.py], "only_listed": bool, "secrets_ref": null | "<id>"}

With a column map (roadmap L7) the reader's SELECT is wrapped by `colmap.compile_select` (keep / rename / cast / fill /
mask / hash / redact / shuffle) before the COPY to Parquet. `run_copy` does the same from an existing Vault Data table.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

try:
    from data_lake import colmap, sources
except ImportError:  # standalone
    import colmap
    import sources

from core.file_source import FORMATS, build_multi_read_expr, detect_any

MEMORY_LIMIT = os.environ.get("DATA_LAKE_MEMORY_LIMIT", "1GB")   # DuckDB spills to disk above this
PART_BYTES = os.environ.get("DATA_LAKE_PART_SIZE", "256MB")      # Parquet output is split into files of ~this size


class LoadError(ValueError):
    pass


def _gather(ctx: Any, spec: dict[str, Any], work: Path) -> list[Path]:
    src = spec.get("source") or {}
    kind = src.get("kind")
    if kind == "upload":
        out = []
        for name in src.get("files") or []:
            p = sources.STAGE.fetch(src["upload_id"], name)
            if p is None:
                raise LoadError(f"The uploaded file '{name}' is gone (uploads are kept 1 day) — upload it again.")
            out.append(p)
        return out
    if kind == "folder":
        files = sources.match(src.get("pattern") or "")
        if not files:
            raise LoadError(f"No files match '{src.get('pattern')}' in the data folder.")
        return files
    if kind == "url":
        ctx.progress["phase"] = "downloading"
        return [sources.download(src.get("url") or "", work, ctx.log)]
    raise LoadError("source.kind must be upload, folder or url")


def _to_readable(files: list[Path], fmt: str, spec: dict[str, Any], work: Path, log,
                 limit_rows: int | None = None) -> tuple[list[Path], str]:
    """XML → JSON lines, Excel → Parquet (both formats can't be read lazily by DuckDB here)."""
    if fmt == "xml":
        import json

        from core.normalizer import normalize

        out = []
        for i, f in enumerate(files):
            data, err = normalize(f.read_text(encoding="utf-8", errors="replace"), "xml")
            if err:
                raise LoadError(f"{f.name}: {err}")
            rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [data]) \
                if isinstance(data, dict) else [data]
            dest = work / f"xml_{i}.jsonl"
            with dest.open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r if isinstance(r, dict) else {"value": r}, default=str) + "\n")
            out.append(dest)
        log("info", f"converted {len(files)} XML file(s)")
        return out, "json"
    if fmt == "excel":
        import pandas as pd

        out = []
        for i, f in enumerate(files):
            sheet = spec.get("sheet") or 0
            df = pd.read_excel(f, sheet_name=sheet, engine="openpyxl", nrows=limit_rows)
            df.columns = [str(c) for c in df.columns]
            dest = work / f"excel_{i}.parquet"
            df.to_parquet(dest, index=False)
            out.append(dest)
            log("info", f"{f.name}: sheet {sheet!r} → {len(df):,} rows")
        return out, "parquet"
    return files, fmt


def run_load(ctx: Any, spec: dict[str, Any]) -> None:
    import duckdb

    from core import lake as lake_store

    lake = lake_store.scoped("data-lake")
    log, p = ctx.log, ctx.progress
    t0 = time.monotonic()
    ws, table, mode = spec["workspace"], spec["table"], spec.get("mode") or "create"
    work = Path(tempfile.mkdtemp(prefix="lake_load_", dir=os.environ.get("DATA_LAKE_TMP")))
    columns = None
    try:
        columns = take_columns(spec)
        p.update(phase="finding files")
        src = spec.get("source") or {}
        s3 = src.get("kind") == "s3"
        fmt = spec.get("format") or "auto"
        if s3:  # roadmap L5: s3://bucket/… read by DuckDB with the Vault S3 location's credentials — nothing staged
            pattern = (src.get("pattern") or "").strip()
            pattern = pattern + "**" if pattern.endswith("/") else pattern
            found_s3 = lake_store.s3_match(src.get("location_id"), pattern)
            if not found_s3["count"]:
                raise LoadError(f"Nothing in S3 matches '{pattern}'.")
            files, total = [], 0
            log("info", f"{found_s3['count']} S3 object(s) match {pattern}")
            if fmt == "auto":
                fmt = format_from_name(found_s3["sample"][0])
            if fmt not in ("csv", "json", "parquet"):
                raise LoadError("From S3: csv, json or parquet files (also .gz) — pick the format under Advanced.")
        else:
            files = _gather(ctx, spec, work)
            total = sum(f.stat().st_size for f in files)
            log("info", f"{len(files)} file(s), {total / 2**20:,.1f} MB")
        if fmt == "auto":
            found = {detect_any(str(f)) for f in files}
            if len(found) > 1:
                raise LoadError(f"The files have different formats ({', '.join(sorted(found))}) — load them separately.")
            fmt = found.pop()
        if fmt not in FORMATS:
            raise LoadError(f"Unknown format '{fmt}'")
        log("info", f"format: {fmt}")
        source = {"kind": src.get("kind"), "format": fmt,
                  "files": found_s3["sample"] if s3 else [f.name for f in files][:20],
                  "file_count": found_s3["count"] if s3 else len(files),
                  "bytes": total, **({"pattern": src["pattern"]} if src.get("pattern") else {}),
                  **({"url": src["url"]} if src.get("url") else {})}
        if spec.get("file"):
            source["file"] = spec["file"]

        if spec.get("external"):
            if columns:
                raise LoadError("A column map (rename, cast, mask…) can't be used on a read-in-place table — it is "
                                "never copied. Untick \"Read in place\" or remove the column map.")
            if src.get("kind") not in ("folder", "s3") or fmt not in ("csv", "json", "parquet"):
                raise LoadError("Read-in-place (external) tables need a data-folder or S3 source in csv, json or "
                                "parquet.")
            p["phase"] = "registering"
            options = {"header": spec.get("header"), "delimiter": spec.get("delimiter"),
                       **({"s3_location": src.get("location_id")} if s3 else {})}
            t = lake.register_external(ws, table, pattern if s3 else str(sources.ROOT / src["pattern"]), fmt,
                                       source=source, options=options,
                                       create_workspace_if_missing=True, replace=mode == "overwrite")
            p.update(phase="done", rows=t["row_count"], seconds=round(time.monotonic() - t0, 1))
            log("ok", f"registered {t['full_name']} (external, {t['row_count']:,} rows, read in place)")
            return

        if not s3:
            files, fmt = _to_readable(files, fmt, spec, work, log)
        add_name = bool(spec.get("add_filename"))

        def make_select(text_columns: list[str] | None = None) -> str:
            expr = build_multi_read_expr([pattern] if s3 else [str(f) for f in files], fmt, header=spec.get("header"),
                                         delimiter=spec.get("delimiter") or None, with_filename=add_name,
                                         varchar_columns=text_columns)
            return (f"SELECT * EXCLUDE (filename), regexp_extract(filename, '[^/]+$') AS _source_file FROM {expr}"
                    if add_name else f"SELECT * FROM {expr}")

        out_dir = work / "parquet"
        con = _connect(work)
        if s3:
            lake_store.use_s3(con, src.get("location_id"), pattern)
        compiled = _copy_to_parquet(ctx, con, make_select, columns, bool(spec.get("only_listed")), out_dir,
                                    csv=fmt == "csv")
        parts = sorted(out_dir.rglob("*.parquet"))
        if not parts:
            raise LoadError("The input produced no rows/columns.")
        p["phase"] = "storing"
        if columns:
            source["column_map"] = colmap.public_summary(columns, bool(spec.get("only_listed")))
        old = None
        try:
            old = lake.get_table(ws, table)
        except lake_store.NotFound:
            pass
        t = lake.write_table(ws, table, parts, mode=mode, source=source, create_workspace_if_missing=True)
        if old is not None and mode == "overwrite":
            before, after = {c["name"] for c in old["columns"]}, {c["name"] for c in t["columns"]}
            if before != after:
                log("warn", "columns changed: " + ", ".join([f"+{c}" for c in sorted(after - before)] +
                                                             [f"−{c}" for c in sorted(before - after)]))
        p.update(phase="done", rows=t["row_count"], table=t["full_name"], percent=100,
                 seconds=round(time.monotonic() - t0, 1))
        log("ok", f"{mode}: {t['full_name']} now has {t['row_count']:,} rows in {t['parts']} Parquet file(s), "
                  f"{t['size_bytes'] / 2**20:,.1f} MB ({p['seconds']} s)")
    except (LoadError, lake_store.LakeError, ValueError) as exc:
        p.update(phase="failed", error=str(exc))
        log("error", str(exc))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        drop_secrets(spec.get("secrets_ref"))
        src = spec.get("source") or {}
        if src.get("kind") == "upload" and p.get("phase") == "done":
            sources.STAGE.remove_all(src["upload_id"])  # staged copies are only needed until the load succeeded


# ---- the column map (roadmap L7) ------------------------------------------------------------------------------------

_SECRET_TTL = 1800


def _secret_store():
    """Short-lived side channel for salts / seeds: they travel to the worker through Redis under `secrets_ref` (30 min,
    deleted when the job ends) instead of the job arguments, which RQ keeps for an hour (a week when a job fails)."""
    try:
        from core.state.sessions import SessionStore

        return SessionStore("data-lake-secrets", ttl_seconds=_SECRET_TTL)
    except Exception:  # noqa: BLE001 — no Redis (standalone / tests): the caller keeps them in the spec
        return None


def stash_secrets(ref: str, secrets: dict) -> bool:
    store = _secret_store()
    if store is None or not secrets:
        return False
    try:
        store.set(ref, {"secrets": secrets})
        return True
    except Exception:  # noqa: BLE001
        return False


def take_columns(spec: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The spec's column map with its salts / seeds put back (validated)."""
    cols = spec.get("columns")
    if not cols:
        return None
    ref = spec.get("secrets_ref")
    if ref:
        store = _secret_store()
        data = store.get(ref) if store is not None else None
        if data is None and any((c.get("protect") or {}).get("has_secret") for c in cols):
            raise LoadError("The salt/seed for this load expired — start the load again.")
        cols = colmap.merge_secrets(cols, (data or {}).get("secrets"))
    try:
        colmap.normalize_entries(cols)
    except colmap.ColmapError as exc:
        raise LoadError(f"Column map: {exc}") from None
    return cols


def drop_secrets(ref: str | None) -> None:
    store = _secret_store() if ref else None
    if store is not None:
        try:
            store.delete(ref)
        except Exception:  # noqa: BLE001
            pass


def _connect(work: Path):
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory = '{work / 'spill'}'")
    return con


def _check_casts(ctx: Any, con: Any, select: str, compiled: "colmap.Compiled") -> None:
    """One pass counting values that don't convert: strict columns stop the load, the others become NULL (warned)."""
    if not compiled.cast_checks:
        return
    ctx.progress["phase"] = "checking conversions"
    row = con.execute(colmap.failing_count_sql(select, compiled.cast_checks)).fetchone()
    warnings = []
    for (name, typ, mode, _sql), n in zip(compiled.cast_checks, row):
        n = int(n or 0)
        if not n:
            continue
        if mode == "fail":
            raise LoadError(f"{n:,} value(s) in '{name}' can't be converted to {typ.lower()} (strict mode) — "
                            f"nothing was loaded. Use \"set to NULL\" instead, or fix the data.")
        warnings.append({"column": name, "type": typ.lower(), "count": n})
        ctx.log("warn", f"{n:,} value(s) in `{name}` couldn't be converted to {typ.lower()} → NULL")
    ctx.progress["warnings"] = warnings


def _copy_to_parquet(ctx: Any, con: Any, make_select: Any, columns: list[dict[str, Any]] | None, only_listed: bool,
                     out_dir: Path, csv: bool = False) -> "colmap.Compiled | None":
    """COPY the reader's SELECT (`make_select(text_columns)`, wrapped by the column map when there is one) to Parquet
    files in out_dir; Stop interrupts it. Closes `con`. For a CSV, columns the map gives an explicit type are read as
    raw text first (so "00123", dates in any format and bad numbers are decided by the map, not by the sniffer).
    When the load protects columns, DuckDB's own error text is NOT shown (it can quote data rows)."""
    import duckdb

    p, log = ctx.progress, ctx.log
    protected = bool(columns) and any((c.get("protect") or {}).get("kind", "none") != "none" for c in columns)
    stop = threading.Event()

    def watch():  # Stop → interrupt DuckDB (its 1.2 Python API reports no progress: the page shows elapsed time)
        while not stop.wait(1.0):
            if ctx.cancel.is_set():
                try:
                    con.interrupt()
                except Exception:  # noqa: BLE001
                    pass

    threading.Thread(target=watch, daemon=True).start()
    compiled = None
    try:
        select = make_select(None)
        final = select
        if columns:
            p["phase"] = "applying the column map"
            available = {r[0]: r[1] for r in con.execute(f"DESCRIBE {select}").fetchall()}
            if csv:
                # (always, even when DESCRIBE says VARCHAR: newer DuckDBs push a TRY_CAST into the CSV reader's own
                # sniffed type, and a bad value would then raise instead of becoming NULL)
                typed = [e.source for e in colmap.normalize_entries(columns) if e.include and e.duck_type and e.source in available]
                if typed:
                    select = make_select(sorted(set(typed)))
                    available = {r[0]: r[1] for r in con.execute(f"DESCRIBE {select}").fetchall()}
            compiled = colmap.compile_select(select, available, columns, only_listed)
            _check_casts(ctx, con, select, compiled)
            final = compiled.select_sql
            prot = [f"{c['name']} ({c['protect']})" for c in compiled.columns if c["protect"] != "none"]
            log("info", f"column map: {len(compiled.columns)} column(s)" + (f"; protected: {', '.join(prot)}" if prot else ""))
            p["protected"] = [{"name": c["name"], "kind": c["protect"]} for c in compiled.columns if c["protect"] != "none"]
        p["phase"] = "converting to Parquet"
        con.execute(f"COPY ({final}) TO '{out_dir}' (FORMAT PARQUET, FILE_SIZE_BYTES '{PART_BYTES}')")
    except duckdb.InterruptException:
        raise LoadError("Stopped.") from None
    except colmap.ColmapError as exc:
        raise LoadError(f"Column map: {exc}") from None
    except duckdb.Error as exc:
        if protected:
            raise LoadError(f"Could not process the data ({type(exc).__name__}) — details are hidden because this "
                            f"load protects columns.") from None
        raise LoadError(f"Could not read the data: {str(exc).splitlines()[0][:400]}") from None
    finally:
        stop.set()
        con.close()
    return compiled


# ---- previewing columns before a load (roadmap L7) -----------------------------------------------------------------

INSPECT_MEMORY = os.environ.get("DATA_LAKE_QUERY_MEMORY", "384MB")
INSPECT_FILES = 5                 # at most this many files are looked at (column names are merged by name anyway)
INSPECT_URL_BYTES = 8 << 20       # a link is read only this far
INSPECT_EXCEL_ROWS = 200


class _Quiet:
    """ctx stand-in for code shared with the jobs (download logging, progress)."""

    def __init__(self):
        self.progress: dict[str, Any] = {}
        self.cancel = threading.Event()

    def log(self, *_a, **_k) -> None:
        pass


def _show(v: Any) -> Any:
    return None if v is None else str(v)[:80]


def inspect_source(spec: dict[str, Any], sample_rows: int = 5) -> dict[str, Any]:
    """Column names, types and a few sample values of what a load would read — WITHOUT loading it (DESCRIBE + LIMIT on the
    first few files). Returns {"format", "files", "file_count", "columns": [{name, type, sql_type, samples,
    suggestion}]}. Samples go to the browser only — nothing is stored or logged."""
    import duckdb

    from core import lake as lake_store

    lake = lake_store.scoped("data-lake")
    work = Path(tempfile.mkdtemp(prefix="lake_inspect_", dir=os.environ.get("DATA_LAKE_TMP")))
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit = '{INSPECT_MEMORY}'")
        con.execute(f"SET temp_directory = '{work / 'spill'}'")
        src = spec.get("source") or {}
        kind = src.get("kind")
        quiet = _Quiet()
        fmt = spec.get("format") or "auto"
        names: list[str]
        count = 1
        if kind == "table":
            ws, _, name = (src.get("table") or "").partition(".")
            t = lake.get_table(ws, name)
            lake.prepare(con, t)
            expr, fmt, names = lake.read_expr(ws, name), "table", [t["full_name"]]
        elif kind == "s3":
            pattern = (src.get("pattern") or "").strip()
            pattern = pattern + "**" if pattern.endswith("/") else pattern
            found = lake_store.s3_match(src.get("location_id"), pattern)
            if not found["count"]:
                raise LoadError(f"Nothing in S3 matches '{pattern}'.")
            fmt = format_from_name(found["sample"][0]) if fmt == "auto" else fmt
            if fmt not in ("csv", "json", "parquet"):
                raise LoadError("From S3: csv, json or parquet files — pick the format under Advanced.")
            lake_store.use_s3(con, src.get("location_id"), found["sample"][0])
            expr = build_multi_read_expr([found["sample"][0]], fmt, header=spec.get("header"),
                                         delimiter=spec.get("delimiter") or None)
            names, count = [found["sample"][0]], found["count"]
        else:
            if kind == "url":
                f = sources.download(src.get("url") or "", work, quiet.log, limit=INSPECT_URL_BYTES)
                if detect_any(str(f)) not in ("csv", "json"):
                    raise LoadError("A preview of a link works for CSV and JSON files — upload the file or use the data "
                                    "folder for other formats, or load without a preview.")
                files = [f]
            elif kind == "upload":
                files = []
                for n in (src.get("files") or [])[:INSPECT_FILES]:
                    p = sources.STAGE.fetch(src["upload_id"], n)
                    if p is None:
                        raise LoadError(f"The uploaded file '{n}' is gone (uploads are kept 1 day) — upload it again.")
                    files.append(p)
                count = len(src.get("files") or [])
            elif kind == "folder":
                matched = sources.match(src.get("pattern") or "")
                if not matched:
                    raise LoadError(f"No files match '{src.get('pattern')}' in the data folder.")
                files, count = matched[:INSPECT_FILES], len(matched)
            else:
                raise LoadError("source.kind must be upload, folder, url, s3 or table")
            if not files:
                raise LoadError("Choose at least one file first.")
            if fmt == "auto":
                found_fmt = {detect_any(str(f)) for f in files}
                if len(found_fmt) > 1:
                    raise LoadError(f"The files have different formats ({', '.join(sorted(found_fmt))}) — load them "
                                    f"separately.")
                fmt = found_fmt.pop()
            if fmt not in FORMATS:
                raise LoadError(f"Unknown format '{fmt}'")
            names = [f.name for f in files]
            use = files[:1] if fmt in ("xml", "excel") else files
            use, rfmt = _to_readable(use, fmt, spec, work, quiet.log, limit_rows=INSPECT_EXCEL_ROWS)
            expr = build_multi_read_expr([str(f) for f in use], rfmt, header=spec.get("header"),
                                         delimiter=spec.get("delimiter") or None)
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {expr}").fetchall()
            rows = con.execute(f"SELECT * FROM {expr} LIMIT 20").fetchall()
        except duckdb.Error as exc:
            raise LoadError(f"Could not read the data: {str(exc).splitlines()[0][:300]}") from None
        cols = []
        for i, d in enumerate(desc):
            vals = [r[i] for r in rows]
            cols.append({"name": d[0], "type": d[1], "sql_type": lake_store.sql_type(d[1]),
                         "samples": [_show(v) for v in vals[:sample_rows]],
                         "suggestion": colmap.suggest_protection(d[0], vals)})
        return {"format": fmt, "files": names[:INSPECT_FILES], "file_count": count, "columns": cols}
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)


# ---- a protected / reshaped COPY of an existing table (roadmap L7) --------------------------------------------------

def run_copy(ctx: Any, spec: dict[str, Any]) -> None:
    """Job body: read a Vault Data table through the column map into another table (e.g. a masked copy to share).
    spec = {"from": "ws.table", "workspace", "table", "mode", "columns", "only_listed", "secrets_ref"}."""
    from core import lake as lake_store

    lake = lake_store.scoped("data-lake")
    log, p = ctx.log, ctx.progress
    t0 = time.monotonic()
    ws, table, mode = spec["workspace"], spec["table"], spec.get("mode") or "create"
    work = Path(tempfile.mkdtemp(prefix="lake_copy_", dir=os.environ.get("DATA_LAKE_TMP")))
    try:
        columns = take_columns(spec)
        fws, _, fname = (spec.get("from") or "").partition(".")
        if (fws, fname) == (ws, table):
            raise LoadError("The copy must go to a different table than its source.")
        p.update(phase="reading the table")
        srct = lake.get_table(fws, fname)
        con = _connect(work)
        lake.prepare(con, srct)
        select = f"SELECT * FROM {lake.read_expr(fws, fname)}"
        log("info", f"copying {srct['full_name']} ({srct['row_count']:,} rows)")
        out_dir = work / "parquet"
        _copy_to_parquet(ctx, con, lambda _text=None: select, columns, bool(spec.get("only_listed")), out_dir)
        parts = sorted(out_dir.rglob("*.parquet"))
        if not parts:
            raise LoadError("The copy produced no rows/columns.")
        p["phase"] = "storing"
        source = {"kind": "copy", "from": srct["full_name"]}
        if columns:
            source["column_map"] = colmap.public_summary(columns, bool(spec.get("only_listed")))
        t = lake.write_table(ws, table, parts, mode=mode, source=source, create_workspace_if_missing=True)
        p.update(phase="done", rows=t["row_count"], table=t["full_name"], percent=100,
                 seconds=round(time.monotonic() - t0, 1))
        log("ok", f"{mode}: {t['full_name']} now has {t['row_count']:,} rows ({p['seconds']} s)")
    except (LoadError, lake_store.LakeError, ValueError) as exc:
        p.update(phase="failed", error=str(exc))
        log("error", str(exc))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        drop_secrets(spec.get("secrets_ref"))


def format_from_name(name: str) -> str:
    """csv / json / parquet / … from a file name's extension (.gz ignored) — S3 objects aren't sniffed."""
    from core.file_source import _EXT_FORMAT

    base = re.sub(r"\.gz$", "", name.lower())
    ext = base.rsplit(".", 1)[-1] if "." in base.rsplit("/", 1)[-1] else ""
    return _EXT_FORMAT.get(ext, "auto")


def default_table_name(filename: str) -> str:
    """'Sales 2026-10.csv.gz' → 'sales_2026_10' (what the page suggests)."""
    from core.lake import safe_name

    base = re.sub(r"(\.gz)?$", "", filename.rsplit("/", 1)[-1], flags=re.I)
    return safe_name(base.rsplit(".", 1)[0] if "." in base else base)
