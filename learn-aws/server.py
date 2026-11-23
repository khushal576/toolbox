"""
Learn AWS — serves the plain-English AWS service notes (learn-aws/notes/, copied from the learn-aws-services repo by sync.py).

Read-only: nothing is stored, nothing is written, no secrets. The notes are loaded once at start-up into an in-memory INDEX; that is a read-only cache
of files baked into the image, not request state, so it does not break the "no state in process memory" rule.
Endpoints (the page uses relative paths): GET /tree · GET /note?path= · GET /search?q= · GET /health.
A note path must be one the index already knows (so '..' or absolute paths can never read anything else).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Learn AWS")

HERE = Path(__file__).resolve().parent
UI_PATH = HERE / "ui" / "index.html"
NOTES = HERE / "notes"
MCQ_DIR = HERE / "mcq"
MAX_RESULTS = 40
TAGS = re.compile(r"</?(?:details|summary)>")
WORD = re.compile(r"[a-z0-9][a-z0-9.\-_]*")


def _title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


ACRONYMS = {"s3", "ebs", "efs", "rds", "sqs", "sns", "dms", "iam", "sts", "kms", "waf", "vpc", "emr", "mwaa", "msk", "ecs", "eks", "ecr", "cli", "ci", "cd",
            "sam", "cdk", "ec2", "ai", "aws", "dns", "nat", "api", "bi"}


def _pretty(slug: str) -> str:
    """'rds-and-aurora' -> 'RDS and Aurora'; 'monitoring-and-cost' -> 'Monitoring and Cost'."""
    slug = re.sub(r"^\d+-", "", slug)                          # folder numbers ('03-storage') only set the order, they are not part of the name
    words = slug.replace("_", "-").split("-")
    return " ".join(w.upper() if w in ACRONYMS else (w if w == "and" else w.capitalize()) for w in words)


def _service_name(sid: str, first_title: str) -> str:
    """The title's own wording ('DynamoDB') when the folder is a single service; a tidy folder name for combined folders ('RDS and Aurora')."""
    sid = re.sub(r"^\d+-", "", sid)
    head = first_title.split(" – ")[0].strip()
    head = re.sub(r"^Amazon\s+", "", head)
    if "-and-" in sid or "," in head or " and " in head or len(head) > 32 or not head:
        return _pretty(sid)
    return head


