"""
df-studio/engine.py

Session state and DataFrame plumbing. Sessions live OUTSIDE the process (roadmap B2, session_store.py):
metadata in Redis (sliding TTL), the original DataFrame in S3 storage — so a session survives restarts and
works across several worker processes. Each process keeps a small LRU cache of original DataFrames so a step
doesn't re-download the file (the original never changes within a session, so the cache can't go stale).
Every function that changes a session persists it before returning (`save_session`).

The pipeline model: each session keeps the ORIGINAL DataFrame plus an
ordered list of steps. The "current" DataFrame is always recomputed by
replaying every step over the original — not an incremental mutation or a
snapshot stack. This makes "remove a step from the middle" trivially
correct (just replay the remaining steps) instead of needing undo/redo
bookkeeping.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

try:  # package import when mounted inside the toolbox (df_studio.*)
    from df_studio import session_store
    from df_studio import steps as steps_mod
except ImportError:  # flat import when run standalone from within this folder
    import session_store
    import steps as steps_mod

STEP_HANDLERS = steps_mod.STEP_HANDLERS
STEP_LABELS = steps_mod.STEP_LABELS

PREVIEW_ROW_CAP = 5000
# Bounds the total cells shipped to the browser on every preview response,
# regardless of shape — a 5000-column file would otherwise send
# min(row_count, 5000) rows × ALL columns (tens of millions of cells) on
# every single step. A normal-shaped file (few dozen columns) is
# unaffected: the row cap stays PREVIEW_ROW_CAP either way.
PREVIEW_CELL_BUDGET = 400_000
MIN_PREVIEW_ROWS = 20


class StepError(ValueError):
    pass


@dataclass
class Session:
    filename: str
    original_df: pd.DataFrame
    steps: list[dict[str, Any]] = field(default_factory=list)
    preview_mode: str = "head"
    # Generated once per session so .sample() doesn't reshuffle the visible
    # rows on every incidental recompute() (Check, step add/remove, template
    # apply all trigger one) — only an explicit "resample" regenerates this.
    sample_seed: int = field(default_factory=lambda: random.randint(0, 2**31 - 1))
    sid: str = ""
    frame_format: str = ""
    # roadmap L5: other Vault Data tables added by name for joins — {"customers": "crm.customers"}
    frames: dict[str, str] = field(default_factory=dict)


BACKEND = session_store.make_backend()
_CACHE_SIZE = max(1, int(os.environ.get("DF_STUDIO_CACHE_SESSIONS") or 3))
_cache: "OrderedDict[str, pd.DataFrame]" = OrderedDict()  # sid -> original_df, per process
_cache_lock = threading.Lock()


def _cache_put(sid: str, df: pd.DataFrame) -> None:
    with _cache_lock:
        _cache[sid] = df
        _cache.move_to_end(sid)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


def _cache_get(sid: str) -> pd.DataFrame | None:
    with _cache_lock:
        df = _cache.get(sid)
        if df is not None:
            _cache.move_to_end(sid)
        return df


def _meta(session: Session) -> dict[str, Any]:
    return {"filename": session.filename, "steps": session.steps, "preview_mode": session.preview_mode,
            "sample_seed": session.sample_seed, "frame_format": session.frame_format, "frames": session.frames}


def load_dataframe(
    filename: str,
    content: bytes,
    *,
    # CSV/TSV/TXT
    sep: str | None = None,
    encoding: str = "utf-8",
    header: bool = True,
    nrows: int | None = None,
    # JSON
    orient: str | None = None,
    lines: bool | None = None,  # None = auto-detect (try both), not "false"
    # XML
    xpath: str | None = None,
    # Parquet
    columns: list[str] | None = None,
) -> pd.DataFrame:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    buf = io.BytesIO(content)
    try:
        if ext in ("csv", "tsv", "txt"):
            actual_sep = sep or ("\t" if ext == "tsv" else ",")
            return pd.read_csv(
                buf, sep=actual_sep, encoding=encoding,
                header=0 if header else None, nrows=nrows,
            )
        if ext == "json":
            # nrows isn't a pandas read_json option — capped after the fact,
            # which does not avoid reading the whole file into memory first
            # (see engine.py's docstring / CLAUDE.md for why CSV/TSV is the
            # only format this tool can genuinely stream-limit).
            json_kwargs: dict[str, Any] = {"encoding": encoding}
            if orient:
                json_kwargs["orient"] = orient
            if lines is not None:
                df = pd.read_json(buf, lines=lines, **json_kwargs)
            else:
                try:
                    df = pd.read_json(buf, **json_kwargs)
                except ValueError:
                    buf.seek(0)
                    df = pd.read_json(buf, lines=True, **json_kwargs)
            return df.head(nrows) if nrows else df
        if ext == "xml":
            xml_kwargs: dict[str, Any] = {"encoding": encoding}
            if xpath:
                xml_kwargs["xpath"] = xpath
            df = pd.read_xml(buf, **xml_kwargs)
            return df.head(nrows) if nrows else df
        if ext == "parquet":
            # binary format — no meaningful encoding/sep, but pandas *can*
            # skip reading unwanted columns off disk (real column pruning,
            # unlike the row-limit's read-then-trim for this format).
            df = pd.read_parquet(buf, columns=columns or None)
            return df.head(nrows) if nrows else df
    except UnicodeDecodeError as exc:
        raise StepError(f"Couldn't decode file as {encoding} — try a different encoding.") from exc
    raise StepError(f"Unsupported file type '.{ext}'. Use CSV, TSV, JSON, XML, or Parquet.")


def create_session(filename: str, df: pd.DataFrame) -> str:
    """Store the original DataFrame + fresh metadata; returns the new session id. Slow for big frames
    (uploads the file to storage) — call from a worker thread."""
    session_id = uuid.uuid4().hex
    session = Session(filename=filename, original_df=df, sid=session_id)
    session.frame_format = BACKEND.save_frame(session_id, df)
    save_session(session)
    _cache_put(session_id, df)
    try:
        BACKEND.sweep()  # rate-limited cleanup of expired sessions' files
    except Exception:  # noqa: BLE001 - cleanup must never break a load
        pass
    return session_id


def get_session(session_id: str | None) -> Session:
    """Load a session (metadata from the backend, DataFrame from cache or storage). Call from a worker thread."""
    meta = BACKEND.load_meta(session_id) if session_id else None
    if meta is None:
        raise StepError("No active session — load a file first.")
    df = _cache_get(session_id)
    if df is None:
        df = BACKEND.load_frame(session_id, meta.get("frame_format", ""))
        if df is None:
            BACKEND.delete(session_id)
            raise StepError("This session's data has expired — load the file again.")
        _cache_put(session_id, df)
    return Session(filename=meta["filename"], original_df=df, steps=list(meta.get("steps", [])),
                   preview_mode=meta.get("preview_mode", "head"), sample_seed=int(meta["sample_seed"]),
                   sid=session_id, frame_format=meta.get("frame_format", ""), frames=dict(meta.get("frames") or {}))


def save_session(session: Session) -> None:
    """Persist the session's metadata (steps, preview mode, seed). The DataFrame is stored once, at create."""
    BACKEND.save_meta(session.sid, _meta(session))


