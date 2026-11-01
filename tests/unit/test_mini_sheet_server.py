"""Mini Sheet (roadmap M1), part 2: the HTTP layer against a real (temporary) Vault Data catalog — open/save round trip with
column types, per-cell 422 list, 409 → replace/backup, partial-sheet guard, limits, names, parse/import/export.
Vault Data writes Parquet through DuckDB, so this skips on a machine without it. Run it inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_mini_sheet_server.py -q
(inside the container the tool is the package `mini_sheet`; in a checkout it is the folder `mini-sheet/`)."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "mini-sheet"
sys.path.insert(0, str(REPO))

duckdb = pytest.importorskip("duckdb", reason="Vault Data writes Parquet through DuckDB — run these inside the container")
pytest.importorskip("pyarrow")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from core import lake  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    for v in ("TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT", "TOOLBOX_DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "files"))
    monkeypatch.setattr(lake, "_ready", False)
    mods = ("server", "sheetio", "mini_sheet.server", "mini_sheet.sheetio")
    for m in mods:
        sys.modules.pop(m, None)
    try:
        try:                                          # inside the container the tool is the package mini_sheet
            from mini_sheet import server
        except ImportError:                           # in a checkout it is the folder mini-sheet/
            monkeypatch.syspath_prepend(str(TOOL))
            import server
    except ImportError as exc:                        # e.g. python-multipart / the vault's crypto library missing here
        pytest.skip(f"mini-sheet server needs the container's libraries: {exc}")
    client = TestClient(server.app)
    client.tmp, client.server = tmp_path, server
    yield client
    for m in mods:
        sys.modules.pop(m, None)


def seed(api, name="people", ws="demo", n=30):
    out = api.tmp / f"{name}.parquet"
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT i::BIGINT AS id, 'person_' || i AS name, (i * 1.5)::DOUBLE AS score, (i * 10.25)::DECIMAL(10,2) AS amount,
        DATE '2026-01-01' + (i::INTEGER) AS joined, (i % 2 = 0) AS active, TIMESTAMP '2026-03-01 10:00:00' + INTERVAL (i) MINUTE AS seen,
        (i::SMALLINT) AS tiny FROM range(1, {n + 1}) t(i)) TO '{out}' (FORMAT PARQUET)""")
    con.close()
    return lake.write_table(ws, name, [out], create_workspace_if_missing=True, source={"kind": "test"})


def test_the_tool_has_the_vault_data_write_scope_and_the_page_is_served(api):
    from core.vault import scope_for

    assert scope_for("mini-sheet").data == "write"
    r = api.get("/")
    assert r.status_code == 200 and "Mini Sheet" in r.text
    j = api.get("/formula.js")
    assert j.status_code == 200 and "javascript" in j.headers["content-type"] and "createEvaluator" in j.text
    assert api.get("/limits").json()["max_rows"] == 50000


def test_open_then_save_keeps_every_column_type(api):
    seed(api)
    d = api.get("/table", params={"ws": "demo", "name": "people"}).json()
    assert d["row_count"] == 30 and not d["partial"]
    assert [(c["name"], c["kind"], c["sql_type"]) for c in d["columns"]] == [
        ("id", "integer", "bigint"), ("name", "text", "varchar"), ("score", "number", "double precision"), ("amount", "number", "numeric(10,2)"),
        ("joined", "date", "date"), ("active", "boolean", "boolean"), ("seen", "datetime", "timestamp"), ("tiny", "integer", "smallint")]
    assert d["rows"][0] == [1, "person_1", 1.5, "10.25", "2026-01-02", False, "2026-03-01 10:01:00", 1]
    d["rows"][0][1] = "edited"
    r = api.post("/save", json={"workspace": "demo", "table": "people_v2", "mode": "create", "columns": d["columns"], "rows": d["rows"],
                                "origin": {"workspace": "demo", "table": "people", "partial": False}})
    assert r.status_code == 200, r.text
    t = lake.get_table("demo", "people_v2")
    assert t["row_count"] == 30 and t["source"]["kind"] == "mini-sheet" and t["source"]["opened_from"] == "demo.people"
    assert [c["sql_type"] for c in t["columns"]] == [c["sql_type"] for c in lake.get_table("demo", "people")["columns"]]
    again = api.get("/table", params={"ws": "demo", "name": "people_v2"}).json()
    assert again["rows"][0][1] == "edited" and again["rows"][1:] == d["rows"][1:]


