"""
sharepoint-lab/auth.py

Getting a Microsoft Graph access token for a Vault `sharepoint_connection` entry. Two ways, chosen per connection:

  client_secret  app-only (client-credentials): an Entra app registration with the Sites.Selected (or
                 Sites.ReadWrite.All) APPLICATION permission. No human involved; edits show up as the app.
  device_code    delegated: the person signs in once at microsoft.com/devicelogin with a short code; we keep the
                 refresh token in the Vault entry. Edits show up as that person and are limited to what they may
                 do. A read-only connection asks only for Sites.Read.All.

No MSAL dependency: three small POSTs to the token endpoint. Access tokens are cached in this process only (they
are short-lived and cheap to get again); the refresh token is the one thing persisted, through `save`.
Nothing here ever returns or logs a secret.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

KIND = "sharepoint_connection"

CLOUDS = {
    "global": ("https://login.microsoftonline.com", "https://graph.microsoft.com"),
    "us_gov": ("https://login.microsoftonline.us", "https://graph.microsoft.us"),
    "china": ("https://login.chinacloudapi.cn", "https://microsoftgraph.chinacloudapi.cn"),
}
_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{2,99}$")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_SKEW = 120  # renew an access token this many seconds before it expires

# Microsoft's own public sign-in app ("Microsoft Graph Command Line Tools", what Graph PowerShell uses). "Sign in as me"
# connections use it, and the tenant "organizations", when the person has no app registration of their own.
PUBLIC_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
PUBLIC_TENANT = "organizations"

# Only for tests / a local Graph stand-in: lets a connection point at another host, over http.
DEV_ENV = "TOOLBOX_SP_DEV"


class AuthError(RuntimeError):
    """Sign-in failed. The message is a plain sentence, already scrubbed."""

    def __init__(self, message: str, *, needs_signin: bool = False):
        super().__init__(message)
        self.needs_signin = needs_signin


def validate(data: dict[str, Any]) -> None:
    """Shape checks for a connection about to be saved (raises AuthError with a plain sentence)."""
    if data.get("auth") not in ("client_secret", "device_code"):
        raise AuthError("Sign-in method must be 'client_secret' or 'device_code'.")
    if not _TENANT_RE.match(str(data.get("tenant_id", ""))):
        raise AuthError("Tenant id looks wrong — use the directory (tenant) id GUID or the tenant's domain.")
    if not _GUID_RE.match(str(data.get("client_id", ""))):
        raise AuthError("Client id must be the application (client) id GUID from the app registration.")
    if data["auth"] == "client_secret" and not str(data.get("client_secret", "")).strip():
        raise AuthError("A client secret is needed for app-only sign-in.")
    if data.get("cloud", "global") not in CLOUDS:
        raise AuthError("Cloud must be one of: " + ", ".join(CLOUDS))


def roots(data: dict[str, Any]) -> tuple[str, str]:
    """(authority base, Graph root) for the connection's cloud."""
    authority, graph = CLOUDS[data.get("cloud") or "global"]
    if os.environ.get(DEV_ENV) == "1":
        authority = data.get("authority_base") or authority
        graph = data.get("graph_base") or graph
    return authority.rstrip("/"), graph.rstrip("/")


def graph_base(data: dict[str, Any]) -> str:
    return roots(data)[1] + "/v1.0"


def _scope(data: dict[str, Any]) -> str:
    graph = roots(data)[1]
    if data["auth"] == "client_secret":
        return f"{graph}/.default"
    sites = "Sites.Read.All" if data.get("read_only") else "Sites.ReadWrite.All"
    return f"{graph}/{sites} offline_access"


def _token_url(data: dict[str, Any], leaf: str) -> str:
    return f"{roots(data)[0]}/{data['tenant_id']}/oauth2/v2.0/{leaf}"


def _scrub(text: str, data: dict[str, Any]) -> str:
    for key in ("client_secret", "refresh_token"):
        if data.get(key):
            text = text.replace(str(data[key]), "***")
    return text


