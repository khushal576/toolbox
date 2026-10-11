"""
core/http_exec.py

A bounded, streaming, async HTTP request executor — the one place that
actually issues an outbound HTTP request on the user's behalf. Built for
curl-builder/server.py's `/execute` endpoint (see curl-builder/CLAUDE.md
for why that tool's original "no backend processing" decision was
deliberately reversed), but kept generic/reusable here in core/ rather
than inlined in that tool's own server.py — a future tool with the same
"make an outbound HTTP call safely" need shouldn't need a second
implementation, same lesson as core/db/'s Dialect abstraction.

Bounded on purpose, not just "whatever httpx defaults to":
- A hard response-size cap (`max_response_bytes`) enforced by streaming
  and cutting off mid-read, never buffering an unbounded body — the same
  "never load unbounded data into memory" discipline as Duck Lab's
  DuckDB spill-to-disk and Vault's chunked encryption.
- A per-request timeout, so a hung/slow target can't tie up a request
  indefinitely (httpx.AsyncClient is genuinely async, so this doesn't
  block the shared `--workers 1` event loop the way a sync DB driver
  would — other tools stay responsive while this awaits a slow response).

Deliberately does NOT block requests to localhost/internal/private IPs —
hitting your own local or internal APIs is an explicit, primary use case
for this feature, not something to silently prevent. See
curl-builder/CLAUDE.md for the full trust-model writeup (same posture as
DataFrame Studio's unsandboxed custom_code: a single trusted local user,
not a multi-tenant service).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 120.0
DEFAULT_MAX_RESPONSE_BYTES = 10_000_000  # 10 MB


@dataclass
class ExecutionResult:
    status_code: Optional[int] = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""              # text, or base64 if is_base64
    is_base64: bool = False
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: Optional[str] = None  # set on connection/timeout failure; status_code stays None


async def execute_request(
    method: str,
    url: str,
    headers: list[tuple[str, str]],
    body: Optional[bytes],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> ExecutionResult:
    """Issue exactly one HTTP request and return its result, never
    raising — any failure (connect error, timeout, etc.) comes back as
    `ExecutionResult.error`, a clean string the caller can show as-is.
    Does not follow redirects by default, matching plain `curl` (no
    `-L`) rather than browser/fetch defaults — the caller decides."""
    timeout_s = min(max(timeout_s, 0.1), MAX_TIMEOUT_S)
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            async with client.stream(method, url, headers=headers, content=body) as resp:
                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_response_bytes:
                        remaining = max_response_bytes - (total - len(chunk))
                        if remaining > 0:
                            chunks.append(chunk[:remaining])
                        truncated = True
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
                elapsed_ms = round((time.monotonic() - start) * 1000, 1)

                try:
                    text = raw.decode("utf-8")
                    return ExecutionResult(
                        status_code=resp.status_code,
                        headers=dict(resp.headers),
                        body=text,
                        is_base64=False,
                        truncated=truncated,
                        elapsed_ms=elapsed_ms,
                    )
                except UnicodeDecodeError:
                    return ExecutionResult(
                        status_code=resp.status_code,
                        headers=dict(resp.headers),
                        body=base64.b64encode(raw).decode("ascii"),
                        is_base64=True,
                        truncated=truncated,
                        elapsed_ms=elapsed_ms,
                    )
    except httpx.TimeoutException:
        return ExecutionResult(
            error=f"Request timed out after {timeout_s:.0f}s.",
            elapsed_ms=round((time.monotonic() - start) * 1000, 1),
        )
    except httpx.RequestError as exc:
        return ExecutionResult(
            error=f"Request failed: {exc}",
            elapsed_ms=round((time.monotonic() - start) * 1000, 1),
        )
