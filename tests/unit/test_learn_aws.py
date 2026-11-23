"""Learn AWS: notes index in study order, search, practice questions, path safety, static-page guards. Host test: loads the server file directly."""
import importlib.util
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "learn-aws"


def _load():
    spec = importlib.util.spec_from_file_location("learn_aws_server", TOOL / "server.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


srv = _load()
client = TestClient(srv.app)


def test_every_note_is_indexed_and_author_files_are_not():
    on_disk = {p.relative_to(TOOL / "notes").as_posix() for p in (TOOL / "notes").rglob("*.md")}
    assert on_disk == set(srv.INDEX["notes"]) and len(on_disk) > 150
    assert all(n["title"] for n in srv.INDEX["notes"].values())
    assert not {Path(p).name for p in srv.INDEX["notes"]} & {"CLAUDE.md", "PLAN.md", "TEMPLATE.md"}
    assert not [p for p in srv.INDEX["notes"] if p.startswith(("mcq/", "web/", "exam/"))]


def test_study_order_follows_the_folder_numbers():
    cats = srv.INDEX["tree"]["categories"]
    ids = [c["id"] for c in cats]
    assert ids == sorted(ids, key=srv._natural) and ids[0].startswith("01-")
    assert cats[0]["name"] == "Governance and Security"                       # the number is not part of the name
    for c in cats:
        sids = [s["id"] for s in c["services"]]
        assert sids == sorted(sids, key=srv._natural), c["id"]
        for s in c["services"]:
            nums = [int(f["path"].rsplit("/", 1)[1].split("-")[0]) for f in s["files"] if f["path"].rsplit("/", 1)[1].split("-")[0].isdigit()]
            assert nums == sorted(nums), s["id"]
    assert srv._natural("2-a.md") < srv._natural("10-a.md")


def test_note_returns_text_and_refuses_anything_unknown():
    path = next(iter(srv.INDEX["notes"]))
    assert client.get("/note", params={"path": path}).json()["text"]
    for bad in ["../server.py", "/etc/passwd", "..%2f..%2fserver.py", "03-storage/../../server.py", "nope.md", ""]:
        assert client.get("/note", params={"path": bad}).status_code in (404, 422), bad


def test_search_needs_all_words_and_is_bounded():
    assert client.get("/search", params={"q": "s3 lifecycle"}).json()["results"]
    assert client.get("/search", params={"q": "s3 zzzqqqxxx"}).json()["results"] == []
    r = client.get("/search", params={"q": "the"}).json()
    assert len(r["results"]) <= srv.MAX_RESULTS
    assert client.get("/search", params={"q": "x" * 500}).status_code == 422
    assert client.get("/search", params={"query": "s3 lifecycle"}).json()["results"]   # the AI action's input name


def test_question_files_mirror_the_notes_repo_and_match_a_service():
    files = {p.relative_to(TOOL / "mcq").with_suffix("").as_posix() for p in (TOOL / "mcq").rglob("*.json")}
    assert files == set(srv.MCQ) and files
    services = {f"{c['id']}/{s['id']}" for c in srv.INDEX["tree"]["categories"] for s in c["services"]}
    assert files <= services                                                   # every question file belongs to a real service folder


def test_every_question_is_well_formed():
    ids = []
    for key, qs in srv.MCQ.items():
        for q in qs:
            ids.append(q["id"])
            assert 3 <= len(q["options"]) <= 6 and all(o.get("t") and o.get("why") for o in q["options"]), q["id"]
            assert q["answer"] and all(0 <= i < len(q["options"]) for i in q["answer"]), q["id"]
            if q.get("source"):
                assert f"{key}/{q['source']}" in srv.INDEX["notes"], q["id"]   # the "open the notes" link works
    assert len(ids) == len(set(ids)) and len(ids) >= 100


def test_question_counts_reach_the_tree_and_the_api():
    t = client.get("/tree").json()
    assert t["questions"] == sum(len(v) for v in srv.MCQ.values())
    s3 = next(s for c in t["categories"] for s in c["services"] if s["id"].endswith("-s3"))
    assert s3["questions"] >= 30
    one = client.get("/mcq/questions", params={"service": "03-storage/01-s3"}).json()
    assert one["count"] == s3["questions"] and all(q["service"] == "03-storage/01-s3" for q in one["questions"])
    assert client.get("/mcq/questions", params={"service": "ALL"}).json()["count"] == t["questions"]
    for bad in ["../../etc/passwd", "03-storage", "nope/x", "03-storage/01-s3.json"]:
        assert client.get("/mcq/questions", params={"service": bad}).status_code == 404, bad


def test_page_never_injects_html_and_keeps_its_rules():
    page = (TOOL / "ui" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", page)
    assert not re.search(r"fetch\(\s*[\"'`]/", page) and page.count("fetch(") == 1
    assert page.count("localStorage.") == 2 and set(re.findall(r'localStorage\.\w+\("([^"]+)"', page)) == {"learnAws."}
    assert set(re.findall(r'store\(\s*"([^"]+)"', page)) <= {"last", "theme", "fs", "quiz"}


def test_docker_image_carries_notes_and_questions():
    d = (ROOT / "Dockerfile").read_text()
    assert "COPY learn-aws/notes/ ./learn_aws/notes/" in d and "COPY learn-aws/mcq/ ./learn_aws/mcq/" in d
