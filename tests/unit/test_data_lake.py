"""Roadmap L2: Data Lake loading. Format detection + data-folder confinement run anywhere; the loader tests need
DuckDB (+ pandas/openpyxl for Excel) — run them inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_data_lake.py -q
"""

import gzip
import json
import os
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data-lake"))

from core.file_source import build_multi_read_expr, detect_any  # noqa: E402


def _tool(module):
    """The Data Lake's modules: package `data_lake` in the image, the `data-lake/` folder in the repo."""
    import importlib

    try:
        return importlib.import_module(f"data_lake.{module}")
    except ImportError:
        return importlib.import_module(module)


def test_detect_by_extension_and_content(tmp_path):
    cases = {"a.csv": b"x,y\n1,2\n", "b.tsv.gz": None, "c.jsonl": b'{"a":1}\n', "d.parquet": b"PAR1",
             "e.xlsx": b"PK\x03\x04", "noext_json": b'  [{"a": 1}]', "noext_xml": b"<root/>", "noext_csv": b"a;b\n1;2"}
    expect = {"a.csv": "csv", "b.tsv.gz": "csv", "c.jsonl": "json", "d.parquet": "parquet", "e.xlsx": "excel",
              "noext_json": "json", "noext_xml": "xml", "noext_csv": "csv"}
    for name, data in cases.items():
        p = tmp_path / name
        if data is None:
            with gzip.open(p, "wb") as f:
                f.write(b"a\tb\n1\t2\n")
        else:
            p.write_bytes(data)
        assert detect_any(str(p)) == expect[name], name
    (tmp_path / "blob").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError, match="Can't tell"):
        detect_any(str(tmp_path / "blob"))


def test_multi_read_expr_quotes_and_options():
    e = build_multi_read_expr(["/data/a.csv", "/data/it's.csv"], "csv", header=False, delimiter=";", with_filename=True)
    assert "['/data/a.csv', '/data/it''s.csv']" in e and "header=false" in e and "delim=';'" in e and "filename=true" in e
    assert build_multi_read_expr(["/x/*.parquet"], "parquet").startswith("read_parquet(['/x/*.parquet']")
    with pytest.raises(ValueError):
        build_multi_read_expr(["a.xml"], "xml")


@pytest.fixture
def folder(tmp_path, monkeypatch):
    sources = _tool("sources")

    root = tmp_path / "data"
    (root / "sales").mkdir(parents=True)
    (root / "sales" / "2026-01.csv").write_text("id,amount\n1,10\n2,20\n")
    (root / "sales" / "2026-02.csv").write_text("id,amount,region\n3,30,eu\n")
    (root / "sales" / ".hidden.csv").write_text("x\n")
    (tmp_path / "secret.csv").write_text("nope\n")
    os.symlink(tmp_path / "secret.csv", root / "link_out.csv")
    monkeypatch.setattr(sources, "ROOT", root)
    return sources


def test_folder_patterns_stay_inside_the_data_folder(folder):
    assert [p.name for p in folder.match("sales/*.csv")] == ["2026-01.csv", "2026-02.csv"]  # hidden skipped
    assert [p.name for p in folder.match("sales")] == ["2026-01.csv", "2026-02.csv"]         # a folder = its files
    assert folder.summary("sales/2026-0*.csv")["count"] == 2
    for bad in ("../secret.csv", "sales/../../secret.csv"):
        with pytest.raises(folder.SourceError):
            folder.match(bad)
    with pytest.raises(folder.SourceError, match="outside"):
        folder.match("link_out.csv")
    b = folder.browse("")
    assert [d["name"] for d in b["dirs"]] == ["sales"] and "link_out.csv" not in [f["name"] for f in b["files"]]


# ---- the loader (DuckDB) -----------------------------------------------------------------------------------------

class Ctx:
    def __init__(self):
        self.cancel, self.progress, self.lines = threading.Event(), {}, []

    def log(self, level, msg, *_):
        self.lines.append((level, msg))


@pytest.fixture
def L(tmp_path, monkeypatch, folder):
    pytest.importorskip("duckdb", reason="loader tests run inside the container")
    from core import lake
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore

    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "lakefiles"))
    monkeypatch.setattr(lake, "_ready", False)
    monkeypatch.setattr(lake, "scoped", lambda plugin: lake.ScopedLake(plugin, "write"))
    monkeypatch.setattr(folder, "STAGE", FileCache("data-lake", tmp_path / "stage"))
    return lake


