"""
df-studio/clean_steps.py

The no-code cleaning steps (roadmap Phase DF, DF1): fill empty values, change type, clean text, replace values, extract /
split / join text, date parts, remove duplicates, drop sparse / constant columns, outliers, bins, bulk rename and the
multi-condition filter. Registered in steps.STEP_HANDLERS next to the older steps.

How a step works here (differs on purpose from the older handlers in steps.py): the handler VALIDATES the params
against the current DataFrame, BUILDS the real pandas code (every user value goes through repr(), never into the code
as raw text), and then RUNS that very code on a copy of the DataFrame. So "the pandas line the pipeline shows" and
"what the step does" can never drift apart — the line IS what ran, and the exported script replays it verbatim.

Every step accepts `columns` as a list, so one step cleans many columns at once. Handlers raise plain ValueError
(see CLAUDE.md: not engine.StepError). Things worth telling the user (cells filled, values that couldn't be
converted, rows removed…) go through note(); engine._run_step collects them and the page shows them.
"""

from __future__ import annotations

import contextvars
import math
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

# Messages a handler wants the page to show ("12 values in 'age' couldn't be converted and became empty").
# engine._run_step sets a list around one handler call; during a plain replay it is None and note() does nothing.
NOTES: contextvars.ContextVar["list[str] | None"] = contextvars.ContextVar("df_studio_notes", default=None)


def note(msg: str) -> None:
    bucket = NOTES.get()
    if bucket is not None:
        bucket.append(msg)


# ---------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------

def lst(items: list[str]) -> str:
    """['a', 'b'] as source text."""
    return "[" + ", ".join(repr(i) for i in items) + "]"


def columns_param(df: pd.DataFrame, params: dict[str, Any], key: str = "columns", *, optional: bool = False,
                  what: str = "Pick at least one column.") -> list[str]:
    raw = params.get(key)
    if isinstance(raw, str):
        raw = [raw]
    cols: list[str] = []
    for c in raw or []:
        if not isinstance(c, str):
            raise ValueError("Column names must be text.")
        if c != "" and c not in cols:
            cols.append(c)
    if not cols:
        if optional:
            return []
        raise ValueError(what)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        shown = ", ".join(missing[:5]) + (f" … (+{len(missing) - 5} more)" if len(missing) > 5 else "")
        raise ValueError(f"Column(s) not found: {shown}")
    return cols


def one_column(df: pd.DataFrame, params: dict[str, Any], key: str = "column") -> str:
    c = params.get(key)
    if isinstance(c, list) and len(c) == 1:
        c = c[0]
    if not isinstance(c, str) or not c:
        raise ValueError("Pick a column.")
    if c not in df.columns:
        raise ValueError(f"Column not found: {c}")
    return c


def new_name(df: pd.DataFrame, params: dict[str, Any], key: str, default: str = "", *, taken: set[str] | None = None) -> str:
    name = str(params.get(key) or default).strip()
    if not name:
        raise ValueError("Give the new column a name.")
    if len(name) > 200:
        raise ValueError("That column name is too long.")
    if name in df.columns or (taken and name in taken):
        raise ValueError(f"A column called '{name}' already exists — pick another name.")
    return name


def is_number(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype)


