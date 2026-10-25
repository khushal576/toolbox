"""Roadmap D1: DataDiff as a shared API + client. The live two-replica check is in the D1 handoff."""

import datetime as dt
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api.app import app  # noqa: E402
from core.clients import datadiff as dd  # noqa: E402

LEFT = '[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]'
RIGHT = '[{"id": 1, "name": "a"}, {"id": 2, "name": "B"}]'
ROWS_L = [{"id": 1, "amount": Decimal("1.10"), "day": dt.date(2026, 1, 2), "ref": uuid.UUID(int=7), "raw": b"\x00\xff"},
          {"id": 2, "amount": Decimal("5.00"), "day": dt.date(2026, 1, 3), "ref": uuid.UUID(int=8), "raw": b"x"}]
ROWS_R = [{"id": 1, "amount": Decimal("1.10"), "day": dt.date(2026, 1, 2), "ref": uuid.UUID(int=7), "raw": b"\x00\xff"},
          {"id": 2, "amount": Decimal("5.01"), "day": dt.date(2026, 1, 3), "ref": uuid.UUID(int=8), "raw": b"x"}]
client = TestClient(app)


def test_codec_round_trips_database_values():
    v = {"a": [Decimal("1.10"), dt.datetime(2026, 1, 2, 3, 4, 5), dt.time(1, 2), dt.timedelta(seconds=90),
               uuid.UUID(int=1), b"\x01", None, True, 3, 2.5, "s", {"n": Decimal("-0.001")}]}
    enc = dd.encode_value(v)
    import json

    assert dd.decode_value(json.loads(json.dumps(enc))) == v
    assert dd.decode_value({"__dd__": "decimal", "v": "1", "extra": 1}) == {"__dd__": "decimal", "v": "1", "extra": 1}


def test_v1_compare_equals_the_old_path():
    body = {"left_data": LEFT, "right_data": RIGHT, "left_format": "json", "right_format": "json"}
    a, b = client.post("/api/v1/compare", json=body).json(), client.post("/compare", json=body).json()
    assert a["ok"] and a["summary"] == b["summary"] and a["records"] == b["records"]


def test_errors_use_the_same_envelope():
    r = client.post("/api/v1/compare", json={"left_data": "{", "right_data": "{}", "left_format": "json",
                                             "right_format": "json"})
    assert r.status_code == 422 and r.json()["ok"] is False and "Left side" in r.json()["error"]
    r = client.post("/api/v1/compare/structured", json={"left": [], "right": [], "mapper_direction": "sideways"})
    assert r.status_code == 422 and "mapper_direction" in r.json()["error"]


def test_structured_compare_over_http_equals_in_process(monkeypatch):
    local = dd.DataDiffClient(base_url="").compare_data(ROWS_L, ROWS_R)

    def fake_post(url, json, timeout):  # route the client's HTTP call into the app
        return client.post(url.split("/tools/datadiff-pro", 1)[-1], json=json)

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    remote = dd.DataDiffClient(base_url="http://rt-datadiff:8080/tools/datadiff-pro").compare_data(ROWS_L, ROWS_R)
    assert remote["summary"] == local["summary"] and remote["records"] == local["records"]
    assert any("5.01" in str(r) for r in remote["records"])  # Decimal arrived as Decimal, came back as text


def test_client_raises_datadiff_error_and_rejects_unknown_options():
    with pytest.raises(dd.DataDiffError, match="Left side"):
        dd.DataDiffClient(base_url="").compare_text("{", "{}", "json", "json")
    with pytest.raises(TypeError, match="unknown DataDiff option"):
        dd.DataDiffClient(base_url="").compare_data([], [], strictmode=True)


def test_openapi_documents_the_v1_api():
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/compare", "/api/v1/compare/structured", "/api/v1/health"} <= set(paths)
    assert "/compare" not in paths  # the alias works but isn't advertised


def test_only_datadiff_itself_imports_its_engine():
    """Roadmap D1: other code goes through core/clients/datadiff.py."""
    for py in REPO.rglob("*.py"):
        rel = py.relative_to(REPO)
        if rel.parts[0] in ("api", "tests", "notebook") or rel.parts[:2] in (("core", "pipeline.py"), ("core", "clients")):
            continue
        if rel.parts[0] == "core" and rel.name != "pipeline.py":
            continue  # the engine's own modules
        text = py.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"from core\.pipeline import|import core\.pipeline|from core import pipeline", text), rel


# ---- roadmap D2: background jobs (thread mode + local files here; queue + S3 verified live) --------------------

@pytest.fixture
def local_jobs(tmp_path, monkeypatch):
    from api import jobs
    from core.jobs.runner import JobRunner
    from core.state.filecache import FileCache

    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    monkeypatch.setattr(jobs, "FILES", FileCache("datadiff", tmp_path))
    monkeypatch.setattr(jobs, "JOBS", JobRunner("datadiff", log_size=50, mode="thread"))
    return jobs


def _wait(job_id, timeout=10):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get(f"/api/v1/jobs/{job_id}").json()
        if st["status"] in ("done", "failed", "cancelled"):
            return st
        time.sleep(0.05)
    raise AssertionError(f"job still {st['status']}")


def test_job_runs_in_background_and_returns_the_same_result(local_jobs):
    body = {"left_data": LEFT, "right_data": RIGHT, "left_format": "json", "right_format": "json"}
    r = client.post("/api/v1/jobs", json={"type": "compare", **body})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    job = r.json()["job_id"]
    st = _wait(job)
    assert st["status"] == "done" and st["summary"]["MISMATCH"] == 1 and st["result_bytes"] > 0
    res = client.get(f"/api/v1/jobs/{job}/result")
    sync = client.post("/api/v1/compare", json=body).json()
    assert res.json()["records"] == sync["records"] and res.json()["meta"]["left_format"] == "json"
    assert not list(local_jobs.FILES.local_dir.glob(f"{job}.input*"))  # the input is gone after the run


def test_structured_job_keeps_database_values(local_jobs):
    job = dd.DataDiffClient(base_url="").submit_data(ROWS_L, ROWS_R)
    result = dd.DataDiffClient(base_url="").wait(job, timeout=10, poll=0.05)
    assert result["summary"] == dd.DataDiffClient(base_url="").compare_data(ROWS_L, ROWS_R)["summary"]


def test_job_errors_unknown_ids_and_early_result(local_jobs):
    bad = client.post("/api/v1/jobs", json={"type": "compare", "left_data": "{", "right_data": "{}",
                                           "left_format": "json", "right_format": "json"}).json()["job_id"]
    st = _wait(bad)
    assert st["status"] == "failed" and "Left side" in st["error"]
    assert client.get(f"/api/v1/jobs/{bad}/result").status_code == 409
    assert client.get("/api/v1/jobs/nope").status_code == 404
    assert client.post("/api/v1/jobs", json={"type": "magic"}).status_code == 422
    assert client.post("/api/v1/jobs", json={"type": "compare", "left_data": " ", "right_data": "x",
                                            "left_format": "json", "right_format": "json"}).status_code == 422


def test_deleting_a_finished_job_deletes_its_result(local_jobs):
    job = client.post("/api/v1/jobs", json={"type": "compare", "left_data": LEFT, "right_data": RIGHT,
                                           "left_format": "json", "right_format": "json"}).json()["job_id"]
    assert _wait(job)["status"] == "done"
    r = client.delete(f"/api/v1/jobs/{job}").json()
    assert r["cancelled"] is False and r["result_deleted"] is True
    assert client.get(f"/api/v1/jobs/{job}/result").status_code == 410
