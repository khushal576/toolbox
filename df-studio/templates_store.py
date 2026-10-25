"""
df-studio/templates_store.py

Saved, reusable transformation pipelines ("templates"): a named list of
{type, params} steps that can be replayed against any future upload — the
point is "clean this kind of file the same way every time" without
re-building the pipeline by hand.

Storage (roadmap B2):
- Inside the Toolbox: Postgres table `df_studio.templates` via core.state.db (survives rebuilds, shared by
  every worker/node). Before B2 this was a JSON file inside the container image's writable layer, so every
  rebuild silently deleted all templates.
- Standalone dev (no TOOLBOX_DATABASE_URL): the old JSON file (data/templates.json, created on first save).

Only {type, params} are persisted, never the generated code string —
code is always regenerated fresh from the current STEP_HANDLERS when a
template is applied, so an edit to a step handler's codegen is reflected
in old templates automatically. Last write wins (same as before).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_STORE_PATH = Path(__file__).resolve().parent / "data" / "templates.json"
_SCHEMA = "df_studio"
_ready = False
_ready_lock = threading.Lock()


def _use_db() -> bool:
    try:
        from core.state import config
    except ImportError:
        return False
    return bool(config.load().database_url)


def _db():
    """core.state.db with the templates table created on first use."""
    global _ready
    from core.state import db

    if not _ready:
        with _ready_lock:
            if not _ready:
                db.ensure_schema(_SCHEMA)
                with db.connection() as conn:
                    conn.execute(f"""CREATE TABLE IF NOT EXISTS {_SCHEMA}.templates (
                        name text PRIMARY KEY, steps jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())""")
                _ready = True
    return db


# --- file backend (standalone) -------------------------------------------------------------------------

def _load() -> dict[str, list[dict[str, Any]]]:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- public API (unchanged signatures) -----------------------------------------------------------------

def save_template(name: str, steps: list[dict[str, Any]]) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Template name is required.")
    clean = [{"type": s["type"], "params": s["params"]} for s in steps]
    if _use_db():
        with _db().connection() as conn:
            conn.execute(f"""INSERT INTO {_SCHEMA}.templates (name, steps) VALUES (%s, %s::jsonb)
                             ON CONFLICT (name) DO UPDATE SET steps = EXCLUDED.steps, updated_at = now()""",
                         (name, json.dumps(clean)))
        return
    data = _load()
    data[name] = clean
    _save(data)


def list_templates() -> list[dict[str, Any]]:
    if _use_db():
        with _db().connection() as conn:
            rows = conn.execute(f"SELECT name, jsonb_array_length(steps) FROM {_SCHEMA}.templates ORDER BY name").fetchall()
        return [{"name": n, "step_count": c} for n, c in rows]
    data = _load()
    return [{"name": name, "step_count": len(steps)} for name, steps in sorted(data.items())]


def get_template(name: str) -> list[dict[str, Any]]:
    if _use_db():
        with _db().connection() as conn:
            row = conn.execute(f"SELECT steps FROM {_SCHEMA}.templates WHERE name = %s", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Template '{name}' not found.")
        return row[0]  # psycopg returns jsonb as Python objects
    data = _load()
    if name not in data:
        raise ValueError(f"Template '{name}' not found.")
    return data[name]


def delete_template(name: str) -> None:
    if _use_db():
        with _db().connection() as conn:
            conn.execute(f"DELETE FROM {_SCHEMA}.templates WHERE name = %s", (name,))
        return
    data = _load()
    if name in data:
        del data[name]
        _save(data)
