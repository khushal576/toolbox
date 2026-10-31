"""
A small in-memory stand-in for Microsoft sign-in + Graph SharePoint lists, for tests and for trying the page without a
tenant. Two ways to use it:

    transport = httpx.MockTransport(FakeGraph().handle)         # unit tests: set service.TRANSPORT = transport
    uvicorn tests.unit.fake_graph:asgi_app                       # a real HTTP server (the page, in a browser)

It implements exactly what sharepoint-lab calls: token (client secret / refresh / device code), sites by path, lists,
columns, items (paged with @odata.nextLink), a single item, PATCH …/fields, POST …/items and $batch. It records every call
in `.calls` and answers any DELETE with 405 — tests assert the tool never sends one.
"""

from __future__ import annotations

import copy
import json
import re
import urllib.parse
from typing import Any, Optional

import httpx

HOST = "contoso.sharepoint.com"
SITE_ID = f"{HOST},11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
SITE2_ID = f"{HOST},33333333-3333-3333-3333-333333333333,44444444-4444-4444-4444-444444444444"
TASKS = "aaaaaaaa-0000-0000-0000-000000000001"
CONTACTS = "aaaaaaaa-0000-0000-0000-000000000002"
HIDDEN = "aaaaaaaa-0000-0000-0000-000000000003"
GOOD_SECRET = "good-secret"
CLIENT = "00000000-0000-0000-0000-0000000000aa"
TENANT = "11111111-2222-3333-4444-555555555555"


def _col(name: str, display: str, **facet: Any) -> dict[str, Any]:
    c = {"id": f"c-{name}", "name": name, "displayName": display, "columnGroup": "Custom Columns", "hidden": False, "readOnly": False,
         "required": False, "indexed": False}
    c.update(facet)
    return c


def tasks_columns() -> list[dict[str, Any]]:
    sysg = {"columnGroup": "Core Document Columns"}
    return [
        _col("Title", "Title", text={"maxLength": 40, "allowMultipleLines": False}, required=True, columnGroup="Base Columns"),
        _col("Status", "Status", choice={"choices": ["Open", "Done", "Blocked"], "allowTextEntry": False, "displayAs": "dropDownMenu"}),
        _col("Priority", "Priority", number={"minimum": 1, "maximum": 5}),
        _col("DueDate", "Due date", dateTime={"format": "dateOnly", "displayAs": "default"}),
        _col("Done", "Done", boolean={}),
        _col("Notes", "Notes", text={"allowMultipleLines": True}),
        _col("Tags", "Tags", choice={"choices": ["a", "b", "c"], "allowTextEntry": False, "displayAs": "checkBoxes"}),
        _col("Owner", "Owner", personOrGroup={"allowMultipleSelection": False}),
        _col("Project", "Project", lookup={"listId": CONTACTS, "columnName": "Title", "allowMultipleValues": False}),
        _col("Total", "Total", calculated={"formula": "=[Priority]*2", "outputType": "number"}),
        _col("Site", "Site link", hyperlinkOrPicture={"isPicture": False}),
        _col("ID", "ID", number={}, readOnly=True, **sysg),
        _col("Created", "Created", dateTime={"format": "dateTime"}, readOnly=True, **sysg),
        _col("Modified", "Modified", dateTime={"format": "dateTime"}, readOnly=True, **sysg),
        _col("Author", "Created By", personOrGroup={}, readOnly=True, **sysg),
        _col("Attachments", "Attachments", boolean={}, readOnly=True, **sysg),
        _col("_UIVersionString", "Version", text={}, readOnly=True, hidden=True, columnGroup="_Hidden"),
    ]


def _task(i: int) -> dict[str, Any]:
    return {"id": str(i), "Title": f"Task {i}", "Status": ["Open", "Done", "Blocked"][i % 3], "Priority": 1 + i % 5,
            "DueDate": f"2026-11-{1 + i % 28:02d}T00:00:00Z", "Done": i % 2 == 0, "Notes": f"note {i}\nline two" if i % 4 == 0 else None,
            "Tags": ["a", "b"] if i % 3 == 0 else [], "OwnerLookupId": str(10 + i % 3), "ProjectLookupId": str(1 + i % 2),
            "Total": (1 + i % 5) * 2, "Created": "2026-01-02T08:00:00Z", "Modified": "2026-02-03T09:00:00Z", "AuthorLookupId": "7",
            "Attachments": False, "_UIVersionString": "1.0"}