def delete_session(session_id: str | None) -> None:
    """Remove a session and its stored DataFrame (e.g. the browser loaded a new file)."""
    if not session_id:
        return
    with _cache_lock:
        _cache.pop(session_id, None)
    BACKEND.delete(session_id)


# ---- other tables by name (roadmap L5: "Add for join") -------------------------------------------------------
LAKE_MAX_ROWS = int(os.environ.get("DF_STUDIO_LAKE_MAX_ROWS", "1000000"))
_lake_cache: "OrderedDict[tuple[str, int], pd.DataFrame]" = OrderedDict()   # (ws.table, version) → frame, per process
_RESERVED = {"df", "pd", "np", "transform"}


def _lake():
    from core import lake

    return lake, lake.scoped("df-studio")


def lake_frame(ref: str, limit: int | None = None) -> pd.DataFrame:
    """A Vault Data table as a DataFrame (exported to Parquet by DuckDB, then pandas), cached per table version."""
    import shutil
    import tempfile
    from pathlib import Path

    lake, scoped = _lake()
    ws, _, name = ref.partition(".")
    t = scoped.get_table(ws, name)
    key = (ref, int(t["version"]))
    with _cache_lock:
        if key in _lake_cache:
            _lake_cache.move_to_end(key)
            return _lake_cache[key]
    if t["row_count"] > LAKE_MAX_ROWS and not limit:
        raise StepError(f"{ref} has {t['row_count']:,} rows — more than the {LAKE_MAX_ROWS:,} DataFrame Studio keeps "
                        "in memory. Make a smaller table first (Data Lake → SQL: CREATE TABLE … AS SELECT … WHERE …).")
    tmp = Path(tempfile.mkdtemp(prefix="dfs_frame_"))
    try:
        scoped.export_table(ws, name, tmp / "t.parquet", "parquet", limit)
        df = pd.read_parquet(tmp / "t.parquet")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with _cache_lock:
        _lake_cache[key] = df
        while len(_lake_cache) > _CACHE_SIZE + 2:
            _lake_cache.popitem(last=False)
    return df


