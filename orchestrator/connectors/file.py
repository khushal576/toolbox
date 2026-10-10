"""
orchestrator/connectors/file.py

Reads a CSV/JSON/Parquet file as a list of dicts, using
core.file_source.build_read_expr() — the same extension-to-DuckDB-
function mapping duck-lab/engine.py's load_file() uses, shared rather
than re-derived here.
"""

from __future__ import annotations

import duckdb

from core.file_source import build_read_expr


def read_rows(path: str) -> list[dict]:
    """Read *path* (.csv/.tsv/.json/.parquet) and return every row as a dict."""
    con = duckdb.connect(":memory:")
    try:
        result = con.execute(f"SELECT * FROM {build_read_expr(path)}")
        columns = [d[0] for d in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        con.close()
