"""Every tool page and the home page load; no tool failed to mount."""

import pytest

from conftest import mounted_tools, request

TOOLS = mounted_tools()


def test_tool_list_found():
    assert len(TOOLS) >= 20, f"expected the 20+ mounted tools from main.py, got {TOOLS}"


def test_home_page_has_no_unavailable_tools():
    r = request("GET", "/")
    assert r.status == 200
    # main.py renders a tool whose import failed as <div class="card card-unavailable" ...>
    # (the bare class name also appears in the page's CSS, so match the element, not the word)
    assert 'class="card card-unavailable"' not in r.text, \
        "a tool failed to load — check `docker compose logs toolbox`"


@pytest.mark.parametrize("tool", TOOLS)
def test_home_page_links_tool(tool):
    assert f'href="/tools/{tool}/"' in request("GET", "/").text


@pytest.mark.parametrize("tool", TOOLS)
def test_tool_page_loads(tool):
    r = request("GET", f"/tools/{tool}/")
    assert r.status == 200, f"/tools/{tool}/ returned {r.status}"
    assert r.ctype == "text/html"
    assert "<html" in r.text.lower()
