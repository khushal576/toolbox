"""
core/db/registry.py

The one lookup point from a `db_type` string ("postgres"/"mssql"/
"oracle") to a Dialect instance — SQL Studio's server.py/db_engine.py
use this instead of hardcoding which dialect class to construct, and
any future tool that needs multi-database support should look things
up here too rather than re-deriving its own dialect-name mapping.
"""

from __future__ import annotations

from core.db.dialect import Dialect
from core.db.dialect_mssql import MssqlDialect
from core.db.dialect_oracle import OracleDialect
from core.db.dialect_postgres import PostgresDialect

DIALECTS: dict[str, Dialect] = {
    "postgres": PostgresDialect(),
    "mssql": MssqlDialect(),
    "oracle": OracleDialect(),
}


def get_dialect(db_type: str) -> Dialect:
    try:
        return DIALECTS[db_type]
    except KeyError:
        raise ValueError(
            f"Unknown database type '{db_type}' — choose one of {sorted(DIALECTS)}."
        ) from None
