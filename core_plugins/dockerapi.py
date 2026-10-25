"""
Small shared helpers for talking to Docker through the docker-proxy (gateway only).

`service_filter()` — the label filter for one compose service OF THIS PROJECT. Filtering by service name alone
would also match another compose project's containers on the same machine (e.g. a second copy of the stack used to
test a restore), and the supervisor/autoscaler/balancer would start, stop or route to them.
"""

from __future__ import annotations

import json
import socket

_project: str | None = None
_looked_up = False


async def own_project(client) -> str | None:
    """The compose project of the container this process runs in (from its own labels). Cached."""
    global _project, _looked_up
    if not _looked_up:
        r = await client.get(f"/containers/{socket.gethostname()}/json")
        body = r.json() if r.status_code == 200 else None
        if isinstance(body, dict):
            _project = ((body.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project")
            _looked_up = True
        # on failure: try again next time (docker-proxy may still be starting)
    return _project


async def service_filter(client, service: str) -> str:
    # oneoff=False: not `docker compose run` containers (e.g. scripts/backup.sh runs one from the worker service)
    labels = [f"com.docker.compose.service={service}", "com.docker.compose.oneoff=False"]
    project = await own_project(client)
    if project:
        labels.append(f"com.docker.compose.project={project}")
    return json.dumps({"label": labels})
