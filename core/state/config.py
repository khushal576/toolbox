"""
State service settings — env vars only (roadmap fixed decision: never hard-code service addresses).

| Env var | Meaning | Compose default |
|---|---|---|
| TOOLBOX_DATABASE_URL | Postgres URL for Toolbox's OWN records | bundled `postgres` service |
| TOOLBOX_DB_POOL_MAX | max pooled connections per process | 5 |
| TOOLBOX_REDIS_URL | Redis URL | bundled `redis` service |
| TOOLBOX_S3_ENDPOINT | S3-compatible endpoint (SeaweedFS today; Garage/AWS S3 later) | bundled `seaweedfs` |
| TOOLBOX_S3_ACCESS_KEY / TOOLBOX_S3_SECRET_KEY | S3 credentials | dev defaults (override in .env) |
| TOOLBOX_S3_BUCKET | bucket for all Toolbox files | toolbox |
| TOOLBOX_S3_REGION | region name sent to the S3 API | us-east-1 |

To use an existing Postgres (e.g. postgres_lab): create a dedicated `toolbox` database + user there and set
TOOLBOX_DATABASE_URL=postgresql://toolbox:<pw>@host.docker.internal:5432/toolbox. Never point it at a lab DB.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class StateNotConfigured(RuntimeError):
    """Raised when a tool needs a state service whose env var is not set."""


@dataclass(frozen=True)
class StateConfig:
    database_url: str | None
    db_pool_max: int
    redis_url: str | None
    s3_endpoint: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_bucket: str
    s3_region: str


def load(env: Mapping[str, str] | None = None) -> StateConfig:
    env = os.environ if env is None else env

    def get(name: str) -> str | None:
        v = (env.get(name) or "").strip()
        return v or None

    try:
        pool_max = max(1, int(get("TOOLBOX_DB_POOL_MAX") or 5))
    except ValueError:
        pool_max = 5
    return StateConfig(
        database_url=get("TOOLBOX_DATABASE_URL"), db_pool_max=pool_max,
        redis_url=get("TOOLBOX_REDIS_URL"),
        s3_endpoint=get("TOOLBOX_S3_ENDPOINT"), s3_access_key=get("TOOLBOX_S3_ACCESS_KEY"),
        s3_secret_key=get("TOOLBOX_S3_SECRET_KEY"), s3_bucket=get("TOOLBOX_S3_BUCKET") or "toolbox",
        s3_region=get("TOOLBOX_S3_REGION") or "us-east-1",
    )


def require(value: str | None, var: str) -> str:
    if not value:
        raise StateNotConfigured(f"{var} is not set — see core/state/config.py")
    return value
