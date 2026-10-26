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


# ---- many files at once (roadmap L2: loading into Vault Data) ---------------------------------------------------

# extension (after stripping .gz) → format; xml/xlsx are converted first (not lazy DuckDB reads)
_EXT_FORMAT = {"csv": "csv", "tsv": "csv", "txt": "csv", "json": "json", "jsonl": "json", "ndjson": "json",
               "parquet": "parquet", "pq": "parquet", "xml": "xml", "xlsx": "excel", "xlsm": "excel"}
FORMATS = ("csv", "json", "parquet", "xml", "excel")


def detect_any(path: str) -> str:
    """Format of one file: by extension (".csv.gz" counts as csv), else by sniffing its first bytes.
    Returns one of FORMATS; raises ValueError if it can't tell."""
    import gzip

    name = path.lower()
    if name.endswith(".gz"):
        name = name[:-3]
    ext = name.rsplit(".", 1)[-1] if "." in name.rsplit("/", 1)[-1] else ""
    if ext in _EXT_FORMAT:
        return _EXT_FORMAT[ext]
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rb") as f:
        head = f.read(4096)
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"PK\x03\x04"):
        return "excel"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if text.startswith((b"{", b"[")):
        return "json"
    if text.startswith(b"<"):
        return "xml"
    if b"," in head or b"\t" in head or b";" in head or b"|" in head:
        return "csv"
    raise ValueError(f"Can't tell what kind of file '{path}' is — give it an extension (.csv, .json, .parquet…)")


def build_multi_read_expr(paths: list[str], fmt: str, *, header: bool | None = None, delimiter: str | None = None,
                          with_filename: bool = False) -> str:
    """One DuckDB expression reading ALL `paths` (same format) as one table: columns matched by name across files
    (`union_by_name`), compression detected from the name (.gz), optional `filename` column for "which file did
    this row come from". csv/json/parquet only (xml/excel are converted to Parquet first)."""
    files = "[" + ", ".join(_quote_literal(p) for p in paths) + "]"
    extra = ", filename=true" if with_filename else ""
    if fmt == "csv":
        opts = ""
        if header is not None:
            opts += f", header={'true' if header else 'false'}"
        if delimiter:
            opts += f", delim={_quote_literal(delimiter)}"
        return f"read_csv({files}, auto_detect=true, union_by_name=true{opts}{extra})"
    if fmt == "json":
        return f"read_json_auto({files}, union_by_name=true{extra})"
    if fmt == "parquet":
        return f"read_parquet({files}, union_by_name=true{extra})"
    raise ValueError(f"{fmt} files are converted before reading")
