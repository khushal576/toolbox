"""core/state pieces that need no running services (roadmap B1). The live round trip is
`docker compose exec toolbox python -m core.state.selftest` and the smoke test for /api/state/health."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.state import config, objects, sessions  # noqa: E402


def test_config_reads_env_and_defaults():
    c = config.load({"TOOLBOX_DATABASE_URL": " postgresql://u:p@h/db ", "TOOLBOX_DB_POOL_MAX": "x"})
    assert c.database_url == "postgresql://u:p@h/db" and c.db_pool_max == 5
    assert c.redis_url is None and c.s3_bucket == "toolbox" and c.s3_region == "us-east-1"


def test_require_names_the_missing_variable():
    with pytest.raises(config.StateNotConfigured, match="TOOLBOX_REDIS_URL"):
        config.require(None, "TOOLBOX_REDIS_URL")


@pytest.mark.parametrize("parts", [("df-studio", "abc", "frame.parquet"), ("data-dumper", "d1/dump.sql")])
def test_object_keys_valid(parts):
    assert objects.key(*parts) == "/".join(parts)


@pytest.mark.parametrize("parts", [("t", ""), ("t", ".."), ("t", "a/../b"), ("t", "/abs"), ("", "x"), ("t", "a//b")])
def test_object_keys_reject_traversal_and_empty(parts):
    with pytest.raises(ValueError):
        objects.key(*parts)


def test_session_store_validates_namespace_and_ids():
    with pytest.raises(ValueError):
        sessions.SessionStore("Bad Name")
    s = sessions.SessionStore("df-studio", ttl_seconds=60)
    assert s.key("abc") == "toolbox:session:df-studio:abc"
    for bad in ("", "a:b", "x" * 129):
        with pytest.raises(ValueError):
            s.key(bad)
    assert len(sessions.SessionStore.new_id()) >= 24


def test_health_reports_unconfigured_services_without_raising(monkeypatch):
    for v in ("TOOLBOX_DATABASE_URL", "TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT"):
        monkeypatch.delenv(v, raising=False)
    from core import state
    h = state.health()
    assert h["ok"] is False and all(not h[k]["ok"] and "not set" in h[k]["error"] for k in ("postgres", "redis", "objects"))