def is_date(s: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(s.dtype)


def need_numbers(df: pd.DataFrame, cols: list[str], what: str) -> None:
    bad = [c for c in cols if not is_number(df[c])]
    if bad:
        raise ValueError(f"{what} needs number columns — not numbers: {', '.join(bad[:5])}. Use 'Change type' first.")


def run(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Execute generated code on a COPY of df (the replay model never mutates the original)."""
    ns: dict[str, Any] = {"df": df.copy(), "pd": pd, "np": np}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with np.errstate(all="ignore"):
                exec(code, ns)  # noqa: S102 — the code was built from validated params + repr() literals only
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Couldn't apply this step: {exc}") from exc
    out = ns["df"]
    if not isinstance(out, pd.DataFrame):
        raise ValueError("The step didn't produce a table.")
    return out


def _short(items: list[str], n: int = 5) -> str:
    return ", ".join(f"'{i}'" for i in items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def _parse_number(text: Any, col: str) -> int | float:
    s = str(text).strip()
    try:
        v: int | float = int(s)
    except ValueError:
        try:
            v = float(s)
        except ValueError:
            raise ValueError(f"'{s}' isn't a number (column '{col}' holds numbers).") from None
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError(f"'{s}' isn't a usable number.")
    return v


def typed_literal(df: pd.DataFrame, col: str, text: Any) -> str:
    """The source text for `text` as a value comparable with column `col` (a number for number columns, a Timestamp
    for date columns, True/False for boolean columns, else a string)."""
    s = df[col]
    if is_number(s):
        return repr(_parse_number(text, col))
    if is_date(s):
        try:
            ts = pd.Timestamp(str(text).strip())
        except Exception:  # noqa: BLE001
            raise ValueError(f"'{text}' isn't a date (column '{col}' holds dates; try 2026-01-31).") from None
        if pd.isna(ts):
            raise ValueError(f"'{text}' isn't a date (column '{col}' holds dates; try 2026-01-31).")
        return f"pd.Timestamp({str(ts)!r})"
    if pd.api.types.is_bool_dtype(s.dtype):
        t = str(text).strip().lower()
        if t in ("true", "yes", "1", "t", "y"):
            return "True"
        if t in ("false", "no", "0", "f", "n"):
            return "False"
        raise ValueError(f"'{text}' isn't true/false (column '{col}' holds True/False).")
    return repr(str(text))


# ---------------------------------------------------------------------------------------------------------------
# fill empty values
# ---------------------------------------------------------------------------------------------------------------

FILL_METHODS = ("value", "mean", "median", "mode", "ffill", "bfill", "zero", "empty_string")


def fill_nulls(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    method = p.get("method") or "value"
    if method not in FILL_METHODS:
        raise ValueError("Pick how to fill the empty values.")
    L = lst(cols)
    if method == "value":
        raw = p.get("value")
        if raw is None or str(raw) == "":
            raise ValueError("Type the value to fill with (or pick 'empty text').")
        pairs = ", ".join(f"{c!r}: {typed_literal(df, c, raw)}" for c in cols)
        code = f"df = df.fillna({{{pairs}}})"
    elif method in ("mean", "median"):
        need_numbers(df, cols, f"Filling with the {method}")
        code = f"df[{L}] = df[{L}].fillna(df[{L}].{method}())"
    elif method == "mode":
        empty = [c for c in cols if df[c].notna().sum() == 0]
        if empty:
            raise ValueError(f"Column(s) {_short(empty)} are completely empty — there is no most-common value to use.")
        code = f"df[{L}] = df[{L}].fillna(df[{L}].mode().iloc[0])"
    elif method in ("ffill", "bfill"):
        code = f"df[{L}] = df[{L}].{method}()"
    elif method == "zero":
        need_numbers(df, cols, "Filling with 0")
        code = f"df[{L}] = df[{L}].fillna(0)"
    else:  # empty_string
        numeric = [c for c in cols if is_number(df[c]) or is_date(df[c])]
        if numeric:
            raise ValueError(f"'Empty text' is for text columns — not text: {_short(numeric)}.")
        code = f"df[{L}] = df[{L}].fillna('')"
    out = run(df, code)
    filled = int(df[cols].isna().sum().sum() - out[cols].isna().sum().sum())
    note(f"Filled {filled:,} empty value(s)." if filled else "No empty values in those columns — nothing changed.")
    return out, code


# ---------------------------------------------------------------------------------------------------------------
# change type
# ---------------------------------------------------------------------------------------------------------------

CAST_TYPES = ("text", "integer", "float", "boolean", "date", "datetime", "category")
_SYMBOLS = r"[,$€£%\s]"
_BOOL_MAP = ("{'true': True, 't': True, 'yes': True, 'y': True, '1': True, '1.0': True, "
             "'false': False, 'f': False, 'no': False, 'n': False, '0': False, '0.0': False}")


def _num_expr(df: pd.DataFrame, c: str, ignore_symbols: bool) -> str:
    s = df[c]
    if pd.api.types.is_bool_dtype(s.dtype):
        return "df[c].astype('Int64')"
    if is_number(s):
        return "pd.to_numeric(df[c], errors='coerce')"
    if ignore_symbols:
        return f"pd.to_numeric(df[c].astype('string').str.replace(r'{_SYMBOLS}', '', regex=True), errors='coerce')"
    return "pd.to_numeric(df[c], errors='coerce')"


def cast_type(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    to = p.get("to")
    if to not in CAST_TYPES:
        raise ValueError("Pick the type to change to.")
    on_error = p.get("on_error") or "coerce"
    if on_error not in ("coerce", "raise"):
        raise ValueError("on_error must be 'coerce' or 'raise'.")
    fmt = str(p.get("format") or "").strip() or None
    L = lst(cols)
    if to == "text":
        code = f"df[{L}] = df[{L}].astype('string')"
    elif to == "category":
        code = f"df[{L}] = df[{L}].astype('category')"
    else:
        ignore = bool(p.get("ignore_symbols"))
        lines = [f"for c in {L}:"]
        if to in ("float", "integer"):
            exprs = {c: _num_expr(df, c, ignore) for c in cols}
            if len(set(exprs.values())) == 1:
                body = next(iter(exprs.values()))
                lines += ([f"    df[c] = {body}.astype('float64')"] if to == "float" else
                          [f"    n = {body}", "    df[c] = n.where(n == n.round()).astype('Int64')"])
            else:  # a mix of bool / number / text columns → one loop each keeps the lines honest
                lines = []
                for c, body in exprs.items():
                    lines += ([f"df[{c!r}] = {body.replace('df[c]', f'df[{c!r}]')}.astype('float64')"] if to == "float" else
                              [f"n = {body.replace('df[c]', f'df[{c!r}]')}",
                               f"df[{c!r}] = n.where(n == n.round()).astype('Int64')"])
        elif to in ("date", "datetime"):
            args = (f", format={fmt!r}" if fmt else "") + (", dayfirst=True" if p.get("dayfirst") and not fmt else "")
            tail = ".dt.normalize()" if to == "date" else ""
            lines.append(f"    df[c] = pd.to_datetime(df[c]{args}, errors='coerce'){tail}")
        else:  # boolean
            lines.append(f"    df[c] = df[c].astype('string').str.strip().str.lower().map({_BOOL_MAP}).astype('boolean')")
        code = "\n".join(lines)
    out = run(df, code)
    if to not in ("text", "category"):
        bad: list[str] = []
        for c in cols:
            lost = df[c].notna() & out[c].isna()
            n = int(lost.sum())
            if not n:
                continue
            if on_error == "raise":
                first = str(df.loc[lost, c].iloc[0])[:40]
                raise ValueError(f"{n:,} value(s) in '{c}' can't be changed to {to} (first one: '{first}'). "
                                 "Choose 'make them empty' to continue anyway.")
            bad.append(f"{n:,} in '{c}'")
        if bad:
            note("Couldn't convert and made empty: " + "; ".join(bad[:6]) + (f"; … (+{len(bad) - 6} more columns)" if len(bad) > 6 else "") + ".")
    return out, code


# ---------------------------------------------------------------------------------------------------------------
# clean text / replace values / extract / split / join
# ---------------------------------------------------------------------------------------------------------------

TEXT_OPS = {
    "strip": ".str.strip()",
    "lower": ".str.lower()",
    "upper": ".str.upper()",
    "title": ".str.title()",
    "collapse_spaces": r".str.replace(r'\s+', ' ', regex=True)",
    "remove_spaces": r".str.replace(r'\s+', '', regex=True)",
    "remove_digits": r".str.replace(r'\d+', '', regex=True)",
    "remove_punctuation": r".str.replace(r'[^\w\s]', '', regex=True)",
    "ascii_only": ".str.encode('ascii', 'ignore').str.decode('ascii')",
}


def _need_text(df: pd.DataFrame, cols: list[str], what: str) -> None:
    bad = [c for c in cols if is_number(df[c]) or is_date(df[c]) or pd.api.types.is_bool_dtype(df[c].dtype)]
    if bad:
        raise ValueError(f"{what} is for text columns — not text: {_short(bad)}. Use 'Change type → text' first.")


def clean_text(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    _need_text(df, cols, "Clean text")
    ops = [o for o in (p.get("ops") or []) if o]
    unknown = [o for o in ops if o not in TEXT_OPS]
    if unknown or not ops:
        raise ValueError("Pick what to clean: " + ", ".join(TEXT_OPS) if not ops else f"Unknown text clean-up: {unknown[0]}")
    chain = "".join(TEXT_OPS[o] for o in ops)
    code = f"for c in {lst(cols)}:\n    df[c] = df[c].astype('string'){chain}"
    out = run(df, code)
    changed = 0
    for c in cols:
        a, b = df[c].astype("string"), out[c]
        same = (a == b).fillna(False) | (a.isna() & b.isna())
        changed += int((~same).sum())
    note(f"Changed {changed:,} cell(s).")
    return out, code


def _num_lit_or_text(df: pd.DataFrame, cols: list[str], text: Any) -> str:
    """For a replace: number columns compare numbers, everything else text."""
    if all(is_number(df[c]) for c in cols):
        return repr(_parse_number(text, cols[0]))
    return repr(str(text))


def replace_values(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    mapping = p.get("mapping") or []
    if not mapping:
        raise ValueError("Add at least one replacement (old value → new value).")
    use_regex = bool(p.get("regex"))
    seen: set[str] = set()
    pairs = []
    for m in mapping:
        old = m.get("from")
        if old is None or str(old) == "":
            raise ValueError("Every replacement needs an old value.")
        if str(old) in seen:
            raise ValueError(f"'{old}' is listed twice.")
        seen.add(str(old))
        if use_regex:
            try:
                re.compile(str(old))
            except re.error as exc:
                raise ValueError(f"'{old}' isn't a valid pattern: {exc}") from None
            k = repr(str(old))
        else:
            k = _num_lit_or_text(df, cols, old)
        to = m.get("to")
        v = "np.nan" if to is None else (repr(str(to)) if use_regex else _num_lit_or_text(df, cols, to))
        pairs.append(f"{k}: {v}")
    L = lst(cols)
    code = f"df[{L}] = df[{L}].replace({{{', '.join(pairs)}}}{', regex=True' if use_regex else ''})"
    out = run(df, code)
    a, b = df[cols], out[cols]
    changed = int(((a != b) & ~(a.isna() & b.isna())).sum().sum())
    note(f"Replaced {changed:,} value(s)." if changed else "Nothing matched — no values changed.")
    return out, code


def extract_text(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    c = one_column(df, p)
    _need_text(df, [c], "Extract text")
    pattern = str(p.get("pattern") or "")
    if not pattern:
        raise ValueError("Type the pattern to look for.")
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"That isn't a valid pattern: {exc}") from None
    if rx.groups != 1:
        raise ValueError("Put exactly one part of the pattern in round brackets ( ) — that part becomes the new column.")
    name = new_name(df, p, "new_column", f"{c}_extract")
    code = f"df[{name!r}] = df[{c!r}].astype('string').str.extract({pattern!r}, expand=False)"
    out = run(df, code)
    note(f"Found a match in {int(out[name].notna().sum()):,} of {len(out):,} rows.")
    return out, code


def split_column(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    c = one_column(df, p)
    _need_text(df, [c], "Split")
    sep = str(p.get("delimiter") if p.get("delimiter") is not None else "")
    if sep == "":
        raise ValueError("Type the character(s) to split on.")
    raw = p.get("new_columns") or []
    names = [n.strip() for n in (raw.split(",") if isinstance(raw, str) else raw) if str(n).strip()]
    if len(names) < 2:
        raise ValueError("Give at least two names for the new columns (comma-separated).")
    if len(set(names)) != len(names):
        raise ValueError("The new column names must be different.")
    for n in names:
        if n in df.columns:
            raise ValueError(f"A column called '{n}' already exists — pick another name.")
    k = len(names)
    lines = [f"_p = df[{c!r}].astype('string').str.split({sep!r}, n={k - 1}, expand=True, regex=False).reindex(columns=range({k}))",
             f"df[{lst(names)}] = _p.to_numpy()"]
    if p.get("drop_original"):
        lines.append(f"df = df.drop(columns=[{c!r}])")
    code = "\n".join(lines)
    return run(df, code), code


def merge_columns(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    if len(cols) < 2:
        raise ValueError("Pick at least two columns to join.")
    sep = str(p.get("separator") if p.get("separator") is not None else "")
    name = new_name(df, p, "new_column")
    parts = [f"df[{c!r}].astype('string').fillna('')" for c in cols]
    joiner = f" + {sep!r} + " if sep else " + "
    lines = [f"df[{name!r}] = " + joiner.join(parts)]
    if p.get("drop_original"):
        lines.append(f"df = df.drop(columns={lst(cols)})")
    code = "\n".join(lines)
    return run(df, code), code


# ---------------------------------------------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------------------------------------------

DATE_PARTS = {
    "year": ".dt.year.astype('Int64')",
    "month": ".dt.month.astype('Int64')",
    "day": ".dt.day.astype('Int64')",
    "weekday": ".dt.dayofweek.astype('Int64')",           # 0 = Monday
    "weekday_name": ".dt.day_name()",
    "month_name": ".dt.month_name()",
    "quarter": ".dt.quarter.astype('Int64')",
    "week": ".dt.isocalendar().week.astype('Int64')",
    "dayofyear": ".dt.dayofyear.astype('Int64')",
    "hour": ".dt.hour.astype('Int64')",
    "minute": ".dt.minute.astype('Int64')",
}


def date_parts(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    c = one_column(df, p)
    if not is_date(df[c]):
        raise ValueError(f"'{c}' isn't a date column — use 'Change type → date' on it first.")
    parts = [x for x in (p.get("parts") or []) if x]
    if not parts:
        raise ValueError("Pick at least one part (year, month, …).")
    bad = [x for x in parts if x not in DATE_PARTS and x != "is_weekend"]
    if bad:
        raise ValueError(f"Unknown date part: {bad[0]}")
    prefix = str(p.get("prefix") or c).strip()
    names = [f"{prefix}_{x}" for x in parts]
    if len(set(names)) != len(names):
        raise ValueError("Each part can be picked once.")
    for n in names:
        if n in df.columns:
            raise ValueError(f"A column called '{n}' already exists — change the prefix.")
    lines = []
    for part, n in zip(parts, names):
        if part == "is_weekend":
            lines.append(f"df[{n!r}] = (df[{c!r}].dt.dayofweek >= 5).astype('boolean').mask(df[{c!r}].isna())")
        else:
            lines.append(f"df[{n!r}] = df[{c!r}]{DATE_PARTS[part]}")
    code = "\n".join(lines)
    return run(df, code), code


# ---------------------------------------------------------------------------------------------------------------
# rows and columns: duplicates, sparse, constant
# ---------------------------------------------------------------------------------------------------------------

def dedupe(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p, "subset", optional=True)
    keep = p.get("keep") or "first"
    if keep not in ("first", "last", "none"):
        raise ValueError("Keep must be first, last or none.")
    args = []
    if cols:
        args.append(f"subset={lst(cols)}")
    args.append(f"keep={'False' if keep == 'none' else repr(keep)}")
    code = f"df = df.drop_duplicates({', '.join(args)})"
    try:
        out = run(df, code)
    except ValueError as exc:
        if "unhashable" in str(exc):
            raise ValueError("Some columns hold lists or objects, which can't be compared — pick other columns.") from None
        raise
    removed = len(df) - len(out)
    note(f"Removed {removed:,} duplicate row(s)." if removed else "No duplicate rows found.")
    return out, code


def drop_sparse(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    try:
        limit = float(p.get("max_null_pct") if p.get("max_null_pct") is not None else 50)
    except (TypeError, ValueError):
        raise ValueError("Type a percentage between 0 and 100.") from None
    if not 0 <= limit <= 100:
        raise ValueError("Type a percentage between 0 and 100.")
    if len(df) == 0:
        raise ValueError("The table has no rows.")
    code = f"df = df.loc[:, df.isna().mean() * 100 <= {limit!r}]"
    out = run(df, code)
    dropped = [c for c in df.columns if c not in out.columns]
    note(f"Dropped {len(dropped):,} column(s) with more than {limit:g}% empty: {_short(dropped)}." if dropped
         else f"No column is more than {limit:g}% empty.")
    return out, code


def drop_constant(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    if len(df) == 0:
        raise ValueError("The table has no rows.")
    code = "df = df.loc[:, df.nunique(dropna=False) > 1]"
    try:
        out = run(df, code)
    except ValueError as exc:
        if "unhashable" in str(exc):
            raise ValueError("Some columns hold lists or objects, which can't be compared.") from None
        raise
    dropped = [c for c in df.columns if c not in out.columns]
    note(f"Dropped {len(dropped):,} column(s) that never change: {_short(dropped)}." if dropped
         else "No column has just one value.")
    return out, code


# ---------------------------------------------------------------------------------------------------------------
# outliers and bins
# ---------------------------------------------------------------------------------------------------------------

def clip_outliers(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    cols = columns_param(df, p)
    need_numbers(df, cols, "Outliers")
    method = p.get("method") or "iqr"
    action = p.get("action") or "clip"
    if method not in ("iqr", "zscore", "percentile") or action not in ("clip", "null", "flag"):
        raise ValueError("Pick a method (iqr, zscore, percentile) and an action (clip, null, flag).")
    try:
        factor = float(p.get("factor") if p.get("factor") is not None else (3.0 if method == "zscore" else 1.5))
        low = float(p.get("low") if p.get("low") is not None else 1)
        high = float(p.get("high") if p.get("high") is not None else 99)
    except (TypeError, ValueError):
        raise ValueError("The factor and percentiles must be numbers.") from None
    if not 0 < factor <= 100:
        raise ValueError("The factor must be between 0 and 100.")
    if method == "percentile" and not 0 <= low < high <= 100:
        raise ValueError("Percentiles need 0 ≤ low < high ≤ 100.")
    flags = [f"{c}_outlier" for c in cols]
    if action == "flag":
        for n in flags:
            if n in df.columns:
                raise ValueError(f"A column called '{n}' already exists.")
    if method == "iqr":
        bounds = [f"    q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)",
                  f"    lo, hi = q1 - {factor!r} * (q3 - q1), q3 + {factor!r} * (q3 - q1)"]
    elif method == "zscore":
        bounds = ["    m, s = df[c].mean(), df[c].std()", f"    lo, hi = m - {factor!r} * s, m + {factor!r} * s"]
    else:
        bounds = [f"    lo, hi = df[c].quantile({low / 100!r}), df[c].quantile({high / 100!r})"]
    do = {"clip": ["    df[c] = df[c].astype('float64').clip(lo, hi)"],
          "null": ["    df[c] = df[c].mask(((df[c] < lo) | (df[c] > hi)).fillna(False))"],
          "flag": ["    df[c + '_outlier'] = ((df[c] < lo) | (df[c] > hi)).fillna(False)"]}[action]
    code = "\n".join([f"for c in {lst(cols)}:"] + bounds + do)
    out = run(df, code)
    if action == "flag":
        n = int(sum(out[f].sum() for f in flags))
    else:
        n = int(sum(((df[c].astype("float64") != out[c].astype("float64")) & df[c].notna()).sum() for c in cols))
    note(f"{n:,} value(s) were outside the normal range.")
    return out, code


def _label_list(raw: Any) -> list[str] | None:
    if raw is None or raw == "" or raw == []:
        return None
    labels = [x.strip() for x in raw.split(",")] if isinstance(raw, str) else [str(x) for x in raw]
    if any(x == "" for x in labels):
        raise ValueError("Labels can't be empty.")
    return labels


def bin_column(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    c = one_column(df, p)
    need_numbers(df, [c], "Bins")
    method = p.get("method") or "equal_width"
    name = new_name(df, p, "new_column", f"{c}_bin")
    labels = _label_list(p.get("labels"))
    if method in ("equal_width", "quantile"):
        try:
            n = int(p.get("bins"))
        except (TypeError, ValueError):
            raise ValueError("Type how many groups you want (a whole number).") from None
        if not 2 <= n <= 200:
            raise ValueError("Use between 2 and 200 groups.")
        count = n
        lab = f", labels={labels!r}" if labels else ""
        expr = (f"pd.cut(df[{c!r}], bins={n}{lab})" if method == "equal_width"
                else f"pd.qcut(df[{c!r}], q={n}{lab}, duplicates='drop')")
    elif method == "custom":
        raw = p.get("edges")
        try:
            edges = [float(x) for x in (raw.split(",") if isinstance(raw, str) else raw or []) if str(x).strip() != ""]
        except ValueError:
            raise ValueError("The edges must be numbers separated by commas, e.g. 0, 18, 65.") from None
        if len(edges) < 2 or any(not math.isfinite(e) for e in edges) or edges != sorted(set(edges)):
            raise ValueError("Give at least two different edges, smallest first, e.g. 0, 18, 65.")
        edges = [int(e) if e == int(e) else e for e in edges]
        count = len(edges) - 1
        lab = f", labels={labels!r}" if labels else ""
        expr = f"pd.cut(df[{c!r}], bins={edges!r}{lab}, include_lowest=True)"
    else:
        raise ValueError("Pick a method: equal width, equal count or my own edges.")
    if labels and len(labels) != count:
        raise ValueError(f"You gave {len(labels)} label(s) but there are {count} group(s).")
    code = f"df[{name!r}] = {expr}.astype('string')"
    return run(df, code), code


# ---------------------------------------------------------------------------------------------------------------
# bulk rename
# ---------------------------------------------------------------------------------------------------------------

def _snake(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"[\W_]+", "_", s).strip("_").lower() or "column"


RENAME_STYLES = {"snake_case": _snake, "lower": str.lower, "upper": str.upper, "title": str.title,
                 "strip": lambda s: re.sub(r"\s+", " ", s).strip()}


def bulk_rename(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    style = p.get("style") or "snake_case"
    if style not in RENAME_STYLES:
        raise ValueError("Pick a style: snake_case, lower, upper, title or strip.")
    cols = columns_param(df, p, optional=True) or [c for c in df.columns if isinstance(c, str)]
    mapping = {c: RENAME_STYLES[style](c) for c in cols}
    mapping = {a: b for a, b in mapping.items() if a != b}
    if not mapping:
        raise ValueError("No column name would change with that style.")
    final = [mapping.get(c, c) for c in df.columns]
    dup = [n for n in dict.fromkeys(final) if final.count(n) > 1]
    if dup:
        raise ValueError(f"That would give two columns the same name ('{dup[0]}'). Pick other columns or another style.")
    pairs = ", ".join(f"{a!r}: {b!r}" for a, b in mapping.items())
    code = f"df = df.rename(columns={{{pairs}}})"
    note(f"Renamed {len(mapping):,} column(s).")
    return run(df, code), code


# ---------------------------------------------------------------------------------------------------------------
# filter builder
# ---------------------------------------------------------------------------------------------------------------

COMPARE_OPS = ("==", "!=", ">", ">=", "<", "<=")
FILTER_OPS = COMPARE_OPS + ("contains", "not_contains", "startswith", "endswith", "isnull", "notnull", "in", "not_in", "between")


def _values(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip() != ""]
    return [x.strip() for x in str(raw or "").split(",") if x.strip() != ""]


def _condition(df: pd.DataFrame, cond: dict[str, Any]) -> str:
    c = cond.get("column")
    if not isinstance(c, str) or c not in df.columns:
        raise ValueError(f"Column not found: {c}")
    op = cond.get("op")
    if op not in FILTER_OPS:
        raise ValueError(f"Unknown condition '{op}'.")
    col = f"df[{c!r}]"
    if op == "isnull":
        return f"({col}.isna())"
    if op == "notnull":
        return f"({col}.notna())"
    raw = cond.get("value")
    if op in ("in", "not_in"):
        vals = _values(raw)
        if not vals:
            raise ValueError(f"Type the values to look for in '{c}', separated by commas.")
        body = f"{col}.isin([{', '.join(typed_literal(df, c, v) for v in vals)}])"
        return f"(~{body})" if op == "not_in" else f"({body})"
    if op == "between":
        vals = _values(raw)
        if len(vals) != 2:
            raise ValueError(f"'between' needs two values separated by a comma, e.g. 10, 20 (column '{c}').")
        return f"({col}.between({typed_literal(df, c, vals[0])}, {typed_literal(df, c, vals[1])}))"
    if raw is None or str(raw) == "":
        raise ValueError(f"Type a value for '{c}'.")
    if op in COMPARE_OPS:
        return f"({col} {op} {typed_literal(df, c, raw)})"
    sensitive = bool(cond.get("case_sensitive"))
    text = str(raw)
    s = f"{col}.astype('string')"
    if op in ("contains", "not_contains"):
        body = f"{s}.str.contains({text!r}, case={sensitive}, regex=False, na=False)"
        return f"(~{body})" if op == "not_contains" else f"({body})"
    if sensitive:
        return f"({s}.str.{op}({text!r}, na=False))"
    return f"({s}.str.lower().str.{op}({text.lower()!r}, na=False))"


def filter_builder(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    conds = p.get("conditions") or []
    if not conds:
        raise ValueError("Add at least one condition.")
    combine = p.get("combine") or "and"
    if combine not in ("and", "or"):
        raise ValueError("Combine must be 'and' or 'or'.")
    joiner = " & " if combine == "and" else " | "
    code = f"df = df[{joiner.join(_condition(df, c) for c in conds)}]"
    out = run(df, code)
    note(f"Kept {len(out):,} of {len(df):,} rows ({len(df) - len(out):,} removed).")
    return out, code


HANDLERS = {
    "fill_nulls": fill_nulls,
    "cast_type": cast_type,
    "clean_text": clean_text,
    "replace_values": replace_values,
    "extract_text": extract_text,
    "split_column": split_column,
    "merge_columns": merge_columns,
    "date_parts": date_parts,
    "dedupe": dedupe,
    "drop_sparse": drop_sparse,
    "drop_constant": drop_constant,
    "clip_outliers": clip_outliers,
    "bin_column": bin_column,
    "bulk_rename": bulk_rename,
    "filter_builder": filter_builder,
}

LABELS = {
    "fill_nulls": "Fill empty values",
    "cast_type": "Change type",
    "clean_text": "Clean text",
    "replace_values": "Replace values",
    "extract_text": "Extract text",
    "split_column": "Split column",
    "merge_columns": "Join columns",
    "date_parts": "Date parts",
    "dedupe": "Remove duplicates",
    "drop_sparse": "Drop mostly-empty columns",
    "drop_constant": "Drop constant columns",
    "clip_outliers": "Outliers",
    "bin_column": "Group into bins",
    "bulk_rename": "Rename columns in bulk",
    "filter_builder": "Filter rows",
}
