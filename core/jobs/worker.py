"""
The job worker process (roadmap B4): `python -m core.jobs.worker` (the `worker` service in docker-compose).
Runs jobs from the "toolbox" queue; each job runs in a forked child, so a crashing job can't take the worker down.
Scale with `docker compose up -d --scale worker=N`.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket

logger = logging.getLogger("core.jobs.worker")


def _clear_stale_registrations(connection, hostname: str) -> None:
    """A container runs ONE worker, so any worker still registered under this hostname is a previous run of this
    container that was killed (no clean shutdown → its Redis record lives ~7 min). Without this, `docker kill` +
    restart crash-looped on "There exists an active worker named …" and health still counted the dead one."""
    from rq import Worker

    for w in Worker.all(connection=connection):
        if w.name.startswith(f"toolbox-worker-{hostname}-"):
            logger.warning("removing stale worker registration %s (previous run of this container)", w.name)
            w.register_death()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from rq import Worker

    from core.jobs import QUEUE_NAME, rq_connection

    host = socket.gethostname()
    _clear_stale_registrations(rq_connection(), host)
    name = f"toolbox-worker-{host}-{os.getpid()}-{secrets.token_hex(3)}"
    Worker([QUEUE_NAME], connection=rq_connection(), name=name).work(with_scheduler=False)


if __name__ == "__main__":
    main()
