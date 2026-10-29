"""
notebook-lab/kernels.py

One Jupyter kernel per workspace (like one Colab runtime), run as a CHILD PROCESS of this server — which is why the
`notebook` runtime is a single uvicorn process: kernels live in its memory (the same standing exception as the SSH
terminal in rt-ssh).

Cells are submitted to a per-kernel queue and run one at a time. The browser does not hold a connection open for a
cell: it POLLS the execution (`Execution.view`), so a long training run survives a reload, a proxy timeout, or a
closed tab (the outputs are still on the server when the page comes back).

Everything jupyter_client related is imported lazily, so the rest of the tool (and its unit tests) work without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

try:  # package import when mounted inside the toolbox (notebook_lab.*)
    from notebook_lab import workspaces
except ImportError:  # flat import when run standalone from within this folder
    import workspaces

logger = logging.getLogger("toolbox.notebook")

# Connection files carry the kernel's HMAC key: keep them (and jupyter's own dirs) in a throw-away temp dir, never in
# a workspace and never in the volume.
_JDIR = Path(tempfile.gettempdir()) / "notebook-jupyter"
os.environ.setdefault("JUPYTER_RUNTIME_DIR", str(_JDIR / "runtime"))
os.environ.setdefault("JUPYTER_DATA_DIR", str(_JDIR / "data"))
os.environ.setdefault("JUPYTER_CONFIG_DIR", str(_JDIR / "config"))

KERNEL_IDLE_S = int(os.environ.get("TOOLBOX_NOTEBOOK_KERNEL_IDLE_S", "1800"))   # free a kernel nobody has used for 30 min
MAX_STREAM_CHARS = 1_000_000          # per execution: stdout/stderr text kept (a notice replaces the rest)
MAX_OUTPUT_BYTES = 8_000_000          # per execution: everything else (images, HTML tables…)
MAX_INSTALL_CHARS = 1_000_000


class KernelDied(Exception):
    pass


# ---- one cell run -------------------------------------------------------------------------------------------------

class Execution:
    """The outputs of one cell run, in nbformat shape (so they save straight into an .ipynb)."""

    def __init__(self, cell_id: str, code: str, batch: Optional[str]):
        self.id = uuid.uuid4().hex[:12]
        self.cell_id = cell_id
        self.code = code
        self.batch = batch
        self.status = "queued"                  # queued | running | ok | error | aborted
        self.count: Optional[int] = None
        self.outputs: list[dict] = []
        self.version = 0                        # bumped on every change; the poll skips the body when unchanged
        self.created = time.time()
        self.ended: Optional[float] = None
        self._bytes = 0
        self._stream_chars = 0
        self._notice = False
        self._display: dict[str, int] = {}      # display_id -> index in outputs

    def touch(self) -> None:
        self.version += 1

    def _full(self, what: str) -> None:
        if not self._notice:
            self._notice = True
            self.outputs.append({"output_type": "stream", "name": "stderr",
                                 "text": f"\n[output truncated: {what} — the rest of this cell's output was dropped]\n"})

    def stream(self, name: str, text: str) -> None:
        if self._stream_chars >= MAX_STREAM_CHARS:
            self._full("too much text")
            self.touch()
            return
        room = MAX_STREAM_CHARS - self._stream_chars
        text = text[:room]
        self._stream_chars += len(text)
        if self.outputs and self.outputs[-1].get("output_type") == "stream" and self.outputs[-1]["name"] == name:
            self.outputs[-1]["text"] += text
        else:
            self.outputs.append({"output_type": "stream", "name": name, "text": text})
        self.touch()

    def add(self, out: dict, display_id: Optional[str] = None) -> None:
        size = len(json.dumps(out))
        if self._bytes + size > MAX_OUTPUT_BYTES:
            self._full("too much output")
            self.touch()
            return
        self._bytes += size
        self.outputs.append(out)
        if display_id:
            self._display[display_id] = len(self.outputs) - 1
        self.touch()

    def update_display(self, display_id: str, out: dict) -> None:
        i = self._display.get(display_id)
        if i is None:
            return self.add(out, display_id)
        self.outputs[i] = out
        self.touch()

    def clear(self) -> None:
        self.outputs.clear()
        self._display.clear()
        self._stream_chars = 0
        self.touch()

    def error(self, ename: str, evalue: str) -> None:
        self.add({"output_type": "error", "ename": ename, "evalue": evalue, "traceback": [evalue]})

    def view(self, since: Optional[int] = None) -> dict:
        v: dict[str, Any] = {"id": self.id, "cell_id": self.cell_id, "status": self.status, "count": self.count,
                             "version": self.version, "ended": self.ended}
        if since != self.version:
            v["outputs"] = self.outputs
        return v


def _convert(msg_type: str, c: dict) -> Optional[dict]:
    if msg_type == "display_data":
        return {"output_type": "display_data", "data": c.get("data", {}), "metadata": c.get("metadata", {})}
    if msg_type == "execute_result":
        return {"output_type": "execute_result", "data": c.get("data", {}), "metadata": c.get("metadata", {}),
                "execution_count": c.get("execution_count")}
    if msg_type == "error":
        return {"output_type": "error", "ename": c.get("ename", ""), "evalue": c.get("evalue", ""),
                "traceback": c.get("traceback", [])}
    return None


# ---- a kernel -----------------------------------------------------------------------------------------------------

class KernelSession:
    def __init__(self, ws: str):
        self.ws = ws
        self.state = "stopped"                  # stopped | starting | idle | busy | dead
        self.km: Any = None
        self.kc: Any = None
        self.queue: asyncio.Queue[Execution] = asyncio.Queue()
        self.runner: Optional[asyncio.Task] = None
        self.current: Optional[Execution] = None
        self.execs: dict[str, Execution] = {}
        self.last_by_cell: dict[str, Execution] = {}
        self.last_used = time.time()
        self.started_at: Optional[float] = None
        self.lock = asyncio.Lock()
        self.message = ""

    # -- lifecycle
    async def start(self) -> None:
        async with self.lock:
            if self.state in ("idle", "busy"):
                return
            self.state = "starting"
            self.message = ""
            try:
                await asyncio.to_thread(workspaces.ensure_env, self.ws)
                from jupyter_client.manager import AsyncKernelManager

                root = workspaces.existing(self.ws)
                km = AsyncKernelManager(kernel_name="python3", kernel_spec_manager=_spec_manager(root / ".kernels"))
                await km.start_kernel(cwd=str(root), env=workspaces.kernel_env(self.ws))
                kc = km.client()
                kc.start_channels()
                await kc.wait_for_ready(timeout=120)
            except BaseException as e:  # noqa: BLE001 — surfaced to the UI, not swallowed
                self.state = "dead"
                self.message = f"The kernel could not start: {e}"
                logger.warning("kernel start failed for %s: %s", self.ws, e)
                if "km" in locals():
                    try:
                        await km.shutdown_kernel(now=True)
                    except Exception:  # noqa: BLE001
                        pass
                if isinstance(e, asyncio.CancelledError):
                    raise
                return
            self.km, self.kc = km, kc
            self.state = "idle"
            self.started_at = time.time()
            self.last_used = time.time()
            self.runner = asyncio.create_task(self._loop())

    async def stop(self, message: str = "") -> None:
        async with self.lock:
            await self._stop(message)

    async def _stop(self, message: str = "") -> None:
        if self.runner:
            self.runner.cancel()
            try:
                await self.runner
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self.runner = None
        for ex in self.execs.values():
            if ex.status in ("queued", "running"):
                ex.status = "aborted"
                ex.ended = time.time()
                ex.touch()
        self.queue = asyncio.Queue()
        self.current = None
        if self.kc is not None:
            try:
                self.kc.stop_channels()
            except Exception:  # noqa: BLE001
                pass
        if self.km is not None:
            try:
                await self.km.shutdown_kernel(now=True)
            except Exception:  # noqa: BLE001
                pass
        self.km = self.kc = None
        self.state = "stopped"
        self.message = message

    async def restart(self) -> None:
        async with self.lock:
            await self._stop()
        await self.start()

    async def interrupt(self) -> None:
        if self.state != "busy" or self.km is None:
            return
        for ex in self.execs.values():          # queued cells would only run into the interrupt: drop them
            if ex.status == "queued":
                ex.status, ex.ended = "aborted", time.time()
                ex.touch()
        await self.km.interrupt_kernel()

    # -- running cells
    async def submit(self, code: str, cell_id: str, batch: Optional[str] = None) -> Execution:
        if self.state in ("stopped", "dead"):
            await self.start()
        if self.state not in ("idle", "busy"):
            raise workspaces.WorkspaceError(self.message or "The kernel is not running.", 503)
        ex = Execution(cell_id, code, batch)
        old = self.last_by_cell.get(cell_id)
        if old and old.status not in ("queued", "running"):
            self.execs.pop(old.id, None)
        self.execs[ex.id] = ex
        self.last_by_cell[cell_id] = ex
        self.last_used = time.time()
        await self.queue.put(ex)
        return ex

    async def _loop(self) -> None:
        while True:
            ex = await self.queue.get()
            if ex.status == "aborted":
                continue
            self.current, self.state = ex, "busy"
            try:
                await self._run(ex)
            except asyncio.CancelledError:
                raise
            except KernelDied:
                ex.status = "error"
                ex.error("KernelDied", "The kernel died — most likely it ran out of memory (this runtime is limited to "
                         "2 GB). Variables are lost; run the cells again.")
                self.state = "dead"
                self.message = "The kernel died (out of memory?). Restart it to continue."
            except Exception as e:  # noqa: BLE001
                ex.status = "error"
                ex.error(type(e).__name__, str(e))
            finally:
                ex.ended = time.time()
                ex.touch()
                self.current = None
                self.last_used = time.time()
            if self.state == "dead":
                return
            self.state = "idle"
            if ex.status == "error" and ex.batch:   # "Run all": stop at the first failing cell
                for other in self.execs.values():
                    if other.batch == ex.batch and other.status == "queued":
                        other.status, other.ended = "aborted", time.time()
                        other.touch()

    async def _run(self, ex: Execution) -> None:
        kc = self.kc
        ex.status = "running"
        ex.touch()
        msg_id = kc.execute(ex.code, store_history=True, allow_stdin=False, stop_on_error=True)
        while True:
            try:
                msg = await kc.get_iopub_msg(timeout=1.0)
            except queue.Empty:
                if not await self.km.is_alive():
                    raise KernelDied()
                continue
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            t, c = msg["msg_type"], msg["content"]
            if t == "status":
                if c.get("execution_state") == "idle":
                    break
            elif t == "stream":
                ex.stream(c.get("name", "stdout"), c.get("text", ""))
            elif t == "clear_output":
                ex.clear()
            elif t == "update_display_data":
                out = _convert("display_data", c)
                did = (c.get("transient") or {}).get("display_id")
                if out and did:
                    ex.update_display(did, out)
            elif t == "execute_input":
                ex.count = c.get("execution_count")
                ex.touch()
            else:
                out = _convert(t, c)
                if out:
                    ex.add(out, (c.get("transient") or {}).get("display_id"))
        reply = None
        for _ in range(30):
            try:
                reply = await kc.get_shell_msg(timeout=1.0)
            except queue.Empty:
                continue
            if reply["parent_header"].get("msg_id") == msg_id:
                break
            reply = None
        content = (reply or {}).get("content", {})
        ex.count = content.get("execution_count", ex.count)
        status = content.get("status", "ok")
        ex.status = {"ok": "ok", "error": "error"}.get(status, "aborted")

    def view(self) -> dict:
        return {
            "state": self.state, "message": self.message, "started_at": self.started_at,
            "running_cell": self.current.cell_id if self.current else None,
            "queued": sum(1 for e in self.execs.values() if e.status == "queued"),
            "executions": [{"id": e.id, "cell_id": e.cell_id, "status": e.status, "version": e.version,
                            "ended": e.ended} for e in self.last_by_cell.values()],
        }


def _spec_manager(kernels_dir: Path):
    """A KernelSpecManager that only knows this workspace's generated kernelspec (python from its venv)."""
    from jupyter_client.kernelspec import KernelSpecManager

    class OneDir(KernelSpecManager):
        @property
        def kernel_dirs(self):  # type: ignore[override]
            return [str(kernels_dir)]

    return OneDir(ensure_native_kernel=False)


