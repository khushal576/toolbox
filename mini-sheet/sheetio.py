"""
mini-sheet/sheetio.py — everything the Mini Sheet does with data that is not HTTP (roadmap M1).

- table_to_json(): a Parquet file (a Vault Data table exported by core.lake) → {columns, rows} for the browser.
- coerce_table(): the browser's rows → a typed pyarrow table, checking EVERY cell. A value that doesn't fit its
  column's type is reported (row, column, value, reason) — never silently turned into NULL or rounded.
- parse_text() / parse_file(): pasted text, CSV/TSV, JSON, XLSX → {columns, rows} with column types guessed from the values.
- build_export(): rows → CSV / XLSX bytes for "Download".
No FastAPI here, so the unit tests can run it on its own.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

MAX_ROWS = int(os.environ.get("MINI_SHEET_MAX_ROWS", "50000"))
MAX_COLS = int(os.environ.get("MINI_SHEET_MAX_COLS", "200"))
MAX_CELLS = int(os.environ.get("MINI_SHEET_MAX_CELLS", "5000000"))
MAX_UPLOAD_BYTES = int(os.environ.get("MINI_SHEET_MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_SHEETS = int(os.environ.get("MINI_SHEET_MAX_SHEETS", "50"))          # sheets in one workbook (Excel-style tabs)
SHEET_NAME_MAX = 31                                                         # Excel's own limit, so an .xlsx download is always valid
_BAD_SHEET_CHARS = set('[]:*?/\\')
MAX_ERRORS = 200            # cell problems listed back to the page (the total is still counted)
SAFE_INT = 9007199254740991  # JS numbers are exact up to 2**53-1; bigger integers travel as text

KINDS = ("text", "integer", "number", "date", "datetime", "boolean")
_INT_RANGE = {"smallint": (-2**15, 2**15 - 1), "integer": (-2**31, 2**31 - 1), "bigint": (-2**63, 2**63 - 1)}


class SheetError(ValueError):
    """A user-facing problem (too big, unreadable file, bad name…)."""


class TooBig(SheetError):
    def __init__(self, message: str, **info: Any):
        super().__init__(message)
        self.info = info


# ---- types ----------------------------------------------------------------------------------------------------------

def kind_of(sql_type: Optional[str]) -> str:
    """The sheet's column kind for a Vault Data SQL type (core.lake.sql_type words)."""
    t = (sql_type or "").strip().lower()
    if t in ("bigint", "integer", "smallint", "tinyint", "int"):
        return "integer"
    if t in ("double precision", "real", "double", "float") or t.startswith(("numeric", "decimal")):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "date":
        return "date"
    if t.startswith("timestamp"):
        return "datetime"
    return "text"


def _decimal_ps(sql_type: str) -> tuple[int, int]:
    m = re.match(r"^(?:numeric|decimal)\((\d+),\s*(\d+)\)$", sql_type.strip().lower())
    return (int(m.group(1)), int(m.group(2))) if m else (38, 10)


def arrow_type(kind: str, sql_type: Optional[str]):
    """The Parquet type a column is saved as: the table's own type when it has one (round trip), else by kind."""
    import pyarrow as pa

    t = (sql_type or "").strip().lower()
    if kind == "integer":
        return {"smallint": pa.int16(), "tinyint": pa.int16(), "integer": pa.int32(), "int": pa.int32()}.get(t, pa.int64())
    if kind == "number":
        if t.startswith(("numeric", "decimal")):
            p, s = _decimal_ps(t)
            return pa.decimal128(min(p, 38), min(s, 38))
        return pa.float32() if t == "real" else pa.float64()
    if kind == "boolean":
        return pa.bool_()
    if kind == "date":
        return pa.date32()
    if kind == "datetime":
        return pa.timestamp("us", tz="UTC") if t == "timestamptz" else pa.timestamp("us")
    return pa.string()


def sql_type_of(kind: str, sql_type: Optional[str]) -> str:
    """SQL words for what arrow_type() saves (what the Tables list will show)."""
    t = (sql_type or "").strip().lower()
    if kind == "integer":
        return t if t in _INT_RANGE else "bigint"
    if kind == "number":
        return t if t.startswith(("numeric", "decimal")) or t == "real" else "double precision"
    return {"boolean": "boolean", "date": "date", "datetime": "timestamptz" if t == "timestamptz" else "timestamp"}.get(kind, "varchar")