def test_bad_cells_give_422_with_the_cell_list_and_write_nothing(api):
    seed(api)
    d = api.get("/table", params={"ws": "demo", "name": "people"}).json()
    d["rows"][2][0] = "abc"; d["rows"][3][3] = "1.234"; d["rows"][4][4] = "2026-13-01"
    r = api.post("/save", json={"workspace": "demo", "table": "never", "mode": "create", "columns": d["columns"], "rows": d["rows"]})
    assert r.status_code == 422
    body = r.json()
    assert body["total_errors"] == 3 and {(e["row"], e["column"]) for e in body["cell_errors"]} == {(3, "id"), (4, "amount"), (5, "joined")}
    with pytest.raises(lake.NotFound):
        lake.get_table("demo", "never")


def test_names_bare_name_goes_to_system_dotted_name_splits(api):
    cols_ = [{"name": "a", "kind": "text"}]
    ok = api.post("/save", json={"workspace": "", "table": "bare", "mode": "create", "columns": cols_, "rows": [["x"]]})
    assert ok.status_code == 200 and ok.json()["table"]["full_name"] == "system.bare"
    ok = api.post("/save", json={"workspace": "ignored", "table": "sales.orders", "mode": "create", "columns": cols_, "rows": [["x"]]})
    assert ok.status_code == 200 and ok.json()["table"]["full_name"] == "sales.orders"
    for bad in ("Bad-Name", "1abc", "has space", "", "x" * 70, "UPPER"):
        r = api.post("/save", json={"workspace": "", "table": bad, "mode": "create", "columns": cols_, "rows": [["x"]]})
        assert r.status_code == 400 and "name" in r.json()["error"].lower(), bad
    r = api.post("/save", json={"workspace": "Bad WS", "table": "t", "mode": "create", "columns": cols_, "rows": []})
    assert r.status_code == 400


def test_existing_table_asks_then_replace_keep_makes_a_backup_overwrite_does_not(api):
    seed(api)
    d = api.get("/table", params={"ws": "demo", "name": "people"}).json()
    body = {"workspace": "demo", "table": "people", "mode": "create", "columns": d["columns"], "rows": d["rows"][:5]}
    r = api.post("/save", json=body)
    assert r.status_code == 409 and "already exists" in r.json()["error"]
    r = api.post("/save", json={**body, "mode": "replace_keep"})
    assert r.status_code == 200 and r.json()["backup"].startswith("demo.people_backup_")
    assert lake.get_table("demo", "people")["row_count"] == 5
    backup = r.json()["backup"].split(".", 1)[1]
    assert lake.get_table("demo", backup)["row_count"] == 30                       # the old data really is still there
    r = api.post("/save", json={**body, "rows": d["rows"][:2], "mode": "overwrite"})
    assert r.status_code == 200 and r.json()["backup"] is None and lake.get_table("demo", "people")["row_count"] == 2
    r = api.post("/save", json={**body, "table": "fresh", "mode": "replace_keep"})      # nothing to back up: simply creates
    assert r.status_code == 200 and r.json()["backup"] is None
    assert api.post("/save", json={**body, "mode": "merge"}).status_code == 400


def test_failed_replace_puts_the_old_table_back(api, monkeypatch):
    seed(api)
    d = api.get("/table", params={"ws": "demo", "name": "people"}).json()
    real = lake.write_table

    def boom(*a, **k):
        raise lake.LakeError("disk full")

    monkeypatch.setattr(lake, "write_table", boom)
    r = api.post("/save", json={"workspace": "demo", "table": "people", "mode": "replace_keep", "columns": d["columns"], "rows": d["rows"][:3]})
    monkeypatch.setattr(lake, "write_table", real)
    assert r.status_code == 400 and "disk full" in r.json()["error"]
    assert lake.get_table("demo", "people")["row_count"] == 30
    assert [t["name"] for t in lake.list_tables("demo")] == ["people"]              # no stray backup table left behind


