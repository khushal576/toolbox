"""
core/file_source.py

Turns a file path into a DuckDB-readable source expression. Extracted out
of duck-lab/engine.py (which had this logic three times, once per format)
and orchestrator/connectors/file.py (which had its own copy) — both now
call build_read_expr() instead of re-deriving the extension-to-DuckDB-
function mapping and the quoting.
"""

from __future__ import annotations


def _quote_literal(s: str) -> str:
    # DuckDB DDL/table functions take the path as a SQL string literal —
    # can't use a prepared-statement parameter here ("Binder Error:
    # Unexpected prepared parameter" on a CREATE VIEW/plain SELECT taking
    # a function call argument), so it's inlined, escaped the same way
    # DuckDB's own string-literal syntax escapes a single quote.
    return "'" + s.replace("'", "''") + "'"


def detect_format(path_or_filename: str) -> str:
    """Return "csv" | "json" | "parquet" from a file's extension.
    Raises ValueError for an unsupported extension. Does not handle xml —
    that's a separate parse-then-register operation, not a lazy DuckDB
    read (see duck-lab/engine.py's load_xml)."""
    ext = path_or_filename.rsplit(".", 1)[-1].lower() if "." in path_or_filename else ""
    if ext in ("csv", "tsv"):
        return "csv"
    if ext == "json":
        return "json"
    if ext == "parquet":
        return "parquet"
    raise ValueError(f"Unsupported file type '.{ext}' — use .csv, .json, or .parquet")


_READERS = {
    "csv": "read_csv_auto",
    "json": "read_json_auto",
    "parquet": "read_parquet",
}


def build_read_expr(path: str) -> str:
    """Return the DuckDB table-function expression to read *path* —
    e.g. read_csv_auto('/data/x.csv'). Raises ValueError for an
    unsupported extension."""
    fmt = detect_format(path)
    return f"{_READERS[fmt]}({_quote_literal(path)})"
