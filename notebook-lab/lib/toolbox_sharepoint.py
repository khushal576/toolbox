"""
toolbox_sharepoint — read SharePoint lists into pandas and STAGE edits from a notebook cell.

    import toolbox_sharepoint as sp
    sp.lists("Contoso")                          # which lists the connection offers
    df = sp.read("Contoso", "Team Site", "Tasks")   # one row per item, index = item id, columns = internal names
    df.loc["3", "Status"] = "Done"
    df["Priority"] = df["Priority"].clip(upper=5)
    sp.stage(df)                                 # records only the cells you changed — nothing is written yet

Then open the SharePoint tool: the changes are in its "Review" screen, shown as old → new, and only your approval there
writes them. This notebook never holds a token or a password: it talks to the SharePoint tool over HTTP and that tool
holds the connection. There is no delete: removing rows from the DataFrame does nothing, and nothing here can delete an
item. Only plain text/number/yes-no/date/choice columns can be staged; person, lookup, link and calculated columns are
read-only.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

import pandas as pd

BASE = os.environ.get("SP_BRIDGE_URL", "").rstrip("/")
TIMEOUT = 120


class SharePointError(RuntimeError):
    pass


def _call(method: str, path: str, body: Any = None, params: Optional[dict] = None) -> Any:
    if not BASE:
        raise SharePointError("The SharePoint tool is not reachable from this notebook (SP_BRIDGE_URL is not set).")
    url = f"{BASE}/{path}" + ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        raise SharePointError(detail or f"The SharePoint tool answered {exc.code}.") from None
    except urllib.error.URLError as exc:
        raise SharePointError(f"Could not reach the SharePoint tool ({exc.reason}).") from None


def _find(rows: list[dict], wanted: str, label: str, *keys: str) -> dict:
    w = wanted.strip().lower()
    for k in keys:
        hit = [r for r in rows if str(r.get(k, "")).lower() == w]
        if len(hit) == 1:
            return hit[0]
    hit = [r for r in rows if any(w in str(r.get(k, "")).lower() for k in keys)]
    if len(hit) == 1:
        return hit[0]
    names = ", ".join(str(r.get(keys[0])) for r in rows[:15])
    raise SharePointError(f"{'No' if not hit else 'More than one'} {label} matches “{wanted}”. Available: {names}")


def connections() -> pd.DataFrame:
    rows = _call("GET", "connections")["connections"]
    return pd.DataFrame([{"name": r["name"], "sign_in": r.get("auth"), "read_only": r.get("read_only"), "signed_in": r.get("signed_in"),
                          "sites": len(r.get("sites", []))} for r in rows])


def _conn(name: str) -> dict:
    return _find(_call("GET", "connections")["connections"], name, "connection", "name", "id")


def _list(conn_name: str, site: str, lst: str) -> tuple[dict, dict, dict]:
    c = _conn(conn_name)
    sites = _call("GET", f"connections/{c['id']}/lists")["sites"]
    ok = [{"name": o["site"]["name"], "url": o["site"]["url"], "id": o["site"]["id"], "lists": o["lists"]} for o in sites if "error" not in o["site"]]
    s = _find(ok, site, "site", "name", "url", "id")
    l = _find(s["lists"], lst, "list", "name", "internal", "id")
    return c, s, l


def lists(connection: str) -> pd.DataFrame:
    c = _conn(connection)
    out = []
    for o in _call("GET", f"connections/{c['id']}/lists")["sites"]:
        for l in o["lists"]:
            out.append({"site": o["site"].get("name"), "list": l["name"], "template": l.get("template"), "staged": l.get("staged", 0)})
    return pd.DataFrame(out)


def schema(connection: str, site: str, list: str) -> pd.DataFrame:  # noqa: A002 - reads naturally: sp.schema(c, s, l)
    c, s, l = _list(connection, site, list)
    cols = _call("GET", "schema", params={"conn": c["id"], "site": s["id"], "list": l["id"]})["columns"]
    return pd.DataFrame(cols)[["display", "name", "kind", "required", "editable", "hidden", "system", "choices", "why"]]


def read(connection: str, site: str, list: str, max_rows: int = 100_000, system: bool = False) -> pd.DataFrame:  # noqa: A002
    """One row per item (index = item id as text), one column per list column (by internal name). `system=True` adds hidden
    and system columns. Keep the returned frame: `stage(df)` compares against what was read."""
    c, s, l = _list(connection, site, list)
    q = {"conn": c["id"], "site": s["id"], "list": l["id"]}
    cols = _call("GET", "schema", params=q)["columns"]
    use = [d for d in cols if system or (not d["hidden"] and not d["system"])]
    items, cursor = [], None
    while len(items) < max_rows:
        page = _call("GET", "items", params={**q, "top": 500, "cursor": cursor})
        items += page["items"]
        cursor = page["next"]
        if not cursor:
            break
    keys = [d["key"] for d in use]
    df = pd.DataFrame([{k: it["fields"].get(k) for k in keys} for it in items], columns=keys, index=pd.Index([it["id"] for it in items], name="ID", dtype="object"))
    editable = [d["key"] for d in use if d["editable"]]
    df.attrs["sharepoint"] = {"conn": c["id"], "site": s["id"], "list": l["id"], "name": l["name"], "editable": editable,
                              "snapshot": {it["id"]: {k: _py(it["fields"].get(k)) for k in editable} for it in items}}
    if cursor:
        print(f"Only the first {len(items):,} rows were read (max_rows={max_rows:,}).")
    return df


def _py(v: Any) -> Any:
    """A cell value as plain JSON-able Python (NaN → None, numpy → python, timestamps → UTC text)."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        if pd.isna(v):
            return None
        v = v.tz_localize("UTC") if v.tzinfo is None else v.tz_convert("UTC")
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if v is pd.NaT:
        return None
    if hasattr(v, "tolist") and not isinstance(v, (str, bytes)):
        v = v.tolist()
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        v = v.item()
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    return v