def test_a_partial_sheet_can_never_overwrite_the_table_it_came_from(api):
    seed(api, n=30)
    api.server.sheetio.MAX_ROWS = 10
    try:
        big = api.get("/table", params={"ws": "demo", "name": "people"})
        assert big.status_code == 413 and big.json()["row_count"] == 30 and big.json()["max_rows"] == 10
        part = api.get("/table", params={"ws": "demo", "name": "people", "limit": 10}).json()
        assert part["partial"] and part["loaded_rows"] == 10 and part["row_count"] == 30 and len(part["rows"]) == 10
        origin = {"workspace": "demo", "table": "people", "partial": True}
        for mode in ("overwrite", "replace_keep"):
            r = api.post("/save", json={"workspace": "demo", "table": "people", "mode": mode, "columns": part["columns"], "rows": part["rows"], "origin": origin})
            assert r.status_code == 400 and "only the first rows" in r.json()["error"]
        assert lake.get_table("demo", "people")["row_count"] == 30
        ok = api.post("/save", json={"workspace": "demo", "table": "first_ten", "mode": "create", "columns": part["columns"], "rows": part["rows"], "origin": origin})
        assert ok.status_code == 200 and lake.get_table("demo", "first_ten")["row_count"] == 10
        r = api.post("/save", json={"workspace": "demo", "table": "toobig", "mode": "create", "columns": part["columns"], "rows": part["rows"] + part["rows"]})
        assert r.status_code == 413 and r.json()["max_rows"] == 10
    finally:
        api.server.sheetio.MAX_ROWS = 50000


def test_wide_tables_are_refused_with_a_clear_message(api):
    seed(api)
    api.server.sheetio.MAX_COLS = 3
    try:
        r = api.get("/table", params={"ws": "demo", "name": "people"})
        assert r.status_code == 413 and "columns" in r.json()["error"]
    finally:
        api.server.sheetio.MAX_COLS = 200


def test_missing_table_and_catalog(api):
    seed(api)
    assert api.get("/table", params={"ws": "demo", "name": "nope"}).status_code == 404
    assert api.get("/table", params={"ws": "demo", "name": "people", "limit": -3}).status_code == 400
    cat = api.get("/catalog-lite").json()["workspaces"]
    assert {"name": "people", "rows": 30, "columns": 8, "kind": "managed"} in next(w for w in cat if w["name"] == "demo")["tables"]
    assert any(w["name"] == "system" for w in cat)


def test_formula_text_in_a_text_column_is_saved_as_text(api):
    r = api.post("/save", json={"workspace": "", "table": "txt", "mode": "create", "columns": [{"name": "a", "kind": "text"}], "rows": [["=1+1"], ["<b>x</b>"]]})
    assert r.status_code == 200
    assert api.get("/table", params={"ws": "system", "name": "txt"}).json()["rows"] == [["=1+1"], ["<b>x</b>"]]


def test_parse_import_and_export_endpoints(api):
    d = api.post("/parse", json={"text": "a\tb\n1\tx\n2\ty\n", "header": True}).json()
    assert [c["kind"] for c in d["columns"]] == ["integer", "text"] and d["rows"] == [[1, "x"], [2, "y"]]
    assert api.post("/parse", json={"text": "  "}).status_code == 400
    r = api.post("/import", files={"file": ("t.csv", b"x,y\n1,a\n2,b\n")}, data={"header": "true"})
    assert r.status_code == 200 and r.json()["rows"] == [[1, "a"], [2, "b"]]
    r = api.post("/import", files={"file": ("t.csv", b"1,a\n2,b\n")}, data={"header": "false"})
    assert r.json()["columns"][0]["name"] == "A"
    api.server.sheetio.MAX_UPLOAD_BYTES = 5
    try:
        assert api.post("/import", files={"file": ("t.csv", b"x,y\n1,a\n2,b\n")}).status_code == 413
    finally:
        api.server.sheetio.MAX_UPLOAD_BYTES = 25 * 1024 * 1024
    e = api.post("/export", json={"format": "csv", "name": "my sheet/../x", "columns": [{"name": "a"}], "rows": [["1"]]})
    assert e.status_code == 200 and 'filename="my_sheet____x.csv"' in e.headers["content-disposition"] and e.content.startswith(b"\xef\xbb\xbfa")
    assert api.post("/export", json={"format": "exe", "columns": [{"name": "a"}], "rows": []}).status_code == 400


# ---- roadmap M2: the draft (autosave), several sheets at once ---------------------------------------------------------------------

import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402


