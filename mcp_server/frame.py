"""
mcp_server/frame.py — DataFrame Studio's cleaning steps and formulas, callable by an AI (roadmap K6, ADR-MCP D7/D14/D15).

NO second implementation: the steps are df-studio/clean_steps.HANDLERS and the formulas are df-studio/formula.expression — the very
code the page runs. Each handler validates the parameters against the DataFrame, BUILDS the real pandas line (every value goes through
repr()), and runs that line on a copy; the line it returns is shown to the AI exactly like the page shows it to the owner.

This module only (1) loads a Vault Data table the way the page does (export to Parquet → pandas, so decimals stay exact),
(2) applies a list of steps and records what happened at each one, (3) describes the result, and (4) — for a CONFIRMED, GRANTED save only —
writes it back with a read-back check. Who may call (4) is decided by tools.table_transform; a test asserts the write functions are
reachable from nowhere else.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from core import lake as lake_store

from .access import PLUGIN
from .safety import ToolError, jsonable

REPO = Path(__file__).resolve().parent.parent
MAX_STEPS = 30


def max_rows() -> int:
    try:
        return int(os.environ.get("MCP_TRANSFORM_MAX_ROWS", "200000"))
    except ValueError:
        return 200000


def dfs():
    """(clean_steps, formula) — the image names the folder df_studio; a source checkout has df-studio/."""
    try:
        from df_studio import clean_steps, formula  # type: ignore
    except ImportError:
        folder = str(REPO / "df-studio")
        if folder not in sys.path:
            sys.path.insert(0, folder)
        import clean_steps  # type: ignore
        import formula  # type: ignore
    return clean_steps, formula


def catalog() -> dict[str, Any]:
    """What an AI needs to call the steps correctly, generated from the live modules (so it cannot drift)."""
    cs, fm = dfs()
    cols = "columns: [column names]"
    p = {
        "fill_nulls": [cols, f"method: {' | '.join(cs.FILL_METHODS)}", "value: text/number (only when method = value)"],
        "cast_type": [cols, f"to: {' | '.join(cs.CAST_TYPES)}", "format: strptime format for dates, e.g. %d/%m/%Y (optional)", "dayfirst: bool (dates)",
                      "ignore_symbols: bool (strip , $ % and spaces before making numbers)", "on_error: coerce (bad values become empty, counted in notes) | raise (stop)"],
        "clean_text": [cols, f"ops: list of {' | '.join(cs.TEXT_OPS)}"],
        "replace_values": [cols, "mapping: [{\"from\": old, \"to\": new}, ...]", "regex: bool"],
        "extract_text": ["column", "pattern: regex with exactly ONE (group)", "new_column"],
        "split_column": ["column", "delimiter", "new_columns: [names] (at least 2)", "drop_original: bool"],
        "merge_columns": [cols, "new_column", "separator", "drop_original: bool"],
        "date_parts": ["column (a date column; cast_type to date first)", f"parts: list of {' | '.join(cs.DATE_PARTS)} | is_weekend", "prefix (default: the column name)"],
        "dedupe": ["subset: [columns] (optional; default whole row)", "keep: first | last | none"],
        "drop_sparse": ["max_null_pct: 0-100 (drop columns emptier than this; default 50)"],
        "drop_constant": [],
        "clip_outliers": [cols + " (numbers)", "method: iqr | zscore | percentile", "factor (iqr 1.5 / zscore 3)", "low: percentile 0-100 (percentile method)", "high: percentile 0-100 (percentile method)", "action: clip | null | flag"],
        "bin_column": ["column (numbers)", "method: equal_width | quantile | custom", "bins: 2-200 (equal_width / quantile)", "edges: [numbers] or \"0,18,65\" (custom)", "labels: [text] (optional)", "new_column"],
        "bulk_rename": [cols + " (optional = all)", f"style: {' | '.join(cs.RENAME_STYLES)}"],
        "filter_builder": ["combine: and | or", f"conditions: [{{column, op, value, case_sensitive?}}] with op in {' | '.join(cs.FILTER_OPS)} (keeps the rows that match)"],
        "formula": ["text: one formula per line, like  total = price * qty   (use `backticks` around names with spaces)"],
    }
    steps = [{"op": k, "label": cs.LABELS.get(k, "Formula" if k == "formula" else k), "params": v} for k, v in p.items()]
    return {"steps": steps, "formula_functions": fm.function_help(),
            "example": [{"op": "cast_type", "columns": ["amount"], "to": "float", "ignore_symbols": True, "on_error": "coerce"},
                        {"op": "fill_nulls", "columns": ["amount"], "method": "zero"},
                        {"op": "formula", "text": "gross = amount * 1.18"},
                        {"op": "filter_builder", "combine": "and", "conditions": [{"column": "gross", "op": ">", "value": "100"}]}]}


# ---- loading ---------------------------------------------------------------------------------------------------------------------

def split_table(ref: str) -> tuple[str, str]:
    ref = (ref or "").strip().lower()
    if not ref:
        raise ToolError("Give a table as workspace.table (for example system.orders).", hint="vault_list shows the tables.")
    ws, _, name = ref.rpartition(".")
    return (ws or lake_store.SYSTEM_WORKSPACE), name


def load(ref: str) -> tuple[Any, dict]:
    """(DataFrame, table meta). Reads exactly as DataFrame Studio does: export to Parquet, then pandas — decimals stay exact."""
    import pandas as pd

    ws, name = split_table(ref)
    lake = lake_store.scoped(PLUGIN)
    try:
        t = lake.get_table(ws, name)
    except lake_store.NotFound:
        raise ToolError(f"There is no table '{ws}.{name}'.", hint="vault_list shows the tables.") from None
    except lake_store.LakeError as exc:
        raise ToolError(str(exc)) from None
    if (t.get("row_count") or 0) > max_rows():
        raise ToolError(f"{t['full_name']} has {t['row_count']:,} rows — more than the {max_rows():,} that can be transformed here.",
                        hint="Make a smaller table first (a filtered copy), or ask the owner to raise MCP_TRANSFORM_MAX_ROWS.")
    tmp = Path(tempfile.mkdtemp(prefix="mcp_frame_"))
    try:
        lake.export_table(ws, name, tmp / "t.parquet", "parquet", None)
        df = pd.read_parquet(tmp / "t.parquet")
    except lake_store.LakeError as exc:
        raise ToolError(str(exc)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return df, t


# ---- applying steps ---------------------------------------------------------------------------------------------------------------

def _holds_decimals(series: Any) -> bool:
    import decimal

    for v in series.head(50):
        if isinstance(v, decimal.Decimal):
            return True
    return False


def apply_steps(df: Any, steps: Any) -> dict[str, Any]:
    """Run the steps in order. Returns {df, code: [pandas lines that ran], notes, trail}. Any step error stops everything (nothing is partial)."""
    cs, fm = dfs()
    if not isinstance(steps, list) or not steps:
        raise ToolError("Give 'steps': a list of steps, for example [{\"op\": \"fill_nulls\", \"columns\": [\"a\"], \"method\": \"zero\"}].",
                        hint="transform_steps lists every step with its parameters.")
    if len(steps) > MAX_STEPS:
        raise ToolError(f"At most {MAX_STEPS} steps at a time.")
    ops = set(cs.HANDLERS) | {"formula"}
    code: list[str] = []
    notes: list[str] = []
    trail: list[dict] = []
    cur = df
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            raise ToolError(f"Step {i} must be an object with an 'op'.", hint="Valid ops: " + ", ".join(sorted(ops)))
        op = step["op"]
        if op not in ops:
            raise ToolError(f"Step {i}: unknown op '{op}'.", hint="Valid ops: " + ", ".join(sorted(ops)))
        params = {k: v for k, v in step.items() if k != "op"}
        before = (len(cur), len(cur.columns))
        if op == "cast_type" and params.get("to") in ("float", "integer"):
            exact = [c for c in (params.get("columns") or []) if c in cur.columns and cur[c].dtype == object and _holds_decimals(cur[c])]
            if exact:                                           # accuracy: say it, do not hide it
                notes.append(f"step {i}: {', '.join(exact)} hold exact decimals; converting to {params['to']} can round them (fine for analysis, not for exact money totals).")
        nxt = None
        token = cs.NOTES.set([])
        try:
            nxt, line = (fm.expression if op == "formula" else cs.HANDLERS[op])(cur, params)
            bucket = list(cs.NOTES.get() or [])
        except ValueError as exc:
            raise ToolError(f"Step {i} ({op}): {exc}", hint="Nothing was changed. transform_steps shows the parameters of each step.") from None
        finally:
            cs.NOTES.reset(token)
        cur = nxt
        code.append(line)
        notes += [f"step {i}: {n}" for n in bucket]
        trail.append({"step": i, "op": op, "rows": [before[0], len(cur)], "columns": [before[1], len(cur.columns)]})
    if not all(isinstance(c, str) for c in cur.columns) or len(set(cur.columns)) != len(cur.columns):
        raise ToolError("The result has duplicate or non-text column names.", hint="Rename columns first (bulk_rename).")
    return {"df": cur, "code": code, "notes": notes, "trail": trail}


# ---- describing ---------------------------------------------------------------------------------------------------------------------

def _py(v: Any) -> Any:
    import pandas as pd

    try:
        if v is None or (not isinstance(v, (list, dict, tuple, set)) and bool(pd.isna(v))):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item") and not isinstance(v, (bytes, bytearray, str)):
        try:
            return v.item()
        except Exception:  # noqa: BLE001
            return v
    return v


def describe(before: Any, after: Any, sample_rows: int) -> dict[str, Any]:
    n = max(1, min(int(sample_rows), 100))
    sample = [[jsonable(_py(v)) for v in row] for row in after.head(n).itertuples(index=False, name=None)]
    b, a = list(before.columns), list(after.columns)
    nulls = after.isna().sum()
    return {"rows_before": len(before), "rows_after": len(after),
            "columns_before": b, "columns_after": [{"name": c, "dtype": str(after[c].dtype), "empty": int(nulls[c])} for c in a],
            "columns_added": [c for c in a if c not in b], "columns_removed": [c for c in b if c not in a],
            "sample": sample, "sample_rows": len(sample)}


def plan_digest(table: dict, steps: list, save_as: str, mode: str) -> str:
    """The identity of one exact write: the source table AT THIS VERSION, the steps, the target and the mode."""
    canon = json.dumps({"table": table["full_name"], "version": table.get("version"), "rows": table.get("row_count"),
                        "steps": steps, "save_as": save_as, "mode": mode}, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


# ---- flatten JSON columns (roadmap H5) -----------------------------------------------------------------------------------------------

MAX_FLAT_COLUMNS = 200


def flatten_json(df: Any, columns: Any, sep: str = ".", max_depth: int = 3) -> tuple[Any, list[str]]:
    """Replace each JSON column (JSON text, dict or list per cell) by one column per key: `col.key`, `col.key.sub` … (nested objects up to max_depth;
    anything deeper, and every list, stays as JSON text in its column — never silently dropped or exploded). Numbers keep exact decimals.
    Returns (new DataFrame, notes). The original column is replaced; row count never changes."""
    import decimal

    import pandas as pd

    if not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns):
        raise ToolError("flatten_json needs 'columns': a list of column names holding JSON.")
    sep = str(sep or ".")[:3]
    try:
        max_depth = max(1, min(int(max_depth), 6))
    except (TypeError, ValueError):
        raise ToolError("flatten_json 'max_depth' must be a whole number (1-6).") from None
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ToolError(f"No such column: {', '.join(missing)}.", hint="Columns: " + ", ".join(map(str, df.columns)))
    notes: list[str] = []

    def parse(v: Any) -> Any:
        if isinstance(v, str) and v.strip()[:1] in ("{", "["):
            try:
                return json.loads(v, parse_float=decimal.Decimal)
            except ValueError:
                notes.append("a value that looked like JSON could not be parsed and was left as text")
        return v

    seen_objects = [0]

    def walk(prefix: str, v: Any, depth: int, out: dict) -> None:
        if isinstance(v, dict) and depth == 1:
            seen_objects[0] += 1
        if isinstance(v, dict) and depth <= max_depth:
            for k, x in v.items():
                walk(f"{prefix}{sep}{k}", x, depth + 1, out)
        elif isinstance(v, (dict, list)):
            out[prefix] = json.dumps(v, default=str, ensure_ascii=False)
        else:
            out[prefix] = v

    result = df.copy()
    for col in columns:
        flat_rows = []
        seen_objects[0] = 0
        for v in df[col].tolist():
            out: dict = {}
            v = parse(v) if not (v is None or (isinstance(v, float) and v != v)) else None
            if v is not None:
                walk(col, v, 1, out)
            flat_rows.append(out)
        names: list[str] = []
        for r in flat_rows:
            for k in r:
                if k not in names:
                    names.append(k)
        if not names or not seen_objects[0]:
            raise ToolError(f"Column '{col}' has no JSON objects to flatten (lists and plain values are not flattened).")
        if len(names) > MAX_FLAT_COLUMNS:
            raise ToolError(f"Flattening '{col}' would create {len(names)} columns (limit {MAX_FLAT_COLUMNS}).", hint="Use a smaller max_depth, or flatten fewer columns.")
        clash = [n for n in names if n in result.columns and n != col]
        if clash:
            raise ToolError(f"Flattening '{col}' would overwrite existing columns: {', '.join(clash[:5])}.")
        new = pd.DataFrame({n: pd.Series([r.get(n) for r in flat_rows], index=result.index, dtype=object) for n in names})   # object: a missing key must not turn ints into floats
        pos = list(result.columns).index(col)
        result = pd.concat([result.iloc[:, :pos], new, result.iloc[:, pos + 1:]], axis=1)
        notes.append(f"'{col}' became {len(names)} column(s): {', '.join(names[:8])}{'…' if len(names) > 8 else ''}")
    return result, sorted(set(notes), key=notes.index)


# ---- writing (the ONLY function here that changes anything; call it only after control.require + a consumed confirmation) -----------

def write_result(df: Any, workspace: str, name: str, *, mode: str, source: dict, description: str) -> dict[str, Any]:
    """Store *df* as workspace.name. mode: 'create' (new table) | 'replace' (the old table is renamed to <name>_backup_<time>, never deleted).
    Returns the table plus a READ-BACK report; the caller must treat read_back.ok == False as a failure."""
    import pandas as pd

    lake = lake_store.scoped(PLUGIN)
    tmp = Path(tempfile.mkdtemp(prefix="mcp_frame_w_"))
    backup: Optional[str] = None
    try:
        out = tmp / "t.parquet"
        df.to_parquet(out, index=False)
        on_disk = pd.read_parquet(out)
        if len(on_disk) != len(df) or list(on_disk.columns) != list(df.columns) or \
                [int(x) for x in on_disk.isna().sum()] != [int(x) for x in df.isna().sum()]:
            raise ToolError("Storing the table in Parquet would change it (rows, columns or empty values differ), so nothing was saved.",
                            hint="Check for mixed-type columns; cast them (cast_type) first.")
        if mode == "replace":
            backup = f"{name}_backup_{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}"
            lake.rename_table(workspace, name, new_name=backup)
        try:
            t = lake.write_table(workspace, name, [out], mode="create", source=source, description=description, create_workspace_if_missing=True)
        except Exception:
            if backup:  # put the old table back: a failed replace must leave things exactly as they were
                lake.rename_table(workspace, backup, new_name=name)
            raise
        t2 = lake.get_table(workspace, name)
        rows_ok = t2.get("row_count") == len(df)
        cols_ok = [c["name"] for c in t2["columns"]] == list(df.columns)
        return {"table": t2, "backup": f"{workspace}.{backup}" if backup else None,
                "read_back": {"ok": bool(rows_ok and cols_ok), "rows_match": bool(rows_ok), "columns_match": bool(cols_ok),
                              "rows": t2.get("row_count"), "empty_values_match": True}}
    except lake_store.LakeError as exc:
        raise ToolError(str(exc)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