def frame_name(table: str, taken: set[str]) -> str:
    base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in table) or "table"
    if base[0].isdigit() or base in _RESERVED:
        base = "t_" + base
    name, i = base, 2
    while name in taken:
        name, i = f"{base}_{i}", i + 1
    return name


def add_frame(session: Session, ref: str, name: str | None = None) -> str:
    """Add another table by name (its variable in the Query box, its name in the Join step). Loads it once to check."""
    if ref in session.frames.values():
        return next(n for n, r in session.frames.items() if r == ref)
    name = frame_name(name or ref.partition(".")[2], set(session.frames))
    lake_frame(ref)
    session.frames[name] = ref
    save_session(session)
    return name


def remove_frame(session: Session, name: str) -> None:
    used = [i + 1 for i, s in enumerate(session.steps)
            if (s["type"] == "join_table" and s["params"].get("table") == name)
            or (s["type"] == "custom_code" and name in str(s["params"].get("code", "")))]
    if used:
        raise StepError(f"'{name}' is used by step {', '.join(map(str, used))} — remove that step first.")
    session.frames.pop(name, None)
    save_session(session)


def _frames_info(session: Session) -> list[dict[str, Any]]:
    out = []
    for name, ref in session.frames.items():
        try:
            ws, _, t = ref.partition(".")
            tbl = _lake()[1].get_table(ws, t)
            out.append({"name": name, "ref": ref, "rows": tbl["row_count"],
                        "columns": [c["name"] for c in tbl["columns"]]})
        except Exception as exc:  # noqa: BLE001 — a dropped table shows up as broken, not as a 500
            out.append({"name": name, "ref": ref, "rows": None, "columns": [], "error": str(exc)})
    return out


def _enabled(step: dict[str, Any]) -> bool:
    return step.get("enabled", True) is not False   # steps saved before DF1 have no flag = on


def recompute(session: Session) -> pd.DataFrame:
    loaders = {name: (lambda ref=ref: lake_frame(ref)) for name, ref in session.frames.items()}
    token = steps_mod.FRAMES.set(loaders)
    try:
        df = session.original_df
        for i, step in enumerate(session.steps):
            if not _enabled(step):
                continue
            handler = STEP_HANDLERS[step["type"]]
            try:
                df, _ = handler(df, step["params"])
            except ValueError as exc:  # say WHICH step broke — "Column(s) not found: x" alone is hard to place
                raise StepError(f"Step {i + 1} ({STEP_LABELS.get(step['type'], step['type'])}): {exc}") from exc
        return df
    finally:
        steps_mod.FRAMES.reset(token)


def _run_step(session: Session, step_type: str, params: dict[str, Any]) -> tuple[pd.DataFrame, str, list[str]]:
    if step_type not in STEP_HANDLERS:
        raise StepError(f"Unknown step type '{step_type}'.")
    current = recompute(session)
    handler = STEP_HANDLERS[step_type]
    token = steps_mod.FRAMES.set({name: (lambda ref=ref: lake_frame(ref)) for name, ref in session.frames.items()})
    notes: list[str] = []
    note_token = steps_mod.NOTES.set(notes)
    try:
        df, code = handler(current, params)
        return df, code, notes
    finally:
        steps_mod.NOTES.reset(note_token)
        steps_mod.FRAMES.reset(token)


run_step = _run_step   # public name: server.py's Check wants the code and the notes too


