"""Sample custom Python plugin (roadmap P1). A plain FastAPI app named `app`; Toolbox mounts it at /tools/hello-python/.
Keep the frontend's calls RELATIVE (fetch('info'), not fetch('/info')) so it works under that prefix."""

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Hello (Python)")

PAGE = """<!doctype html><meta charset="utf-8"><title>Hello (Python)</title>
<body style="font-family:system-ui;max-width:560px;margin:40px auto">
<h1>🐍 Hello from a custom Python plugin</h1>
<p>This page is served by code in <code>plugins/hello_python/</code>, running inside the <b id="rt">…</b> runtime.</p>
<p style="color:#6b7180">It is trusted code: it has the same access as that runtime. Delete the folder to remove it.</p>
<script>fetch("info").then(r => r.json()).then(d => { document.getElementById("rt").textContent = d.runtime; });</script></body>"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(PAGE)


@app.get("/info")
async def info() -> JSONResponse:
    return JSONResponse({"plugin": "hello-python", "runtime": os.environ.get("TOOLBOX_RUNTIME", "standalone")})
