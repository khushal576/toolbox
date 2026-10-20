"""
core/pgclient.py

Runs the bundled PostgreSQL client tools (`pg_dump`, `pg_restore`, `psql`) as
subprocesses. Shared by Schema Copy and Data Dumper (moved here from
schema-copy/pgtools.py when the second consumer appeared — see ../CLAUDE.md
"Shared connectors"; schema-copy/pgtools.py is now a thin re-export).

The tools are COPIED into the image from an official postgres image in a
multi-stage Docker build (see ../Dockerfile, stage "pgclient") rather than
apt-installed: the toolbox image is Debian 12, the stock `postgres:N` image
is Debian 13 (its binaries won't run here), and a pinned bookworm stage makes
the bundle reproducible without adding apt repositories at build time. The
shared libraries travel with them in /opt/pgclient/lib, put on
LD_LIBRARY_PATH for these child processes ONLY — nothing else in the
container sees them.

Credentials go to the child via the PGPASSWORD environment variable, never
on the command line (a command line is visible to every process on the box
and ends up in logs). Nothing here ever logs the environment.

Every long-running call takes a `cancel` Event (polled; the child is
terminated) and an optional `on_line(text)` callback that receives the tool's
stderr line by line AS IT RUNS — that is how a UI shows `pg_dump -v` progress.
"""

from __future__ import annotations

import gzip
import os
import re
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional

PG_BIN_DIR = Path(os.environ.get("PGCLIENT_BIN_DIR", "/opt/pgclient/bin"))
PG_LIB_DIR = Path(os.environ.get("PGCLIENT_LIB_DIR", "/opt/pgclient/lib"))

LineFn = Callable[[str], None]


class PgToolError(RuntimeError):
    """A client tool is missing, or a run failed; the message is user-facing."""


def _env(password: str, app_name: str) -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PGPASSWORD": password or "",
        "PGCONNECT_TIMEOUT": "15",
        "PGCLIENTENCODING": "UTF8",
        "PGAPPNAME": app_name,
        "LANG": "C.UTF-8",
    }
    if PG_LIB_DIR.is_dir():
        env["LD_LIBRARY_PATH"] = str(PG_LIB_DIR)
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
    """Major version of a bundled client (e.g. 18). pg_dump only dumps servers up to
    its OWN major version, so this gates every dump."""
    out = subprocess.run(
        [str(tool_path(name)), "--version"], env=_env("", "toolbox"), capture_output=True, text=True, timeout=20
    )
    m = re.search(r"(\d+)(?:\.\d+)?", out.stdout)
    if out.returncode != 0 or not m:
        raise PgToolError(f"could not run {name}: {(out.stderr or out.stdout).strip()[:300]}")
    return int(m.group(1))


def _run(
    argv: list[str], env: dict, cancel: threading.Event, *, stdout_path: Optional[Path] = None,
    stdin_feed: Optional[Callable[[object], None]] = None, on_line: Optional[LineFn] = None,
    keep_stdout: bool = False,
) -> tuple[int, str, str]:
    """Run to completion, polling *cancel*. Returns (returncode, stderr_tail, stdout_text).
    stderr is read line by line on a thread (so a chatty `pg_dump -v` can never fill a pipe and
    deadlock) and forwarded to *on_line*. stdout goes to *stdout_path* if given (a dump can be
    hundreds of MB — never held in memory), is returned as text if *keep_stdout*, else discarded.
    *stdin_feed(pipe)* streams data into the child's stdin (used to feed a .gz script to psql).
    A cancelled run is terminated and raises InterruptedError — for a single-transaction psql /
    pg_restore the server then rolls everything back."""
    out_f = open(stdout_path, "wb") if stdout_path else None
    tail: deque[str] = deque(maxlen=400)
    try:
        proc = subprocess.Popen(
            argv, env=env, stdin=subprocess.PIPE if stdin_feed else subprocess.DEVNULL,
            stdout=out_f if out_f else (subprocess.PIPE if keep_stdout else subprocess.DEVNULL),
            stderr=subprocess.PIPE, text=False,
        )
        collected: list[bytes] = []

        def read_err() -> None:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                tail.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:  # noqa: BLE001 — a UI callback must never break the run
                        pass

        def read_out() -> None:
            for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
                collected.append(chunk)

        threads = [threading.Thread(target=read_err, daemon=True)]
        if keep_stdout and not out_f:
            threads.append(threading.Thread(target=read_out, daemon=True))
        if stdin_feed:
            def feed() -> None:
                try:
                    stdin_feed(proc.stdin)
                except (BrokenPipeError, OSError):
                    pass  # the child exited early (an error); its stderr says why
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
            threads.append(threading.Thread(target=feed, daemon=True))
        for t in threads:
            t.start()
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
        for t in threads:
            t.join(timeout=5)
    finally:
        if out_f:
            out_f.close()
    return proc.returncode, "\n".join(tail)[-20000:], b"".join(collected).decode("utf-8", "replace")


