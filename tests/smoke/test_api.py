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
