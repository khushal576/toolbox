"""
ai-bridge/store.py — the helper's own chat log (roadmap H2 follow-up): so a chat can be shown again after a reload, in any browser, and long chats load in pages.

SQLite file on the HOST next to the bridge's settings (private, 0600): chats(id = the Claude session id, title, tool, created, last) and messages(id, chat, role, text, meta, ts).
Roles: user | assistant | tool | system. The log is for DISPLAY only — the conversation Claude remembers lives in Claude Code's own session; deleting a log entry here does not change that.
Stdlib only. Never stores secrets by design (the bridge only sees the question, the answer and tool NAMES); text is capped; old chats are pruned.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

MAX_TEXT = 20_000
MAX_CHATS = 300
PAGE_DEFAULT, PAGE_MAX = 30, 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, tool TEXT NOT NULL, created REAL NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, meta TEXT, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS messages_chat ON messages (chat, id);
CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT NOT NULL, msg INTEGER, tool TEXT NOT NULL, rating TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS reviews_tool ON reviews (tool, status, id);
"""


class ChatStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()

    def ensure_chat(self, chat_id: str, title: str, tool: str) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO chats (id, title, tool, created, last) VALUES (?, ?, ?, ?, ?)", (chat_id, " ".join(title.split())[:80] or "Chat", (tool or "home")[:60], now, now))
            old = c.execute("SELECT id FROM chats ORDER BY last DESC LIMIT -1 OFFSET ?", (MAX_CHATS,)).fetchall()
            for r in old:
                c.execute("DELETE FROM messages WHERE chat = ?", (r["id"],))
                c.execute("DELETE FROM chats WHERE id = ?", (r["id"],))

    def add(self, chat_id: str, role: str, text: str, meta: Optional[dict] = None) -> int:
        now = time.time()
        with self._conn() as c:
            cur = c.execute("INSERT INTO messages (chat, role, text, meta, ts) VALUES (?, ?, ?, ?, ?)", (chat_id, role, (text or "")[:MAX_TEXT], json.dumps(meta) if meta else None, now))
            c.execute("UPDATE chats SET last = ? WHERE id = ?", (now, chat_id))
            return int(cur.lastrowid)

    def chats(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT c.id, c.title, c.tool, c.created, c.last, (SELECT COUNT(*) FROM messages m WHERE m.chat = c.id AND m.role IN ('user','assistant')) AS n "
                             "FROM chats c ORDER BY c.last DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
        return [dict(r) for r in rows]

    def messages(self, chat_id: str, before: Optional[int] = None, limit: int = PAGE_DEFAULT) -> dict[str, Any]:
        """The newest `limit` messages (older than `before` if given), oldest first, plus has_more — so a long chat loads in pages."""
        limit = max(1, min(int(limit or PAGE_DEFAULT), PAGE_MAX))
        with self._conn() as c:
            if before:
                rows = c.execute("SELECT * FROM messages WHERE chat = ? AND id < ? ORDER BY id DESC LIMIT ?", (chat_id, int(before), limit + 1)).fetchall()
            else:
                rows = c.execute("SELECT * FROM messages WHERE chat = ? ORDER BY id DESC LIMIT ?", (chat_id, limit + 1)).fetchall()
        more = len(rows) > limit
        out = [{"id": r["id"], "role": r["role"], "text": r["text"], "meta": json.loads(r["meta"]) if r["meta"] else None, "ts": r["ts"]} for r in rows[:limit]][::-1]
        return {"messages": out, "has_more": more}

    def delete(self, chat_id: str) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE chat = ?", (chat_id,))
            return bool(c.execute("DELETE FROM chats WHERE id = ?", (chat_id,)).rowcount)

    # ---- the owner's reviews of answers (👍 / 👎 + a note): the raw material for each tool's policy ----
    def add_review(self, chat: str, msg: Optional[int], tool: str, rating: str, note: str) -> int:
        if rating not in ("up", "down"):
            raise ValueError("rating must be up or down")
        with self._conn() as c:
            if msg is not None:
                c.execute("DELETE FROM reviews WHERE chat = ? AND msg = ?", (chat, int(msg)))          # one review per answer: the latest wins
            cur = c.execute("INSERT INTO reviews (chat, msg, tool, rating, note, ts) VALUES (?, ?, ?, ?, ?, ?)",
                            (chat, None if msg is None else int(msg), (tool or "home")[:60], rating, " ".join((note or "").split())[:400], time.time()))
            return int(cur.lastrowid)

    def reviews(self, tool: str = "", status: str = "new", limit: int = 30) -> list[dict[str, Any]]:
        q, args = "SELECT id, chat, msg, tool, rating, note, status, ts FROM reviews WHERE rating = 'down' AND note != ''", []
        if tool:
            q += " AND tool = ?"; args.append(tool)
        if status:
            q += " AND status = ?"; args.append(status)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(int(limit), 100)))).fetchall()]

    def set_review_status(self, rid: int, status: str) -> bool:
        if status not in ("new", "used", "dismissed"):
            raise ValueError("bad status")
        with self._conn() as c:
            return bool(c.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, int(rid))).rowcount)

    def review_summary(self, tool: str = "", days: int = 30) -> dict[str, Any]:
        since = time.time() - days * 86400
        with self._conn() as c:
            rows = c.execute("SELECT tool, rating, COUNT(*) AS n FROM reviews WHERE ts >= ?" + (" AND tool = ?" if tool else "") + " GROUP BY tool, rating", (since, tool) if tool else (since,)).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["tool"], {"up": 0, "down": 0})[r["rating"]] = r["n"]
        return {"days": days, "tools": out}