def _conninfo(host: str, port: int, user: str, database: str) -> str:
    """The connection as a libpq conninfo string, handed to the tools as `-d`. Unlike -h/-p/-U/-d, a
    conninfo can carry TCP KEEPALIVES: a dump or restore holds one connection for minutes, and NATs,
    load balancers and proxies silently drop idle-looking connections (the classic symptom is
    'SSL error: unexpected eof'). The password is NOT in it — PGPASSWORD carries that."""
    from psycopg.conninfo import make_conninfo
    return make_conninfo(
        host=host, port=port, user=user, dbname=database, connect_timeout=15,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )


def _conn_args(host: str, port: int, user: str, database: str) -> list[str]:
    return ["-d", _conninfo(host, port, user, database), "--no-password"]


# ------------------------------------------------------------------ pg_dump

def pg_dump(
    *, host: str, port: int, user: str, password: str, database: str, out_path: Path,
    schemas: Optional[list[str]] = None, exclude_tables: Optional[list[str]] = None, keep_owner: bool = False,
    cancel: threading.Event, app_name: str = "toolbox-schema-copy",
) -> None:
    """Schema-only plain-SQL dump of exactly the given schemas (every one named with -n — see
    schema-copy/engine.py for why a bare, unfiltered dump is NOT used)."""
    argv = [
        str(tool_path("pg_dump")), "--schema-only", "--no-tablespaces", "--no-publications", "--no-subscriptions",
        *_conn_args(host, port, user, database), "-f", "-",
    ]
    if not keep_owner:
        argv += ["--no-owner", "--no-privileges"]
    for s in schemas or []:
        argv += ["-n", quote_pattern(s)]
    for t in exclude_tables or []:
        argv += ["-T", t]
    code, err, _ = _run(argv, _env(password, app_name), cancel, stdout_path=out_path)
    if code != 0:
        raise PgToolError("pg_dump failed: " + (err.strip() or f"exit code {code}")[:1500])


def dump_database(
    *, host: str, port: int, user: str, password: str, database: str, out_path: Path, fmt: str = "custom",
    scope: str = "all", keep_owner: bool = False, cancel: threading.Event, on_line: Optional[LineFn] = None,
    app_name: str = "toolbox-data-dumper",
) -> None:
    """A whole-database dump (one consistent snapshot) into *out_path*.
    fmt: 'custom' (-Fc, compressed, restorable selectively with pg_restore) or 'plain' (SQL,
    gzip-compressed by pg_dump itself — restores with psql, whole only). scope: 'all' |
    'schema' (structure only) | 'data' (rows only). -v makes pg_dump narrate which table it is on."""
    if fmt not in ("custom", "plain"):
        raise PgToolError("format must be 'custom' or 'plain'")
    argv = [str(tool_path("pg_dump")), *_conn_args(host, port, user, database), "-v", "-f", str(out_path)]
    argv += ["-Fc"] if fmt == "custom" else ["-Fp", "-Z", "gzip:6"]
    argv += ["--no-tablespaces"]
    if scope == "schema":
        argv += ["--schema-only"]
    elif scope == "data":
        argv += ["--data-only"]
    if not keep_owner:
        argv += ["--no-owner", "--no-privileges"]
    code, err, _ = _run(argv, _env(password, app_name), cancel, on_line=on_line)
    if code != 0:
        raise PgToolError("pg_dump failed: " + _last_error(err, code))