def _draft(name="wb", sheets=1, rows=2, changed=True):
    return {"v": 1, "changed": changed, "wb": {"name": name, "active": 0, "sheets": [
        {"id": i + 1, "name": f"Sheet{i + 1}", "cols": [{"id": 1, "name": "a", "kind": "text", "sql": "", "w": 100, "wrap": 1}],
         "rows": [[r + 1, [f"v{r}"]] for r in range(rows)], "nextRid": rows + 1, "nextCid": 2, "origin": None,
         "orig": {"mode": "diff", "fresh": [], "diff": [], "gone": 0}, "sel": {"ar": 0, "ac": 0, "cr": 0, "cc": 0}} for i in range(sheets)]}}


def _put(c, d, rev=None, gz=True, **kw):
    raw = json.dumps(d).encode()
    h = {"X-Draft-Encoding": "gzip" if gz else "identity", **kw.pop("headers", {})}
    if rev is not None:
        h["X-Draft-Rev"] = str(rev)
    return c.put("/draft", content=gzip.compress(raw) if gz else raw, headers=h, **kw)


def test_draft_round_trip_sets_a_cookie_and_gives_the_workbook_back(api):
    assert api.get("/draft").json() == {"draft": None}                           # nothing yet, and no cookie is invented for a read
    assert "mini_sheet_sid" not in api.cookies
    r = _put(api, _draft(name="demo.people"))
    assert r.status_code == 200 and r.json()["rev"] == 1
    sc = r.headers["set-cookie"].lower()
    assert "mini_sheet_sid=" in sc and "httponly" in sc and "samesite=lax" in sc
    g = api.get("/draft").json()
    assert g["rev"] == 1 and g["draft"]["wb"]["name"] == "demo.people" and g["draft"]["wb"]["sheets"][0]["rows"][1] == [2, ["v1"]]
    assert g["draft"]["wb"]["sheets"][0]["cols"][0]["wrap"] == 1                 # the per-column wrap flag survives
    assert _put(api, _draft(), rev=1, gz=False).json()["rev"] == 2               # a plain (uncompressed) body works too
    assert api.delete("/draft").json() == {"ok": True}
    assert api.get("/draft").json() == {"draft": None}


def test_two_browsers_never_see_each_others_draft(api):
    from fastapi.testclient import TestClient

    other = TestClient(api.server.app)
    _put(api, _draft(name="mine"))
    _put(other, _draft(name="theirs"))
    assert api.get("/draft").json()["draft"]["wb"]["name"] == "mine"
    assert other.get("/draft").json()["draft"]["wb"]["name"] == "theirs"
    other.delete("/draft")
    assert api.get("/draft").json()["draft"]["wb"]["name"] == "mine" and other.get("/draft").json() == {"draft": None}
    nocookie = TestClient(api.server.app)
    assert nocookie.get("/draft").json() == {"draft": None}
    forged = TestClient(api.server.app, cookies={"mini_sheet_sid": api.cookies["mini_sheet_sid"][:-1] + "!"})    # not a valid id: treated as none
    assert forged.get("/draft").json() == {"draft": None}


def test_a_second_tab_cannot_silently_overwrite_the_draft(api):
    assert _put(api, _draft(name="a")).json()["rev"] == 1
    assert _put(api, _draft(name="b"), rev=1).json()["rev"] == 2                 # tab 1 carries on
    stale = _put(api, _draft(name="from the other tab"), rev=1)                  # tab 2 still thinks rev 1 is current
    assert stale.status_code == 409 and stale.json()["rev"] == 2
    assert api.get("/draft").json()["draft"]["wb"]["name"] == "b"
    assert _put(api, _draft(name="forced"), headers={"X-Draft-Rev": "force"}).json()["rev"] == 3
    assert api.get("/draft").json()["draft"]["wb"]["name"] == "forced"


