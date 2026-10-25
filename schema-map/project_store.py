"""
schema-map/project_store.py

Persistence for Projects and their Versions — the foundation everything
in Schema Map's v2 design sits on top of (Editor, Clusters-per-project,
DDL export). A "Project" is the top-level container the owner always
starts from, seeded one of three ways (direct database connection, from
scratch, or a pasted custom-query JSON result) — none of that origin
logic lives here, this module only knows how to store and retrieve
whatever schema snapshot it's handed.

Storage (since roadmap B6): Toolbox's own Postgres, schema `schema_map`, via core/state/sqlstore.py — the old
SQLite file is copied in once on first start and kept as a backup; standalone (no TOOLBOX_DATABASE_URL) the
SQLite file below is still the store. The original reasoning, kept for history:
a single SQLite file at /app/data/schema-map/projects.db,
deliberately NOT the same database as whatever Postgres the owner is
exploring or designing — this is only ever Schema Map's own memory of
its projects. SQLite (not Postgres, not a new service) because it needs
zero new infrastructure and no new dependency (stdlib `sqlite3`),
matching this whole repo's "one container, no new services" rule (see
../CLAUDE.md). The file must live on the `schema_map_data` Docker volume
(see ../docker-compose.yml) — without that mount, every image rebuild
would silently erase every project and its entire version history,
since a container's own writable layer doesn't survive a rebuild.

Versioning model (decided after explicit back-and-forth, not a default):
every version is a COMPLETE, INDEPENDENT snapshot of the schema at that
point — never a diff against the previous version. This is deliberate:
it's what makes "delete any one version" always safe (nothing else can
depend on it structurally), at the cost of some storage duplication
between consecutive versions. That cost is absorbed by gzip-compressing
each snapshot before writing it (schema JSON — table/column/constraint
names — compresses very well, commonly 5-10x), not by adding diffing —
diffing was considered and rejected specifically because it would make
deleting a middle version either break later versions or require a
"repair the chain" step, both of which contradict the owner's explicit
requirement that delete is simple, explicit, and never cascades.
"""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from core.state.sqlstore import SqlStore
except ImportError:  # standalone without the repo root on the path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.state.sqlstore import SqlStore

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "schema-map" / "projects.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    origin TEXT NOT NULL,       -- 'database' | 'scratch' | 'paste'
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version_number INTEGER NOT NULL,
    label TEXT,
    snapshot_gzip BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_project ON versions(project_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


STORE = SqlStore("schema_map", sqlite_path=DB_PATH, ddl=_SCHEMA)
_connect = STORE.connect


def init_db() -> None:
    STORE.init()


def create_project(name: str, origin: str) -> dict[str, Any]:
    if origin not in ("database", "scratch", "paste"):
        raise ValueError(f"Unknown project origin: {origin!r}")
    project = {"id": uuid.uuid4().hex, "name": name, "origin": origin, "created_at": _now()}
    with _connect() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, origin, created_at) VALUES (?, ?, ?, ?)",
            (project["id"], project["name"], project["origin"], project["created_at"]),
        )
    return project


def list_projects() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


def save_version(project_id: str, snapshot: dict[str, Any], label: Optional[str] = None) -> dict[str, Any]:
    """Compresses and stores one full, independent snapshot. Never touches
    or depends on any other version — see this module's own docstring for
    why that independence is load-bearing, not incidental."""
    if get_project(project_id) is None:
        raise ValueError(f"No such project: {project_id!r}")
    snapshot_gzip = gzip.compress(json.dumps(snapshot).encode("utf-8"))
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_number), -1) + 1 AS next FROM versions WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        version_number = row["next"]
        version = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "version_number": version_number,
            "label": label,
            "created_at": _now(),
        }
        conn.execute(
            "INSERT INTO versions (id, project_id, version_number, label, snapshot_gzip, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (version["id"], project_id, version_number, label, snapshot_gzip, version["created_at"]),
        )
    return version


def list_versions(project_id: str) -> list[dict[str, Any]]:
    """Metadata only — deliberately excludes snapshot_gzip, which can be
    sizeable across many versions and is never needed just to render a
    version history list."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, project_id, version_number, label, created_at FROM versions "
            "WHERE project_id = ? ORDER BY version_number DESC",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def load_version(version_id: str) -> Optional[dict[str, Any]]:
    """Returns the decompressed snapshot dict, or None if the version
    doesn't exist (already deleted, or a bad id)."""
    with _connect() as conn:
        row = conn.execute("SELECT snapshot_gzip FROM versions WHERE id = ?", (version_id,)).fetchone()
        if row is None:
            return None
        return json.loads(gzip.decompress(row["snapshot_gzip"]).decode("utf-8"))


def delete_version(version_id: str) -> None:
    """Permanent, explicit, and always safe — a version is a fully
    independent snapshot (see module docstring), so deleting it can never
    orphan or invalidate any other version, regardless of order."""
    with _connect() as conn:
        conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))


def delete_project(project_id: str) -> None:
    """Permanent — deletes the project AND every one of its versions.
    Unlike delete_version() there's no "safe by construction" story here
    (a project's versions genuinely stop existing with it), so the UI
    confirms before calling this; this function itself doesn't ask
    again. No FOREIGN KEY ... ON DELETE CASCADE in _SCHEMA (sqlite3
    doesn't enforce FK constraints unless PRAGMA foreign_keys=ON is set
    per-connection, which this module doesn't do), so versions are
    deleted explicitly first rather than relying on cascade."""
    with _connect() as conn:
        conn.execute("DELETE FROM versions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
