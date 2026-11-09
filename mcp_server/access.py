"""
mcp_server/access.py — the AI can USE a Vault connection by name; it never gets the credentials (ADR D4).

All Vault reads go through the scoped Vault (`vault_scope.yaml`: read postgres_connection + s3_location, datasets read,
data read — no write kind, ever). A decrypted entry stays inside this process: it is registered with the redactor (so its
secrets are scrubbed from any output, including driver errors) and only the allow-listed fields below are ever shown.
"""

from __future__ import annotations

from typing import Any

from core import vault as vault_store

from .safety import REDACTOR, ToolError, environment_of

PLUGIN = "mcp-server"
CONNECTION_KIND = "postgres_connection"
S3_KIND = "s3_location"

# Fields of a connection that may be shown. Everything else (username, password, ssh_tunnel contents, keys …) is dropped.
PUBLIC_CONNECTION_FIELDS = ("db_type", "host", "port", "database")


def vault() -> "vault_store.ScopedVault":
    return vault_store.scoped(PLUGIN)


def _learn(data: dict) -> None:
    """Register what must never be echoed: secrets (anywhere) and the user names (in messages)."""
    REDACTOR.learn(data)
    tunnel = data.get("ssh_tunnel") or {}
    REDACTOR.learn_identity(data.get("username"), tunnel.get("ssh_username") if isinstance(tunnel, dict) else None)


def public_connection(item: dict, data: dict) -> dict[str, Any]:
    out = {"name": item["name"], "id": item["id"], "db_type": data.get("db_type") or "postgres",
           **{k: data.get(k) for k in PUBLIC_CONNECTION_FIELDS if k != "db_type"},
           "via_ssh_tunnel": bool(data.get("ssh_tunnel")), "environment": environment_of(data)}
    return out


def list_connections() -> tuple[list[dict], list[str]]:
    """(public views, warnings). An entry that cannot be decrypted is reported by name only."""
    v, out, warn = vault(), [], []
    for item in v.list_secrets(CONNECTION_KIND):
        try:
            data = v.get_secret(item["id"])
        except Exception:  # noqa: BLE001
            warn.append(f"connection '{item['name']}' could not be read (wrong Vault key?)")
            continue
        _learn(data)
        out.append(public_connection(item, data))
    return out, warn


def list_s3_locations() -> list[dict]:
    return [{"name": i["name"], "id": i["id"]} for i in vault().list_secrets(S3_KIND)]


def resolve_connection(name: str) -> tuple[dict, dict]:
    """(decrypted data — keep inside the process, public view). Unknown name → a ToolError listing the NAMES available."""
    v = vault()
    try:
        secret_id = None
        for item in v.list_secrets(CONNECTION_KIND):
            if item["name"] == name:
                secret_id = item["id"]
                break
        if secret_id is None:
            raise v.SecretNotFound(name)
        data = v.get_secret(secret_id)
    except v.SecretNotFound:
        names = [i["name"] for i in v.list_secrets(CONNECTION_KIND)]
        raise ToolError(f"There is no saved connection named '{name}'.",
                        hint="Saved connections: " + (", ".join(names) if names else "none (add one on the Vault page)")) from None
    _learn(data)
    return data, public_connection({"name": name, "id": secret_id}, data)


def target_environment(kind: str, name: str, vault_obj=None) -> str:
    """'prod' | 'non-prod' | 'unknown' for a grant target. Workspaces have no environment (non-prod). Anything that cannot be
    looked up counts as 'unknown' — i.e. protected — so a typo or a missing scope can never LOWER the protection."""
    if kind == "workspace":
        return "non-prod"
    v = vault_obj or vault()
    secret_kind = {"connection": CONNECTION_KIND, "ssh_server": "ssh_server"}.get(kind)
    if not secret_kind:
        return "unknown"
    try:
        for item in v.list_secrets(secret_kind):
            if item["name"] == name:
                return environment_of(v.get_secret(item["id"]))
    except Exception:  # noqa: BLE001 - missing scope / wrong key / DB down: stay protected
        return "unknown"
    return "unknown"


SSH_KIND = "ssh_server"


def public_ssh_server(item: dict, data: dict) -> dict[str, Any]:
    """What may be shown about a saved SSH server: name, address, label, whether its host key is pinned. NO user name, key or password."""
    return {"name": item["name"], "id": item["id"], "host": data.get("host"), "port": int(data.get("port") or 22),
            "host_key_pinned": bool((data.get("host_key") or {}).get("key_b64")), "environment": environment_of(data)}


def list_ssh_servers() -> tuple[list[dict], list[str]]:
    v, out, warn = vault(), [], []
    for item in v.list_secrets(SSH_KIND):
        try:
            data = v.get_secret(item["id"])
        except Exception:  # noqa: BLE001
            warn.append(f"SSH server '{item['name']}' could not be read (wrong Vault key?)")
            continue
        _learn(data)
        out.append(public_ssh_server(item, data))
    return out, warn


def resolve_ssh_server(name: str) -> tuple[dict, dict]:
    v = vault()
    for item in v.list_secrets(SSH_KIND):
        if item["name"] == name:
            data = v.get_secret(item["id"])
            _learn(data)
            return data, public_ssh_server(item, data)
    names = [i["name"] for i in v.list_secrets(SSH_KIND)]
    raise ToolError(f"There is no saved SSH server named '{name}'.",
                    hint="Saved servers: " + (", ".join(names) if names else "none (the owner adds one on the Vault page)"))

