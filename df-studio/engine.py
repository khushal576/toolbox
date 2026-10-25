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
            "sample_seed": session.sample_seed, "frame_format": session.frame_format}


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
                   sid=session_id, frame_format=meta.get("frame_format", ""))


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


def recompute(session: Session) -> pd.DataFrame:
    df = session.original_df
    for step in session.steps:
        handler = STEP_HANDLERS[step["type"]]
        df, _ = handler(df, step["params"])
    return df


def _run_step(session: Session, step_type: str, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    if step_type not in STEP_HANDLERS:
        raise StepError(f"Unknown step type '{step_type}'.")
    current = recompute(session)
    handler = STEP_HANDLERS[step_type]
    return handler(current, params)


def preview_step(session: Session, step_type: str, params: dict[str, Any]) -> pd.DataFrame:
    """Run a step against the current DataFrame without committing it to the
    pipeline — the "Check" half of the query box's edit/check workflow."""
    new_df, _ = _run_step(session, step_type, params)
    return new_df


def apply_step(session: Session, step_type: str, params: dict[str, Any]) -> pd.DataFrame:
    _, code = _run_step(session, step_type, params)  # validates against current df before committing
    session.steps.append({"type": step_type, "params": params, "code": code})
    save_session(session)
    return recompute(session)


def remove_step(session: Session, index: int) -> pd.DataFrame:
    if index < 0 or index >= len(session.steps):
        raise StepError("Step not found.")
    session.steps.pop(index)
    save_session(session)
    return recompute(session)


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
    for step in session.steps:
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
        "columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns],
        "row_count": total_rows,
        "shown_rows": shown_rows,
        "preview_mode": session.preview_mode,
        "rows": json.loads(capped.to_json(orient="records", date_format="iso")),
        "steps": [
            {"type": s["type"], "label": STEP_LABELS[s["type"]], "code": s["code"]}
            for s in session.steps
        ],
    }
