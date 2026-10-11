"""
core/normalizer.py

Responsible for converting raw input strings (JSON, XML, or CSV) into
Python dicts/lists that the rest of the pipeline can work with uniformly.

Each format has its own parser. On any failure the parser returns a clear,
human-readable error message (with line number / position where possible)
instead of raising a bare exception.
"""

import json
import csv
import io
import re
from typing import Any

# Optional: xmltodict is the cleanest way to handle XML → dict.
# It is listed in requirements.txt.
try:
    import xmltodict
    _XML_AVAILABLE = True
except ImportError:
    _XML_AVAILABLE = False

# PyYAML — already a dependency (used by the orchestrator's recipe
# configs), reused here so .yaml/.yml comparison needs no new package.
import yaml


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalize(raw: str, fmt: str) -> tuple[Any, str | None]:
    """
    Parse *raw* text in the given *fmt* ("json", "xml", or "csv") and return
    a normalized Python object (dict or list of dicts).

    Returns
    -------
    (data, error)
        data  — parsed Python object, or None if parsing failed
        error — human-readable error string, or None if parsing succeeded
    """
    raw = raw.strip()
    if not raw:
        return None, "Input is empty. Please paste some data to compare."

    fmt = fmt.lower().strip()
    if fmt == "json":
        return _parse_json(raw)
    elif fmt == "xml":
        return _parse_xml(raw)
    elif fmt == "csv":
        return _parse_csv(raw)
    elif fmt == "yaml":
        return _parse_yaml(raw)
    elif fmt == "env":
        return _parse_env(raw)
    else:
        return None, (
            f"Unknown format '{fmt}'. Supported formats are: json, xml, csv, yaml, env."
        )


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> tuple[Any, str | None]:
    """Parse a JSON string into a Python dict or list."""
    try:
        data = json.loads(raw)
        return data, None
    except json.JSONDecodeError as e:
        # e.lineno, e.colno, e.msg are all set by the stdlib decoder
        snippet = _get_snippet(raw, e.lineno)
        return None, (
            f"JSON parse error on line {e.lineno}, column {e.colno}: {e.msg}.\n"
            f"  Near: {snippet}\n"
            f"Hint: Check for missing commas, unmatched braces/brackets, or "
            f"unquoted keys."
        )


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

def _parse_xml(raw: str) -> tuple[Any, str | None]:
    """Parse an XML string into a nested Python dict using xmltodict."""
    if not _XML_AVAILABLE:
        return None, (
            "XML parsing is unavailable: the 'xmltodict' library is not installed. "
            "Add 'xmltodict' to requirements.txt and rebuild the image."
        )
    try:
        # Pre-process: inject any missing namespace declarations so expat
        # doesn't throw "unbound prefix" on e.g. xsi:nil.
        raw = _inject_missing_namespaces(raw)

        common_kwargs: dict = dict(
            attr_prefix="@",    # keep XML attributes prefixed with @
            cdata_key="#text",  # text content stored in #text key
        )

        # Pass 1 — parse with default settings to discover which tags
        # xmltodict naturally promotes to lists (i.e. tags with multiple
        # sibling occurrences in the document).
        first_pass = xmltodict.parse(raw, force_list=(), **common_kwargs)
        list_tags: set[str] = set()
        _collect_list_tag_names(first_pass, list_tags)

        # Pass 2 — re-parse forcing those tags to ALWAYS be lists.
        # This fixes the case where a tag has only ONE child element:
        # xmltodict would return a dict, but we want a list of one item
        # so the structure stays consistent with the JSON equivalent.
        parsed = xmltodict.parse(raw, force_list=tuple(list_tags), **common_kwargs)

        # Step 1 — convert OrderedDicts to plain dicts.
        data = _ordereddict_to_dict(parsed)
        # Step 2 — unwrap single-child list wrappers created by xmltodict.
        #   e.g. {"skills": {"skill": [...]}} → {"skills": [...]}
        #   This makes the XML structure match the equivalent JSON structure.
        data = _unwrap_xml_lists(data)
        # Step 3 — normalize XML attributes:
        #   • Strip the '@' prefix so @type → type (matches JSON field names)
        #   • Hoist mixed-content nodes: <amount currency="INR">2599.75</amount>
        #     becomes amount=2599.75 with currency="INR" as a sibling field
        #   • xsi:nil="true" elements become None
        data = _normalize_xml_attrs(data)
        # Step 4 — coerce numeric strings to int/float so they MATCH (not
        #   just EQUIVALENT) against JSON numeric values.
        data = _coerce_xml_numbers(data)
        return data, None
    except Exception as e:  # xmltodict raises ExpatError or similar
        line, col = _extract_xml_position(str(e))
        hint = ""
        if line:
            snippet = _get_snippet(raw, line)
            hint = f"\n  Near line {line}: {snippet}"
        return None, (
            f"XML parse error: {e}.{hint}\n"
            f"Hint: Make sure the document has a single root element, all tags "
            f"are properly closed, and special characters like & are escaped as "
            f"&amp;."
        )


