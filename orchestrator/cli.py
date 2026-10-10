"""
orchestrator/cli.py

Headless entrypoint for orchestrator recipes. Run from inside the running
container (reuses the exact same Python environment the web tools run
in — no separate deploy, no new service):

    docker compose exec toolbox python -m orchestrator.cli compare \\
        --left-kind postgres --left-host ... --left-database ... --left-username ... --left-password ... \\
        --left-query "SELECT * FROM t ORDER BY id" \\
        --right-kind file --right-path /app/data/expected.csv

Postgres sources can go through an SSH tunnel (--left-ssh-host etc.), or
skip specifying connection fields entirely with --left-vault <name> to
load a secret saved in core.vault (see vault/CLAUDE.md) — the same store
sql-studio/schema-map's "Save this connection" button writes to.

--left-vault-dataset <name> (a different thing from --left-vault) loads
an actual DATA result instead of a connection — e.g. duck-lab's "Save to
Vault" after a query, or sql-studio's "Export FULL result to Vault"
(the real, uncapped result, not the UI's 500-row display cap). This is
the hand-off point for "feed one tool's output into another":

    docker compose exec toolbox python -m orchestrator.cli compare \\
        --left-vault-dataset "transformed-postgres-data" \\
        --right-kind file --right-path /app/data/expected.csv

Prints the diff result as JSON to stdout (or writes it to --output).
Exits 0 on a successful run (regardless of whether differences were
found — "ran successfully and found MISMATCHes" is not a failure);
exits 1 on a bad input/connection/query error.
"""

from __future__ import annotations

import argparse
import json
import sys

from core import vault
from orchestrator.recipes.compare import Source, compare


def _source_from_args(args: argparse.Namespace, prefix: str) -> Source:
    g = lambda field: getattr(args, f"{prefix}_{field}")  # noqa: E731 - local shorthand, used ~15x below

    dataset_name = g("vault_dataset")
    if dataset_name:
        return {"kind": "vault_dataset", "name": dataset_name}

    vault_name = g("vault")
    if vault_name:
        data = vault.get_secret_by_name(vault_name, kind="postgres_connection")
        return {
            "kind": "postgres",
            "host": data["host"], "port": data.get("port", 5432), "database": data["database"],
            "username": data["username"], "password": data["password"],
            "query": g("query"),
            "ssh_tunnel": data.get("ssh_tunnel"),
        }

    kind = g("kind")
    if kind is None:
        raise ValueError(f"--{prefix}-kind is required unless --{prefix}-vault is given")
    if kind == "postgres":
        ssh_tunnel = None
        if g("ssh_host"):
            key_path = g("ssh_key_file")
            ssh_tunnel = {
                "ssh_host": g("ssh_host"), "ssh_port": g("ssh_port"),
                "ssh_username": g("ssh_username"), "ssh_password": g("ssh_password"),
                "ssh_private_key": open(key_path, encoding="utf-8").read() if key_path else None,
            }
        return {
            "kind": "postgres",
            "host": g("host"), "port": g("port"),
            "database": g("database"), "username": g("username"),
            "password": g("password"), "query": g("query"),
            "ssh_tunnel": ssh_tunnel,
        }
    return {"kind": "file", "path": g("path")}


def _add_source_args(parser: argparse.ArgumentParser, prefix: str, label: str) -> None:
    parser.add_argument(f"--{prefix}-kind", choices=["postgres", "file"],
                         help=f"{label} source type (omit if using --{prefix}-vault or --{prefix}-vault-dataset)")
    parser.add_argument(f"--{prefix}-vault", help=f"Load {label.lower()} connection (+ SSH tunnel, if saved) from the vault by name")
    parser.add_argument(f"--{prefix}-vault-dataset",
                         help=f"Load a dataset (e.g. saved by duck-lab's or sql-studio's 'Save to Vault') from the vault by name — "
                              f"a different thing from --{prefix}-vault, which loads a DB connection, not data")
    parser.add_argument(f"--{prefix}-host", help=f"{label} Postgres host")
    parser.add_argument(f"--{prefix}-port", type=int, default=5432, help=f"{label} Postgres port")
    parser.add_argument(f"--{prefix}-database", help=f"{label} Postgres database")
    parser.add_argument(f"--{prefix}-username", help=f"{label} Postgres username")
    parser.add_argument(f"--{prefix}-password", help=f"{label} Postgres password")
    parser.add_argument(f"--{prefix}-query", help=f"{label} SQL query (postgres kind only)")
    parser.add_argument(f"--{prefix}-path", help=f"{label} file path (file kind only)")
    parser.add_argument(f"--{prefix}-ssh-host", help=f"{label} SSH tunnel host (omit to connect directly)")
    parser.add_argument(f"--{prefix}-ssh-port", type=int, default=22, help=f"{label} SSH tunnel port")
    parser.add_argument(f"--{prefix}-ssh-username", help=f"{label} SSH tunnel username")
    parser.add_argument(f"--{prefix}-ssh-password", help=f"{label} SSH tunnel password")
    parser.add_argument(f"--{prefix}-ssh-key-file", help=f"{label} path to an SSH private key file (PEM)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser("compare", help="Diff two sources (DB query and/or file)")
    _add_source_args(compare_parser, "left", "Left")
    _add_source_args(compare_parser, "right", "Right")
    compare_parser.add_argument("--environment-yaml", help="Path to a YAML file with equivalence_rules/list_keys")
    compare_parser.add_argument("--deep-mode", action="store_true",
                                 help="Parse string-encoded JSON/XML values before diffing")
    compare_parser.add_argument("--output", help="Write JSON result here instead of stdout")

    args = parser.parse_args(argv)

    if args.command == "compare":
        environment_yaml = None
        if args.environment_yaml:
            with open(args.environment_yaml, encoding="utf-8") as f:
                environment_yaml = f.read()

        try:
            result = compare(
                _source_from_args(args, "left"),
                _source_from_args(args, "right"),
                environment_yaml=environment_yaml,
                deep_mode=args.deep_mode,
            )
        except Exception as exc:  # connector errors, PipelineError, etc. all land here
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        output_text = json.dumps(result, indent=2, default=str)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
        else:
            print(output_text)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
