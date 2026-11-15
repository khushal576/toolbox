"""
SQL Practice — server. See CLAUDE.md for the design; provision.py holds the database logic.

  GET  /                      the page
  GET  /status                is the practice database loaded? (datasets, up-to-date flags)
  POST /setup                 create role + database, load/refresh datasets   {"reset": false}
  GET  /facets, /questions, /questions/{id}      browse / search (the reference SQL is never sent)
  GET  /datasets/{name}/schema.json              {table: {column: type}} for editor autocomplete
  GET  /datasets/{name}/schema.html              the stored Schema Map export (static) — shown by the Schema button
  POST /explain               plan tree of YOUR query (EXPLAIN, not executed)   {dataset, sql}
  GET  /mocks, /mocks/{set}, POST /mocks/{set}/start|finish   mock interviews (timed sets of 3 questions)
  GET  /revisits, /weak-topics   revisit queue (reveal / hard-won -> due in 3 days, then 10) and per-topic weakness
  POST /run                   run YOUR query read-only on the question's dataset
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import provision as pv

app = FastAPI(title="SQL Practice")

_UI = Path(__file__).resolve().parent / "ui"


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": message})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> HTMLResponse:
    return HTMLResponse((_UI / "index.html").read_text(encoding="utf-8"))


@app.get("/vendor/cm-bundle.js", include_in_schema=False)
async def editor_bundle() -> Response:
    """The editor's local CodeMirror bundle — a COPY of SQL Studio's, so changing SQL Studio never breaks this tool."""
    return Response(content=(_UI / "vendor" / "cm-bundle.js").read_bytes(), media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "tool": "sql-practice"})


@app.get("/status")
async def status() -> JSONResponse:
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(pv.status)})
    except pv.PracticeError as e:
        return _err(str(e))


class SetupBody(BaseModel):
    reset: bool = False


@app.post("/setup")
async def setup(body: SetupBody) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(pv.setup, body.reset)})
    except pv.PracticeError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001 - show the real cause (bad SQL in a dataset file, Postgres down) to the owner
        return _err(f"Setup failed: {e}", 500)


@app.get("/facets")
async def facets() -> JSONResponse:
    return JSONResponse({"ok": True, **await asyncio.to_thread(pv.facets)})


@app.get("/questions")
async def questions(q: str = "", topic: str = "", difficulty: str = "", dataset: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, **await asyncio.to_thread(pv.list_questions, q, topic, difficulty, dataset)})


@app.get("/questions/{qid}")
async def question(qid: str) -> JSONResponse:
    """One question with its sample output. The reference SQL / trap / follow-up appear only once it is completed."""
    try:
        return JSONResponse({"ok": True, "question": await asyncio.to_thread(pv.get_question, qid)})
    except pv.PracticeError as e:
        return _err(str(e), 404)


class CheckBody(BaseModel):
    id: str
    sql: str


@app.post("/check")
async def check(body: CheckBody) -> JSONResponse:
    """Run your query AND the reference, compare both result sets with DataDiff, record the attempt."""
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(pv.check, body.id, body.sql)})
    except pv.PracticeError as e:
        return _err(str(e))


@app.post("/questions/{qid}/reveal")
async def reveal(qid: str) -> JSONResponse:
    """Give up and look (unlocks after 3 wrong Checks). Counts for moving on, not for the completed mark."""
    try:
        return JSONResponse({"ok": True, "question": await asyncio.to_thread(pv.reveal, qid)})
    except pv.PracticeError as e:
        return _err(str(e), 403)


@app.post("/questions/{qid}/reset")
async def reset(qid: str) -> JSONResponse:
    """Redo: forget the progress of this one question."""
    try:
        await asyncio.to_thread(pv.reset, qid)
        return JSONResponse({"ok": True})
    except pv.PracticeError as e:
        return _err(str(e), 404)


@app.get("/datasets/{name}/schema.json")
async def schema_json(name: str) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, "schema": await asyncio.to_thread(pv.schema_json, name)})
    except pv.PracticeError as e:
        return _err(str(e), 404)
    except Exception as e:  # noqa: BLE001
        return _err(f"The practice database is not ready yet ({e}). Press Set up.", 503)


@app.get("/datasets/{name}/schema.html", include_in_schema=False)
async def schema_html(name: str) -> Response:
    """The Schema panel's page. A hand-saved datasets/<name>/schema.html (e.g. a Schema Map export) wins when present;
    otherwise the page is generated from the live practice database, so it is always current and needs no manual step."""
    try:
        return FileResponse(pv.schema_html_path(name), media_type="text/html")
    except pv.PracticeError:
        pass
    try:
        template = (_UI / "schema_template.html").read_text(encoding="utf-8")
        return HTMLResponse(await asyncio.to_thread(pv.schema_page, name, template), headers={"Cache-Control": "no-cache"})
    except pv.PracticeError as e:
        return _err(str(e), 404)
    except Exception as e:  # noqa: BLE001
        return _err(f"The practice database is not ready yet ({e}). Press Set up.", 503)


@app.get("/validate")
async def validate() -> JSONResponse:
    """Authoring check: runs every question's reference SQL (see provision.validate_questions)."""
    report = await asyncio.to_thread(pv.validate_questions)
    mocks = await asyncio.to_thread(pv.validate_mocks)
    return JSONResponse({"ok": all(r["ok"] for r in report) and all(r["ok"] for r in mocks), "questions": report, "mocks": mocks})