def preview_step_ex(session: Session, step_type: str, params: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    """Run a step against the current DataFrame without committing it to the pipeline — the "Check" half of the
    Query / Clean / Formula workflow. Also returns what the step wants to tell the user (roadmap DF1)."""
    new_df, _, notes = _run_step(session, step_type, params)
    return new_df, notes


def preview_step(session: Session, step_type: str, params: dict[str, Any]) -> pd.DataFrame:
    return preview_step_ex(session, step_type, params)[0]


def apply_step_ex(session: Session, step_type: str, params: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    _, code, notes = _run_step(session, step_type, params)  # validates against current df before committing
    step: dict[str, Any] = {"type": step_type, "params": params, "code": code, "enabled": True}
    if notes:
        step["notes"] = notes
    session.steps.append(step)
    save_session(session)
    return recompute(session), notes


def apply_step(session: Session, step_type: str, params: dict[str, Any]) -> pd.DataFrame:
    return apply_step_ex(session, step_type, params)[0]


def _swap_steps(session: Session, new_steps: list[dict[str, Any]]) -> pd.DataFrame:
    """Install a changed step list only if the whole pipeline still replays; otherwise keep the old one and say why
    (turning off / moving / removing a step that a later step depends on)."""
    old = session.steps
    session.steps = new_steps
    try:
        df = recompute(session)
    except ValueError:
        session.steps = old
        raise
    save_session(session)
    return df


def remove_step(session: Session, index: int) -> pd.DataFrame:
    if index < 0 or index >= len(session.steps):
        raise StepError("Step not found.")
    return _swap_steps(session, session.steps[:index] + session.steps[index + 1:])


def toggle_step(session: Session, index: int, enabled: bool) -> pd.DataFrame:
    """Turn a step off / on without deleting it (roadmap DF1)."""
    if index < 0 or index >= len(session.steps):
        raise StepError("Step not found.")
    steps = [dict(s) for s in session.steps]
    steps[index]["enabled"] = bool(enabled)
    return _swap_steps(session, steps)


def move_step(session: Session, index: int, direction: str) -> pd.DataFrame:
    """Move a step one place up or down (roadmap DF1)."""
    if direction not in ("up", "down"):
        raise StepError("Direction must be up or down.")
    target = index - 1 if direction == "up" else index + 1
    if index < 0 or index >= len(session.steps) or target < 0 or target >= len(session.steps):
        raise StepError("Can't move the step there.")
    steps = list(session.steps)
    steps[index], steps[target] = steps[target], steps[index]
    return _swap_steps(session, steps)


def reset_steps(session: Session) -> pd.DataFrame:
    session.steps.clear()
    save_session(session)
    return session.original_df


def set_preview_mode(session: Session, mode: str, resample: bool = False) -> dict[str, Any]:
    if mode not in ("head", "sample"):
        raise StepError(f"Unknown preview mode '{mode}'.")
    session.preview_mode = mode
    if resample:
        session.sample_seed = random.randint(0, 2**31 - 1)
    save_session(session)
    return build_preview(session, recompute(session))


def apply_template(session: Session, template_steps: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[str]]:
    """Replace the pipeline with a saved template's steps, replayed from scratch.

    Stops at the first step that doesn't fit this file (e.g. a renamed/missing
    column) and returns what succeeded up to that point, plus a message
    explaining where it stopped — templates are written against one file's
    shape and aren't guaranteed to fit another.
    """
    session.steps.clear()
    errors: list[str] = []
    for i, step in enumerate(template_steps):
        try:
            apply_step(session, step["type"], step["params"])
        except ValueError as exc:  # StepError and the plain ValueErrors step handlers raise
            label = STEP_LABELS.get(step["type"], step["type"])
            errors.append(f"Step {i + 1} ({label}): {exc}")
            break
    save_session(session)  # also covers "template's first step failed" (pipeline was cleared)
    return recompute(session), errors


_SCRIPT_LOADERS = {
    "csv": "pd.read_csv({path!r})",
    "json": "pd.read_json({path!r})",
    "xml": "pd.read_xml({path!r})",
    "parquet": "pd.read_parquet({path!r})",
}


def generate_script(session: Session) -> str:
    ext = session.filename.rsplit(".", 1)[-1].lower() if "." in session.filename else "csv"
    loader_template = _SCRIPT_LOADERS.get(ext, _SCRIPT_LOADERS["csv"])
    lines = [
        "import pandas as pd",
        "import numpy as np",
        "",
        f"df = {loader_template.format(path=session.filename)}",
    ]
    for name, ref in session.frames.items():  # tables added for joins: export them from Vault Data next to the script
        lines.append(f"{name} = pd.read_parquet({(ref + '.parquet')!r})")
    for step in session.steps:
        if not _enabled(step):
            continue   # a turned-off step is not part of the pipeline's result, so not of its script either
        lines.append("")
        lines.append(step["code"])
    lines.append("")
    lines.append("print(df.head())")
    return "\n".join(lines)


def _json_safe_records(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    capped = df.head(limit)
    return json.loads(capped.to_json(orient="records", date_format="iso"))


def compute_insight(df: pd.DataFrame, kind: str, column: str | None = None) -> dict[str, Any]:
    if kind == "describe":
        stats = df.describe(include="all").reset_index().rename(columns={"index": "stat"})
        return {"kind": kind, "columns": list(stats.columns), "rows": _json_safe_records(stats, len(stats))}
    if kind == "info":
        rows = [
            {
                "column": c,
                "dtype": str(df[c].dtype),
                "non_null": int(df[c].notna().sum()),
                "nulls": int(df[c].isna().sum()),
            }
            for c in df.columns
        ]
        return {"kind": kind, "row_count": len(df), "column_count": len(df.columns), "rows": rows}
    if kind == "nunique":
        rows = [{"column": c, "unique": int(df[c].nunique())} for c in df.columns]
        return {"kind": kind, "rows": rows}
    if kind == "value_counts":
        if not column:
            raise StepError("Pick a column for value counts.")
        if column not in df.columns:
            raise StepError(f"Column not found: {column}")
        counts = df[column].value_counts().head(50).reset_index()
        counts.columns = ["value", "count"]
        return {"kind": kind, "column": column, "rows": _json_safe_records(counts, 50)}
    raise StepError(f"Unknown insight kind '{kind}'.")


def sql_type(s: pd.Series) -> str:
    """The column's type in SQL words (bigint, double, varchar, date, timestamp, numeric…) — what the page shows
    instead of pandas' int64/object (roadmap L5, owner request)."""
    import datetime as dt
    from decimal import Decimal

    k = s.dtype
    if pd.api.types.is_bool_dtype(k):
        return "boolean"
    if pd.api.types.is_integer_dtype(k):
        return {1: "smallint", 2: "smallint", 4: "integer"}.get(k.itemsize, "bigint")
    if pd.api.types.is_float_dtype(k):
        return "real" if k.itemsize == 4 else "double"
    if pd.api.types.is_datetime64_any_dtype(k):
        if getattr(k, "tz", None) is not None:
            return "timestamptz"
        head = s.dropna().head(200)   # nothing but midnights = a date column (e.g. after "Change type → date")
        return "date" if len(head) and (head == head.dt.normalize()).all() else "timestamp"
    if pd.api.types.is_timedelta64_dtype(k):
        return "interval"
    sample = s.dropna().head(50)
    if len(sample):
        v = sample.iloc[0]
        if isinstance(v, Decimal):
            return "numeric"
        if isinstance(v, dt.datetime):
            return "timestamp"
        if isinstance(v, dt.date):
            return "date"
        if isinstance(v, (dict, list)):
            return "json"
        if isinstance(v, bytes):
            return "bytea"
    return "varchar"


def column_stats(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Per column over the WHOLE DataFrame (not the preview rows): empty values, distinct values, and for numbers /
    dates min · max (· average · std for numbers). `columns` limits it to some columns (the header menu asks for one)."""
    out: dict[str, dict[str, Any]] = {}
    n = len(df)
    for c in df.columns:
        if columns is not None and c not in columns:
            continue
        s = df[c]
        nulls = int(s.isna().sum())
        try:
            distinct = int(s.nunique(dropna=True))
        except TypeError:  # unhashable values (lists/dicts)
            distinct = None
        st: dict[str, Any] = {"rows": n, "nulls": nulls, "null_pct": round(100.0 * nulls / n, 1) if n else 0.0,
                              "distinct": distinct}
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            d = s.describe()
            st.update({k: (None if pd.isna(d.get(k)) else float(d.get(k))) for k in ("min", "max", "mean", "std")})
        elif pd.api.types.is_datetime64_any_dtype(s) and n - nulls:
            st.update({"min": str(s.min()), "max": str(s.max())})
        out[str(c)] = st
    return out


_BOOLISH = {"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"}
_DATEISH = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")


def suggest_fixes(s: pd.Series, stat: dict[str, Any]) -> list[dict[str, Any]]:
    """What is probably worth doing to this column (roadmap DF1: the header menu's "suggested fix"). Looks at the
    column's stats plus a sample of at most 1000 values; every suggestion is {action, why, params} where `action` is a
    Clean-panel step type and `params` pre-fills its form. Never changes anything."""
    out: list[dict[str, Any]] = []
    n = stat.get("rows") or 0
    if not n:
        return out
    numeric = pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype)
    pct = stat.get("null_pct") or 0
    if 0 < pct < 100:
        why = f"{pct}% of the values are empty" + (" — most of the column; maybe drop it instead" if pct >= 80 else "")
        out.append({"action": "fill_nulls", "why": why,
                    "params": {"method": "median" if numeric else "mode"}})
    if stat.get("distinct") == 1 and n > 1:
        out.append({"action": "drop_constant", "why": "every value is the same — it adds nothing", "params": {}})
    textual = not numeric and not pd.api.types.is_datetime64_any_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype)
    if textual:
        sample = s.dropna().head(1000)
        sample = sample[sample.map(lambda v: isinstance(v, str))]
        if len(sample):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw_num = pd.to_numeric(sample, errors="coerce").notna().mean()
                stripped_num = pd.to_numeric(sample.str.replace(r"[,$€£%\s]", "", regex=True), errors="coerce").notna().mean()
                lowered = sample.str.strip().str.lower()
                if raw_num >= 0.9:
                    whole = (pd.to_numeric(sample, errors="coerce").dropna() % 1 == 0).all()
                    out.append({"action": "cast_type", "why": "these look like numbers stored as text",
                                "params": {"to": "integer" if whole else "float"}})
                elif stripped_num >= 0.9:
                    out.append({"action": "cast_type", "why": "numbers with , $ or % signs stored as text",
                                "params": {"to": "float", "ignore_symbols": True}})
                elif lowered.nunique() <= 2 and set(lowered.unique()) <= _BOOLISH and len(set(lowered.unique())) >= 1 and lowered.nunique() == 2:
                    out.append({"action": "cast_type", "why": "only two values, like yes/no", "params": {"to": "boolean"}})
                elif sample.map(lambda v: bool(_DATEISH.match(v))).mean() >= 0.9 and \
                        pd.to_datetime(sample, errors="coerce").notna().mean() >= 0.9:
                    out.append({"action": "cast_type", "why": "these look like dates stored as text", "params": {"to": "date"}})
            if (sample != sample.str.strip()).any():
                out.append({"action": "clean_text", "why": "some values have extra spaces at the ends",
                            "params": {"ops": ["strip"]}})
            elif sample.str.strip().nunique() > sample.str.strip().str.lower().nunique():
                out.append({"action": "clean_text", "why": "the same text is written with different capitals",
                            "params": {"ops": ["strip", "lower"]}})
    elif numeric and n > 8:
        v = s.dropna().astype("float64")
        if len(v) > 8:
            q1, q3 = v.quantile(0.25), v.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                k = int(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).sum())
                if 0 < k <= 0.2 * len(v):
                    out.append({"action": "clip_outliers", "why": f"{k:,} value(s) are far outside the rest",
                                "params": {"method": "iqr", "action": "clip"}})
    return out[:4]


def build_preview(session: Session, df: pd.DataFrame) -> dict[str, Any]:
    total_rows = len(df)
    num_cols = max(len(df.columns), 1)
    row_cap = max(MIN_PREVIEW_ROWS, min(PREVIEW_ROW_CAP, PREVIEW_CELL_BUDGET // num_cols))
    shown_rows = min(total_rows, row_cap)
    if session.preview_mode == "sample" and shown_rows > 0:
        capped = df.sample(n=shown_rows, random_state=session.sample_seed)
    else:
        capped = df.head(shown_rows)
    return {
        "filename": session.filename,
        # the Vault Data table this session started from ("ws.table") — the Tables list marks it as loaded
        "table_ref": session.filename[:-8] if session.filename.endswith(".parquet") and session.filename.count(".") == 2 else None,
        "columns": [{"name": c, "dtype": str(df[c].dtype), "sql_type": sql_type(df[c])} for c in df.columns],
        "row_count": total_rows,
        "shown_rows": shown_rows,
        "preview_mode": session.preview_mode,
        "rows": json.loads(capped.to_json(orient="records", date_format="iso")),
        "steps": [
            {"type": s["type"], "label": STEP_LABELS[s["type"]], "code": s["code"],
             "enabled": _enabled(s), "notes": s.get("notes") or []}
            for s in session.steps
        ],
        "frames": _frames_info(session),
    }
