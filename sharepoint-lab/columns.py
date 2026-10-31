"""
sharepoint-lab/columns.py

What a SharePoint list column IS and what may be written to it — pure functions, no network.

  describe(graph_column)  → a flat dict the page and the checks both use (kind, editable + why not, choices, …)
  coerce(desc, value)     → the canonical value that will be compared and written, or ValueError with a plain sentence
  same(desc, a, b)        → "is this the same value?" (numbers by value, dates as instants, multi-choice as a set, empty == empty)
  payload(desc, value)    → the Graph `fields` entries to send (multi-choice needs an @odata.type annotation)

Editable kinds: text, note (multi-line), number, currency, boolean, date, datetime, choice (single / multi).
Everything else — lookup, person, hyperlink, calculated, managed metadata, location, thumbnail, approval status and every
system column (ID, Created, Modified, Author, Editor, …) — is shown but read-only: writing those needs ids the tool does
not resolve, and a wrong guess would put wrong data in a shared list.

Dates travel as UTC instants ("2026-10-30T18:30:00Z", exactly what Graph returns); the page converts to and from the
browser's time zone for date-only columns. A bare "2026-10-30" sent by an API/Python caller means UTC midnight.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

FACETS = ("text", "number", "currency", "boolean", "dateTime", "choice", "lookup", "personOrGroup", "calculated",
          "hyperlinkOrPicture", "geolocation", "term", "thumbnail", "contentApprovalStatus")

# Columns every list has; never edited through this tool even though some are technically writable.
SYSTEM = {"ID", "Id", "Created", "Modified", "Author", "Editor", "_UIVersionString", "_UIVersion", "Attachments",
          "ContentType", "ContentTypeId", "FileLeafRef", "FileRef", "FileDirRef", "_ComplianceFlags", "_ComplianceTag",
          "_ComplianceTagWrittenTime", "_ComplianceTagUserId", "_IsRecord", "_ColorTag", "AppAuthor", "AppEditor",
          "Edit", "LinkTitleNoMenu", "LinkTitle", "DocIcon", "ItemChildCount", "FolderChildCount", "_VirusStatus",
          "_VirusInfo", "_VirusVendorID", "_CommentCount", "_LikeCount", "UniqueId", "FSObjType", "SortBehavior",
          "CheckedOutUserId", "IsCheckedoutToLocal", "CheckoutUser", "ScopeId", "_Level", "_IsCurrentVersion", "GUID",
          "WorkflowVersion", "WorkflowInstanceID", "owshiddenversion", "MetaInfo", "_ModerationStatus",
          "_ModerationComments", "ParentVersionString", "ParentLeafName", "_HasCopyDestinations", "_CopySource",
          "InstanceID", "Order", "SelectTitle", "SelectFilename", "ServerUrl", "EncodedAbsUrl", "BaseName", "ProgId",
          "HTML_x0020_File_x0020_Type", "File_x0020_Type", "_SharedFileIndex", "_dlc_DocId", "_dlc_DocIdUrl",
          "_dlc_DocIdPersistId", "TriggerFlowInfo", "_ExtendedDescription", "AccessPolicy", "_DisplayName", "OData__UIVersionString"}
HIDDEN_GROUPS = {"_Hidden"}

_ISO_OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def key_of(d: dict[str, Any]) -> str:
    """The property name this column has inside an item's `fields` (lookups and people are stored as <name>LookupId)."""
    return d["name"] + "LookupId" if d["kind"] in ("lookup", "person") else d["name"]


def describe(col: dict[str, Any]) -> dict[str, Any]:
    facet = next((f for f in FACETS if f in col), None)
    name = col.get("name") or ""
    d: dict[str, Any] = {
        "name": name, "display": col.get("displayName") or name, "group": col.get("columnGroup") or "",
        "description": col.get("description") or "", "required": bool(col.get("required")), "indexed": bool(col.get("indexed")),
        "hidden": bool(col.get("hidden")), "read_only": bool(col.get("readOnly")), "choices": [], "multi": False,
        "allow_text": False, "maximum": None, "minimum": None, "max_length": None, "default": (col.get("defaultValue") or {}).get("value"),
    }
    if facet == "text":
        t = col["text"]
        d["kind"] = "note" if t.get("allowMultipleLines") else "text"
        d["max_length"] = None if d["kind"] == "note" else t.get("maxLength", 255)
    elif facet == "number":
        d["kind"], n = "number", col["number"]
        d["minimum"], d["maximum"] = n.get("minimum"), n.get("maximum")
    elif facet == "currency":
        d["kind"] = "currency"
    elif facet == "boolean":
        d["kind"] = "boolean"
    elif facet == "dateTime":
        d["kind"] = "date" if (col["dateTime"].get("format") == "dateOnly") else "datetime"
    elif facet == "choice":
        c = col["choice"]
        d["kind"], d["choices"] = "choice", list(c.get("choices") or [])
        d["allow_text"] = bool(c.get("allowTextEntry"))
        d["multi"] = c.get("displayAs") == "checkBoxes"
    elif facet == "lookup":
        d["kind"], d["multi"] = "lookup", bool(col["lookup"].get("allowMultipleValues"))
        d["lookup"] = {"list_id": col["lookup"].get("listId"), "column": col["lookup"].get("columnName")}
    elif facet == "personOrGroup":
        d["kind"], d["multi"] = "person", bool(col["personOrGroup"].get("allowMultipleSelection"))
    elif facet == "calculated":
        d["kind"] = "calculated"
    elif facet == "hyperlinkOrPicture":
        d["kind"] = "link"
    elif facet == "geolocation":
        d["kind"] = "location"
    elif facet == "term":
        d["kind"] = "term"
    elif facet == "thumbnail":
        d["kind"] = "image"
    elif facet == "contentApprovalStatus":
        d["kind"] = "approval"
    else:
        d["kind"] = "other"
    d["system"] = name in SYSTEM or d["group"] in HIDDEN_GROUPS
    d["key"] = key_of(d)
    d["editable"], d["why"] = _editable(d)
    return d


