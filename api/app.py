"""
api/app.py

FastAPI application for DataDiff Pro.

Endpoints
---------
GET  /          — serves the single-page UI (ui/index.html)
POST /compare   — runs the full comparison pipeline and returns a diff JSON

The /compare endpoint wires together all core modules:
  normalizer → mapper → diff_engine (equivalence + list_resolver)

All errors are returned as structured JSON with a human-readable message
so the UI can display them without any parsing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Core pipeline imports
from core.normalizer import normalize
from core.pipeline import run_compare, PipelineError

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DataDiff Pro",
    description="Deep smart diff for JSON, XML, and CSV data.",
    version="1.0.0",
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

class CompareRequest(BaseModel):
    """All fields the UI sends when the user clicks Compare."""

    left_data: str = Field(..., description="Raw text of the left-side input.")
    right_data: str = Field(..., description="Raw text of the right-side input.")
    left_format: str = Field(..., description="Format of the left input: json | xml | csv")
    right_format: str = Field(..., description="Format of the right input: json | xml | csv")
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


@app.post("/compare")
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

    valid_formats = {"json", "xml", "csv"}
    if req.left_format.lower() not in valid_formats:
        return _error(
            f"Invalid left format '{req.left_format}'. "
            f"Choose one of: json, xml, csv."
        )
    if req.right_format.lower() not in valid_formats:
        return _error(
            f"Invalid right format '{req.right_format}'. "
            f"Choose one of: json, xml, csv."
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
        result = run_compare(
            left_data, right_data,
            mapper_csv=req.mapper_csv,
            mapper_direction=req.mapper_direction,
            strict_mode=req.strict_mode,
            multi_match_rule=req.multi_match_rule,
            deep_mode=req.deep_mode,
            environment_yaml=req.environment_yaml,
            null_missing_equivalent=req.null_missing_equivalent,
        )
    except PipelineError as exc:
        return _error(str(exc))

    result["ok"] = True
    result["meta"]["left_format"] = req.left_format
    result["meta"]["right_format"] = req.right_format
    return JSONResponse(content=result)


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
