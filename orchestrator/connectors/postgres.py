"""
orchestrator/connectors/postgres.py

A fresh, minimal, ONE-SHOT Postgres connector: connect (optionally
through an SSH tunnel), run one query, fetch everything as plain dicts,
close. Deliberately NOT built on core.pooled_postgres.PooledPostgresConnection
— that class is async and built around a pool+reaper lifecycle; a script
that connects once, runs one query, and exits has no use for either. It
shares core.postgres_conn's build_conninfo/scrub_password/open_ssh_tunnel
with the pooled tools (sql-studio, schema-map), so both the connection
mechanics and the error-message shape are the same everywhere.
"""

from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from core.postgres_conn import SSHTunnelConfig, build_conninfo, open_ssh_tunnel, scrub_password


def fetch_rows(
    host: str, port: int, database: str, username: str, password: str, query: str,
    *, ssh_tunnel: Optional[SSHTunnelConfig] = None,
) -> list[dict]:
    """Connect to host/port/database (optionally through an SSH tunnel),
    run *query*, return every row as a plain dict. The tunnel (if any) is
    opened and torn down around this single connection — there's no
    lifecycle to manage beyond this one call, unlike the pooled tools."""
    tunnel = None
    connect_host, connect_port = host, port
    try:
        if ssh_tunnel is not None:
            tunnel = open_ssh_tunnel(ssh_tunnel, remote_host=host, remote_port=port)
            connect_host, connect_port = "127.0.0.1", tunnel.local_bind_port
        conninfo = build_conninfo(connect_host, connect_port, database, username, password)
        with psycopg.connect(conninfo, row_factory=dict_row) as con:
            with con.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()
    except psycopg.Error as exc:
        raise RuntimeError(scrub_password(str(exc))) from exc
    finally:
        if tunnel is not None:
            tunnel.stop()