def _editable(d: dict[str, Any]) -> tuple[bool, str]:
    if d["system"]:
        return False, "system column"
    if d["read_only"]:
        return False, "read-only in SharePoint"
    if d["kind"] in ("calculated",):
        return False, "calculated column"
    if d["kind"] in ("lookup", "person", "link", "location", "term", "image", "approval", "other"):
        return False, f"{d['kind']} columns are shown but not edited here"
    return True, ""


def describe_all(cols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [describe(c) for c in cols if c.get("name")]
    rank = {"Title": 0, "LinkTitle": 0}
    out.sort(key=lambda d: (rank.get(d["name"], 3 if d["system"] else 1 if d["group"] == "Custom Columns" else 2), d["display"].lower()))
    return out


# ---------------------------------------------------------------- values
def _num(v: Any) -> float:
    if isinstance(v, bool):
        raise ValueError("Not a number.")
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = str(v).strip().replace(",", "") if not re.fullmatch(r"\s*-?\d+,\d+\s*", str(v)) else str(v).strip().replace(",", ".")
        try:
            f = float(s)
        except ValueError:
            raise ValueError(f"“{str(v)[:30]}” is not a number.") from None
    if math.isnan(f) or math.isinf(f):
        raise ValueError("Not a number.")
    return f


def _instant(v: Any) -> str:
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T00:00:00Z"
    elif not _ISO_OFFSET.search(s):
        s += "Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"“{str(v)[:30]}” is not a date (use 2026-10-30 or 2026-10-30T14:30:00Z).") from None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank(kind: str, v: Any) -> bool:
    """Empty means "clear the field". Text keeps whitespace-only strings (they are real values); everything else trims."""
    if v is None or (isinstance(v, (list, tuple)) and not v) or v == "":
        return True
    return isinstance(v, str) and v.strip() == "" and kind not in ("text", "note")


def coerce(d: dict[str, Any], value: Any) -> Any:
    """Canonical value for column `d`, or ValueError(plain sentence). None = clear the field."""
    if not d["editable"]:
        raise ValueError(f"“{d['display']}” can't be edited here ({d['why']}).")
    kind = d["kind"]
    if _blank(kind, value):
        if d["required"]:
            raise ValueError(f"“{d['display']}” is required — it can't be empty.")
        return None
    if kind in ("text", "note"):
        s = str(value)
        if d["max_length"] and len(s) > d["max_length"]:
            raise ValueError(f"Too long: {len(s)} characters, the column allows {d['max_length']}.")
        return s
    if kind in ("number", "currency"):
        f = _num(value)
        if d["minimum"] is not None and f < d["minimum"]:
            raise ValueError(f"Below the minimum ({d['minimum']}).")
        if d["maximum"] is not None and f > d["maximum"]:
            raise ValueError(f"Above the maximum ({d['maximum']}).")
        return int(f) if f.is_integer() and abs(f) < 1e15 else f
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "yes", "y", "1", "on"):
            return True
        if s in ("false", "no", "n", "0", "off"):
            return False
        raise ValueError("Use true or false.")
    if kind in ("date", "datetime"):
        return _instant(value)
    if kind == "choice":
        vals = list(value) if isinstance(value, (list, tuple)) else [value]
        if len(vals) > 1 and not d["multi"]:
            raise ValueError("This column takes a single choice.")
        out = []
        for v in vals:
            s = str(v)
            if s not in d["choices"] and not d["allow_text"]:
                raise ValueError(f"“{s[:40]}” is not one of the choices ({', '.join(d['choices'][:8])}{'…' if len(d['choices']) > 8 else ''}).")
            out.append(s)
        return out if d["multi"] else out[0]
    raise ValueError("This column type can't be edited here.")  # pragma: no cover


def normalize_current(d: dict[str, Any], value: Any) -> Any:
    """A value as SharePoint returned it → the same canonical form `coerce` produces (never raises: unknown → as is)."""
    kind = d["kind"]
    if _blank(kind, value):
        return None
    try:
        if kind in ("date", "datetime"):
            return _instant(value)
        if kind in ("number", "currency"):
            f = _num(value)
            return int(f) if f.is_integer() and abs(f) < 1e15 else f
        if kind == "boolean":
            return bool(value)
        if kind == "choice":
            return list(value) if isinstance(value, (list, tuple)) else (
                [str(value)] if d["multi"] else str(value))
        if kind in ("text", "note"):
            return str(value)
    except ValueError:
        pass
    return value


def same(d: dict[str, Any], a: Any, b: Any) -> bool:
    a, b = normalize_current(d, a), normalize_current(d, b)
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return a == b


def payload(d: dict[str, Any], value: Any) -> dict[str, Any]:
    """Graph `fields` entries for writing `value` (already coerced) to this column."""
    if d["kind"] == "choice" and d["multi"]:
        return {d["name"]: value or [], d["name"] + "@odata.type": "Collection(Edm.String)"}
    return {d["name"]: value}
