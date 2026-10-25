"""
Lazy ASGI mounts (roadmap A3).

`LazyApp` stands in for a plugin's real app: the plugin's module is imported on the FIRST request, not at
startup, so an unused tool costs no memory. Same fault isolation as before: if the import fails the tool
answers 503 with a clear page and every other tool keeps working.

`DisabledApp` answers for a tool that is turned off in workspace.yaml — its code is never imported.

Imports run on the event loop (not in a thread): it blocks only the first request of a tool for its import
time (worst case ~0.5 s, see docs/roadmap/baseline.md) and keeps module-level code in the normal context.
"""

from __future__ import annotations

import asyncio
import html
import importlib
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("toolbox.plugins")

ASGIApp = Callable[..., Any]


async def _html(send, status: int, title: str, body: str) -> None:
    page = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:15vh auto;padding:0 16px;"
            "color:#1c2035;background:#f4f6fb}h1{font-size:20px}code{background:#e8ebf6;padding:1px 5px;"
            "border-radius:4px}a{color:#4f5ef0}</style></head>"
            f"<body><h1>{html.escape(title)}</h1>{body}<p><a href='/'>← Back to the workspace</a></p></body></html>")
    data = page.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})


async def _reject(scope, send, status: int, title: str, body: str) -> None:
    if scope["type"] == "http":
        await _html(send, status, title, body)
    elif scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1013})


class LazyApp:
    def __init__(self, name: str, module: str, attr: str = "app",
                 on_failure: Callable[[str, str], None] | None = None,
                 on_loaded: Callable[[str], None] | None = None):
        self.name, self.module, self.attr = name, module, attr
        self.state = "not_loaded"  # not_loaded | loaded | failed
        self.error: str | None = None
        self.load_seconds: float | None = None
        self.loaded_at: float | None = None
        self._app: ASGIApp | None = None
        self._lock: asyncio.Lock | None = None
        self._on_failure = on_failure
        self._on_loaded = on_loaded

    def _load(self) -> None:
        t0 = time.perf_counter()
        try:
            self._app = getattr(importlib.import_module(self.module), self.attr)
        except Exception as exc:  # noqa: BLE001 - ANY failure in one tool must not affect the others
            logger.exception("Tool '%s' (%s) failed to load", self.name, self.module)
            self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"
            if self._on_failure:
                self._on_failure(self.name, self.error)
            return
        self.state, self.load_seconds, self.loaded_at = "loaded", time.perf_counter() - t0, time.time()
        logger.info("Tool '%s' loaded on first use in %.2fs", self.name, self.load_seconds)
        if self._on_loaded:
            self._on_loaded(self.name)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":  # Starlette doesn't forward lifespan to mounts; ignore if it ever does
            return
        if self._app is None and self.state != "failed":
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:  # concurrent first requests import once
                if self._app is None and self.state != "failed":
                    self._load()
        if self._app is None:
            await _reject(scope, send, 503, f"{self.name} failed to load",
                          "<p>This tool could not start. The other tools are not affected.</p>"
                          "<p>Check <code>docker compose logs toolbox</code>, fix the tool, then restart.</p>")
            return
        await self._app(scope, receive, send)


class DisabledApp:
    def __init__(self, name: str, title: str):
        self.name, self.title = name, title

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return
        await _reject(scope, send, 404, f"{self.title} is turned off",
                      f"<p>The tool <code>{html.escape(self.name)}</code> is disabled in the workspace settings, "
                      "so its code is not loaded and it uses no memory.</p>"
                      "<p>Turn it on in the workspace settings (or set it to <code>true</code> under "
                      "<code>enabled:</code> in <code>workspace.yaml</code>) and restart.</p>")


class Slot:
    """A stable mount point whose inner app can be swapped at runtime (roadmap A4: live on/off switches).

    main.py mounts one Slot per tool; turning a tool on/off replaces `slot.app` (LazyApp <-> DisabledApp)
    without touching Starlette's routing table. A tool that was already imported and is then turned off stops
    answering immediately, but its module stays in memory until the next restart (Python can't unload it).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        await self.app(scope, receive, send)


# CSP "sandbox" without allow-same-origin gives a custom static page an opaque origin: its scripts run, but it
# cannot read Toolbox APIs (Vault, workspace settings) or the workspace's storage, even from the same server.
STATIC_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads"


class StaticApp:
    """Serves a `kind: static` plugin folder (roadmap A5): `/` → the manifest's entry file, other paths → files
    inside the folder only (no `..`, no hidden files, never the manifest). Sandboxed with STATIC_CSP."""

    def __init__(self, name: str, folder, entry: str):
        from pathlib import Path
        self.name = name
        self.folder = Path(folder).resolve()
        self.entry = entry

    def _resolve(self, rel: str):
        import os
        rel = rel.lstrip("/") or self.entry
        parts = [p for p in rel.split("/") if p]
        if any(p.startswith(".") for p in parts) or rel.split("/")[-1] == "manifest.yaml":
            return None
        path = (self.folder / os.path.join(*parts)).resolve() if parts else None
        if path is None or not path.is_relative_to(self.folder):
            return None
        if path.is_dir():
            path = path / "index.html"
        return path if path.is_file() else None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return
        if scope["type"] != "http":
            await _reject(scope, send, 404, "Not found", "")
            return
        if scope["method"] not in ("GET", "HEAD"):
            await _reject(scope, send, 405, "Method not allowed", "<p>Static apps only serve files.</p>")
            return
        import mimetypes
        # Starlette keeps the full path in scope["path"] and the mount prefix in scope["root_path"]
        full, root = scope.get("path", "/"), scope.get("root_path", "")
        path = self._resolve(full[len(root):] if root and full.startswith(root) else full)
        if path is None:
            await _reject(scope, send, 404, "Not found", f"<p>No such file in custom app <code>{html.escape(self.name)}</code>.</p>")
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", ctype.encode()), (b"content-length", str(len(data)).encode()),
            (b"content-security-policy", STATIC_CSP.encode()), (b"x-content-type-options", b"nosniff"),
            (b"cache-control", b"no-cache")]})
        await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else data})


class ExternalApp:
    """`kind: external` (roadmap A5): `/tools/<name>/` redirects to the manifest URL, so cards, tabs and
    "New window" behave like any tool. Whether it shows inside a tab depends on the target site's frame policy."""

    def __init__(self, name: str, url: str):
        self.name, self.url = name, url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return
        if scope["type"] != "http":
            await _reject(scope, send, 404, "Not found", "")
            return
        await send({"type": "http.response.start", "status": 307,
                    "headers": [(b"location", self.url.encode()), (b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})
