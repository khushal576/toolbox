"""
api/app.py

FastAPI application for DataDiff Pro.

Endpoints (OpenAPI: <mount>/docs, <mount>/openapi.json)
---------
GET  /                          — serves the single-page UI (ui/index.html)
POST /api/v1/compare            — raw text on both sides (json | xml | csv | yaml | env) → diff JSON
POST /api/v1/compare/structured — already-parsed values (DB rows, files) → diff JSON (roadmap D1)
GET  /api/v1/health             — liveness of this stateless service
POST /api/v1/jobs               — run a compare in the background: {"type": "compare" | "compare_structured", …the
                                  matching request…} → 202 {job_id} (roadmap D2; input/result in S3 storage)
GET  /api/v1/jobs/{id}          — queued | running | done | failed | cancelled (+ phase, summary, error)
GET  /api/v1/jobs/{id}/result   — the result JSON (gzip-encoded) once done; any replica can serve it
DELETE /api/v1/jobs/{id}        — cancel a queued/running job, or delete a finished one's result
POST /compare                   — the pre-D1 name of /api/v1/compare, kept as an alias

Since roadmap D1 DataDiff is a shared, stateless service (its own `rt-datadiff` image, 2 replicas behind the
gateway); other code calls it through core/clients/datadiff.py, never core.pipeline directly.

The /compare endpoint wires together all core modules:
  normalizer → mapper → diff_engine (equivalence + list_resolver)

All errors are returned as structured JSON with a human-readable message
so the UI can display them without any parsing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Core pipeline imports
from core.clients.datadiff import decode_value, to_json_safe
from core.normalizer import normalize
from core.pipeline import run_compare, PipelineError

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DataDiff Pro",
    description="Deep smart diff for JSON, XML, and CSV data.",
    version="1.1.0",
)

# Allow all origins for local dev (the UI is served from the same origin in
# production, but during development people may open the file directly).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Path to the single-file UI
_UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CompareOptions(BaseModel):
    """How to compare — shared by the text and the structured endpoint."""

    mapper_csv: Optional[str] = Field(
        default=None,
        description=(
            "Optional field mapping in CSV format: source_path,target_path "
            "(one per line). Applied to the side specified by mapper_direction."
        ),
    )
    mapper_direction: str = Field(
        default="left_to_right",
        description=(
            "Direction the mapper is applied: "
            "'left_to_right' renames LEFT fields to match RIGHT (default), "
            "'right_to_left' renames RIGHT fields to match LEFT."
        ),
    )
    strict_mode: bool = Field(
        default=False,
        description=(
            "When True, the mapper raises an error if a declared source path "
            "is not found in the data instead of silently skipping it."
        ),
    )
    multi_match_rule: str = Field(
        default="keep_list",
        description=(
            "What to do when a mapping path resolves to multiple values "
            "(e.g. a field inside a list): "
            "'keep_list' (default) | 'flatten' | 'pick_first'."
        ),
    )
    deep_mode: bool = Field(
        default=False,
        description=(
            "When True, recursively scan all string-valued fields on both sides "
            "and attempt to parse them as JSON or XML before diffing. "
            "Useful when structured data is stored as escaped strings."
        ),
    )
    environment_yaml: Optional[str] = Field(
        default=None,
        description="Optional YAML config with equivalence_rules and list_keys.",
    )
    null_missing_equivalent: bool = Field(
        default=False,
        description=(
            "When True, a field that is null or empty string on one side and "
            "completely absent on the other is treated as EQUIVALENT instead of "
            "EXTRA_LEFT / EXTRA_RIGHT."
        ),
    )


class CompareRequest(CompareOptions):
    """All fields the UI sends when the user clicks Compare."""

    left_data: str = Field(..., description="Raw text of the left-side input.")
    right_data: str = Field(..., description="Raw text of the right-side input.")
    left_format: str = Field(..., description="Format of the left input: json | xml | csv | yaml | env")
    right_format: str = Field(..., description="Format of the right input: json | xml | csv | yaml | env")


class StructuredCompareRequest(CompareOptions):
    """Already-parsed values (e.g. lists of row dicts). Non-JSON values (Decimal, dates, UUID, bytes) arrive tagged
    by core/clients/datadiff.py and are restored before diffing."""

    left: Any = Field(..., description="Left value: object, list of rows, scalar.")
    right: Any = Field(..., description="Right value.")


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    """Serve the single-page frontend."""
    if not _UI_PATH.exists():
        return HTMLResponse(
            content="<h1>UI not found</h1><p>ui/index.html is missing.</p>",
            status_code=404,
        )
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


v1 = APIRouter(prefix="/api/v1", tags=["v1"])


@v1.get("/health")
async def health() -> dict:
    import socket

    # replica = container hostname: tells the replicas apart behind the gateway (each runs one process, pid 1)
    return {"ok": True, "service": "datadiff", "api": "v1", "replica": socket.gethostname(), "pid": os.getpid()}


@v1.post("/compare/structured")
async def compare_structured(req: StructuredCompareRequest) -> JSONResponse:
    """Diff two already-parsed values (the orchestrator's DB rows / files) — no text parsing step."""
    try:
        result = run_compare(decode_value(req.left), decode_value(req.right), **_options(req))
    except PipelineError as exc:
        return _error(str(exc))
    except (ValueError, TypeError) as exc:  # a malformed tagged value
        return _error(f"Bad structured input: {exc}")
    return JSONResponse(content={"ok": True, **to_json_safe(result)})


def _options(req: CompareOptions) -> dict:
    return {k: getattr(req, k) for k in CompareOptions.model_fields}


@v1.post("/compare")
@app.post("/compare", include_in_schema=False)  # pre-D1 path, kept as an alias
async def compare(req: CompareRequest) -> JSONResponse:
    """
    Run the full diff pipeline.

    Steps
    -----
    1. Validate inputs are not empty.
    2. Parse left + right using the normalizer.
    3. Delegate everything else (mapping, deep-expand, equivalence/list-
       resolver construction, the actual diff) to core.pipeline.run_compare
       — the same function the headless orchestrator calls directly with
       already-structured data (DB rows, parsed files), skipping steps 1-2.
    """

    # ------------------------------------------------------------------
    # Step 1 — Basic validation
    # ------------------------------------------------------------------
    if not req.left_data or not req.left_data.strip():
        return _error("Left input is empty. Please paste some data to compare.")
    if not req.right_data or not req.right_data.strip():
        return _error("Right input is empty. Please paste some data to compare.")

    valid_formats = {"json", "xml", "csv", "yaml", "env"}
    if req.left_format.lower() not in valid_formats:
        return _error(
            f"Invalid left format '{req.left_format}'. "
            f"Choose one of: json, xml, csv, yaml, env."
        )
    if req.right_format.lower() not in valid_formats:
        return _error(
            f"Invalid right format '{req.right_format}'. "
            f"Choose one of: json, xml, csv, yaml, env."
        )

    # ------------------------------------------------------------------
    # Step 2 — Normalize (parse) both sides
    # ------------------------------------------------------------------
    left_data, left_err = normalize(req.left_data, req.left_format)
    if left_err:
        return _error(f"Left side — {left_err}")

    right_data, right_err = normalize(req.right_data, req.right_format)
    if right_err:
        return _error(f"Right side — {right_err}")

    # ------------------------------------------------------------------
    # Step 3 — Mapping + diff, via the shared pipeline
    # ------------------------------------------------------------------
    try:
        result = run_compare(left_data, right_data, **_options(req))
    except PipelineError as exc:
        return _error(str(exc))

    result["ok"] = True
    result["meta"]["left_format"] = req.left_format
    result["meta"]["right_format"] = req.right_format
    return JSONResponse(content=to_json_safe(result))


# ---- background jobs (roadmap D2) -------------------------------------------------------------------------------

def _check_text(req: CompareRequest) -> Optional[str]:
    """The cheap checks of /compare, done before queueing so obvious mistakes answer at once."""
    if not req.left_data.strip() or not req.right_data.strip():
        return "Both inputs must contain data."
    for side, fmt in (("left", req.left_format), ("right", req.right_format)):
        if fmt.lower() not in {"json", "xml", "csv", "yaml", "env"}:
            return f"Invalid {side} format '{fmt}'. Choose one of: json, xml, csv, yaml, env."
    return None


@v1.post("/jobs", status_code=202)
async def submit_job(body: dict = Body(..., examples=[{"type": "compare", "left_data": "[]", "right_data": "[]",
                                                       "left_format": "json", "right_format": "json"}])):
    """Queue a compare; poll GET /api/v1/jobs/{id}, then fetch /result. Body = {"type": ..., **request}."""
    import asyncio

    from pydantic import ValidationError

    from api import jobs

    kind = body.pop("type", None)
    model = {"compare": CompareRequest, "compare_structured": StructuredCompareRequest}.get(kind)
    if model is None:
        return _error("type must be 'compare' or 'compare_structured'.")
    try:
        req = model.model_validate(body)
    except ValidationError as exc:
        return _error(f"Invalid request: {exc.errors()[0].get('loc')} {exc.errors()[0].get('msg')}")
    if kind == "compare" and (problem := _check_text(req)):
        return _error(problem)
    job_id = await asyncio.to_thread(jobs.submit, kind, req.model_dump())
    return JSONResponse(status_code=202, content={"ok": True, "job_id": job_id, "status": "queued",
                                                  "status_url": f"api/v1/jobs/{job_id}",
                                                  "result_url": f"api/v1/jobs/{job_id}/result"})


@v1.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    import asyncio

    from api import jobs

    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(jobs.status, job_id)})
    except jobs.JobNotFound:
        return _error("Unknown job (or older than 7 days).", 404)