def _explain(resp: httpx.Response, data: dict[str, Any]) -> AuthError:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    code = str(body.get("error") or resp.status_code)
    desc = _scrub(str(body.get("error_description") or "").split("\r\n")[0].split("\n")[0], data)
    if code in ("invalid_grant", "interaction_required", "consent_required"):
        return AuthError("Sign-in has expired or was revoked — sign in again." + (f" ({desc})" if desc else ""),
                         needs_signin=True)
    if code == "invalid_client":
        return AuthError("Microsoft rejected the client id or secret." + (f" ({desc})" if desc else ""))
    return AuthError(f"Microsoft sign-in failed ({code})" + (f": {desc}" if desc else "."))


async def _post(url: str, form: dict[str, str], data: dict[str, Any], transport: Optional[httpx.AsyncBaseTransport]) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
            return await client.post(url, data=form)
    except httpx.HTTPError as exc:
        raise AuthError(f"Could not reach Microsoft sign-in ({type(exc).__name__}).") from exc


_TOKENS: dict[str, tuple[str, float]] = {}   # connection id -> (access token, expiry): a cache, rebuildable


def forget(conn_id: str) -> None:
    _TOKENS.pop(conn_id, None)


class TokenProvider:
    """`await provider.token()` → a valid access token for one connection."""

    def __init__(self, conn_id: str, data: dict[str, Any], *, transport: Optional[httpx.AsyncBaseTransport] = None,
                 save: Optional[Callable[[dict[str, Any]], None]] = None):
        self.conn_id, self.data, self.transport, self.save = conn_id, data, transport, save

    async def token(self, force: bool = False) -> str:
        cached = _TOKENS.get(self.conn_id)
        if cached and not force and cached[1] - _SKEW > time.time():
            return cached[0]
        d = self.data
        if d["auth"] == "client_secret":
            form = {"grant_type": "client_credentials", "client_id": d["client_id"], "client_secret": d["client_secret"],
                    "scope": _scope(d)}
        else:
            if not d.get("refresh_token"):
                raise AuthError("Not signed in yet — use the sign-in button for this connection.", needs_signin=True)
            form = {"grant_type": "refresh_token", "client_id": d["client_id"], "refresh_token": d["refresh_token"],
                    "scope": _scope(d)}
        resp = await _post(_token_url(d, "token"), form, d, self.transport)
        if resp.status_code != 200:
            forget(self.conn_id)
            raise _explain(resp, d)
        body = resp.json()
        _TOKENS[self.conn_id] = (body["access_token"], time.time() + float(body.get("expires_in", 3600)))
        new_refresh = body.get("refresh_token")
        if d["auth"] == "device_code" and new_refresh and new_refresh != d.get("refresh_token") and self.save:
            d["refresh_token"] = new_refresh
            self.save(d)
        return body["access_token"]


async def device_start(data: dict[str, Any], *, transport: Optional[httpx.AsyncBaseTransport] = None) -> dict[str, Any]:
    """Begin a device-code sign-in. Returns what the person must see plus the opaque device_code to poll with."""
    if data["auth"] != "device_code":
        raise AuthError("This connection uses a client secret — there is nothing to sign in to.")
    resp = await _post(_token_url(data, "devicecode"), {"client_id": data["client_id"], "scope": _scope(data)}, data, transport)
    if resp.status_code != 200:
        raise _explain(resp, data)
    b = resp.json()
    return {"device_code": b["device_code"], "user_code": b["user_code"], "verification_uri": b.get("verification_uri") or b.get("verification_url"),
            "expires_in": int(b.get("expires_in", 900)), "interval": int(b.get("interval", 5))}


async def device_poll(data: dict[str, Any], device_code: str, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> dict[str, Any]:
    """One poll. {"status": "pending"|"slow_down"|"done"|"expired"|"declined", "refresh_token"?, "access"?}"""
    form = {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": data["client_id"], "device_code": device_code}
    resp = await _post(_token_url(data, "token"), form, data, transport)
    b = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code == 200:
        return {"status": "done", "refresh_token": b.get("refresh_token", ""), "access_token": b["access_token"],
                "expires_in": float(b.get("expires_in", 3600))}
    err = b.get("error")
    if err == "authorization_pending":
        return {"status": "pending"}
    if err == "slow_down":
        return {"status": "slow_down"}
    if err in ("expired_token", "code_expired"):
        return {"status": "expired"}
    if err in ("authorization_declined", "access_denied"):
        return {"status": "declined"}
    raise _explain(resp, data)


def remember_access(conn_id: str, access_token: str, expires_in: float) -> None:
    _TOKENS[conn_id] = (access_token, time.time() + expires_in)
