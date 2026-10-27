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
        "header": null|true|false, "delimiter": null|",", "add_filename": bool, "sheet": null|"Sheet1", "external": bool}
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
    from data_lake import sources
except ImportError:  # standalone
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


def _to_readable(files: list[Path], fmt: str, spec: dict[str, Any], work: Path, log) -> tuple[list[Path], str]:
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
            df = pd.read_excel(f, sheet_name=sheet, engine="openpyxl")
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
    try:
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
        p["phase"] = "converting to Parquet"
        add_name = bool(spec.get("add_filename"))
        expr = build_multi_read_expr([pattern] if s3 else [str(f) for f in files], fmt, header=spec.get("header"),
                                     delimiter=spec.get("delimiter") or None, with_filename=add_name)
        select = (f"SELECT * EXCLUDE (filename), regexp_extract(filename, '[^/]+$') AS _source_file FROM {expr}"
                  if add_name else f"SELECT * FROM {expr}")
        out_dir = work / "parquet"
        con = duckdb.connect(":memory:")
        con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
        con.execute(f"SET temp_directory = '{work / 'spill'}'")
        if s3:
            lake_store.use_s3(con, src.get("location_id"), pattern)
        stop = threading.Event()

        def watch():  # Stop → interrupt DuckDB (its 1.2 Python API reports no progress: the page shows elapsed time)
            while not stop.wait(1.0):
                if ctx.cancel.is_set():
                    try:
                        con.interrupt()
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=watch, daemon=True).start()
        try:
            con.execute(f"COPY ({select}) TO '{out_dir}' (FORMAT PARQUET, FILE_SIZE_BYTES '{PART_BYTES}')")
        except duckdb.InterruptException:
            raise LoadError("Stopped.") from None
        except duckdb.Error as exc:
            raise LoadError(f"Could not read the data: {str(exc).splitlines()[0][:400]}") from None
        finally:
            stop.set()
            con.close()
        parts = sorted(out_dir.rglob("*.parquet"))
        if not parts:
            raise LoadError("The input produced no rows/columns.")
        p["phase"] = "storing"
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
        src = spec.get("source") or {}
        if src.get("kind") == "upload" and p.get("phase") == "done":
            sources.STAGE.remove_all(src["upload_id"])  # staged copies are only needed until the load succeeded


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
