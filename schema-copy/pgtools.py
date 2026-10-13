"""
schema-copy/pgtools.py

Runs the bundled PostgreSQL client tools (`pg_dump`, `psql`) as subprocesses.
They are COPIED into the image from an official postgres image in a
multi-stage Docker build (see ../Dockerfile, stage "pgclient") rather than
apt-installed: the toolbox image is Debian 12, the stock `postgres:17` image
is Debian 13 (its binaries won't run here), and a pinned bookworm stage makes
the bundle reproducible without adding apt repositories at build time. The
shared libraries travel with them in /opt/pgclient/lib, put on
LD_LIBRARY_PATH for these child processes ONLY — nothing else in the
container sees them.

Credentials go to the child via the PGPASSWORD environment variable, never
on the command line (a command line is visible to every process on the box
and ends up in logs). Nothing here ever logs the environment.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

PG_BIN_DIR = Path(os.environ.get("PGCLIENT_BIN_DIR", "/opt/pgclient/bin"))
PG_LIB_DIR = Path(os.environ.get("PGCLIENT_LIB_DIR", "/opt/pgclient/lib"))


class PgToolError(RuntimeError):
    """A client tool is missing, or a run failed; the message is user-facing."""


def _env(host: str, port: int, password: str, extra: Optional[dict] = None) -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PGPASSWORD": password or "",
        "PGCONNECT_TIMEOUT": "15",
        "PGCLIENTENCODING": "UTF8",
        "PGAPPNAME": "toolbox-schema-copy",
        "LANG": "C.UTF-8",
    }
    if PG_LIB_DIR.is_dir():
        env["LD_LIBRARY_PATH"] = str(PG_LIB_DIR)
    if extra:
        env.update(extra)
    return env


def tool_path(name: str) -> Path:
    p = PG_BIN_DIR / name
    if not p.exists():
        raise PgToolError(
            f"'{name}' was not found at {p}. The PostgreSQL client bundle is built into the Docker image "
            "(Dockerfile stage 'pgclient') — rebuild the image with `docker-compose up --build -d`."
        )
    return p


def client_major(name: str = "pg_dump") -> int:
    """Major version of the bundled client (e.g. 17). pg_dump refuses to dump
    a server NEWER than itself, so this gates every run."""
    out = subprocess.run(
        [str(tool_path(name)), "--version"], env=_env("", 0, ""), capture_output=True, text=True, timeout=20
    )
    m = re.search(r"(\d+)(?:\.\d+)?", out.stdout)
    if out.returncode != 0 or not m:
        raise PgToolError(f"could not run {name}: {(out.stderr or out.stdout).strip()[:300]}")
    return int(m.group(1))


def _run(argv: list[str], env: dict, cancel: threading.Event, stdout_path: Optional[Path]) -> tuple[int, str]:
    """Run to completion (polling the cancel flag), returning (returncode,
    stderr text). stdout goes to *stdout_path* if given (a dump can be
    hundreds of MB — never held in memory), else it is captured with stderr.
    A cancelled run is terminated, which for a single-transaction psql makes
    the server roll everything back."""
    with tempfile.TemporaryFile("w+") as err:
        out_f = open(stdout_path, "wb") if stdout_path else err
        try:
            proc = subprocess.Popen(argv, env=env, stdout=out_f, stderr=err, stdin=subprocess.DEVNULL)
            while True:
                try:
                    proc.wait(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        raise InterruptedError()
        finally:
            if stdout_path:
                out_f.close()
        err.seek(0)
        text = err.read()
    return proc.returncode, text[-20000:]


def pg_dump(
    *, host: str, port: int, user: str, password: str, database: str, out_path: Path,
    schemas: list[str], exclude_tables: list[str], keep_owner: bool, cancel: threading.Event,
) -> None:
    """Schema-only dump of exactly the given schemas (every one named with -n
    — see engine.py for why a bare, unfiltered dump is NOT used)."""
    argv = [
        str(tool_path("pg_dump")), "--schema-only", "--no-tablespaces", "--no-publications", "--no-subscriptions",
        "-h", host, "-p", str(port), "-U", user, "-d", database, "--no-password", "-f", "-",
    ]
    if not keep_owner:
        argv += ["--no-owner", "--no-privileges"]
    for s in schemas:
        argv += ["-n", quote_pattern(s)]
    for t in exclude_tables:
        argv += ["-T", t]
    code, err = _run(argv, _env(host, port, password), cancel, out_path)
    if code != 0:
        raise PgToolError("pg_dump failed: " + (err.strip() or f"exit code {code}")[:1500])


def psql_apply(
    *, host: str, port: int, user: str, password: str, database: str, script_path: Path, cancel: threading.Event,
) -> tuple[bool, str]:
    """Run a script in ONE transaction, stopping at the first error. Returns
    (ok, stderr_text). Nothing is left half-applied: a failure rolls back."""
    argv = [
        str(tool_path("psql")), "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction", "--no-password",
        "-h", host, "-p", str(port), "-U", user, "-d", database, "-f", str(script_path),
    ]
    code, err = _run(argv, _env(host, port, password), cancel, None)
    return code == 0, err


def quote_pattern(name: str) -> str:
    """A pg_dump -n/-T pattern for an exact identifier: double-quoted (so no
    case folding or wildcard meaning), embedded quotes doubled."""
    return '"' + name.replace('"', '""') + '"'


def qualified_pattern(schema: str, table: str) -> str:
    return f"{quote_pattern(schema)}.{quote_pattern(table)}"
