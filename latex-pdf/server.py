"""
latex-pdf/server.py

LaTeX -> PDF, fully offline. Posts LaTeX source to /compile, runs the image's own
`pdflatex` in a throw-away temp dir and returns the PDF bytes (or the error log).
The page shows the PDF with the browser's built-in viewer, so nothing is loaded
from the internet.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

app = FastAPI(title="LaTeX to PDF", description="Offline LaTeX compiler and PDF viewer.")

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
_MAX_SOURCE = 500_000          # bytes of LaTeX accepted
_TIMEOUT = 30                  # seconds per pdflatex pass
_MAX_PASSES = 2                # second pass only when LaTeX asks for a rerun
_SLOTS = asyncio.Semaphore(2)  # at most 2 compiles at once; the rest wait


class CompileRequest(BaseModel):
    source: str


def _engine() -> str | None:
    return shutil.which("pdflatex")


async def _run_pass(workdir: str) -> tuple[int, str]:
    # shell-escape stays off (pdflatex default); the openin/openout "p" (paranoid) settings
    # also stop \input / \openout from reading or writing outside the temp dir.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": workdir,
        "TEXMFVAR": workdir,
        "TEXMFCONFIG": workdir,
        "openin_any": "p",
        "openout_any": "p",
    }
    proc = await asyncio.create_subprocess_exec(
        "pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
        "-output-directory", workdir, "main.tex",
        cwd=workdir, env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace")


def _summarise(log: str) -> str:
    """The lines LaTeX flags with '!' plus the 'l.<line>' context after each."""
    lines = log.splitlines()
    picked: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            picked.extend(lines[i:i + 4])
            picked.append("")
    return "\n".join(picked).strip() or log[-1500:]


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict:
    return {"engine": _engine()}


@app.post("/compile")
async def compile_tex(req: CompileRequest):
    if _engine() is None:
        return JSONResponse({"error": "pdflatex is not installed in this environment.", "log": ""}, status_code=503)
    if len(req.source.encode("utf-8")) > _MAX_SOURCE:
        return JSONResponse({"error": "Source is too large (500 KB limit).", "log": ""}, status_code=413)

    async with _SLOTS:
        with tempfile.TemporaryDirectory(prefix="latexpdf-") as workdir:
            Path(workdir, "main.tex").write_text(req.source, encoding="utf-8")
            log = ""
            code = 0
            try:
                for n in range(_MAX_PASSES):
                    code, out = await _run_pass(workdir)
                    log = out
                    if code != 0 or not re.search(r"Rerun to get|Label\(s\) may have changed", out):
                        break
            except asyncio.TimeoutError:
                return JSONResponse({"error": f"Compile timed out after {_TIMEOUT}s.", "log": log}, status_code=408)

            pdf = Path(workdir, "main.pdf")
            if code != 0 or not pdf.exists():
                return JSONResponse({"error": _summarise(log), "log": log[-8000:]}, status_code=422)
            return Response(content=pdf.read_bytes(), media_type="application/pdf")
