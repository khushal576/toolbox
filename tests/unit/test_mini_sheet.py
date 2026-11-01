"""Mini Sheet (roadmap M1), part 1: the formula language (run by node), the page's JavaScript, and everything in
sheetio.py — typing, per-cell errors, size limits, paste/CSV/JSON/XLSX parsing, downloads.
Needs `node` for the first group, pyarrow (+ openpyxl for xlsx) for the rest; each group skips when its tool is missing.
The HTTP layer + Vault Data (needs DuckDB) is in test_mini_sheet_server.py."""

import io
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "mini-sheet"
sys.path.insert(0, str(REPO))


# ---- the formula language (browser code, executed by node) --------------------------------------------------------

def test_formula_language_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(REPO / "tests" / "unit" / "mini_sheet_formula_cases.js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wrap_line_counter_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(REPO / "tests" / "unit" / "mini_sheet_wrap_cases.js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_page_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    import re

    html = (TOOL / "ui" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts, "the page has no inline script"
    for name, code in [("formula.js", (TOOL / "ui" / "formula.js").read_text(encoding="utf-8")), ("wrap.js", (TOOL / "ui" / "wrap.js").read_text(encoding="utf-8"))] + [(f"inline{i}", c) for i, c in enumerate(scripts)]:
        r = subprocess.run([node, "--check", "-"], input=code, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_page_loads_formula_js_and_has_no_eval():
    import re

    html = (TOOL / "ui" / "index.html").read_text(encoding="utf-8")
    assert '<script src="formula.js"></script>' in html
    assert '<script src="wrap.js"></script>' in html
    def code_of(name):
        js = (TOOL / "ui" / name).read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)                 # the header comment talks about eval(): not code
        return re.sub(r"(?m)^\s*//.*$|(?<=\s)//\s.*$", "", code)

    for name, text in (("index.html", html), ("formula.js", code_of("formula.js")), ("wrap.js", code_of("wrap.js"))):
        for pattern in (r"\beval\s*\(", r"\bnew\s+Function\b", r"\bFunction\s*\(", r"setTimeout\s*\(\s*[\"']", r"document\.write", r"\bimport\s*\("):
            assert not re.search(pattern, text), f"{name} must not use {pattern}"


# ---- sheetio: typing, per-cell errors, limits -----------------------------------------------------------------------------

@pytest.fixture
def sio(monkeypatch):
    pytest.importorskip("pyarrow")
    for m in ("sheetio", "mini_sheet.sheetio"):
        sys.modules.pop(m, None)
    try:                                              # inside the container the tool is the package mini_sheet
        from mini_sheet import sheetio
    except ImportError:                               # in a checkout it is the folder mini-sheet/
        monkeypatch.syspath_prepend(str(TOOL))
        import sheetio
    yield sheetio
    for m in ("sheetio", "mini_sheet.sheetio"):
        sys.modules.pop(m, None)


def cols(*pairs):
    return [{"name": n, "kind": k, "sql_type": s} for n, k, s in pairs]


def test_round_trip_types_are_the_tables_own(sio):
    c = cols(("id", "integer", "bigint"), ("small", "integer", "smallint"), ("name", "text", "varchar"), ("x", "number", "double precision"),
             ("amt", "number", "numeric(10,2)"), ("d", "date", "date"), ("ts", "datetime", "timestamp"), ("tz", "datetime", "timestamptz"), ("ok", "boolean", "boolean"))
    rows = [[1, 2, "a", 1.5, "10.25", "2026-01-02", "2026-03-01 10:00:00", "2026-03-01 10:00:00", True],
            [None, None, None, None, None, None, None, None, None]]
    t, errors, total = sio.coerce_table(c, rows)
    assert (errors, total) == ([], 0)
    assert [str(f.type) for f in t.schema] == ["int64", "int16", "string", "double", "decimal128(10, 2)", "date32[day]", "timestamp[us]", "timestamp[us, tz=UTC]", "bool"]
    assert t.column("amt")[0].as_py() == Decimal("10.25") and t.column("d")[0].as_py() == date(2026, 1, 2)
    assert t.column("ts")[0].as_py() == datetime(2026, 3, 1, 10, 0, 0) and t.column("id")[1].as_py() is None


def test_every_bad_cell_is_reported_and_nothing_is_built(sio):
    c = cols(("id", "integer", "bigint"), ("amt", "number", "numeric(10,2)"), ("d", "date", "date"), ("ok", "boolean", "boolean"), ("s", "integer", "smallint"), ("x", "number", "double precision"))
    rows = [["1.5", "1.234", "2026-13-01", "maybe", 40000, "NaN"], ["abc", "123456789012", "yesterday", "yes", 5, "1e3"], [7, "5", "2026-02-30", "no", "7", "inf"]]
    t, errors, total = sio.coerce_table(c, rows)
    assert t is None and total == len(errors)
    got = {(e["row"], e["column"]): e["reason"] for e in errors}
    assert got[(1, "id")] == "not a whole number" and "decimal places" in got[(1, "amt")] and got[(1, "d")] == "not a real date"
    assert got[(1, "ok")] == "not true/false" and "out of range" in got[(1, "s")] and got[(1, "x")] == "not a number"
    assert got[(2, "id")] and "too many digits" in got[(2, "amt")] and "date" in got[(2, "d")]
    assert got[(3, "d")] == "not a real date" and (3, "x") in got and (3, "id") not in got and (3, "s") not in got
    _, errors, _ = sio.coerce_table(cols(("x", "number", "double precision")), [[float("nan")], [float("inf")], [1.5]])
    assert [e["reason"] for e in errors] == ["not a finite number"] * 2


def test_errors_are_capped_but_counted(sio):
    c = cols(("n", "integer", "bigint"))
    t, errors, total = sio.coerce_table(c, [["x"]] * 500)
    assert t is None and total == 500 and len(errors) == sio.MAX_ERRORS


def test_blanks_become_null_text_stays_text_and_formula_looking_text_is_kept(sio):
    t, errors, _ = sio.coerce_table(cols(("a", "text", "varchar"), ("n", "integer", "bigint"), ("b", "boolean", "boolean")), [["", "", ""], ["  ", None, None], ["=1+1", " 42 ", "Yes"], [12, 3.0, 1], [1.5, "7", "false"]])
    assert not errors
    assert t.column("a").to_pylist() == [None, None, "=1+1", "12", "1.5"] and t.column("n").to_pylist() == [None, None, 42, 3, 7]
    assert t.column("b").to_pylist() == [None, None, True, True, False]


def test_date_and_timestamp_forms(sio):
    t, errors, _ = sio.coerce_table(cols(("d", "date", "date"), ("ts", "datetime", "timestamp"), ("tz", "datetime", "timestamptz")),
                                    [["2026/1/5", "2026-01-05", "2026-01-05T10:00:00+05:30"], ["2026-01-05 00:00:00", "2026-01-05 10:30", "2026-01-05T10:00:00Z"]])
    assert not errors
    assert t.column("d").to_pylist() == [date(2026, 1, 5)] * 2 and t.column("ts")[0].as_py() == datetime(2026, 1, 5)
    assert t.column("tz")[0].as_py().hour == 4 and t.column("tz")[1].as_py().hour == 10      # +05:30 → UTC


def test_bad_shapes_and_names_are_refused(sio):
    with pytest.raises(sio.SheetError, match="no columns"):
        sio.coerce_table([], [])
    with pytest.raises(sio.SheetError, match="Two columns"):
        sio.coerce_table(cols(("a", "text", ""), ("A", "text", "")), [])
    with pytest.raises(sio.SheetError, match="needs a name"):
        sio.coerce_table(cols((" ", "text", "")), [])
    with pytest.raises(sio.SheetError, match="unknown type"):
        sio.coerce_table(cols(("a", "money", "")), [])
    with pytest.raises(sio.SheetError, match="3 cells but there are 2 columns"):
        sio.coerce_table(cols(("a", "text", ""), ("b", "text", "")), [["x", "y"], ["1", "2", "3"]])


def test_size_limits(sio, monkeypatch):
    monkeypatch.setattr(sio, "MAX_ROWS", 5)
    monkeypatch.setattr(sio, "MAX_COLS", 3)
    with pytest.raises(sio.TooBig, match="rows is more than"):
        sio.coerce_table(cols(("a", "text", "")), [["x"]] * 6)
    with pytest.raises(sio.TooBig, match="columns is more than"):
        sio.coerce_table(cols(("a", "text", ""), ("b", "text", ""), ("c", "text", ""), ("d", "text", "")), [])
    monkeypatch.setattr(sio, "MAX_ROWS", 50000)
    monkeypatch.setattr(sio, "MAX_CELLS", 10)
    with pytest.raises(sio.TooBig, match="too big"):
        sio.coerce_table(cols(("a", "text", ""), ("b", "text", "")), [["x", "y"]] * 6)


# ---- opening data: paste, csv, json, xlsx -------------------------------------------------------------------------------------

def test_paste_from_excel_guesses_column_types(sio):
    d = sio.parse_text("name\tqty\tprice\tday\tok\tcode\nap\t3\t1.5\t2026-02-01\ttrue\t007\nbe\t4\t2\t2026-02-02\tfalse\t010\n", header=True)
    assert [c["kind"] for c in d["columns"]] == ["text", "integer", "number", "date", "boolean", "text"]     # 007 / 010 stay text (leading zeros)
    assert d["rows"][0] == ["ap", 3, 1.5, "2026-02-01", True, "007"] and d["row_count"] == 2 and not d["partial"]


def test_paste_without_header_and_ragged_rows(sio):
    d = sio.parse_text("1\t2\n3\n4\t5\t6\n", header=False)
    assert [c["name"] for c in d["columns"]] == ["A", "B", "C"] and d["rows"][1] == [3, None, None]


def test_duplicate_and_empty_headers_are_made_unique(sio):
    d = sio.parse_text("a,a,,A\n1,2,3,4\n")
    assert [c["name"] for c in d["columns"]] == ["a", "a_2", "C", "A_3"]


def test_csv_quotes_semicolons_and_bom(sio):
    d = sio.parse_file("x.csv", ("﻿name;note\n\"a;b\";\"line1\nline2\"\n").encode("utf-8"))
    assert d["rows"] == [["a;b", "line1\nline2"]]
    d = sio.parse_file("x.tsv", b"a\tb\n1\t2\n")
    assert d["columns"][1]["kind"] == "integer"
    d = sio.parse_file("x.csv", "naïve,x\n1,2\n".encode("latin-1"))
    assert d["columns"][0]["name"] == "naïve"


def test_json_shapes(sio):
    assert sio.parse_file("a.json", b'[{"a":1,"b":"x"},{"a":2,"c":true}]')["columns"][2]["name"] == "c"
    assert sio.parse_file("a.json", b'{"rows":[{"a":1},{"a":2}]}')["rows"] == [[1], [2]]
    assert sio.parse_file("a.json", b'{"a":[1,2],"b":["x","y"]}')["rows"] == [[1, "x"], [2, "y"]]
    assert sio.parse_file("a.json", b'[["h1","h2"],[1,2]]')["columns"][0]["name"] == "h1"
    assert sio.parse_file("a.json", b'{"a":1}\n{"a":2}\n')["rows"] == [[1], [2]]
    assert sio.parse_file("a.json", b'[{"a":{"n":1}}]')["rows"] == [['{"n": 1}']]
    with pytest.raises(sio.SheetError):
        sio.parse_file("a.json", b'{nope')


def test_xlsx_round_trip_and_sheet_choice(sio):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "First"
    ws.append(["name", "qty", "day"]); ws.append(["a", 1, datetime(2026, 1, 2)]); ws.append(["b", 2.5, datetime(2026, 1, 3, 4, 5)])
    ws2 = wb.create_sheet("Second"); ws2.append(["z"]); ws2.append([9])
    buf = io.BytesIO(); wb.save(buf)
    d = sio.parse_file("t.xlsx", buf.getvalue())
    assert [c["kind"] for c in d["columns"]] == ["text", "number", "datetime"] and d["sheets"] == ["First", "Second"]
    assert d["rows"][0][2] == "2026-01-02" if d["columns"][2]["kind"] == "date" else True
    assert sio.parse_file("t.xlsx", buf.getvalue(), sheet="Second")["rows"] == [[9]]
    with pytest.raises(sio.SheetError, match="no sheet"):
        sio.parse_file("t.xlsx", buf.getvalue(), sheet="Nope")
    with pytest.raises(sio.SheetError):
        sio.parse_file("t.xlsx", b"PK not really")
    with pytest.raises(sio.SheetError, match=r"\.xls"):
        sio.parse_file("old.xls", b"\xd0\xcf\x11\xe0")


def test_big_inputs_are_offered_as_first_rows(sio, monkeypatch):
    monkeypatch.setattr(sio, "MAX_ROWS", 4)
    text = "a\n" + "\n".join(str(i) for i in range(10))
    with pytest.raises(sio.TooBig) as e:
        sio.parse_text(text)
    assert e.value.info["row_count"] == 10 and e.value.info["max_rows"] == 4
    d = sio.parse_text(text, limit=4)
    assert len(d["rows"]) == 4 and d["partial"] and d["row_count"] == 10
    monkeypatch.setattr(sio, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(sio.TooBig, match="small data"):
        sio.parse_file("big.csv", b"a,b\n" + b"1,2\n" * 10)


def test_empty_and_garbage_input_is_a_clear_error(sio):
    for bad in ("", "   \n \n"):
        with pytest.raises(sio.SheetError, match="nothing to open"):
            sio.parse_text(bad)


# ---- downloads ---------------------------------------------------------------------------------------------------------------------

def test_csv_download_is_quoted_and_safe_to_open_in_excel(sio):
    data, media, ext = sio.build_export("csv", [{"name": "a"}, {"name": "b"}], [["x,y", 'say "hi"'], ["=1+1", "@cmd"], ["-5", True], [-5, None], ["+x", "ok"]])
    text = data.decode("utf-8-sig").splitlines()
    assert ext == "csv" and data.startswith(b"\xef\xbb\xbf") and text[0] == "a,b"
    assert text[1] == '"x,y","say ""hi"""' and text[2] == "'=1+1,'@cmd" and text[3] == "-5,TRUE" and text[4] == "-5," and text[5] == "'+x,ok"


def test_xlsx_download_keeps_numbers_dates_and_never_makes_live_formulas(sio):
    openpyxl = pytest.importorskip("openpyxl")
    data, media, ext = sio.build_export("xlsx", [{"name": "n", "kind": "integer"}, {"name": "d", "kind": "date"}, {"name": "t", "kind": "text"}],
                                        [["5", "2026-01-02", "=SUM(A1)"], [None, None, "plain"], ["12.5", "x", "@y"]])
    ws = openpyxl.load_workbook(io.BytesIO(data))["Sheet1"]
    assert [c.value for c in ws[1]] == ["n", "d", "t"] and ws["A2"].value == 5 and ws["B2"].value.date() == date(2026, 1, 2)
    assert ws["C2"].value == "=SUM(A1)" and ws["C2"].data_type == "s", "text starting with = must stay text, not become a formula"
    assert ws["A4"].value == 12.5 and ws["B4"].value == "x"
    with pytest.raises(sio.SheetError):
        sio.build_export("pdf", [], [])


# ---- workbook (several sheets): names, xlsx in/out, size limits ------------------------------------------------------------

def _xlsx(sheets):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("name", ["Sheet1", "My data", "a" * 31, "Q1 2026", "naïve ünï", "x.y", "it's", "a b c"])
def test_good_sheet_names(sio, name):
    assert sio.check_sheet_name(name) == name


@pytest.mark.parametrize("name", ["", "   ", None, "a" * 32, "a/b", "a\\b", "a:b", "a*b", "a?b", "a[b", "a]b", "'quoted", "quoted'", "tab\tname"])
def test_bad_sheet_names(sio, name):
    with pytest.raises(sio.SheetError):
        sio.check_sheet_name(name)


def test_sheet_names_must_be_unique_ignoring_case_and_few_enough(sio):
    assert sio.check_sheet_names(["A", "B"]) == ["A", "B"]
    with pytest.raises(sio.SheetError, match="different"):
        sio.check_sheet_names(["Sales", "sales"])
    with pytest.raises(sio.SheetError):
        sio.check_sheet_names([])
    with pytest.raises(sio.TooBig):
        sio.check_sheet_names([f"S{i}" for i in range(sio.MAX_SHEETS + 1)])
    assert len(sio.check_sheet_names([f"S{i}" for i in range(sio.MAX_SHEETS)])) == sio.MAX_SHEETS


def test_workbook_size_limits(sio, monkeypatch):
    sh = lambda n, r, c: {"name": n, "columns": [{}] * c, "rows": [[None] * c] * r}
    assert sio.check_workbook_size([sh("a", 10, 3), sh("b", 5, 2)]) == 40
    with pytest.raises(sio.TooBig, match="columns"):
        sio.check_workbook_size([sh("wide", 1, sio.MAX_COLS + 1)])
    with pytest.raises(sio.TooBig, match="rows"):
        sio.check_workbook_size([sh("long", sio.MAX_ROWS + 1, 1)])
    monkeypatch.setattr(sio, "MAX_CELLS", 100)
    with pytest.raises(sio.TooBig, match="in all"):
        sio.check_workbook_size([sh("a", 10, 6), sh("b", 10, 6)])        # each fine alone, too big together


def test_xlsx_with_three_sheets_opens_all_of_them(sio):
    raw = _xlsx([("Sales", [["id", "amount"], [1, 2.5], [2, 3.5]]), ("Empty", []), ("People data", [["name"], ["ann"], ["bob"]]), ("sales ", [["q"], [5]])])
    out = sio.parse_xlsx_all(raw)
    assert [x["name"] for x in out["sheets"]] == ["Sales", "People data", "sales (2)"]       # empty skipped, the near-duplicate renamed
    assert out["skipped"] == [{"name": "Empty", "reason": "empty"}]
    sales = out["sheets"][0]
    assert [c["kind"] for c in sales["columns"]] == ["integer", "number"] and len(sales["rows"]) == 2
    assert [r[0] for r in out["sheets"][1]["rows"]] == ["ann", "bob"]


def test_xlsx_all_empty_sheets_is_an_error(sio):
    with pytest.raises(sio.SheetError, match="empty"):
        sio.parse_xlsx_all(_xlsx([("A", []), ("B", [])]))


def test_xlsx_skips_a_sheet_over_the_limits_but_keeps_the_rest(sio, monkeypatch):
    monkeypatch.setattr(sio, "MAX_ROWS", 3)
    raw = _xlsx([("Small", [["a"], [1], [2]]), ("Big", [["a"]] + [[i] for i in range(10)])])
    out = sio.parse_xlsx_all(raw)
    assert [x["name"] for x in out["sheets"]] == ["Small"]
    assert out["skipped"][0]["name"] == "Big" and "too big" in out["skipped"][0]["reason"]
    with pytest.raises(sio.TooBig):                                                   # nothing left → the problem is raised
        sio.parse_xlsx_all(_xlsx([("Big", [["a"]] + [[i] for i in range(10)])]))


def test_xlsx_total_cell_limit_across_sheets(sio, monkeypatch):
    monkeypatch.setattr(sio, "MAX_CELLS", 12)
    raw = _xlsx([("A", [["x", "y"]] + [[1, 2]] * 4), ("B", [["x", "y"]] + [[1, 2]] * 4)])     # 8 cells each
    out = sio.parse_xlsx_all(raw)
    assert [x["name"] for x in out["sheets"]] == ["A"] and "size limit" in out["skipped"][0]["reason"]


def test_xlsx_sheet_count_limit(sio, monkeypatch):
    monkeypatch.setattr(sio, "MAX_SHEETS", 2)
    out = sio.parse_xlsx_all(_xlsx([(f"S{i}", [["a"], [i]]) for i in range(4)]))
    assert len(out["sheets"]) == 2 and len(out["skipped"]) == 2


def test_xlsx_round_trip_with_three_sheets_keeps_names_and_values(sio):
    openpyxl = pytest.importorskip("openpyxl")
    sheets = [{"name": "Sales", "columns": cols(("id", "integer", "bigint"), ("amt", "number", "double precision")), "rows": [[1, 2.5], [2, None]]},
              {"name": "People data", "columns": cols(("name", "text", "varchar")), "rows": [["ann"], ["=SUM(1)"]]},
              {"name": "Dates", "columns": cols(("d", "date", "date")), "rows": [["2026-01-02"]]}]
    data, media, ext = sio.build_export_workbook("xlsx", sheets)
    assert ext == "xlsx" and "spreadsheetml" in media
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Sales", "People data", "Dates"]
    assert [list(r) for r in wb["Sales"].values] == [["id", "amt"], [1, 2.5], [2, None]]
    assert wb["People data"]["A3"].value == "=SUM(1)" and wb["People data"]["A3"].data_type == "s"       # text that looks like a formula stays text
    back = sio.parse_xlsx_all(data)
    assert [x["name"] for x in back["sheets"]] == ["Sales", "People data", "Dates"]


def test_export_workbook_refuses_bad_input(sio):
    with pytest.raises(sio.SheetError, match="xlsx"):
        sio.build_export_workbook("csv", [{"name": "A", "columns": [], "rows": []}])
    with pytest.raises(sio.SheetError):
        sio.build_export_workbook("xlsx", [{"name": "A", "columns": [], "rows": []}, {"name": "a", "columns": [], "rows": []}])
    with pytest.raises(sio.SheetError):
        sio.build_export_workbook("xlsx", [{"name": "bad/name", "columns": [], "rows": []}])


# ---- the draft store (memory backend; the Redis/S3 one has the same API and is exercised in the container) ----------------------

@pytest.fixture
def ds(monkeypatch):
    for m in ("draftstore", "mini_sheet.draftstore"):
        sys.modules.pop(m, None)
    try:
        from mini_sheet import draftstore
    except ImportError:
        monkeypatch.syspath_prepend(str(TOOL))
        import draftstore
    yield draftstore
    for m in ("draftstore", "mini_sheet.draftstore"):
        sys.modules.pop(m, None)


def test_draft_store_round_trip_rev_and_expiry(ds, monkeypatch):
    b = ds.MemoryBackend()
    assert b.get("s" * 20) is None
    m1 = b.put("a" * 20, b"one", {"sheets": 1}, None)
    assert m1["rev"] == 1 and m1["size"] == 3
    meta, data = b.get("a" * 20)
    assert data == b"one" and meta["rev"] == 1
    m2 = b.put("a" * 20, b"two!", {"sheets": 1}, 1)
    assert m2["rev"] == 2 and b.get("a" * 20)[1] == b"two!"
    with pytest.raises(ds.RevConflict) as e:
        b.put("a" * 20, b"stale", {}, 1)                                   # another tab wrote since: refused
    assert e.value.current == 2 and b.get("a" * 20)[1] == b"two!"
    b.put("a" * 20, b"forced", {}, None)                                   # no expected rev = take over
    assert b.get("a" * 20)[1] == b"forced"
    b.put("b" * 20, b"other", {}, None)                                    # a second browser has its own draft
    assert b.get("b" * 20)[1] == b"other" and b.get("a" * 20)[1] == b"forced"
    b.delete("a" * 20)
    assert b.get("a" * 20) is None and b.get("b" * 20) is not None
    monkeypatch.setattr(ds, "TTL_SECONDS", -1)                             # everything written from now on is already expired
    b.put("c" * 20, b"x", {}, None)
    assert b.sweep() >= 1 and b.get("c" * 20) is None


def test_draft_session_ids_are_checked(ds):
    assert ds.valid_sid("A" * 32) and ds.valid_sid("abc-DEF_123456789012")
    for bad in (None, "", "short", "a" * 200, "has space " * 3, "../../etc/passwd", "a:b" + "c" * 20, "x/y" + "z" * 20):
        assert not ds.valid_sid(bad), bad