@app.get("/revisits")
async def revisits() -> JSONResponse:
    return JSONResponse({"ok": True, **await asyncio.to_thread(pv.revisits)})


@app.get("/weak-topics")
async def weak_topics() -> JSONResponse:
    return JSONResponse({"ok": True, **await asyncio.to_thread(pv.weak_topics)})


# ---- mock interviews: timed sets of 3 chained questions (clock kept by the server)

async def _mock(fn, *args) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(fn, *args)})
    except pv.MockError as e:
        return _err(str(e), e.status)
    except pv.PracticeError as e:
        return _err(str(e), 404)


@app.get("/mocks")
async def mocks() -> JSONResponse:
    return await _mock(pv.mock_list)


@app.get("/mocks/questions")
async def mock_questions() -> JSONResponse:
    return JSONResponse({"ok": True, "questions": await asyncio.to_thread(pv.mock_questions)})


@app.post("/mocks/runs/{run_id}/discard")
async def mock_discard(run_id: int) -> JSONResponse:
    await asyncio.to_thread(pv.mock_discard, run_id)
    return JSONResponse({"ok": True})


@app.get("/mocks/{set_id}")
async def mock_get(set_id: str) -> JSONResponse:
    return await _mock(pv.mock_get, set_id)


@app.post("/mocks/{set_id}/start")
async def mock_start(set_id: str) -> JSONResponse:
    return await _mock(pv.mock_start, set_id)


@app.post("/mocks/{set_id}/finish")
async def mock_finish(set_id: str) -> JSONResponse:
    return await _mock(pv.mock_finish, set_id)


class RunBody(BaseModel):
    dataset: str
    sql: str
    limit: int = 200


@app.post("/run")
async def run(body: RunBody) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(pv.run_query, body.dataset, body.sql, body.limit)})
    except pv.PracticeError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001 - e.g. practice database missing -> tell the learner to run Set up
        return _err(f"Could not reach the practice database ({e}). Press Set up.", 503)


@app.post("/explain")
async def explain(body: RunBody) -> JSONResponse:
    """The plan tree of a query (EXPLAIN (FORMAT JSON), never executed): {nodes, node_types, text}."""
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(pv.explain_plan, body.dataset, body.sql)})
    except pv.PracticeError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001
        return _err(f"Could not reach the practice database ({e}). Press Set up.", 503)