def run(spec):
    loader = _tool("loader")

    ctx = Ctx()
    loader.run_load(ctx, spec)
    return ctx


def test_folder_pattern_becomes_one_table_with_source_file(L, folder):
    ctx = run({"source": {"kind": "folder", "pattern": "sales/*.csv"}, "workspace": "sales", "table": "monthly",
               "mode": "create", "add_filename": True})
    assert ctx.progress["phase"] == "done", ctx.lines
    t = L.get_table("sales", "monthly")
    assert t["row_count"] == 3 and [c["name"] for c in t["columns"]] == ["id", "amount", "region", "_source_file"]
    rows = L.preview("sales", "monthly", 10)["rows"]
    assert sorted((r[0], r[3]) for r in rows) == [(1, "2026-01.csv"), (2, "2026-01.csv"), (3, "2026-02.csv")]
    assert t["source"]["file_count"] == 2 and t["source"]["pattern"] == "sales/*.csv"


def test_upload_gz_jsonl_append_and_overwrite(L, folder, tmp_path):
    def stage(name, data):
        uid = folder.new_upload_id()
        p = folder.STAGE.local(folder.stage_name(uid, 0, name))
        p.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".gz"):
            with gzip.open(p, "wb") as f:
                f.write(data)
        else:
            p.write_bytes(data)
        return {"kind": "upload", "upload_id": uid, "files": [p.name]}

    src = stage("events.jsonl.gz", b'{"id":1,"ev":"a"}\n{"id":2,"ev":"b"}\n')
    assert run({"source": src, "workspace": "w", "table": "events", "mode": "create"}).progress["phase"] == "done"
    assert not list(folder.STAGE.local_dir.glob(src["upload_id"] + "*"))   # staged copy removed after success
    run({"source": stage("more.jsonl", b'{"id":3,"ev":"c"}\n'), "workspace": "w", "table": "events", "mode": "append"})
    assert L.get_table("w", "events")["row_count"] == 3
    ctx = run({"source": stage("new.jsonl", b'{"id":9,"kind":"x"}\n'), "workspace": "w", "table": "events",
               "mode": "overwrite"})
    t = L.get_table("w", "events")
    assert (t["row_count"], t["version"]) == (1, 2) and any("columns changed" in m for _, m in ctx.lines)


def test_excel_and_xml(L, folder, tmp_path):
    import pandas as pd

    pd.DataFrame({"sku": ["a", "b"], "qty": [1, 2]}).to_excel(folder.ROOT / "stock.xlsx", index=False)
    assert run({"source": {"kind": "folder", "pattern": "stock.xlsx"}, "workspace": "w", "table": "stock"}
               ).progress["phase"] == "done"
    assert L.preview("w", "stock")["rows"] == [["a", 1], ["b", 2]]
    (folder.ROOT / "items.xml").write_text("<items><item><id>1</id></item><item><id>2</id></item></items>")
    ctx = run({"source": {"kind": "folder", "pattern": "items.xml"}, "workspace": "w", "table": "items"})
    assert ctx.progress["phase"] == "done", ctx.lines and L.get_table("w", "items")["row_count"] == 2


def test_external_table_reads_in_place(L, folder):
    ctx = run({"source": {"kind": "folder", "pattern": "sales/2026-01.csv"}, "workspace": "ext", "table": "jan",
               "external": True})
    t = L.get_table("ext", "jan")
    assert ctx.progress["phase"] == "done" and (t["kind"], t["row_count"], t["parts"]) == ("external", 2, 0)
    (folder.ROOT / "sales" / "2026-01.csv").write_text("id,amount\n1,10\n2,20\n5,50\n")
    assert len(L.preview("ext", "jan")["rows"]) == 3  # read in place: the change shows up


def test_clear_errors(L, folder):
    (folder.ROOT / "mix.json").write_text('{"a":1}')
    (folder.ROOT / "mix.csv").write_text("a\n1\n")  # (the link pointing outside is skipped by the pattern)
    ctx = run({"source": {"kind": "folder", "pattern": "*.*"}, "workspace": "w", "table": "mixed"})
    assert ctx.progress["phase"] == "failed" and "different formats" in ctx.progress["error"]
    ctx = run({"source": {"kind": "folder", "pattern": "nothing/*.csv"}, "workspace": "w", "table": "x"})
    assert ctx.progress["phase"] == "failed" and "No files match" in ctx.progress["error"]