@v1.get("/jobs/{job_id}/result")
async def job_result(job_id: str):
    import asyncio

    from api import jobs

    try:
        st = await asyncio.to_thread(jobs.status, job_id)
    except jobs.JobNotFound:
        return _error("Unknown job (or older than 7 days).", 404)
    if st["status"] != "done":
        return _error(f"The job is {st['status']}" + (f": {st['error']}" if st["error"] else "") + ".", 409)
    path = await asyncio.to_thread(jobs.result_path, job_id)
    if path is None:
        return _error("The result is gone (deleted or expired).", 410)
    # stored gzipped; sent as-is with Content-Encoding so browsers/httpx decompress it transparently
    return FileResponse(path, media_type="application/json", headers={"Content-Encoding": "gzip"})


@v1.delete("/jobs/{job_id}")
async def job_cancel(job_id: str) -> JSONResponse:
    import asyncio

    from api import jobs

    try:
        await asyncio.to_thread(jobs.status, job_id)
    except jobs.JobNotFound:
        return _error("Unknown job (or older than 7 days).", 404)
    stopped = await asyncio.to_thread(jobs.cancel, job_id)
    return JSONResponse({"ok": True, "cancelled": stopped, "result_deleted": not stopped})


app.include_router(v1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message: str, status_code: int = 422) -> JSONResponse:
    """Return a consistent error envelope the UI can detect via `ok: false`."""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": message},
    )


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app:app", host="0.0.0.0", port=8080, reload=True)
