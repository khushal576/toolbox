"""
Write/read/delete round trip on every state service (roadmap B1 "done when").

    docker compose exec toolbox python -m core.state.selftest      # exit 0 = all good
"""

from __future__ import annotations

import json
import secrets
import sys

from core.state import _probe, db, objects, sessions


def _pg() -> dict:
    schema = db.ensure_schema("toolbox_selftest")
    token = secrets.token_hex(8)
    with db.connection() as conn, conn.transaction():
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{schema}".probe (token text PRIMARY KEY)')
        conn.execute(f'INSERT INTO "{schema}".probe VALUES (%s)', (token,))
        got = conn.execute(f'SELECT token FROM "{schema}".probe WHERE token = %s', (token,)).fetchone()
        conn.execute(f'DELETE FROM "{schema}".probe WHERE token = %s', (token,))
    assert got and got[0] == token, "postgres read-back mismatch"
    return {"roundtrip": "ok"}


def _redis() -> dict:
    store = sessions.SessionStore("selftest", ttl_seconds=60)
    sid = store.new_id()
    store.set(sid, {"n": 1})
    assert store.update(sid, n=2) == {"n": 2}
    assert store.get(sid) == {"n": 2}
    ttl = sessions.client().ttl(store.key(sid))
    store.delete(sid)
    assert store.get(sid) is None
    return {"roundtrip": "ok", "ttl_seconds": ttl}


def _objects() -> dict:
    k = objects.key("selftest", secrets.token_hex(8), "probe.bin")
    data = secrets.token_bytes(1024)
    objects.put_bytes(k, data)
    assert objects.exists(k) and objects.get_bytes(k) == data, "object read-back mismatch"
    assert k in objects.list_keys(k.rsplit("/", 1)[0] + "/")
    objects.delete(k)
    assert not objects.exists(k) and objects.get_bytes(k) is None
    return {"roundtrip": "ok"}


def main() -> int:
    result = {"postgres": _probe(_pg), "redis": _probe(_redis), "objects": _probe(_objects)}
    print(json.dumps(result, indent=2))
    return 0 if all(r["ok"] for r in result.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