# ---- table → JSON -----------------------------------------------------------------------------------------------------

def _json_cell(v: Any) -> Any:
    """One Parquet value → something JSON carries exactly and the sheet shows as typed."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v if abs(v) <= SAFE_INT else str(v)
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.isoformat(sep=" ")
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, default=str)
    return str(v)


def table_to_json(path: Any, columns_meta: list[dict[str, Any]], limit: Optional[int] = None) -> dict[str, Any]:
    """Read a Parquet file written by core.lake.export_table. `columns_meta` = the catalog's columns (name/type/sql_type)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    if limit:
        table = table.slice(0, int(limit))
    meta = {c["name"]: c for c in columns_meta}
    cols, notes = [], []
    for field in table.schema:
        m = meta.get(field.name, {})
        sql = m.get("sql_type") or m.get("type") or ""
        kind = kind_of(sql)
        if pa.types.is_binary(field.type) or pa.types.is_large_binary(field.type):
            notes.append(f"Column “{field.name}” is binary — shown as hex text; saving stores it as text.")
        elif pa.types.is_nested(field.type):
            notes.append(f"Column “{field.name}” holds nested values — shown as JSON text; saving stores it as text.")
        if kind == "text" and sql.lower() in ("uuid", "json", "time", "interval"):
            notes.append(f"Column “{field.name}” is {sql} — it is edited as text and saved as varchar.")
        cols.append({"name": field.name, "sql_type": sql_type_of(kind, sql) if kind != "text" else "varchar", "kind": kind})
    data = [[_json_cell(v) for v in table.column(i).to_pylist()] for i in range(table.num_columns)]
    rows = [list(r) for r in zip(*data)] if data else []
    return {"columns": cols, "rows": rows, "notes": notes}


# ---- JSON → typed table ------------------------------------------------------------------------------------------------

_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}
_INT_RE = re.compile(r"^[+-]?\d+$")
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")


class CellError(ValueError):
    pass


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _to_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v)


def _conv(kind: str, sql_type: str, v: Any) -> Any:
    """One cell → the Python value pyarrow stores. Raises CellError with a plain reason."""
    t = (sql_type or "").lower()
    if kind == "text":
        return _to_text(v)
    if kind == "integer":
        if isinstance(v, bool):
            raise CellError("not a whole number")
        if isinstance(v, int):
            n = v
        elif isinstance(v, float):
            if not v.is_integer():
                raise CellError("not a whole number")
            n = int(v)
        elif isinstance(v, str) and _INT_RE.match(v.strip()):
            n = int(v.strip())
        elif isinstance(v, str) and _NUM_RE.match(v.strip()) and Decimal(v.strip()) == Decimal(v.strip()).to_integral_value():
            n = int(Decimal(v.strip()))
        else:
            raise CellError("not a whole number")
        lo, hi = _INT_RANGE.get(t, _INT_RANGE["bigint"])
        if not lo <= n <= hi:
            raise CellError(f"out of range for {t if t in _INT_RANGE else 'bigint'}")
        return n
    if kind == "number":
        if isinstance(v, bool):
            raise CellError("not a number")
        s = v.strip() if isinstance(v, str) else None
        if s is not None and not _NUM_RE.match(s):
            raise CellError("not a number")
        if t.startswith(("numeric", "decimal")):
            p, sc = _decimal_ps(t)
            try:
                d = Decimal(s if s is not None else repr(v))
            except InvalidOperation:
                raise CellError("not a number") from None
            if not d.is_finite():
                raise CellError("not a number")
            if -d.as_tuple().exponent > sc and d != d.quantize(Decimal(1).scaleb(-sc)):
                raise CellError(f"more than {sc} decimal places for numeric({p},{sc})")
            q = d.quantize(Decimal(1).scaleb(-sc))
            if len(q.as_tuple().digits) > p:
                raise CellError(f"too many digits for numeric({p},{sc})")
            return q
        f = float(s) if s is not None else float(v)
        if math.isnan(f) or math.isinf(f):
            raise CellError("not a finite number")
        return f
    if kind == "boolean":
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)) and v in (0, 1):
            return bool(v)
        s = str(v).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise CellError("not true/false")
    if kind == "date":
        s = str(v).strip()
        m = _DATE_RE.match(s)
        if not m:                                                       # "2026-01-05 00:00:00" is still just a date
            m2 = re.match(r"^(\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T]00:00(:00(\.0+)?)?$", s)
            m = _DATE_RE.match(m2.group(1)) if m2 else None
        if not m:
            raise CellError("not a date — use YYYY-MM-DD")
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            raise CellError("not a real date") from None
    if kind == "datetime":
        s = str(v).strip().replace("/", "-", 2)
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00") if s.endswith("Z") else s)
        except ValueError:
            raise CellError("not a date/time — use YYYY-MM-DD HH:MM:SS") from None
        if t == "timestamptz":
            return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo is not None else d
    raise CellError("unknown column type")


