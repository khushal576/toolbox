"""One read-only API call per tool that has a backend. Nothing here changes data or calls outside systems."""

import pytest

from conftest import mounted_tools, request

SMALL_DIFF = {
    "left_data": '[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]',
    "right_data": '[{"id": 1, "name": "a"}, {"id": 2, "name": "B"}]',
    "left_format": "json",
    "right_format": "json",
}
LATEX = r"\documentclass{article}\begin{document}Smoke test.\end{document}"

# (tool, method, path, body, expected content type)
API_CHECKS = [
    ("datadiff-pro", "POST", "/compare", SMALL_DIFF, "application/json"),
    ("df-studio", "GET", "/template/list", None, "application/json"),
    ("sql-studio", "GET", "/status", None, "application/json"),
    ("schema-map", "GET", "/status", None, "application/json"),
    ("schema-map", "GET", "/projects", None, "application/json"),
    ("duck-lab", "GET", "/tables", None, "application/json"),
    ("vault", "GET", "/secrets", None, "application/json"),
    ("data-lake", "GET", "/workspaces", None, "application/json"),
    ("data-lake", "GET", "/catalog", None, "application/json"),
    ("data-lake", "GET", "/history", None, "application/json"),
    ("data-lake", "GET", "/connections", None, "application/json"),
    ("vault", "GET", "/data/catalog", None, "application/json"),
    ("data-syncer", "GET", "/projects", None, "application/json"),
    ("data-syncer", "GET", "/connections", None, "application/json"),
    ("schema-copy", "GET", "/tools", None, "application/json"),
    ("schema-copy", "GET", "/projects", None, "application/json"),
    ("data-dumper", "GET", "/tools", None, "application/json"),
    ("data-dumper", "GET", "/dumps", None, "application/json"),
    ("ssh-sftp", "GET", "/servers", None, "application/json"),
    ("ssh-sftp", "GET", "/transfers", None, "application/json"),
    ("latex-pdf", "GET", "/health", None, "application/json"),
    ("latex-pdf", "POST", "/compile", {"source": LATEX}, "application/pdf"),
]

# Tools with no safe backend call: client-side tools, or tools whose only API reaches outside systems
# (curl-builder's /execute makes a real outbound HTTP request).
PAGE_ONLY = {
    "encode-decode", "subnet-calc", "dns-lookup", "vlan-designer", "packet-journey",
    "header-reference", "http-methods-status", "cookie-lab", "curl-builder",
}


def test_every_tool_is_classified():
    """A new tool must be added to API_CHECKS or PAGE_ONLY, so coverage grows with the toolbox."""
    covered = {t for t, *_ in API_CHECKS} | PAGE_ONLY
    missing = sorted(set(mounted_tools()) - covered)
    assert not missing, f"add an API check or mark page-only in tests/smoke/test_api.py: {missing}"


@pytest.mark.parametrize("tool,method,path,body,ctype", API_CHECKS,
                         ids=[f"{t} {m} {p}" for t, m, p, *_ in API_CHECKS])
def test_api(tool, method, path, body, ctype):
    r = request(method, f"/tools/{tool}{path}", body)
    assert r.status == 200, f"{method} /tools/{tool}{path} returned {r.status}: {r.text[:300]}"
    assert r.ctype == ctype, f"expected {ctype}, got {r.ctype}"
    if ctype == "application/json":
        r.json()  # must parse
    if ctype == "application/pdf":
        assert r.body.startswith(b"%PDF")


def test_latex_engine_present():
    assert request("GET", "/tools/latex-pdf/health").json().get("engine"), "pdflatex missing in the image"


def test_datadiff_finds_the_change():
    out = request("POST", "/tools/datadiff-pro/compare", SMALL_DIFF).json()
    assert "B" in str(out), "compare result should mention the changed value"


def test_datadiff_v1_api_and_replicas():
    """Roadmap D1: the versioned API answers like the old path; health names the replica that answered."""
    v1 = request("POST", "/tools/datadiff-pro/api/v1/compare", SMALL_DIFF).json()
    old = request("POST", "/tools/datadiff-pro/compare", SMALL_DIFF).json()
    assert v1["ok"] and v1["summary"] == old["summary"]
    h = request("GET", "/tools/datadiff-pro/api/v1/health").json()
    assert h["ok"] and h["service"] == "datadiff" and h["replica"]
    assert "/api/v1/compare/structured" in request("GET", "/tools/datadiff-pro/openapi.json").json()["paths"]


def test_data_lake_sql():
    """Roadmap L3: an instant query runs, its stored result pages, and writes are refused (leaves one history row)."""
    r = request("POST", "/tools/data-lake/query", {"sql": "SELECT range AS n FROM range(250)"})
    assert r.status == 200, r.body
    q = r.json()
    assert (q["state"], q["row_count"], len(q["page"]["rows"])) == ("done", 250, 100)
    assert request("GET", f"/tools/data-lake/queries/{q['id']}/rows?offset=240&limit=50").json()["rows"][0] == [240]
    assert request("POST", "/tools/data-lake/query", {"sql": "SELECT * FROM read_csv('/etc/passwd')"}).status == 400
    assert request("POST", "/tools/data-lake/query", {"sql": "DROP TABLE x.y"}).status == 400
    assert request("DELETE", f"/tools/data-lake/history/{q['id']}").status == 200


def test_new_visitors_get_their_own_session():
    """Roadmap L4 finding: the gateway's proxy client kept a cookie jar and handed one visitor's session cookie to
    the next visitor without a cookie (Duck Lab / DataFrame Studio sessions were shared)."""
    sids = {request("GET", "/tools/duck-lab/tables").headers.get("Set-Cookie", "").split(";")[0] for _ in range(3)}
    assert len(sids) == 3 and all(s.startswith("duck_lab_sid=") for s in sids)


def test_vault_data_catalog():
    """Roadmap L1: the Vault's 📦 Data section — workspaces can be created, listed and deleted."""
    import uuid

    name = "smoke_" + uuid.uuid4().hex[:8]
    assert request("GET", "/tools/vault/data").status == 200
    r = request("POST", "/tools/vault/data/workspaces", {"name": name})
    assert r.status == 200 and r.json()["name"] == name
    assert any(w["name"] == name for w in request("GET", "/tools/vault/data").json()["workspaces"])
    assert request("GET", f"/tools/vault/data/workspaces/{name}/tables").json()["tables"] == []
    assert request("POST", "/tools/vault/data/workspaces", {"name": "Bad Name"}).status == 400
    assert request("DELETE", f"/tools/vault/data/workspaces/{name}").status == 200