def test_draft_size_and_shape_limits(api):
    api.server._DRAFT_MAX_GZ = 2000
    try:
        import os

        big = _draft(rows=3000)
        for r in big["wb"]["sheets"][0]["rows"]:
            r[1][0] = os.urandom(12).hex()                                       # random text does not compress
        r = _put(api, big)
        assert r.status_code == 413 and "bigger than" in r.json()["error"]
        assert api.get("/draft").json() == {"draft": None}                       # a refused draft stores nothing
    finally:
        api.server._DRAFT_MAX_GZ = 40 * 2**20
    assert _put(api, _draft(sheets=api.server.sheetio.MAX_SHEETS + 1)).status_code == 413
    sheets = _draft(sheets=2); sheets["wb"]["sheets"][1]["name"] = "sheet1"
    r = _put(api, sheets)
    assert r.status_code == 400 and "different" in r.json()["error"]            # two sheets called the same
    bad = _draft(); bad["wb"]["sheets"][0]["name"] = "a/b"
    assert _put(api, bad).status_code == 400
    assert _put(api, {"wb": {}}).status_code == 400 and _put(api, {"nothing": 1}).status_code == 400
    assert api.put("/draft", content=b"not json", headers={"X-Draft-Encoding": "identity"}).status_code == 400
    assert api.put("/draft", content=b"not gzip", headers={"X-Draft-Encoding": "gzip"}).status_code == 400
    assert api.put("/draft", content=b"{}", headers={"X-Draft-Encoding": "brotli"}).status_code == 400
    api.server.sheetio.MAX_CELLS = 5
    try:
        assert _put(api, _draft(sheets=2, rows=3)).status_code == 413            # 6 cells in all
    finally:
        api.server.sheetio.MAX_CELLS = 5000000


def test_a_zip_bomb_draft_is_refused(api):
    api.server._DRAFT_MAX_RAW = 10000
    try:
        bomb = gzip.compress(b'{"wb":{"sheets":[]},"pad":"' + b"a" * 200000 + b'"}')
        assert len(bomb) < 2000
        r = api.put("/draft", content=bomb, headers={"X-Draft-Encoding": "gzip"})
        assert r.status_code == 413 and "unpacked" in r.json()["error"]
    finally:
        api.server._DRAFT_MAX_RAW = 400 * 2**20


def test_limits_tell_the_page_about_sheets_and_drafts(api):
    lim = api.get("/limits").json()
    assert lim["max_sheets"] == 50 and lim["sheet_name_max"] == 31 and lim["draft_max_mb"] == 40
    assert api.get("/wrap.js").status_code == 200 and "countLines" in api.get("/wrap.js").text


def _xlsx_bytes(sheets):
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


