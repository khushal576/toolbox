"""
schema-copy/pgtools.py

Thin re-export: the bundled pg_dump/psql runner moved to core/pgclient.py when
Data Dumper became its second consumer. Kept as a module so engine.py/server.py
(and their flat standalone-dev imports) don't change.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from core.pgclient import (  # noqa: F401
        PG_BIN_DIR, PG_LIB_DIR, PgToolError, client_major, pg_dump, psql_apply, qualified_pattern, quote_pattern, tool_path,
    )
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.pgclient import (  # noqa: F401
        PG_BIN_DIR, PG_LIB_DIR, PgToolError, client_major, pg_dump, psql_apply, qualified_pattern, quote_pattern, tool_path,
    )
