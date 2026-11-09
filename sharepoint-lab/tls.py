"""
sharepoint-lab/tls.py

The CA bundle for calls to Microsoft. Normally the stock one (certifi). Behind a TLS-inspecting proxy (Zscaler …) the
proxy's root CA must be trusted too: drop its `*.crt` / `*.pem` into the folder mounted at /certs (see certs/README.md).
No such files → the default verification is used, unchanged.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Union

EXTRA_DIR_ENV = "TOOLBOX_EXTRA_CA_DIR"
_cached: Union[ssl.SSLContext, bool, None] = None


def verify() -> Union[ssl.SSLContext, bool]:
    """Value for httpx's `verify=`: True (default) or a context that also trusts the extra CAs."""
    global _cached
    if _cached is not None:
        return _cached
    folder = Path(os.environ.get(EXTRA_DIR_ENV, "/certs"))
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".crt", ".pem")) if folder.is_dir() else []
    if not files:
        _cached = True
        return _cached
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    for p in files:
        try:
            ctx.load_verify_locations(cafile=str(p))
        except ssl.SSLError:   # not a certificate (a stray key, a half-copied file): skip it rather than break every call
            continue
    _cached = ctx
    return ctx
