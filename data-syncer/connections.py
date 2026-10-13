"""
data-syncer/connections.py

Thin re-export: the Vault-entry -> live-connection code moved to
core/db_endpoint.py when Schema Copy became its second consumer. Kept as a
module so engine.py/server.py (and their flat standalone-dev imports) don't change.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from core.db_endpoint import (  # noqa: F401
        CONNECTION_KIND, ConnectionError_, Endpoint, describe, list_vault_connections, resolve,
    )
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.db_endpoint import (  # noqa: F401
        CONNECTION_KIND, ConnectionError_, Endpoint, describe, list_vault_connections, resolve,
    )