def stage(df: pd.DataFrame, batch: int = 500) -> dict[str, Any]:
    """Record every cell you changed since `read` (only editable columns) as a staged change. Nothing is written to
    SharePoint — approve it in the SharePoint tool's Review screen."""
    meta = df.attrs.get("sharepoint")
    if not meta:
        raise SharePointError("This DataFrame did not come from sp.read(...) — read the list first, then edit that frame.")
    snap, editable = meta["snapshot"], [c for c in meta["editable"] if c in df.columns]
    rows, new_rows = [], 0
    for item_id, row in zip(df.index, df[editable].itertuples(index=False, name=None)):
        old = snap.get(str(item_id))
        if old is None:
            new_rows += 1
            continue
        fields = {c: _py(v) for c, v in zip(editable, row) if _py(v) != old.get(c)}
        if fields:
            rows.append({"item_id": str(item_id), "fields": fields, "old": {c: old.get(c) for c in fields}})
    total = {"staged": 0, "unchanged": 0, "problem_count": 0, "problems": []}
    for i in range(0, len(rows), batch):
        r = _call("POST", "staged/bulk", {"conn": meta["conn"], "site": meta["site"], "list": meta["list"], "rows": rows[i:i + batch]})
        for k in ("staged", "unchanged", "problem_count"):
            total[k] += r[k]
        total["problems"] += r["problems"]
    total["rows"] = len(rows)
    total["ignored_new_rows"] = new_rows
    msg = f"Staged {total['staged']} cell(s) in {len(rows)} row(s) of “{meta['name']}”."
    if total["problem_count"]:
        msg += f" {total['problem_count']} cell(s) were refused — see the 'problems' list."
    if new_rows:
        msg += f" {new_rows} new row(s) were ignored (add items in the SharePoint tool)."
    print(msg + " Nothing is written yet: open the SharePoint tool and use Review to approve.")
    return total


def pending(connection: str, site: str, list: str) -> pd.DataFrame:  # noqa: A002
    """What is staged for a list right now (from the page or from Python)."""
    c, s, l = _list(connection, site, list)
    rv = _call("GET", "staged", params={"conn": c["id"], "site": s["id"], "list": l["id"]})
    return pd.DataFrame([{"item": r["item_id"] or "new", "column": f["display"], "old": f["old"], "new": f["new"], "source": r["source"], "problem": f["error"]}
                         for r in rv["rows"] for f in r["fields"]])


def discard(connection: str, site: str, list: str) -> int:  # noqa: A002
    """Throw away everything staged for the list. Never touches SharePoint."""
    c, s, l = _list(connection, site, list)
    return _call("POST", "staged/discard", {"conn": c["id"], "site": s["id"], "list": l["id"]})["discarded"]