_ERR_RE = re.compile(r"error|fatal|could not|permission denied|no space", re.I)
# failures worth retrying: the connection died, not the dump being wrong
TRANSIENT_RE = re.compile(
    r"SSL error|unexpected eof|server closed the connection|connection (?:to server .* )?(?:was lost|failed|reset|timed out)|"
    r"could not receive data|could not connect|Connection reset|Connection refused|terminating connection|timeout expired|"
    r"Broken pipe|could not send data|No route to host|Network is unreachable", re.I,
)


def _last_error(err: str, code: int) -> str:
    """The useful part of a tool's stderr: the error lines, plus the LAST STEP the tool reported
    before failing (with -v it narrates what it is doing) — that tells a catalog-phase failure from
    a failure while copying a table's rows."""
    lines = err.splitlines()
    errors = [ln for ln in lines if _ERR_RE.search(ln)]
    steps = [ln for ln in lines if ln.strip() and not _ERR_RE.search(ln)]
    text = " ".join((errors or lines or [f"exit code {code}"])[-6:])
    if errors and steps:
        text += f"  [last step: {steps[-1].strip()[:160]}]"
    return text[:1500]


def is_transient(message: str) -> bool:
    """Does this failure look like a dropped/unreachable connection (worth retrying)?"""
    return bool(TRANSIENT_RE.search(message or ""))


# ------------------------------------------------------------------ pg_restore / psql

def restore_list(dump_path: Path, cancel: Optional[threading.Event] = None) -> str:
    """`pg_restore --list` — the table of contents of a custom-format dump."""
    code, err, out = _run(
        [str(tool_path("pg_restore")), "--list", str(dump_path)], _env("", "toolbox-data-dumper"),
        cancel or threading.Event(), keep_stdout=True,
    )
    if code != 0:
        raise PgToolError("could not read the dump: " + _last_error(err, code))
    return out


def restore_script(dump_path: Path, extra_args: list[str], cancel: Optional[threading.Event] = None) -> str:
    """The SQL pg_restore WOULD run for these options, as text (`-f -`, no database involved).
    Used to read structure out of a dump (which index belongs to which table, partitions, foreign
    keys) and to preview a selection. Only ever call with --section=pre-data/post-data or a list:
    a data section would stream every row into memory."""
    code, err, out = _run(
        [str(tool_path("pg_restore")), "-f", "-", *extra_args, str(dump_path)], _env("", "toolbox-data-dumper"),
        cancel or threading.Event(), keep_stdout=True,
    )
    if code != 0:
        raise PgToolError("could not read the dump: " + _last_error(err, code))
    return out


def pg_restore(
    *, host: str, port: int, user: str, password: str, database: str, dump_path: Path, extra_args: list[str],
    single_transaction: bool = True, replace_existing: bool = False, keep_owner: bool = False,
    cancel: threading.Event, on_line: Optional[LineFn] = None, app_name: str = "toolbox-data-dumper",
) -> tuple[bool, str]:
    """Restore a custom-format dump. Returns (ok, error_text). *extra_args* carries the selection
    (--section / --schema-only / --data-only / -L listfile). Single transaction: the first error
    rolls EVERYTHING back (and stops), so a failed restore leaves the target untouched."""
    argv = [str(tool_path("pg_restore")), *_conn_args(host, port, user, database), "-v"]
    if single_transaction:
        argv += ["--single-transaction"]  # implies --exit-on-error
    else:
        argv += ["--exit-on-error"]
    if replace_existing:
        argv += ["--clean", "--if-exists"]
    if not keep_owner:
        argv += ["--no-owner", "--no-privileges"]
    argv += [*extra_args, str(dump_path)]
    code, err, _ = _run(argv, _env(password, app_name), cancel, on_line=on_line)
    return code == 0, ("" if code == 0 else err)