def _unwrap_root(parsed: dict) -> Any:
    """
    xmltodict always returns a single-key dict whose key is the XML root tag.
    If that's the case, return the value so the caller works with the content.
    """
    if isinstance(parsed, dict) and len(parsed) == 1:
        return next(iter(parsed.values()))
    return parsed


def _extract_xml_position(msg: str) -> tuple[int | None, int | None]:
    """Try to pull line/column numbers out of an XML error message string."""
    m = re.search(r"line (\d+), column (\d+)", msg, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _ordereddict_to_dict(obj: Any) -> Any:
    """Recursively convert OrderedDict (and any Mapping) to plain dict."""
    if isinstance(obj, dict):
        return {k: _ordereddict_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ordereddict_to_dict(item) for item in obj]
    return obj


def _collect_list_tag_names(obj: Any, result: set) -> None:
    """
    Walk *obj* (output of the first xmltodict pass) and collect tag names
    that should always be forced to lists in the second parse.

    Two cases are detected:
    a) A key whose value is already a list — multiple sibling occurrences in
       the document; xmltodict already made it a list.
    b) A single-key wrapper dict whose sole child value is a dict, AND the
       parent key name looks like a collection wrapper for the child key
       (e.g. ``purchases`` → ``purchase``, ``employees`` → ``employee``).
       This handles single-item repeating collections consistently with the
       multi-item case, while NOT incorrectly flagging structural nesting
       like ``<c><d>…</d></c>`` where ``c`` and ``d`` have no plural
       relationship.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                result.add(k)
            elif (
                isinstance(v, dict)
                and len(v) == 1
                and not k.startswith("@")
                and k != "#text"
            ):
                # Single-child wrapper: inspect the child
                child_key = next(iter(v))
                child_val = v[child_key]
                if (
                    not child_key.startswith("@")
                    and child_key != "#text"
                    and isinstance(child_val, dict)
                    and _is_collection_of(k, child_key)
                ):
                    # Parent looks like a plural/collection wrapper for child
                    result.add(child_key)
            _collect_list_tag_names(v, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_list_tag_names(item, result)


def _is_collection_of(parent: str, child: str) -> bool:
    """
    Return True when *parent* looks like a collection/plural wrapper for *child*.

    Handles common English plural patterns:
        purchases   → purchase   (+s)
        employees   → employee   (+s)
        orders      → order      (+s)
        entries     → entry      (y → ies)
        boxes       → box        (+es, approximate)
        userList    → user       (List / Array / Items / Set / Collection suffix)

    Does NOT match arbitrary structural nesting like c → d or root → data.
    """
    p, c = parent.lower(), child.lower()
    return (
        p == c + "s"                                   # purchase → purchases
        or p == c + "es"                               # box → boxes (approx)
        or (c.endswith("y") and p == c[:-1] + "ies")  # entry → entries
        or p == c + "list"
        or p == c + "_list"
        or p == c + "array"
        or p == c + "_array"
        or p == c + "items"
        or p == c + "_items"
        or p == c + "set"
        or p == c + "collection"
        or p.endswith(("list", "array", "items", "set", "collection"))
    )


def _unwrap_xml_lists(obj: Any, _depth: int = 0) -> Any:
    """
    Recursively unwrap single-child list-wrapper dicts produced by xmltodict.

    xmltodict converts repeated XML sibling tags into a list under their tag
    name, but keeps that list wrapped in a parent dict:
        <skills><skill>A</skill><skill>B</skill></skills>
        → {"skills": {"skill": ["A", "B"]}}   ← xmltodict output
        → {"skills": ["A", "B"]}              ← after this function

    Rule: if a dict has exactly ONE key and its value is a list, replace the
    dict with just the list.  Applied at depth > 0 only — the top-level root
    dict is never unwrapped so that the root tag name (e.g. "employees") is
    preserved and can be matched against the equivalent JSON key.

    Safe cases that are NOT touched:
        {"address": {"city": "X", "state": "Y"}}  — 2 keys, not a wrapper
        {"name": "Alice"}                          — value is str, not a list
    """
    if isinstance(obj, dict):
        # Recurse into every value first (incrementing depth).
        unwrapped = {k: _unwrap_xml_lists(v, _depth + 1) for k, v in obj.items()}
        # Unwrap only at depth > 0 so the root key (e.g. "employees") stays.
        if _depth > 0 and len(unwrapped) == 1:
            sole_value = next(iter(unwrapped.values()))
            if isinstance(sole_value, list):
                return sole_value
        return unwrapped
    if isinstance(obj, list):
        # List items stay at the same depth as the list itself.
        return [_unwrap_xml_lists(item, _depth) for item in obj]
    return obj


# Well-known namespace URIs injected when a prefix is used but not declared.
_KNOWN_NS: dict[str, str] = {
    "xsi":  "http://www.w3.org/2001/XMLSchema-instance",
    "xs":   "http://www.w3.org/2001/XMLSchema",
    "xsd":  "http://www.w3.org/2001/XMLSchema",
    "xlink":"http://www.w3.org/1999/xlink",
}


def _inject_missing_namespaces(raw: str) -> str:
    """
    Scan for namespace prefixes used in the XML (e.g. ``xsi:nil``) and inject
    any missing ``xmlns:`` declarations into the root element so the expat
    parser doesn't throw an 'unbound prefix' error.
    """
    # Collect all namespace prefixes actually used (e.g. "xsi" from "xsi:nil")
    used: set[str] = set(re.findall(r'\b([a-zA-Z][a-zA-Z0-9_]*):[a-zA-Z]', raw))
    # Collect already-declared prefixes
    declared: set[str] = set(re.findall(r'xmlns:([a-zA-Z][a-zA-Z0-9_]*)\s*=', raw))
    missing = used - declared
    if not missing:
        return raw

    injections = " ".join(
        f'xmlns:{p}="{_KNOWN_NS.get(p, "urn:" + p)}"'
        for p in sorted(missing)
    )

    # Inject into the first opening tag (the root element).
    def _add(m: re.Match) -> str:
        return f"<{m.group(1)} {injections}{m.group(2)}"

    return re.sub(r"<([a-zA-Z][^>]*?)(\s*/?>)", _add, raw, count=1)


def _normalize_xml_attrs(obj: Any) -> Any:
    """
    Recursively post-process the xmltodict output to make XML attributes
    look like ordinary JSON fields:

    1. Strip the ``@`` prefix from every attribute key.
    2. Strip namespace prefixes (``xsi:nil`` → ``nil``).
    3. Elements with ``nil="true"`` / ``xsi:nil="true"`` become ``None``.
    4. Mixed-content elements — a tag that carries both text content
       (``#text``) and attributes — are "hoisted":
       ``{"amount": {"@currency": "INR", "#text": "2599.75"}}``
       becomes ``{"amount": "2599.75", "currency": "INR"}``.
    5. Pure-text elements (``{"#text": "hello"}``) collapse to the string.
    """
    if isinstance(obj, list):
        return [_normalize_xml_attrs(item) for item in obj]
    if not isinstance(obj, dict):
        return obj

    # ---- nil check: if THIS dict represents a nil element, return None ----
    for k, v in obj.items():
        if k.startswith("@"):
            local = k[1:]
            if ":" in local:
                local = local.split(":", 1)[1]
            if local.lower() == "nil" and str(v).lower() in ("true", "1"):
                return None

    result: dict = {}
    for k, v in obj.items():
        if k.startswith("@"):
            # Strip '@' prefix
            local = k[1:]
            # Skip namespace declarations (xmlns, xmlns:foo) — these are
            # parser artefacts, not data fields.
            if local == "xmlns" or local.startswith("xmlns:"):
                continue
            # Strip any remaining namespace prefix (e.g. xsi:nil → nil)
            if ":" in local:
                local = local.split(":", 1)[1]
            if local.lower() == "nil":
                continue
            result[local] = _normalize_xml_attrs(v)
        elif k == "#text":
            # Retain temporarily; resolved in mixed-content step below.
            result["#text"] = _normalize_xml_attrs(v)
        else:
            child = _normalize_xml_attrs(v)
            # Mixed-content: child dict has a '#text' key alongside attrs.
            if isinstance(child, dict) and "#text" in child:
                text_val = child.pop("#text")
                result[k] = text_val
                # Hoist the attribute-derived fields as siblings of k.
                for attr_k, attr_v in child.items():
                    result[attr_k] = attr_v
            else:
                result[k] = child

    # Collapse pure-text dict to its value.
    if "#text" in result and len(result) == 1:
        return result["#text"]

    return result


def _coerce_xml_numbers(obj: Any) -> Any:
    """
    Recursively convert numeric strings to Python int or float.

    XML has no type system — every leaf value comes out of xmltodict as a
    string.  This makes "101" → 101 and "85000.5" → 85000.5 so that numeric
    fields MATCH their JSON counterparts instead of being marked EQUIVALENT.

    Booleans are intentionally left alone (they are not strings here).
    """
    if isinstance(obj, dict):
        return {k: _coerce_xml_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_xml_numbers(item) for item in obj]
    if isinstance(obj, str):
        # Try integer first (avoids turning "6" into 6.0)
        try:
            return int(obj)
        except ValueError:
            pass
        try:
            return float(obj)
        except ValueError:
            pass
    return obj


# ---------------------------------------------------------------------------
# CSV value coercion
# ---------------------------------------------------------------------------

def _coerce_csv_value(v: str) -> Any:
    """
    Attempt to parse a raw CSV string value into its natural Python type.

    CSV has no type system — every cell is a string.  When CSV data was
    originally exported from JSON (or stored with JSON-encoded columns),
    complex values like arrays and objects are serialised as JSON strings.
    This function reverses that:

    - JSON arrays / objects: ``'["a","b"]'`` → ``["a", "b"]``
    - Integers:  ``"42"``   → ``42``
    - Floats:    ``"3.14"`` → ``3.14``
    - Booleans:  ``"true"`` / ``"false"`` → ``True`` / ``False``
    - Null-like: ``""`` / ``"null"`` / ``"none"`` → ``None``
    - Everything else: returned as-is (plain string)
    """
    if v == "" or v.lower() in ("null", "none", "na", "n/a", "nil"):
        return None

    # JSON array or object — try full JSON parse
    if v.startswith(("{", "[")):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass

    # Boolean literals
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False

    # Numeric — integer first to avoid turning "6" into 6.0
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass

    return v


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def _parse_csv(raw: str) -> tuple[list[dict], str | None]:
    """
    Parse a CSV string into a list of dicts (one dict per data row).
    The first row is treated as the header / column names.

    Handles:
    - comma-delimited (default)
    - automatic delimiter sniffing (tab, semicolon, pipe)
    - quoted fields containing commas or newlines
    - trailing whitespace in values and headers
    """
    try:
        # Sniff the delimiter from the first 2 KB of the input.
        sample = raw[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            # Default to comma if sniffer cannot decide.
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.DictReader(
            io.StringIO(raw),
            dialect=dialect,
            skipinitialspace=True,
        )

        rows: list[dict] = []
        for line_num, row in enumerate(reader, start=2):  # header is line 1
            # Strip whitespace from keys and values, then coerce complex values.
            clean_row = {
                k.strip(): _coerce_csv_value(v.strip() if v is not None else "")
                for k, v in row.items()
                if k is not None  # DictReader adds None key for overflow cols
            }
            rows.append(clean_row)

        if not rows:
            return None, (
                "CSV parsed successfully but contains no data rows. "
                "Make sure there is at least one row below the header."
            )

        # Validate that headers were detected (non-empty).
        if reader.fieldnames is None or all(
            f is None or f.strip() == "" for f in reader.fieldnames
        ):
            return None, (
                "CSV header row appears to be empty or unreadable. "
                "The first row must contain column names."
            )

        return rows, None

    except csv.Error as e:
        return None, (
            f"CSV parse error: {e}.\n"
            f"Hint: Make sure the file uses consistent delimiters (comma, tab, "
            f"semicolon, or pipe) and that quoted fields are properly closed."
        )
    except Exception as e:
        return None, (
            f"Unexpected error while parsing CSV: {e}.\n"
            f"Please check your input and try again."
        )


# ---------------------------------------------------------------------------
# YAML parser
# ---------------------------------------------------------------------------

def _parse_yaml(raw: str) -> tuple[Any, str | None]:
    """Parse a YAML string into a Python dict/list/scalar via PyYAML's
    safe_load (never the plain loader — safe_load refuses to construct
    arbitrary Python objects from tags like `!!python/object`, which
    matters here since this is user-pasted text, not a trusted config
    file on disk).

    A `---`-separated multi-document YAML file (e.g. a Kubernetes
    manifest) is parsed as a LIST of documents, one entry per document
    — the same "one root value, but it can be a list" shape CSV's
    list-of-rows already uses — rather than raising on anything but a
    single document. A single document stays its own bare value (dict/
    list/scalar), not wrapped in a one-element list, since that's by
    far the common case (an ordinary config file) and wrapping it would
    surprise anyone comparing two plain single-document YAML files.
    """
    try:
        docs = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            line_num = mark.line + 1  # PyYAML's mark is 0-indexed
            snippet = _get_snippet(raw, line_num)
            problem = getattr(e, "problem", None) or str(e)
            return None, (
                f"YAML parse error on line {line_num}, column {mark.column + 1}: {problem}.\n"
                f"  Near: {snippet}\n"
                f"Hint: YAML is indentation-sensitive — check that nested lines "
                f"line up consistently, and that any value containing a colon "
                f"or '#' is quoted."
            )
        return None, f"YAML parse error: {e}"

    if not docs or all(d is None for d in docs):
        return None, (
            "YAML parsed successfully but produced no data (empty document)."
        )
    data = docs[0] if len(docs) == 1 else docs
    return data, None


# ---------------------------------------------------------------------------
# .env parser
# ---------------------------------------------------------------------------

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _parse_env(raw: str) -> tuple[dict, str | None]:
    """Parse a .env-style `KEY=VALUE` file into a flat dict.

    Supports: an optional leading `export `, full-line `#` comments,
    blank lines, single/double-quoted values (quotes are stripped and
    the inner text is kept as a literal string — NOT further type-
    coerced, the same convention real dotenv parsers use, since an
    explicit quote is the author saying "treat this as text"), and a
    trailing ` #comment` on an unquoted value. An unquoted value is run
    through the same `_coerce_csv_value()` CSV already uses, so
    `PORT=8080` compares naturally against a YAML/JSON config's
    `"port": 8080` instead of always being the string `"8080"` — .env
    has no real type system either, same problem CSV already solves.
    A key assigned more than once keeps its LAST value, matching real
    shell/.env sourcing semantics (not an error — intentional overrides
    are a normal, valid pattern in real .env files).

    Explicitly NOT supported (reads the file's literal text, doesn't
    emulate a shell sourcing it): multi-line values, `${OTHER_VAR}`
    interpolation, and backslash escaping inside unquoted values.
    """
    result: dict[str, Any] = {}
    for line_num, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            snippet = _get_snippet(raw, line_num)
            return None, (
                f".env parse error on line {line_num}: expected KEY=VALUE.\n"
                f"  Near: {snippet}\n"
                f"Hint: Each non-comment line must look like NAME=value "
                f"(an optional leading 'export ' is fine)."
            )
        key, value = m.group(1), m.group(2).strip()
        if value and value[0] not in ("'", '"'):
            if value.startswith("#"):
                value = ""
            else:
                hash_pos = value.find(" #")
                if hash_pos != -1:
                    value = value[:hash_pos].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = _coerce_csv_value(value)
        result[key] = value
    if not result:
        return None, (
            ".env parsed successfully but contains no variables. "
            "Make sure there is at least one NAME=value line."
        )
    return result, None


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _get_snippet(raw: str, line_num: int, context: int = 60) -> str:
    """
    Return a short snippet of *raw* centred on *line_num* (1-based).
    Useful for error messages so the user can see exactly where things broke.
    """
    lines = raw.splitlines()
    idx = line_num - 1
    if 0 <= idx < len(lines):
        snippet = lines[idx].strip()
        if len(snippet) > context:
            snippet = snippet[:context] + "…"
        return repr(snippet)
    return "(line not available)"
