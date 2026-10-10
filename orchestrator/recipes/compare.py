"""
orchestrator/recipes/compare.py

The first real recipe: fetch two "sources" (each either a Postgres query
or a file) and diff them via core.pipeline.run_compare — the exact same
function DataDiff Pro's web UI calls, just skipping normalize() entirely
since DB/file rows are already structured Python objects. This is what
proves the "plug and play" idea: one recipe, two independent connectors,
one unchanged diff engine.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, TypedDict

from core import vault
from core.pipeline import run_compare
from core.postgres_conn import ssh_tunnel_from_dict
from orchestrator.connectors import file as file_connector
from orchestrator.connectors import postgres as postgres_connector


class SSHTunnelSource(TypedDict, total=False):
    ssh_host: str
    ssh_port: int
    ssh_username: str
    ssh_password: Optional[str]
    ssh_private_key: Optional[str]


class Source(TypedDict, total=False):
    kind: str  # "postgres" | "file" | "vault_dataset"
    # postgres
    host: str
    port: int
    database: str
    username: str
    password: str
    query: str
    ssh_tunnel: Optional[SSHTunnelSource]
    # file
    path: str
    # vault_dataset
    name: str


def _read_vault_dataset(name: str) -> list[dict]:
    """A dataset saved via vault.save_dataset() (e.g. duck-lab's "Save to
    Vault" or sql-studio's "Export FULL result to Vault") — decrypt to a
    temp file, read it the same way the plain file connector does, then
    delete the temp file. This is the hand-off point: one tool's output
    becomes another tool's input without ever pasting it through a
    browser textarea or holding the whole thing in memory at once."""
    tmp_path = vault.load_dataset_file_by_name(name)
    try:
        return file_connector.read_rows(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)


def _fetch(source: Source) -> list[dict]:
    kind = source.get("kind")
    if kind == "postgres":
        ssh_tunnel = ssh_tunnel_from_dict(source.get("ssh_tunnel"))
        return postgres_connector.fetch_rows(
            source["host"], source.get("port", 5432), source["database"],
            source["username"], source["password"], source["query"],
            ssh_tunnel=ssh_tunnel,
        )
    if kind == "file":
        return file_connector.read_rows(source["path"])
    if kind == "vault_dataset":
        return _read_vault_dataset(source["name"])
    raise ValueError(f"Unknown source kind '{kind}' — use 'postgres', 'file', or 'vault_dataset'")


def compare(left: Source, right: Source, **diff_kwargs: Any) -> dict:
    """Fetch both sides and diff them. diff_kwargs are passed straight
    through to run_compare (mapper_csv, environment_yaml, deep_mode, ...).

    The two fetches run concurrently (a thread each) — each is a
    blocking call dominated by network/SSH-tunnel-setup latency (the
    motivating case is literally "two databases on different hosts"),
    so running them one after another would mean total wall-clock is
    the sum of both instead of the slower of the two.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        left_future = pool.submit(_fetch, left)
        right_future = pool.submit(_fetch, right)
        left_rows = left_future.result()
        right_rows = right_future.result()
    return run_compare(left_rows, right_rows, **diff_kwargs)