def pg_restore_replace(
    *, host: str, port: int, user: str, password: str, database: str, dump_path: Path, extra_args: list[str],
    pre_sql: str, keep_owner: bool = False, cancel: threading.Event, on_line: Optional[LineFn] = None,
    app_name: str = "toolbox-data-dumper",
) -> tuple[bool, str]:
    """Restore a custom-format dump AFTER running *pre_sql* (the DROPs that clear the way), all in
    ONE transaction: `pg_restore -f -` (a plain script, data inline) is piped into
    `psql --single-transaction`, with pre_sql written first. Any error — in the drops or the restore —
    rolls EVERYTHING back, so "replace" can never leave the target half-wiped. This exists because
    `pg_restore --clean` fails on partitioned tables ("cannot drop inherited constraint") and cannot
    be made atomic with our own drops. Returns (ok, stderr_text)."""
    rargv = [str(tool_path("pg_restore")), "-f", "-", "-v"]
    if not keep_owner:
        rargv += ["--no-owner", "--no-privileges"]
    rargv += [*extra_args, str(dump_path)]
    pargv = [
        str(tool_path("psql")), "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction",
        *_conn_args(host, port, user, database), "-f", "-",
    ]
    env = _env(password, app_name)
    restore = subprocess.Popen(rargv, env=_env("", app_name), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    psql = subprocess.Popen(pargv, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    r_tail: deque[str] = deque(maxlen=200)
    p_tail: deque[str] = deque(maxlen=200)

    def drain(proc, tail, forward):
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            if forward and on_line:
                try:
                    on_line(line)
                except Exception:  # noqa: BLE001
                    pass

    def feed() -> None:
        try:
            psql.stdin.write(pre_sql.encode("utf-8"))
            for chunk in iter(lambda: restore.stdout.read(1 << 20), b""):
                psql.stdin.write(chunk)
        except (BrokenPipeError, OSError):
            pass  # psql stopped on an error; its stderr says why
        finally:
            try:
                psql.stdin.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=drain, args=(restore, r_tail, True), daemon=True),
        threading.Thread(target=drain, args=(psql, p_tail, False), daemon=True),
        threading.Thread(target=feed, daemon=True),
    ]
    for t in threads:
        t.start()
    try:
        while psql.poll() is None or restore.poll() is None:
            if psql.poll() is not None and psql.returncode != 0 and restore.poll() is None:
                restore.terminate()  # psql gave up (error): stop generating the rest
            if cancel.is_set():
                for pr in (restore, psql):
                    pr.terminate()
                for pr in (restore, psql):
                    try:
                        pr.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pr.kill()
                raise InterruptedError()
            threading.Event().wait(0.3)
    finally:
        for t in threads:
            t.join(timeout=5)
    ok = psql.returncode == 0 and restore.returncode in (0, -15)
    return ok, ("" if ok else "\n".join([*p_tail, *r_tail])[-20000:])


def psql_apply(
    *, host: str, port: int, user: str, password: str, database: str, script_path: Path, cancel: threading.Event,
    app_name: str = "toolbox-schema-copy", on_line: Optional[LineFn] = None,
) -> tuple[bool, str]:
    """Run a SQL script (plain, or gzip-compressed if the name ends in .gz) in ONE transaction,
    stopping at the first error. Returns (ok, stderr_text). Nothing is left half-applied."""
    argv = [
        str(tool_path("psql")), "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction",
        *_conn_args(host, port, user, database),
    ]
    feed = None
    if str(script_path).endswith(".gz"):
        argv += ["-f", "-"]

        def feed(pipe) -> None:  # stream-decompress: a multi-GB script is never held in memory
            with gzip.open(script_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    pipe.write(chunk)
    else:
        argv += ["-f", str(script_path)]
    code, err, _ = _run(argv, _env(password, app_name), cancel, stdin_feed=feed, on_line=on_line)
    return code == 0, err


def quote_pattern(name: str) -> str:
    """A pg_dump -n/-T pattern for an exact identifier: double-quoted (so no case folding or
    wildcard meaning), embedded quotes doubled."""
    return '"' + name.replace('"', '""') + '"'


def qualified_pattern(schema: str, table: str) -> str:
    return f"{quote_pattern(schema)}.{quote_pattern(table)}"
