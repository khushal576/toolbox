"""Roadmap L7: the column map of a load (data-lake/colmap.py) — keep / rename / cast / fill / mask / hash / redact /
shuffle — plus its use by the loader (run_load, run_copy, inspect_source). Needs DuckDB (+ pyarrow): runs on a dev
machine with them installed, and in the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_colmap.py -q
"""

import json
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data-lake"))

duckdb = pytest.importorskip("duckdb", reason="column-map tests need DuckDB (run them in the container)")
pytest.importorskip("pyarrow")


def _tool(module):
    import importlib

    try:
        return importlib.import_module(f"data_lake.{module}")
    except ImportError:
        return importlib.import_module(module)


colmap = _tool("colmap")


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        (1, 'john.doe@example.com', '4111111111111111', '12',  'a', '31/10/2026'),
        (2, 'a@y.org',              NULL,               'zz',  '',  '01/11/2026'),
        (3, NULL,                   '5500000000000004', '7',   'c', 'bad'),
        (4, 'plain text',           '12',               NULL,  '   ', NULL)
      ) v(id, email, card, amt, note, d)""")
    yield c
    c.close()


def compile_run(con, cols, only_listed=False, source="SELECT * FROM t"):
    avail = {r[0]: r[1] for r in con.execute(f"DESCRIBE {source}").fetchall()}
    cm = colmap.compile_select(source, avail, cols, only_listed)
    return cm, con.execute(cm.select_sql).fetchall(), [d[0] for d in con.description]


# ---- keep / rename / include --------------------------------------------------------------------------------------

def test_rename_include_exclude_and_only_listed(con):
    cm, rows, names = compile_run(con, [{"source": "id", "name": "row_id"}, {"source": "note", "include": False}])
    assert names == ["row_id", "email", "card", "amt", "d"]            # note dropped, the rest passes through
    cm, rows, names = compile_run(con, [{"source": "id", "name": "row_id"}, {"source": "amt"}], only_listed=True)
    assert names == ["row_id", "amt"] and [r[0] for r in rows] == [1, 2, 3, 4]
    # one source column can appear twice under different names (plain + protected)
    _, rows, names = compile_run(con, [{"source": "email"}, {"source": "email", "name": "email_hash",
                                                                 "protect": {"kind": "hash", "salt": "s"}}], True)
    assert names == ["email", "email_hash"] and rows[0][0] == "john.doe@example.com" and len(rows[0][1]) == 64


def test_rejects_bad_maps(con):
    avail = {"id": "INTEGER", "email": "VARCHAR"}
    bad = {
        "unknown column": [{"source": "nope"}],
        "bad name": [{"source": "id", "name": 'x"; DROP TABLE t; --'}],
        "reserved": [{"source": "id", "name": "__rn"}],
        "duplicate": [{"source": "id", "name": "email"}],
        "type": [{"source": "id", "type": "integer); DROP TABLE t; --"}],
        "decimal range": [{"source": "id", "type": "decimal(40,2)"}],
        "format on text": [{"source": "id", "type": "text", "format": "%Y"}],
        "format chars": [{"source": "id", "type": "date", "format": "%Y'); --"}],
        "cast mode": [{"source": "id", "cast_mode": "explode"}],
        "protect kind": [{"source": "id", "protect": {"kind": "encrypt"}}],
        "mask char": [{"source": "email", "protect": {"kind": "mask", "char": "**"}}],
        "mask range": [{"source": "email", "protect": {"kind": "mask", "keep_first": 99}}],
        "numeric default": [{"source": "id", "type": "integer", "default": "1); DROP TABLE t; --"}],
        "default needs type": [{"source": "id", "default": "x"}],
        "nothing left": [{"source": "id", "include": False}, {"source": "email", "include": False}],
    }
    for label, cols in bad.items():
        only = label == "nothing left"
        with pytest.raises(colmap.ColmapError):
            colmap.compile_select("SELECT * FROM t", avail, cols, only_listed=not only and False)
    with pytest.raises(colmap.ColmapError):
        colmap.compile_select("SELECT * FROM t", avail, [], False)
    with pytest.raises(colmap.ColmapError):
        colmap.normalize_entries("not a list")


def test_hostile_text_stays_data(con):
    # a column called  we"ird  and a default full of quotes: both become plain data, never SQL
    con.execute('CREATE TABLE w AS SELECT NULL::VARCHAR AS "we""ird", 1 AS n')
    hostile = "x'); DROP TABLE t; --"
    _, rows, names = compile_run(con, [{"source": 'we"ird', "default": hostile}], source="SELECT * FROM w")
    assert names[0] == 'we"ird' and rows[0][0] == hostile
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 4
    _, rows, _ = compile_run(con, [{"source": "id", "protect": {"kind": "redact", "text": hostile}}])
    assert rows[0][0] == hostile and con.execute("SELECT count(*) FROM t").fetchone()[0] == 4


# ---- cast and fill ------------------------------------------------------------------------------------------------

def test_cast_null_vs_fail_and_failure_counts(con):
    cm, rows, _ = compile_run(con, [{"source": "amt", "type": "integer"}], True)
    assert [r[0] for r in rows] == [12, None, 7, None]                    # 'zz' → NULL, real NULL stays NULL
    assert cm.columns[0]["type"] == "INTEGER"
    n = con.execute(colmap.failing_count_sql("SELECT * FROM t", cm.cast_checks)).fetchone()
    assert n == (1,)                                                        # only 'zz' is a failed conversion
    assert cm.cast_checks[0][:3] == ("amt", "INTEGER", "null")
    strict = colmap.compile_select("SELECT * FROM t", {"amt": "VARCHAR"}, [{"source": "amt", "type": "integer",
                                                                           "cast_mode": "fail"}], True)
    assert strict.cast_checks[0][2] == "fail"
    with pytest.raises(duckdb.Error):
        con.execute(strict.select_sql).fetchall()                          # strict CAST really raises


def test_decimal_double_boolean_and_date_format(con):
    con.execute("CREATE TABLE n AS SELECT * FROM (VALUES ('1.239','true'),('x','0')) v(a,b)")
    _, rows, _ = compile_run(con, [{"source": "a", "type": "decimal(10,2)"}, {"source": "b", "type": "boolean"}], True,
                             source="SELECT * FROM n")
    assert str(rows[0][0]) == "1.24" and rows[0][1] is True and rows[1][0] is None and rows[1][1] is False
    cm, rows, _ = compile_run(con, [{"source": "d", "type": "date", "format": "%d/%m/%Y"}], True)
    assert [str(r[0]) for r in rows] == ["2026-10-31", "2026-11-01", "None", "None"]
    assert con.execute(colmap.failing_count_sql("SELECT * FROM t", cm.cast_checks)).fetchone() == (1,)   # only 'bad'


def test_fill_empty_values(con):
    _, rows, _ = compile_run(con, [{"source": "amt", "type": "integer", "default": "0"},
                                   {"source": "note", "default": "n/a"},
                                   {"source": "card", "default": "none"}], True)
    assert [r[0] for r in rows] == [12, 0, 7, 0]                           # NULLs and the failed 'zz' get the default
    assert [r[1] for r in rows] == ["a", "n/a", "c", "n/a"]                # text: '' and blanks count as empty too
    assert rows[1][2] == "none" and rows[0][2] == "4111111111111111"


# ---- protection ---------------------------------------------------------------------------------------------------

def test_mask(con):
    _, rows, _ = compile_run(con, [
        {"source": "card", "name": "c4", "protect": {"kind": "mask", "keep_last": 4}},
        {"source": "email", "protect": {"kind": "mask", "keep_first": 1, "email": True}},
        {"source": "note", "name": "n", "protect": {"kind": "mask", "keep_first": 1, "keep_last": 1, "char": "#"}}], True)
    assert rows[0][0] == "************1111" and rows[2][0] == "************0004"
    assert rows[1][0] is None                                               # NULL stays NULL
    assert rows[3][0] == "**"                                               # too short to show anything: fully masked
    assert rows[0][1] == "j*******@example.com" and rows[1][1] == "*@y.org"  # keeps the domain, one letter
    assert rows[3][1] == "p*********"                                       # not an email → generic mask (first char)
    assert rows[0][2] == "#" and rows[2][2] == "#"                          # 1 char <= keep_first+keep_last: fully masked
    assert rows[3][2] == " # "                                              # 3 chars: first and last kept, middle masked
    # short value fully masked even when keep_* would cover it
    _, rows, _ = compile_run(con, [{"source": "id", "protect": {"kind": "mask", "keep_first": 2, "keep_last": 2}}], True)
    assert [r[0] for r in rows] == ["*", "*", "*", "*"]


def test_hash_is_deterministic_salted_and_keeps_nulls(con):
    cols = [{"source": "email", "protect": {"kind": "hash", "salt": "pepper", "length": 16}}]
    _, a, _ = compile_run(con, cols, True)
    _, b, _ = compile_run(con, cols, True)
    _, c, _ = compile_run(con, [{"source": "email", "protect": {"kind": "hash", "salt": "other", "length": 16}}], True)
    assert a == b and a != c and len(a[0][0]) == 16 and a[2][0] is None
    assert a[0][0] != a[1][0]
    import hashlib

    assert a[0][0] == hashlib.sha256(b"pepper|john.doe@example.com").hexdigest()[:16]


def test_redact_and_nullify(con):
    cm, rows, _ = compile_run(con, [{"source": "email", "protect": {"kind": "redact"}},
                                    {"source": "amt", "type": "integer", "protect": {"kind": "nullify"}}], True)
    assert [r[0] for r in rows] == ["[REDACTED]", "[REDACTED]", None, "[REDACTED]"]
    assert all(r[1] is None for r in rows)
    assert [c["type"] for c in cm.columns] == ["VARCHAR", "INTEGER"]       # nullify keeps the column's type


def test_shuffle_keeps_the_values_but_moves_them(con):
    con.execute("CREATE TABLE big AS SELECT i AS id, 'name' || i AS name, i * 10 AS score FROM range(1000) r(i)")
    cols = [{"source": "id"}, {"source": "name", "protect": {"kind": "shuffle"}},
            {"source": "score", "protect": {"kind": "shuffle"}}]
    cm, rows, names = compile_run(con, cols, True, source="SELECT * FROM big")
    assert cm.uses_shuffle and names == ["id", "name", "score"] and len(rows) == 1000
    assert sorted(r[1] for r in rows) == sorted(f"name{i}" for i in range(1000))      # same multiset
    assert sorted(r[2] for r in rows) == [i * 10 for i in range(1000)]
    assert [r[0] for r in rows].count(None) == 0
    moved = sum(1 for r in rows if r[1] != f"name{r[0]}")
    assert moved > 900                                                                 # a real permutation
    assert sum(1 for r in rows if r[2] != r[0] * 10) > 900
    assert sum(1 for r in rows if int(r[1][4:]) != r[2] // 10) > 900                  # each column shuffled on its own
    # seeded → repeatable, a different seed → a different order
    def seeded(seed):
        cols2 = [{"source": "id"}, {"source": "name", "protect": {"kind": "shuffle", "seed": seed}}]
        return dict(compile_run(con, cols2, True, "SELECT * FROM big")[1])         # id → shuffled name

    assert seeded("s") == seeded("s") and seeded("s") != seeded("z")


def test_shuffle_with_nulls_and_one_row(con):
    _, rows, _ = compile_run(con, [{"source": "email", "protect": {"kind": "shuffle"}}], True)
    assert sorted(map(str, (r[0] for r in rows))) == sorted(map(str, ["john.doe@example.com", "a@y.org", None, "plain text"]))


# ---- what gets stored / shown -------------------------------------------------------------------------------------

COLS = [{"source": "email", "name": "mail", "protect": {"kind": "hash", "salt": "S3CR3T"}},
        {"source": "id", "protect": {"kind": "shuffle", "seed": "SEED"}, "default": "7", "type": "integer"},
        {"source": "amt", "type": "integer", "default": "0"},
        {"source": "note", "include": False}]


def test_summary_and_templates_never_hold_secrets():
    blob = json.dumps(colmap.public_summary(COLS, True)) + json.dumps(colmap.template_columns(COLS))
    for secret in ("S3CR3T", "SEED"):
        assert secret not in blob
    summary = colmap.public_summary(COLS, True)
    assert summary["only_listed"] is True and [c["name"] for c in summary["columns"]] == ["mail", "id", "amt"]
    assert summary["columns"][0]["protect"] == "hash" and "default" not in json.dumps(summary)
    tpl = colmap.template_columns(COLS)
    assert "default" not in tpl[1] and tpl[2]["default"] == "0"           # a protected column's default is dropped
    clean, secrets = colmap.split_secrets(COLS)
    assert "S3CR3T" not in json.dumps(clean) and "SEED" not in json.dumps(clean)
    assert secrets == {"0": {"salt": "S3CR3T"}, "1": {"seed": "SEED"}}
    assert colmap.merge_secrets(clean, secrets)[0]["protect"]["salt"] == "S3CR3T"
    assert COLS[0]["protect"]["salt"] == "S3CR3T"                          # the input is not modified


def test_suggest_protection():
    s = colmap.suggest_protection
    assert s("email_address", [])["params"]["email"] is True
    assert s("contact", ["a@b.com", "c@d.org"])["reason"].endswith("email address")
    assert s("uidai", [])["params"]["keep_last"] == 4 and s("x", ["1234 5678 9012", "123456789012"])["reason"].startswith("looks like an Aadhaar")
    assert s("pan_no", [])["kind"] == "mask" and s("tax", ["ABCDE1234F"])["reason"] == "looks like a PAN"
    assert s("cc", ["4111 1111 1111 1111"])["reason"] == "looks like a card number"
    assert s("mobile", [])["params"]["keep_last"] == 2
    assert s("Customer_Name", [])["kind"] == "shuffle" and s("firstName", [])["kind"] == "shuffle"
    assert s("home_address", [])["kind"] == "redact" and s("dob", [])["kind"] == "shuffle"
    assert s("password", [])["kind"] == "redact"
    for plain in ("amount", "product_name", "order_id", "created_at", "region"):
        assert s(plain, ["10", "20"]) is None, plain


# ---- templates (the colmaps table) --------------------------------------------------------------------------------

@pytest.fixture
def templates(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    q = _tool("query")
    store = SqlStore("data_lake", sqlite_path=tmp_path / "dl.db", ddl=q._SCHEMA, backend="sqlite")
    monkeypatch.setattr(q, "STORE", store)
    monkeypatch.setattr(q, "_connect", store.connect)
    store.init()
    return colmap


def test_template_roundtrip_drops_secrets(templates):
    saved = templates.save_template("sales export", COLS, only_listed=True)
    again = templates.save_template("sales export", COLS[:1])                 # same name replaces
    lst = templates.list_templates()
    assert len(lst) == 1 and lst[0]["id"] == saved["id"] == again["id"] and lst[0]["only_listed"] is False
    assert "S3CR3T" not in json.dumps(lst) and lst[0]["columns"][0]["protect"] == {"kind": "hash"}
    with pytest.raises(colmap.ColmapError):
        templates.save_template("", COLS)
    with pytest.raises(colmap.ColmapError):
        templates.save_template("bad", [{"nosource": 1}])
    templates.delete_template(saved["id"])
    assert templates.list_templates() == []


# ---- the loader ---------------------------------------------------------------------------------------------------

class Ctx:
    def __init__(self):
        self.cancel, self.progress, self.lines = threading.Event(), {}, []

    def log(self, level, msg, *_):
        self.lines.append((level, msg))

    def text(self):
        return "\n".join(m for _, m in self.lines)


@pytest.fixture
def L(tmp_path, monkeypatch):
    from core import lake
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore

    sources, loader = _tool("sources"), _tool("loader")
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "lakefiles"))
    monkeypatch.setattr(lake, "_ready", False)
    monkeypatch.setattr(lake, "scoped", lambda plugin: lake.ScopedLake(plugin, "write"))
    root = tmp_path / "data"
    root.mkdir()
    (root / "people.csv").write_text(
        "id,full_name,email,age,joined,notes\n1,Asha Rao,asha@example.com,31,03/01/2026,\n"
        "2,Ravi Iyer,ravi@example.com,not-a-number,04/01/2026,vip\n3,Mei Lin,,45,05/01/2026,\n")
    monkeypatch.setattr(sources, "ROOT", root)
    monkeypatch.setattr(sources, "STAGE", FileCache("data-lake", tmp_path / "stage"))
    monkeypatch.setattr(loader, "_secret_store", lambda: None)             # no Redis in unit tests
    return lake


def load(spec):
    ctx = Ctx()
    _tool("loader").run_load(ctx, {"source": {"kind": "folder", "pattern": "people.csv"}, "workspace": "w",
                                   "table": "people", "mode": "create", **spec})
    return ctx


def test_load_with_a_column_map(L):
    cols = [{"source": "id"}, {"source": "full_name", "name": "customer", "protect": {"kind": "shuffle", "seed": "k"}},
            {"source": "email", "protect": {"kind": "mask", "keep_first": 1, "email": True}, "default": "x"},
            {"source": "age", "type": "integer", "default": "0"},
            {"source": "joined", "type": "date", "format": "%d/%m/%Y"},
            {"source": "notes", "include": False}]
    ctx = load({"columns": cols, "only_listed": True})
    assert ctx.progress["phase"] == "done", ctx.text()
    t = L.get_table("w", "people")
    assert [c["name"] for c in t["columns"]] == ["id", "customer", "email", "age", "joined"]
    assert [c["type"] for c in t["columns"]] == ["BIGINT", "VARCHAR", "VARCHAR", "INTEGER", "DATE"]
    rows = sorted(L.preview("w", "people", 10)["rows"], key=lambda r: r[0])
    assert [r[3] for r in rows] == [31, 0, 45]                                   # 'not-a-number' → NULL → default 0
    assert sorted(r[1] for r in rows) == ["Asha Rao", "Mei Lin", "Ravi Iyer"]
    assert rows[0][2] == "a***@example.com" and rows[2][2] == "*"          # NULL → default 'x' → then masked
    assert str(rows[0][4]) == "2026-01-03"
    assert ctx.progress["warnings"] == [{"column": "age", "type": "integer", "count": 1}]
    assert {(p["name"], p["kind"]) for p in ctx.progress["protected"]} == {("customer", "shuffle"), ("email", "mask")}
    assert any(lvl == "warn" and "`age`" in m for lvl, m in ctx.lines)
    # what the catalog remembers: names and kinds — no salts, seeds, defaults
    stored = json.dumps(t["source"])
    assert "column_map" in stored and '"k"' not in stored and '"x"' not in stored and "protect" in stored
    assert t["source"]["column_map"]["only_listed"] is True
    log = ctx.text()
    assert "asha@" not in log and "Asha" not in log


def test_strict_cast_stops_before_anything_is_written(L):
    ctx = load({"columns": [{"source": "age", "type": "integer", "cast_mode": "fail"}], "only_listed": True})
    assert ctx.progress["phase"] == "failed" and "'age'" in ctx.progress["error"] and "strict" in ctx.progress["error"]
    assert "not-a-number" not in ctx.progress["error"] + ctx.text()               # the bad value is never quoted
    with pytest.raises(L.NotFound):
        L.get_table("w", "people")


def test_pass_through_when_not_only_listed_and_append_by_name(L):
    ctx = load({"columns": [{"source": "id", "name": "pid"}]})
    assert ctx.progress["phase"] == "done"
    assert [c["name"] for c in L.get_table("w", "people")["columns"]] == ["pid", "full_name", "email", "age", "joined", "notes"]
    ctx = load({"mode": "append", "columns": [{"source": "id", "name": "pid"}]})
    assert ctx.progress["phase"] == "done" and L.get_table("w", "people")["row_count"] == 6


def test_bad_map_fails_clearly_and_external_refuses_a_map(L):
    ctx = load({"columns": [{"source": "nope"}]})
    assert ctx.progress["phase"] == "failed" and "nope" in ctx.progress["error"]
    ctx = load({"columns": [{"source": "id"}], "external": True})
    assert ctx.progress["phase"] == "failed" and "read-in-place" in ctx.progress["error"]
    with pytest.raises(L.NotFound):
        L.get_table("w", "people")


def test_worker_side_secret_handoff(L, monkeypatch):
    loader = _tool("loader")
    kept = {}

    class Store:
        def get(self, k):
            return kept.get(k)

        def set(self, k, v):
            kept[k] = v

        def delete(self, k):
            kept.pop(k, None)

    monkeypatch.setattr(loader, "_secret_store", lambda: Store())
    cols = [{"source": "email", "protect": {"kind": "hash", "salt": "PEPPER"}}]
    clean, secrets = colmap.split_secrets(cols)
    assert loader.stash_secrets("job1", secrets) and "PEPPER" in json.dumps(kept)
    assert "PEPPER" not in json.dumps(clean)
    ctx = load({"columns": clean, "secrets_ref": "job1", "only_listed": True})
    assert ctx.progress["phase"] == "done", ctx.text()
    assert kept == {}                                                              # taken and deleted
    h = L.preview("w", "people", 10)["rows"]
    import hashlib

    assert hashlib.sha256(b"PEPPER|asha@example.com").hexdigest() in [r[0] for r in h]
    assert "PEPPER" not in json.dumps(L.get_table("w", "people")["source"])
    # an expired side channel is a clear failure, never a silently unsalted hash
    ctx = load({"table": "again", "columns": clean, "secrets_ref": "gone", "only_listed": True})
    assert ctx.progress["phase"] == "failed" and "expired" in ctx.progress["error"]


def test_masked_copy_of_an_existing_table(L):
    load({})
    ctx = Ctx()
    _tool("loader").run_copy(ctx, {"from": "w.people", "workspace": "shared", "table": "people_safe", "mode": "create",
                                   "columns": [{"source": "id"}, {"source": "email", "protect": {"kind": "redact"}},
                                               {"source": "full_name", "protect": {"kind": "hash", "salt": "s", "length": 12}}],
                                   "only_listed": True})
    assert ctx.progress["phase"] == "done", ctx.text()
    t = L.get_table("shared", "people_safe")
    assert [c["name"] for c in t["columns"]] == ["id", "email", "full_name"] and t["source"]["from"] == "w.people"
    rows = sorted(L.preview("shared", "people_safe", 10)["rows"])
    assert rows[0][1] == "[REDACTED]" and rows[2][1] is None and len(rows[0][2]) == 12      # NULL stays NULL
    assert [r[0] for r in rows] == [1, 2, 3] and L.get_table("w", "people")["row_count"] == 3   # source untouched
    ctx = Ctx()
    _tool("loader").run_copy(ctx, {"from": "w.people", "workspace": "w", "table": "people", "columns": []})
    assert ctx.progress["phase"] == "failed" and "different table" in ctx.progress["error"]


def test_inspect_source_describes_without_loading(L):
    info = _tool("loader").inspect_source({"source": {"kind": "folder", "pattern": "people.csv"}})
    assert info["format"] == "csv" and info["files"] == ["people.csv"] and info["file_count"] == 1
    cols = {c["name"]: c for c in info["columns"]}
    assert list(cols) == ["id", "full_name", "email", "age", "joined", "notes"]
    assert cols["id"]["sql_type"] == "bigint" and cols["full_name"]["samples"][0] == "Asha Rao"
    assert cols["email"]["suggestion"]["kind"] == "mask" and cols["full_name"]["suggestion"]["kind"] == "shuffle"
    assert cols["age"]["suggestion"] is None
    load({})
    again = _tool("loader").inspect_source({"source": {"kind": "table", "table": "w.people"}})
    assert again["format"] == "table" and [c["name"] for c in again["columns"]][:2] == ["id", "full_name"]
    with pytest.raises(_tool("loader").LoadError, match="No files match"):
        _tool("loader").inspect_source({"source": {"kind": "folder", "pattern": "missing/*.csv"}})
    with pytest.raises(L.LakeError):
        _tool("loader").inspect_source({"source": {"kind": "table", "table": "w.nope"}})


def test_explicit_type_reads_csv_text_raw(L, tmp_path):
    root = _tool("sources").ROOT
    (root / "zips.csv").write_text("zip,qty\n00123,5\n04567,x\n")
    ctx = load({"source": {"kind": "folder", "pattern": "zips.csv"}, "table": "zips", "only_listed": True,
                "columns": [{"source": "zip", "type": "text"}, {"source": "qty", "type": "integer"}]})
    assert ctx.progress["phase"] == "done", ctx.text()
    rows = sorted(L.preview("w", "zips", 10)["rows"])
    assert rows == [["00123", 5], ["04567", None]]                          # leading zeros kept; 'x' → NULL (warned)
    assert ctx.progress["warnings"] == [{"column": "qty", "type": "integer", "count": 1}]
    # without a map nothing changes: the quick path loads everything as the sniffer typed it
    quick = load({"source": {"kind": "folder", "pattern": "zips.csv"}, "table": "zips2"})
    assert quick.progress["phase"] == "done" and L.get_table("w", "zips2")["row_count"] == 2
    assert "column_map" not in L.get_table("w", "zips2")["source"] and "warnings" not in quick.progress