def test_import_all_sheets_of_an_xlsx_and_export_them_again(api):
    raw = _xlsx_bytes([("Sales", [["id", "amt"], [1, 2.5]]), ("Blank", []), ("People", [["name"], ["ann"]]), ("Dates", [["d"], ["2026-01-02"]])])
    r = api.post("/import", files={"file": ("book.xlsx", raw)}, data={"header": "true", "all_sheets": "true"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert [s["name"] for s in d["sheets"]] == ["Sales", "People", "Dates"] and d["skipped"] == [{"name": "Blank", "reason": "empty"}]
    one = api.post("/import", files={"file": ("book.xlsx", raw)}, data={"header": "true", "sheet": "People"}).json()      # naming a sheet = just that one
    assert one["rows"] == [["ann"]] and "sheets" in one and one["sheets"][0] == "Sales"
    csv_ = api.post("/import", files={"file": ("t.csv", b"x\n1\n")}, data={"all_sheets": "true"}).json()                 # not an xlsx: the normal single sheet
    assert csv_["rows"] == [[1]]
    out = api.post("/export", json={"format": "xlsx", "name": "book", "sheets": [{"name": s["name"], "columns": s["columns"], "rows": s["rows"]} for s in d["sheets"]]})
    assert out.status_code == 200 and 'filename="book.xlsx"' in out.headers["content-disposition"]
    openpyxl = pytest.importorskip("openpyxl")
    assert openpyxl.load_workbook(io.BytesIO(out.content)).sheetnames == ["Sales", "People", "Dates"]
    assert api.post("/export", json={"format": "csv", "sheets": [{"name": "A", "columns": [], "rows": []}]}).status_code == 400
    assert api.post("/export", json={"format": "xlsx", "sheets": [{"name": "A", "columns": [], "rows": []}, {"name": "a", "columns": [], "rows": []}]}).status_code == 400
    assert api.post("/import", files={"file": ("e.xlsx", _xlsx_bytes([("A", [])]))}, data={"all_sheets": "true"}).status_code == 400


def _item(sheet, table, rows, kind="integer", origin=None):
    return {"sheet": sheet, "table": table, "columns": [{"name": "n", "kind": kind, "sql_type": "bigint" if kind == "integer" else "varchar"}], "rows": rows, "origin": origin}


def test_save_all_writes_every_sheet_to_its_own_table(api):
    r = api.post("/save-all", json={"workspace": "wb", "items": [_item("One", "one", [[1], [2]]), _item("Two", "two", [[3]]), _item("Txt", "sales.txt", [["x"]], kind="text")]})
    assert r.status_code == 200 and r.json()["ok"] and [x["table"]["full_name"] for x in r.json()["results"]] == ["wb.one", "wb.two", "sales.txt"]
    assert lake.get_table("wb", "one")["row_count"] == 2 and lake.get_table("sales", "txt")["row_count"] == 1
    assert lake.get_table("wb", "one")["source"]["kind"] == "mini-sheet"


def test_save_all_is_all_or_nothing_when_any_cell_is_bad(api):
    r = api.post("/save-all", json={"workspace": "wb", "items": [_item("Good", "good", [[1]]), _item("Bad", "bad", [[1], ["abc"]]), _item("Worse", "worse", [["x"], ["y"]])]})
    assert r.status_code == 422
    b = r.json()
    assert [s["sheet"] for s in b["sheets"]] == ["Bad", "Worse"] and b["total_errors"] == 3 and b["sheets"][0]["cell_errors"][0]["row"] == 2
    for t in ("good", "bad", "worse"):
        with pytest.raises(lake.NotFound):
            lake.get_table("wb", t)


def test_save_all_asks_before_replacing_and_checks_names_first(api):
    api.post("/save-all", json={"workspace": "wb", "items": [_item("A", "a", [[1]]), _item("B", "b", [[2]])]})
    again = {"workspace": "wb", "items": [_item("A", "a", [[10], [11]]), _item("C", "c", [[3]])]}
    r = api.post("/save-all", json=again)
    assert r.status_code == 409 and r.json()["existing"] == ["wb.a"]
    with pytest.raises(lake.NotFound):
        lake.get_table("wb", "c")                                                # the new sheet was NOT written while another one needed an answer
    r = api.post("/save-all", json={**again, "on_exists": "replace_keep"})
    assert r.status_code == 200 and r.json()["ok"]
    assert r.json()["results"][0]["backup"].startswith("wb.a_backup_") and r.json()["results"][1]["backup"] is None
    assert lake.get_table("wb", "a")["row_count"] == 2 and lake.get_table("wb", "c")["row_count"] == 1
    r = api.post("/save-all", json={**again, "on_exists": "overwrite"})
    assert r.status_code == 200 and lake.get_table("wb", "a")["row_count"] == 2
    same = api.post("/save-all", json={"workspace": "wb", "items": [_item("A", "dup", [[1]]), _item("B", "dup", [[2]])]})
    assert same.status_code == 400 and "different table names" in same.json()["error"]
    badname = api.post("/save-all", json={"workspace": "wb", "items": [_item("A", "fine", [[1]]), _item("Q1 sales", "Bad Name", [[2]])]})
    assert badname.status_code == 400 and "Q1 sales" in badname.json()["error"]
    with pytest.raises(lake.NotFound):
        lake.get_table("wb", "fine")
    assert api.post("/save-all", json={"workspace": "wb", "items": []}).status_code == 400
    assert api.post("/save-all", json={"workspace": "wb", "on_exists": "merge", "items": [_item("A", "a", [[1]])]}).status_code == 400


def test_save_all_keeps_the_partial_sheet_guard_and_the_size_limits(api):
    seed(api, n=30)
    part = {"workspace": "demo", "table": "people", "partial": True}
    r = api.post("/save-all", json={"workspace": "demo", "on_exists": "overwrite", "items": [_item("People", "people", [[1]], origin=part)]})
    assert r.status_code == 400 and "only the first rows" in r.json()["error"] and lake.get_table("demo", "people")["row_count"] == 30
    api.server.sheetio.MAX_CELLS = 3
    try:
        r = api.post("/save-all", json={"workspace": "wb", "items": [_item("A", "a", [[1], [2]]), _item("B", "b", [[3], [4]])]})
        assert r.status_code == 413 and "in all" in r.json()["error"]
    finally:
        api.server.sheetio.MAX_CELLS = 5000000
    api.server.sheetio.MAX_SHEETS = 1
    try:
        assert api.post("/save-all", json={"workspace": "wb", "items": [_item("A", "a", [[1]]), _item("B", "b", [[2]])]}).status_code == 413
    finally:
        api.server.sheetio.MAX_SHEETS = 50