def _natural(name: str):
    """'2-x.md' < '10-x.md': split digits from text so numbers sort as numbers."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _readme_order(text: str, pattern: str) -> list[str]:
    """Names in the order the owner listed them in a README (category links / service-folder table rows)."""
    return list(dict.fromkeys(re.findall(pattern, text, flags=re.M)))


def _ordered(ids, wanted: list[str]) -> list[str]:
    """Follow the README order; anything it does not mention goes after, in natural order."""
    ids = list(ids)
    first = [w for w in wanted if w in ids]
    return first + sorted((i for i in ids if i not in first), key=_natural)


def _load() -> dict:
    notes: dict[str, dict] = {}
    if NOTES.is_dir():
        for p in sorted(NOTES.rglob("*.md")):
            rel = p.relative_to(NOTES).as_posix()
            text = p.read_text(encoding="utf-8")
            notes[rel] = {"path": rel, "title": _title_of(text, p.stem), "text": text, "lower": text.lower()}
    cats: dict[str, dict] = {}
    for rel, n in notes.items():
        parts = rel.split("/")
        if len(parts) == 3:                                   # category/service/file.md
            cat = cats.setdefault(parts[0], {"id": parts[0], "name": _pretty(parts[0]), "readme": None, "services": {}})
            svc = cat["services"].setdefault(parts[1], {"id": parts[1], "name": _pretty(parts[1]), "files": []})
            svc["files"].append({"path": rel, "title": n["title"]})
        elif len(parts) == 2 and parts[1] == "README.md":
            cats.setdefault(parts[0], {"id": parts[0], "name": _pretty(parts[0]), "readme": None, "services": {}})["readme"] = rel
    root = notes.get("README.md", {}).get("text", "")
    cat_order = _ordered(cats, _readme_order(root, r"^- \[[^\]]+\]\(\./([a-z0-9-]+)/README\.md\)"))
    out_cats = []
    for cid in cat_order:
        c = cats[cid]
        readme = notes.get(c["readme"], {}).get("text", "") if c["readme"] else ""
        svc_order = _ordered(c["services"], _readme_order(readme, r"^\|\s*`([a-z0-9-]+)/`"))
        services = []
        for sid in svc_order:
            s = c["services"][sid]
            s["files"].sort(key=lambda f: _natural(f["path"].rsplit("/", 1)[1]))
            s["name"] = _service_name(sid, s["files"][0]["title"])
            services.append(s)
        out_cats.append({"id": cid, "name": c["name"], "readme": c["readme"], "services": services})
    tree = {
        "categories": out_cats,
        "extras": [{"path": p, "title": notes[p]["title"]} for p in ("README.md", "EXAM-COVERAGE.md") if p in notes],
    }
    return {"notes": notes, "tree": tree}


def _load_mcq() -> dict[str, list[dict]]:
    """mcq/<category>/<service>.json -> {"category/service": [question, ...]} (the same path as the service folder, as in the notes repo)."""
    out: dict[str, list[dict]] = {}
    if MCQ_DIR.is_dir():
        for p in sorted(MCQ_DIR.rglob("*.json")):
            key = p.relative_to(MCQ_DIR).with_suffix("").as_posix()
            qs = []
            for q in json.loads(p.read_text(encoding="utf-8")).get("questions", []):
                if not (isinstance(q.get("q"), str) and q.get("options") and q.get("answer")):
                    continue                                     # the notes repo's build already rejects bad files; never serve a half question
                qs.append({**q, "service": key})
            out[key] = qs
    return out


INDEX = _load()
MCQ = _load_mcq()
for _c in INDEX["tree"]["categories"]:
    for _s in _c["services"]:
        _s["questions"] = len(MCQ.get(f"{_c['id']}/{_s['id']}", []))
INDEX["tree"]["questions"] = sum(len(v) for v in MCQ.values())


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "tool": "learn-aws"})


@app.get("/tree")
async def tree() -> JSONResponse:
    return JSONResponse({**INDEX["tree"], "count": len(INDEX["notes"])})


@app.get("/note")
async def note(path: str = Query(..., max_length=200)) -> JSONResponse:
    n = INDEX["notes"].get(path)
    if n is None:
        raise HTTPException(404, "No such note.")
    return JSONResponse({"path": n["path"], "title": n["title"], "text": n["text"]})


def _terms(q: str) -> list[str]:
    return list(dict.fromkeys(WORD.findall(q.lower())))[:8]


@app.get("/search")
async def search(q: str = Query("", max_length=200), query: str = Query("", max_length=200)) -> JSONResponse:
    """Every word must appear in the note. Ranked: words in the title/path > number of matching lines. Returns up to 3 matching lines per note."""
    q = q or query                                            # the page sends ?q=; the AI action (manifest `query`) sends ?query=
    terms = _terms(q)
    if not terms:
        return JSONResponse({"query": q, "results": [], "truncated": False})
    scored = []
    for n in INDEX["notes"].values():
        low = n["lower"]
        if not all(t in low for t in terms):
            continue
        head = (n["title"] + " " + n["path"]).lower()
        score = sum(10 for t in terms if t in head) + sum(low.count(t) for t in terms)
        scored.append((score, n))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    results = []
    for _score, n in scored[:MAX_RESULTS]:
        lines = [ln.strip() for ln in n["text"].splitlines() if ln.strip() and any(t in ln.lower() for t in terms)]
        lines.sort(key=lambda ln: -sum(t in ln.lower() for t in terms))
        results.append({"path": n["path"], "title": n["title"], "snippets": [TAGS.sub("", ln)[:240] for ln in lines[:3]]})
    return JSONResponse({"query": q, "results": results, "truncated": len(scored) > MAX_RESULTS, "total": len(scored)})


@app.get("/mcq/questions")
async def mcq_questions(service: str = Query("ALL", max_length=120)) -> JSONResponse:
    """Questions of one service ('03-storage/01-s3') or all of them ('ALL'). Only keys the loader found are accepted."""
    if service == "ALL":
        qs = [q for key in sorted(MCQ) for q in MCQ[key]]
    elif service in MCQ:
        qs = MCQ[service]
    else:
        raise HTTPException(404, "No questions for that service.")
    return JSONResponse({"service": service, "count": len(qs), "questions": qs})