def check_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the column list (names, kinds, count). Returns it normalised."""
    if not columns:
        raise SheetError("The sheet has no columns.")
    if len(columns) > MAX_COLS:
        raise TooBig(f"{len(columns)} columns is more than Mini Sheet handles ({MAX_COLS}).", max_cols=MAX_COLS)
    seen, out = set(), []
    for c in columns:
        name = str(c.get("name", "")).strip()
        kind = c.get("kind") or "text"
        if not name:
            raise SheetError("Every column needs a name.")
        if len(name) > 128 or any(ord(ch) < 32 for ch in name):
            raise SheetError(f"Column name “{name[:40]}” is too long or has control characters.")
        if name.lower() in seen:
            raise SheetError(f"Two columns are called “{name}” — names must be different.")
        if kind not in KINDS:
            raise SheetError(f"Column “{name}” has an unknown type “{kind}”.")
        seen.add(name.lower())
        out.append({"name": name, "kind": kind, "sql_type": c.get("sql_type") or ""})
    return out


def coerce_table(columns: list[dict[str, Any]], rows: list[list[Any]]):
    """→ (pyarrow.Table | None, errors, total_errors). errors = [{row, column, value, reason}] (row is 1-based, as the
    sheet's row numbers). When there are any errors nothing is built — the page shows them and the user fixes them."""
    import pyarrow as pa

    cols = check_columns(columns)
    if len(rows) > MAX_ROWS:
        raise TooBig(f"{len(rows):,} rows is more than Mini Sheet handles ({MAX_ROWS:,}).", max_rows=MAX_ROWS)
    if len(rows) * len(cols) > MAX_CELLS:
        raise TooBig("The sheet is too big for Mini Sheet.", max_cells=MAX_CELLS)
    errors: list[dict[str, Any]] = []
    total = 0
    values: list[list[Any]] = [[] for _ in cols]
    for ri, row in enumerate(rows):
        if len(row) != len(cols):
            raise SheetError(f"Row {ri + 1} has {len(row)} cells but there are {len(cols)} columns.")
        for ci, c in enumerate(cols):
            v = row[ci]
            if _blank(v):
                values[ci].append(None)
                continue
            try:
                values[ci].append(_conv(c["kind"], c["sql_type"], v))
            except CellError as exc:
                total += 1
                values[ci].append(None)
                if len(errors) < MAX_ERRORS:
                    shown = str(v)
                    errors.append({"row": ri + 1, "column": c["name"], "value": shown[:60], "reason": str(exc)})
    if total:
        return None, errors, total
    arrays = [pa.array(values[i], type=arrow_type(c["kind"], c["sql_type"])) for i, c in enumerate(cols)]
    return pa.table(arrays, names=[c["name"] for c in cols]), [], 0


# ---- parsing pasted text / files -----------------------------------------------------------------------------------------

def _dedupe_headers(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, n in enumerate(names):
        n = (n or "").strip() or _letters(i)
        key = n.lower()
        if key in seen:
            seen[key] += 1
            n = f"{n}_{seen[key]}"
            seen[n.lower()] = 1
        else:
            seen[key] = 1
        out.append(n[:128])
    return out


def _letters(i: int) -> str:
    s, i = "", i + 1
    while i > 0:
        i, m = divmod(i - 1, 26)
        s = chr(65 + m) + s
    return s


def infer_kind(values: list[Any]) -> str:
    """Guess a column's kind from its (text) values: whole numbers, numbers, true/false, dates, else text."""
    seen = [v for v in values if not _blank(v)]
    if not seen:
        return "text"
    strs = [v.strip() if isinstance(v, str) else v for v in seen]

    def all_(f) -> bool:
        return all(f(s) for s in strs)

    if all_(lambda s: isinstance(s, bool) or (isinstance(s, str) and s.lower() in ("true", "false"))):
        return "boolean"
    if all_(lambda s: (isinstance(s, int) and not isinstance(s, bool)) or (isinstance(s, str) and _INT_RE.match(s) and not (len(s.lstrip("+-")) > 1 and s.lstrip("+-").startswith("0")))):
        return "integer"
    if all_(lambda s: (isinstance(s, (int, float)) and not isinstance(s, bool)) or (isinstance(s, str) and _NUM_RE.match(s) and not (len(s.lstrip("+-")) > 1 and s.lstrip("+-")[0] == "0" and s.lstrip("+-")[1] != "."))):
        return "number"
    if all_(lambda s: isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", s) is not None and _is_date(s)):
        return "date"
    if all_(lambda s: isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$", s) is not None and _is_datetime(s)):
        return "datetime"
    return "text"


def _is_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _is_datetime(s: str) -> bool:
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def _typed(kind: str, v: Any) -> Any:
    """Raw parsed value → what the sheet holds for that column kind (numbers as numbers, the rest as text)."""
    if _blank(v):
        return None
    if kind == "integer":
        n = int(str(v).strip()) if not isinstance(v, int) else v
        return n if abs(n) <= SAFE_INT else str(n)
    if kind == "number":
        return float(v) if not isinstance(v, (int, float)) or isinstance(v, bool) else v
    if kind == "boolean":
        return v if isinstance(v, bool) else str(v).strip().lower() == "true"
    return v if isinstance(v, str) else _to_text(v)


def _finish(header: list[str], raw_rows: list[list[Any]], limit: Optional[int], source: str) -> dict[str, Any]:
    n_cols = len(header)
    if n_cols > MAX_COLS:
        raise TooBig(f"{source} has {n_cols} columns — Mini Sheet handles up to {MAX_COLS}.", max_cols=MAX_COLS)
    total = len(raw_rows)
    allowed = min(MAX_ROWS, MAX_CELLS // max(1, n_cols))
    if total > allowed and not limit:
        raise TooBig(f"{source} has {total:,} rows — Mini Sheet handles up to {allowed:,}.", row_count=total, max_rows=allowed)
    if limit:
        raw_rows = raw_rows[:min(int(limit), allowed)]
    rows = [(list(r) + [None] * n_cols)[:n_cols] for r in raw_rows]
    cols = []
    for i, name in enumerate(header):
        kind = infer_kind([r[i] for r in rows])
        cols.append({"name": name, "kind": kind, "sql_type": sql_type_of(kind, "") if kind != "text" else "varchar"})
        for r in rows:
            r[i] = _typed(kind, r[i])
    return {"columns": cols, "rows": rows, "row_count": total, "partial": len(rows) < total}


def _sniff_delimiter(sample: str) -> str:
    first = sample.split("\n", 1)[0]
    counts = {d: first.count(d) for d in ("\t", ",", ";", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def parse_text(text: str, header: bool = True, limit: Optional[int] = None, delimiter: Optional[str] = None,
               source: str = "The pasted data") -> dict[str, Any]:
    """Pasted/CSV text → {columns, rows}. Tab is preferred (Excel/Sheets copy gives TSV); falls back to , ; |."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise SheetError("There is nothing to open — the text is empty.")
    delim = delimiter or _sniff_delimiter(text[:20000])
    try:
        grid = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim) if r and any(c.strip() for c in r)]
    except csv.Error as exc:
        raise SheetError(f"Could not read the text as a table: {exc}") from None
    if not grid:
        raise SheetError("There is nothing to open — the text is empty.")
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    if header:
        head, body = _dedupe_headers(grid[0]), grid[1:]
    else:
        head, body = [_letters(i) for i in range(width)], grid
    return _finish(head, body, limit, source)


def parse_json(data: Any, limit: Optional[int] = None, source: str = "The JSON file") -> dict[str, Any]:
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1 and all(isinstance(x, (dict, list)) for x in lists[0][:5]):
            data = lists[0]
        elif data and all(isinstance(v, list) for v in data.values()):    # {"a": [1,2], "b": [3,4]}
            data = [dict(zip(data.keys(), vals)) for vals in zip(*data.values())]
        else:
            data = [data]
    if not isinstance(data, list) or not data:
        raise SheetError("The JSON must be a list of rows (objects or lists).")
    if all(isinstance(r, dict) for r in data):
        keys: list[str] = []
        for r in data:
            for k in r:
                if k not in keys:
                    keys.append(k)
        rows = [[_cell_from_json(r.get(k)) for k in keys] for r in data]
        return _finish(_dedupe_headers([str(k) for k in keys]), rows, limit, source)
    if all(isinstance(r, list) for r in data):
        return _finish(_dedupe_headers([str(c) for c in data[0]]), [[_cell_from_json(c) for c in r] for r in data[1:]], limit, source)
    raise SheetError("The JSON must be a list of objects or a list of lists.")


def _cell_from_json(v: Any) -> Any:
    return json.dumps(v) if isinstance(v, (list, dict)) else v


def parse_xlsx(raw: bytes, header: bool = True, sheet: Optional[str] = None, limit: Optional[int] = None,
               source: str = "The Excel file") -> dict[str, Any]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many different things for a bad file
        raise SheetError(f"Could not read the Excel file: {exc}") from None
    try:
        if sheet:
            if sheet not in wb.sheetnames:
                raise SheetError(f"The workbook has no sheet “{sheet}” (it has: {', '.join(wb.sheetnames)}).")
            ws = wb[sheet]
        else:
            ws = wb[wb.sheetnames[0]]
        grid = []
        for r in ws.iter_rows(values_only=True):
            cells = [_xl_cell(c) for c in r]
            if any(not _blank(c) for c in cells):
                grid.append(cells)
            if len(grid) > MAX_ROWS * 4:
                raise TooBig(f"{source} has more than {MAX_ROWS * 4:,} rows.", max_rows=MAX_ROWS)
        sheets = list(wb.sheetnames)
    finally:
        wb.close()
    if not grid:
        raise SheetError("The sheet is empty.")
    width = max(len(r) for r in grid)
    grid = [r + [None] * (width - len(r)) for r in grid]
    if header:
        head, body = _dedupe_headers([("" if c is None else str(c)) for c in grid[0]]), grid[1:]
    else:
        head, body = [_letters(i) for i in range(width)], grid
    out = _finish(head, body, limit, source)
    out["sheets"] = sheets
    return out


def _xl_cell(c: Any) -> Any:
    if isinstance(c, datetime):
        return c.isoformat(sep=" ") if (c.hour or c.minute or c.second) else c.date().isoformat()
    if isinstance(c, (date, time)):
        return c.isoformat()
    if isinstance(c, float) and c.is_integer() and abs(c) < 1e15:
        return int(c)
    return c


def parse_file(filename: str, raw: bytes, header: bool = True, sheet: Optional[str] = None, limit: Optional[int] = None) -> dict[str, Any]:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise TooBig(f"“{filename}” is {len(raw) / 2**20:,.1f} MB — Mini Sheet is for small data (up to {MAX_UPLOAD_BYTES // 2**20} MB). "
                     "Load big files with Vault Data → Load files instead.", max_mb=MAX_UPLOAD_BYTES // 2**20)
    name = (filename or "").lower()
    src = f"“{filename}”"
    if name.endswith((".xlsx", ".xlsm")) or raw[:2] == b"PK":
        return parse_xlsx(raw, header, sheet, limit, src)
    if name.endswith(".xls"):
        raise SheetError("Old .xls files aren't supported — save the file as .xlsx or .csv first.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if name.endswith(".json") or text.lstrip()[:1] in ("[", "{"):
        try:
            return parse_json(json.loads(text), limit, src)
        except json.JSONDecodeError:
            if name.endswith(".json"):                                  # maybe JSON Lines
                try:
                    return parse_json([json.loads(line) for line in text.splitlines() if line.strip()], limit, src)
                except json.JSONDecodeError:
                    raise SheetError("The file is not valid JSON.") from None
    return parse_text(text, header, limit, "\t" if name.endswith((".tsv", ".tab")) else None, src)


# ---- download ----------------------------------------------------------------------------------------------------------------

def build_export(fmt: str, columns: list[dict[str, Any]], rows: list[list[Any]]) -> tuple[bytes, str, str]:
    """(bytes, media type, file extension) for CSV or XLSX of what the sheet shows."""
    names = [str(c.get("name", "")) for c in columns]
    if len(rows) > MAX_ROWS or len(rows) * max(1, len(names)) > MAX_CELLS:
        raise TooBig("The sheet is too big for Mini Sheet.", max_rows=MAX_ROWS)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(names)
        for r in rows:
            w.writerow([_csv_safe(v) for v in r])
        return ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "csv"
    if fmt == "xlsx":
        import openpyxl

        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet("Sheet1")
        ws.append(names)
        kinds = [c.get("kind") for c in columns]
        from openpyxl.cell import WriteOnlyCell

        def cell(v: Any):
            if isinstance(v, str) and v.startswith("="):                # text stays text — openpyxl would store it as a formula
                c = WriteOnlyCell(ws, value=v)
                c.data_type = "s"
                return c
            return v

        for r in rows:
            ws.append([cell(_xl_out(v, kinds[i] if i < len(kinds) else "text")) for i, v in enumerate(r)])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    raise SheetError("format must be csv or xlsx")


def _csv_safe(v: Any) -> Any:
    """Text that Excel would run as a formula when the CSV is opened (=, @, +x, -x) gets a leading apostrophe."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str) and v[:1] in ("=", "@", "\t", "\r") or (isinstance(v, str) and re.match(r"^[+-][^\d.\s]", v)):
        return "'" + v
    return v


def _xl_out(v: Any, kind: str) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    s = str(v)
    if kind in ("integer", "number") and _NUM_RE.match(s.strip()):
        return float(s) if ("." in s or "e" in s.lower()) else (int(s) if abs(int(s)) <= SAFE_INT else s)
    if kind == "date" and _DATE_RE.match(s.strip()) and _is_date(s.strip()):
        return date.fromisoformat(s.strip())
    if kind == "datetime" and _is_datetime(s.strip().replace(" ", "T", 1)):
        return datetime.fromisoformat(s.strip().replace(" ", "T", 1))
    return s


# ---- workbook (several sheets) ------------------------------------------------------------------------------------------------

def check_sheet_name(name: Any) -> str:
    """A sheet's tab name: 1–31 characters, none of [ ] : * ? / \\ , no leading/trailing apostrophe (Excel's rules)."""
    n = "" if name is None else str(name).strip()
    if not n:
        raise SheetError("A sheet needs a name.")
    if len(n) > SHEET_NAME_MAX:
        raise SheetError(f"A sheet name can have at most {SHEET_NAME_MAX} characters (“{n[:20]}…” is {len(n)}).")
    bad = sorted({ch for ch in n if ch in _BAD_SHEET_CHARS})
    if bad:
        raise SheetError("A sheet name can't contain " + " ".join(bad) + ".")
    if any(ord(ch) < 32 for ch in n):
        raise SheetError("A sheet name can't contain control characters.")
    if n.startswith("'") or n.endswith("'"):
        raise SheetError("A sheet name can't start or end with an apostrophe.")
    return n


def check_sheet_names(names: list[Any]) -> list[str]:
    """Every name valid and unique (case-insensitive), at most MAX_SHEETS of them."""
    if not names:
        raise SheetError("A workbook needs at least one sheet.")
    if len(names) > MAX_SHEETS:
        raise TooBig(f"A workbook can have at most {MAX_SHEETS} sheets.", max_sheets=MAX_SHEETS)
    out, seen = [], set()
    for raw in names:
        n = check_sheet_name(raw)
        if n.lower() in seen:
            raise SheetError(f"Two sheets are called “{n}” — sheet names must be different.")
        seen.add(n.lower())
        out.append(n)
    return out


def check_workbook_size(sheets: list[dict[str, Any]]) -> int:
    """Total cells over every sheet within MAX_CELLS (and each sheet within the row/column limits). Returns the total."""
    total = 0
    for sh in sheets:
        nr, nc = len(sh.get("rows") or []), len(sh.get("columns") or [])
        if nc > MAX_COLS:
            raise TooBig(f"Sheet “{sh.get('name', '?')}” has {nc} columns — Mini Sheet handles up to {MAX_COLS}.", max_cols=MAX_COLS)
        if nr > MAX_ROWS:
            raise TooBig(f"Sheet “{sh.get('name', '?')}” has {nr:,} rows — Mini Sheet handles up to {MAX_ROWS:,}.", max_rows=MAX_ROWS)
        total += nr * max(1, nc)
    if total > MAX_CELLS:
        raise TooBig(f"The workbook has {total:,} cells in all — Mini Sheet handles up to {MAX_CELLS:,}.", max_cells=MAX_CELLS)
    return total


def _unique_sheet_name(base: str, taken: set[str]) -> str:
    base = (base or "Sheet").strip()[:SHEET_NAME_MAX] or "Sheet"
    cand, i = base, 2
    while cand.lower() in taken:
        suffix = f" ({i})"
        cand = base[:SHEET_NAME_MAX - len(suffix)] + suffix
        i += 1
    taken.add(cand.lower())
    return cand


def parse_xlsx_all(raw: bytes, header: bool = True, limit: Optional[int] = None, source: str = "The Excel file") -> dict[str, Any]:
    """Every sheet of an .xlsx as its own sheet: {"sheets": [{name, columns, rows, row_count, partial}], "skipped": [{name, reason}]}.
    Empty sheets are skipped (with a note); so are sheets over the row/column limits and any sheet that would take the workbook over
    MAX_SHEETS sheets or MAX_CELLS cells. If nothing is left, the first problem is raised."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many different things for a bad file
        raise SheetError(f"Could not read the Excel file: {exc}") from None
    sheets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    first_problem: Optional[Exception] = None
    taken: set[str] = set()
    total_cells = 0
    try:
        for title in wb.sheetnames:
            if len(sheets) >= MAX_SHEETS:
                skipped.append({"name": title, "reason": f"over the limit of {MAX_SHEETS} sheets"})
                continue
            ws = wb[title]
            grid: list[list[Any]] = []
            too_long = False
            for r in ws.iter_rows(values_only=True):
                cells = [_xl_cell(c) for c in r]
                if any(not _blank(c) for c in cells):
                    grid.append(cells)
                if len(grid) > MAX_ROWS * 4:
                    too_long = True
                    break
            if too_long:
                err = TooBig(f"Sheet “{title}” has more than {MAX_ROWS * 4:,} rows.", max_rows=MAX_ROWS)
                first_problem = first_problem or err
                skipped.append({"name": title, "reason": "too many rows for Mini Sheet"})
                continue
            if not grid:
                skipped.append({"name": title, "reason": "empty"})
                continue
            width = max(len(r) for r in grid)
            grid = [r + [None] * (width - len(r)) for r in grid]
            if header:
                head, body = _dedupe_headers([("" if c is None else str(c)) for c in grid[0]]), grid[1:]
            else:
                head, body = [_letters(i) for i in range(width)], grid
            try:
                one = _finish(head, body, limit, f"Sheet “{title}”")
            except TooBig as exc:
                first_problem = first_problem or exc
                skipped.append({"name": title, "reason": "too big for Mini Sheet (" + str(exc).split("—")[0].strip().rstrip(".") + ")"})
                continue
            cells = len(one["rows"]) * max(1, len(one["columns"]))
            if total_cells + cells > MAX_CELLS:
                first_problem = first_problem or TooBig(f"The workbook is too big for Mini Sheet (over {MAX_CELLS:,} cells in all).", max_cells=MAX_CELLS)
                skipped.append({"name": title, "reason": "the workbook would go over the size limit"})
                continue
            total_cells += cells
            one["name"] = _unique_sheet_name(re.sub(r"[\[\]:*?/\\]", "_", title).strip("'") or "Sheet", taken)
            sheets.append(one)
    finally:
        wb.close()
    if not sheets:
        if isinstance(first_problem, TooBig):
            raise first_problem
        raise SheetError("Every sheet in the file is empty.")
    return {"sheets": sheets, "skipped": skipped}


def build_export_workbook(fmt: str, sheets: list[dict[str, Any]]) -> tuple[bytes, str, str]:
    """An .xlsx with one worksheet per sheet (computed values, tab names kept). Only xlsx — a CSV has no sheets."""
    if fmt != "xlsx":
        raise SheetError("Only .xlsx can hold several sheets — download a CSV from one sheet at a time.")
    names = check_sheet_names([sh.get("name") for sh in sheets])
    check_workbook_size(sheets)
    import openpyxl
    from openpyxl.cell import WriteOnlyCell

    wb = openpyxl.Workbook(write_only=True)
    for name, sh in zip(names, sheets):
        ws = wb.create_sheet(name)
        cols = sh.get("columns") or []
        ws.append([str(c.get("name", "")) for c in cols])
        kinds = [c.get("kind") for c in cols]

        def cell(v: Any, _ws=ws):
            if isinstance(v, str) and v.startswith("="):                # text stays text — openpyxl would store it as a formula
                c = WriteOnlyCell(_ws, value=v)
                c.data_type = "s"
                return c
            return v

        for r in sh.get("rows") or []:
            ws.append([cell(_xl_out(v, kinds[i] if i < len(kinds) else "text")) for i, v in enumerate(r)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
