"""Live terminal sessions (ssh-sftp/terminal.py): output buffer with absolute offsets (re-attach without gaps or
repeats), the scrollback cap, input/resize, ending, the session limit and the read-only refusal — with a fake SSH
channel (a real OpenSSH server was used for the live checks, see ssh-sftp/CLAUDE.md). Needs the rt-ssh image's
packages — run it there:
    docker cp tests toolbox-rt-ssh-1:/tmp/tests && docker exec -w /app toolbox-rt-ssh-1 python -m pytest /tmp/tests/unit/test_ssh_terminal.py -q
"""

import importlib
import queue
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "ssh-sftp"))
pytest.importorskip("paramiko")
pytest.importorskip("sshtunnel", reason="runs in the rt-ssh container")


def _terminal():
    try:
        return importlib.import_module("ssh_sftp.terminal")
    except ImportError:
        return importlib.import_module("terminal")


class FakeChan:
    def __init__(self):
        self.q, self.sent, self.size, self.closed = queue.Queue(), b"", None, False

    def recv(self, n):
        return self.q.get()

    def sendall(self, data):
        self.sent += data

    def resize_pty(self, width, height):
        self.size = (width, height)

    def exit_status_ready(self):
        return True

    def recv_exit_status(self):
        return 0

    def close(self):
        self.closed = True
        self.q.put(b"")


class FakeClient:
    def close(self):
        pass


def wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_buffer_offsets_reattach_and_cap(monkeypatch):
    T = _terminal()
    monkeypatch.setattr(T, "MAX_BUFFER", 10)
    ch = FakeChan()
    t = T.Term("srv", "box", FakeClient(), ch)
    ch.q.put(b"hello ")
    ch.q.put(b"world")
    assert wait(lambda: t.read(0)[1] == 11)
    data, off, cut = t.read(0)
    assert (data, off, cut) == (b"ello world", 11, True)          # only the last 10 bytes are kept
    assert t.read(6) == (b"world", 11, False)                      # a re-attach from offset 6: no gap, no repeat
    assert t.read(11) == (b"", 11, False)
    t.write("ls\r")
    t.resize(2000, 1)
    assert ch.sent == b"ls\r" and ch.size == (500, 3)              # clamped
    ch.q.put(b"")                                                 # the shell exits
    assert wait(lambda: t.closed) and t.exit_status == 0
    with pytest.raises(T.TermError):
        t.write("x")


def test_open_refuses_read_only_and_caps_sessions(monkeypatch):
    T = _terminal()
    with pytest.raises(T.TermError, match="read-only"):
        T.open_term({"_id": "a", "read_only": True, "host": "h", "username": "u"})
    monkeypatch.setattr(T, "MAX_TERMS", 1)
    t = T.Term("srv", "box", FakeClient(), FakeChan())
    monkeypatch.setitem(T._terms, t.id, t)
    with pytest.raises(T.TermError, match="already open"):
        T.open_term({"_id": "a", "host": "h", "username": "u"})
    T.close(t.id)
    assert t.closed and t.id not in T._terms