class FakeGraph:
    def __init__(self, n_tasks: int = 25, page: int = 10) -> None:
        self.calls: list[tuple[str, str]] = []
        self.tasks: dict[str, dict[str, Any]] = {str(i): _task(i) for i in range(1, n_tasks + 1)}
        self.next_id = n_tasks + 1
        self.page = page
        self.refresh_n = 0
        self.valid_refresh = {"rt-0"}
        self.device_polls_before_ok = 1
        self._polls = 0
        self.throttle = 0           # the next N Graph requests answer 429
        self.batch_throttle = 0     # the next N batch SUB-requests answer 429
        self.fail_patch_for: set[str] = set()
        self.expired_tokens = False
        self.public_base = "https://graph.microsoft.com/v1.0"   # what @odata.nextLink points at (the page test sets its own host)

    # ------------------------------------------------------------ httpx entry point
    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content and request.headers.get("content-type", "").startswith("application/json") else None
        form = dict(urllib.parse.parse_qsl(request.content.decode())) if request.content and body is None else {}
        status, payload, headers = self.dispatch(request.method, request.url.path, dict(request.url.params), dict(request.headers), body, form, str(request.url))
        return httpx.Response(status, json=payload, headers=headers)

    # ------------------------------------------------------------ routing
    def dispatch(self, method: str, path: str, query: dict[str, str], headers: dict[str, str], body: Any, form: dict[str, str], url: str = "") -> tuple[int, Any, dict[str, str]]:
        self.calls.append((method, path))
        if method == "DELETE":
            return 405, {"error": {"code": "methodNotAllowed", "message": "no deletes here"}}, {}
        m = re.match(r"^/([^/]+)/oauth2/v2\.0/(token|devicecode)$", path)
        if m:
            return self._oauth(m.group(2), form)
        if not path.startswith("/v1.0"):
            return 404, {"error": {"code": "notFound", "message": "x"}}, {}
        if self.expired_tokens or headers.get("authorization") != "Bearer at-good":
            self.expired_tokens = False
            return 401, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty or expired."}}, {}
        if self.throttle:
            self.throttle -= 1
            return 429, {"error": {"code": "activityLimitReached", "message": "slow down"}}, {"Retry-After": "1"}
        s, p, h = self.graph(method, path[len("/v1.0"):], query, body, url)
        return s, p, h

    def _oauth(self, leaf: str, form: dict[str, str]) -> tuple[int, Any, dict[str, str]]:
        if leaf == "devicecode":
            return 200, {"device_code": "dc-1", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900, "interval": 1}, {}
        g = form.get("grant_type")
        tok = lambda **kw: (200, {"access_token": "at-good", "expires_in": 3600, "token_type": "Bearer", **kw}, {})
        if g == "client_credentials":
            if form.get("client_secret") != GOOD_SECRET:
                return 401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided.\r\nTrace ID: x"}, {}
            return tok()
        if g == "refresh_token":
            if form.get("refresh_token") not in self.valid_refresh:
                return 400, {"error": "invalid_grant", "error_description": "AADSTS70008: The refresh token has expired."}, {}
            self.refresh_n += 1
            new = f"rt-{self.refresh_n}"
            self.valid_refresh.add(new)
            return tok(refresh_token=new)
        if g == "urn:ietf:params:oauth:grant-type:device_code":
            self._polls += 1
            if self._polls <= self.device_polls_before_ok:
                return 400, {"error": "authorization_pending", "error_description": "pending"}, {}
            self.valid_refresh.add("rt-dev")
            return tok(refresh_token="rt-dev")
        return 400, {"error": "unsupported_grant_type"}, {}

    def graph(self, method: str, path: str, query: dict[str, str], body: Any, url: str) -> tuple[int, Any, dict[str, str]]:
        if method == "POST" and path == "/$batch":
            out = []
            for r in body["requests"]:
                if self.batch_throttle:
                    self.batch_throttle -= 1
                    out.append({"id": r["id"], "status": 429, "headers": {"Retry-After": "1"}, "body": {"error": {"code": "tooManyRequests", "message": "slow"}}})
                    continue
                u = urllib.parse.urlsplit(r["url"])
                s, p, _ = self.graph(r["method"], u.path, dict(urllib.parse.parse_qsl(u.query)), r.get("body"), r["url"])
                out.append({"id": r["id"], "status": s, "body": p})
            return 200, {"responses": out}, {}
        m = re.match(r"^/sites/([^/:]+):(/.*)?$", path) or re.match(r"^/sites/([^/:]+)$", path)
        if m and method == "GET" and "/lists" not in path:
            host, sp = m.group(1), (m.group(2) if m.re.groups > 1 else "") or ""
            if host != HOST:
                return 404, {"error": {"code": "itemNotFound", "message": "Requested site could not be found"}}, {}
            sites = {"/sites/Team": (SITE_ID, "Team Site"), "/sites/Ops": (SITE2_ID, "Operations"), "": (SITE_ID, "Root")}
            if sp not in sites:
                return 404, {"error": {"code": "itemNotFound", "message": "Requested site could not be found"}}, {}
            sid, name = sites[sp]
            return 200, {"id": sid, "displayName": name, "name": name, "webUrl": f"https://{HOST}{sp}"}, {}
        m = re.match(r"^/sites/([^/]+)/lists$", path)
        if m and method == "GET":
            if m.group(1) == SITE2_ID:
                return 200, {"value": [{"id": CONTACTS, "name": "Contacts", "displayName": "Contacts", "list": {"template": "genericList", "hidden": False}}]}, {}
            return 200, {"value": [
                {"id": TASKS, "name": "Tasks", "displayName": "Tasks", "webUrl": f"https://{HOST}/sites/Team/Lists/Tasks", "list": {"template": "genericList", "hidden": False}},
                {"id": CONTACTS, "name": "Contacts", "displayName": "Contacts", "list": {"template": "genericList", "hidden": False}},
                {"id": HIDDEN, "name": "appdata", "displayName": "appdata", "list": {"template": "genericList", "hidden": True}}]}, {}
        m = re.match(r"^/sites/([^/]+)/lists/([^/]+)/columns$", path)
        if m and method == "GET":
            return 200, {"value": tasks_columns() if m.group(2) == TASKS else [_col("Title", "Title", text={"maxLength": 255}, required=True)]}, {}
        m = re.match(r"^/sites/([^/]+)/lists/([^/]+)/items$", path)
        if m and method == "GET":
            keys = sorted(self.tasks, key=int)
            start = int(query.get("$skiptoken", "0"))
            top = int(query.get("$top", "100"))
            chunk = keys[start:start + min(top, self.page)]
            res: dict[str, Any] = {"value": [self._item(k) for k in chunk]}
            if start + len(chunk) < len(keys):
                res["@odata.nextLink"] = f"{self.public_base}/sites/{m.group(1)}/lists/{m.group(2)}/items?$skiptoken={start + len(chunk)}&$expand=fields&$top={top}"
            return 200, res, {}
        if m and method == "POST":
            fields = (body or {}).get("fields", {})
            err = self._validate(fields)
            if err:
                return 400, {"error": {"code": "invalidRequest", "message": err}}, {}
            i = str(self.next_id)
            self.next_id += 1
            self.tasks[i] = {**_task(0), "id": i, "Title": "", "Status": None, "Priority": None, "Done": False, "DueDate": None, "Tags": [], "Notes": None, "Total": None}
            self._apply(i, fields)
            return 201, self._item(i), {}
        m = re.match(r"^/sites/([^/]+)/lists/([^/]+)/items/([^/]+)$", path)
        if m and method == "GET":
            if m.group(3) not in self.tasks:
                return 404, {"error": {"code": "itemNotFound", "message": "The item was not found."}}, {}
            item = self._item(m.group(3))
            sel = re.search(r"fields\(\$select=([^)]*)\)", query.get("$expand", ""))
            if sel:
                want = set(sel.group(1).split(","))
                item["fields"] = {k: v for k, v in item["fields"].items() if k in want}
            return 200, item, {}
        m = re.match(r"^/sites/([^/]+)/lists/([^/]+)/items/([^/]+)/fields$", path)
        if m and method == "PATCH":
            i = m.group(3)
            if i not in self.tasks:
                return 404, {"error": {"code": "itemNotFound", "message": "The item was not found."}}, {}
            if i in self.fail_patch_for:
                return 423, {"error": {"code": "resourceLocked", "message": "The file is locked for editing."}}, {}
            err = self._validate(body or {})
            if err:
                return 400, {"error": {"code": "invalidRequest", "message": err}}, {}
            self._apply(i, body or {})
            return 200, self._item(i)["fields"], {}
        return 404, {"error": {"code": "notFound", "message": f"fake graph: {method} {path}"}}, {}

    # ------------------------------------------------------------ data
    def _item(self, i: str) -> dict[str, Any]:
        f = copy.deepcopy(self.tasks[i])
        return {"id": i, "eTag": f'"{i},1"', "webUrl": f"https://{HOST}/sites/Team/Lists/Tasks/{i}_.000", "createdBy": {"user": {"displayName": "Ada"}},
                "lastModifiedBy": {"user": {"displayName": "Bob"}}, "fields": f}

    def _validate(self, fields: dict[str, Any]) -> Optional[str]:
        cols = {c["name"]: c for c in tasks_columns()}
        for k, v in fields.items():
            if k.endswith("@odata.type"):
                continue
            c = cols.get(k)
            if c is None:
                return f"Field '{k}' is not recognized"
            if c.get("readOnly") or "calculated" in c:
                return f"Field '{k}' cannot be written"
            if "choice" in c and c["choice"]["displayAs"] == "checkBoxes" and not isinstance(v, list):
                return f"Field '{k}' needs a collection"
            if "choice" in c and c["choice"]["displayAs"] == "checkBoxes" and fields.get(k + "@odata.type") != "Collection(Edm.String)":
                return f"The field '{k}' requires an odata.type annotation"
            if "choice" in c and c["choice"]["displayAs"] != "checkBoxes" and v is not None and v not in c["choice"]["choices"]:
                return f"Value '{v}' is not a valid choice for '{k}'"
        return None

    def _apply(self, i: str, fields: dict[str, Any]) -> None:
        for k, v in fields.items():
            if not k.endswith("@odata.type"):
                self.tasks[i][k] = v
        if "Priority" in fields and fields["Priority"] is not None:
            self.tasks[i]["Total"] = fields["Priority"] * 2
        self.tasks[i]["Modified"] = "2026-10-30T12:00:00Z"

    def mutate(self, item_id: str, **fields: Any) -> None:
        """Change an item behind the tool's back (conflict tests)."""
        self.tasks[item_id].update(fields)

    # ------------------------------------------------------------ helpers for assertions
    def sent(self, method: str) -> list[str]:
        return [p for m, p in self.calls if m == method]


# ---------------------------------------------------------------- an ASGI wrapper (a real server for browser tests)
def make_asgi(fake: Optional[FakeGraph] = None, prefix: str = ""):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    fg = fake or FakeGraph()

    async def any_route(request: Request) -> JSONResponse:
        raw = await request.body()
        ctype = request.headers.get("content-type", "")
        body = json.loads(raw) if raw and ctype.startswith("application/json") else None
        form = dict(urllib.parse.parse_qsl(raw.decode())) if raw and body is None else {}
        path = request.url.path[len(prefix):] if prefix and request.url.path.startswith(prefix) else request.url.path
        status, payload, headers = fg.dispatch(request.method, path, dict(request.query_params), dict(request.headers), body, form)
        return JSONResponse(payload, status_code=status, headers=headers)

    return Starlette(routes=[Route("/{path:path}", any_route, methods=["GET", "POST", "PATCH", "PUT", "DELETE"])])