# ---- registry + reaper --------------------------------------------------------------------------------------------

_sessions: dict[str, KernelSession] = {}
_reaper: Optional[asyncio.Task] = None


def session(ws: str) -> KernelSession:
    workspaces.existing(ws)
    global _reaper
    if _reaper is None or _reaper.done():
        _reaper = asyncio.create_task(_reap())
    return _sessions.setdefault(ws, KernelSession(ws))


def peek(ws: str) -> Optional[KernelSession]:
    return _sessions.get(ws)


def forget(ws: str) -> None:
    _sessions.pop(ws, None)


async def _reap() -> None:
    while True:
        await asyncio.sleep(60)
        for s in list(_sessions.values()):
            if s.state == "idle" and time.time() - s.last_used > KERNEL_IDLE_S:
                logger.info("stopping idle kernel of workspace %s", s.ws)
                await s.stop("The kernel was stopped after %d minutes without use." % (KERNEL_IDLE_S // 60))


# ---- pip ----------------------------------------------------------------------------------------------------------

class Install:
    def __init__(self, ws: str, args: list[str]):
        self.id = uuid.uuid4().hex[:10]
        self.ws = ws
        self.args = args
        self.text = ""
        self.status = "running"                 # running | ok | failed
        self.version = 0
        self.proc: Optional[asyncio.subprocess.Process] = None

    def view(self, since: Optional[int] = None) -> dict:
        v = {"id": self.id, "args": self.args, "status": self.status, "version": self.version}
        if since != self.version:
            v["text"] = self.text
        return v


_installs: dict[str, Install] = {}


def last_install(ws: str) -> Optional[Install]:
    return _installs.get(ws)


async def start_install(ws: str, args: list[str]) -> Install:
    cur = _installs.get(ws)
    if cur and cur.status == "running":
        raise workspaces.WorkspaceError("An install is already running in this workspace.", 409)
    await asyncio.to_thread(workspaces.ensure_env, ws)
    ins = Install(ws, args)
    _installs[ws] = ins
    root = workspaces.existing(ws)
    ins.proc = await asyncio.create_subprocess_exec(
        str(workspaces.venv_python(ws)), "-m", "pip", "install", "--progress-bar", "off", *args,
        cwd=str(root), env=workspaces.kernel_env(ws),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    asyncio.create_task(_pump(ins))
    return ins


async def _pump(ins: Install) -> None:
    assert ins.proc and ins.proc.stdout
    while line := await ins.proc.stdout.readline():
        if len(ins.text) < MAX_INSTALL_CHARS:
            ins.text += line.decode("utf-8", errors="replace")
            ins.version += 1
    rc = await ins.proc.wait()
    ins.status = "ok" if rc == 0 else "failed"
    ins.text += "\nDone." if rc == 0 else f"\npip exited with code {rc}."
    ins.version += 1
    session_ = peek(ins.ws)
    if session_:
        session_.last_used = time.time()


async def cancel_install(ws: str) -> None:
    cur = _installs.get(ws)
    if cur and cur.status == "running" and cur.proc:
        cur.proc.terminate()


def installed(ws: str) -> list[dict]:
    """Packages installed in THIS workspace's venv only (--local hides the base image's)."""
    import subprocess

    if not workspaces.env_ready(ws):
        return []
    r = subprocess.run([str(workspaces.venv_python(ws)), "-m", "pip", "list", "--local", "--format=json"],
                       capture_output=True, text=True, timeout=60, env=workspaces.kernel_env(ws),
                       cwd=str(workspaces.existing(ws)))
    try:
        return sorted(json.loads(r.stdout or "[]"), key=lambda p: p["name"].lower())
    except ValueError:
        return []
