"""Unit tests for lazy mounts and workspace settings (roadmap A3). Run: python3 -m pytest tests/unit -q"""

import sys
import textwrap
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import DisabledApp, LazyApp, Manifest, load_workspace  # noqa: E402


@pytest.fixture
def fake_plugins(tmp_path, monkeypatch):
    """Two throwaway plugin modules on sys.path: one healthy, one whose import raises."""
    (tmp_path / "lazy_ok_plugin.py").write_text(textwrap.dedent("""
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        IMPORTS = 1
        async def hello(request):
            return PlainTextResponse("hello from " + request.url.path)
        app = Starlette(routes=[Route("/hi", hello)])
    """), encoding="utf-8")
    (tmp_path / "lazy_broken_plugin.py").write_text("raise RuntimeError('boom at import')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in ("lazy_ok_plugin", "lazy_broken_plugin"):
        sys.modules.pop(m, None)
    yield
    for m in ("lazy_ok_plugin", "lazy_broken_plugin"):
        sys.modules.pop(m, None)


def client_for(**mounts):
    return TestClient(Starlette(routes=[Mount(f"/tools/{n}", a) for n, a in mounts.items()]))


def test_module_is_imported_only_on_first_request(fake_plugins):
    lazy = LazyApp("ok", "lazy_ok_plugin")
    c = client_for(ok=lazy)
    assert "lazy_ok_plugin" not in sys.modules and lazy.state == "not_loaded"
    r = c.get("/tools/ok/hi")
    assert r.status_code == 200 and r.text == "hello from /tools/ok/hi"
    assert "lazy_ok_plugin" in sys.modules and lazy.state == "loaded" and lazy.load_seconds is not None
    assert c.get("/tools/ok/hi").status_code == 200  # second request reuses the loaded app


def test_failed_import_is_isolated_and_reported(fake_plugins):
    failures = {}
    bad = LazyApp("bad", "lazy_broken_plugin", on_failure=lambda n, e: failures.update({n: e}))
    good = LazyApp("ok", "lazy_ok_plugin")
    c = client_for(bad=bad, ok=good)
    r = c.get("/tools/bad/anything")
    assert r.status_code == 503 and "failed to load" in r.text
    assert bad.state == "failed" and "boom at import" in failures["bad"]
    assert c.get("/tools/bad/again").status_code == 503  # stays failed, no import retry storm
    assert c.get("/tools/ok/hi").status_code == 200  # other tools unaffected


def test_disabled_tool_is_never_imported(fake_plugins):
    c = client_for(off=DisabledApp("off", "Off Tool"))
    r = c.get("/tools/off/")
    assert r.status_code == 404 and "Off Tool is turned off" in r.text
    assert "lazy_ok_plugin" not in sys.modules


def _m(name, default=True):
    return Manifest(name=name, title=name, kind="static", enabled_by_default=default)


def test_workspace_missing_file_means_defaults(tmp_path):
    ws = load_workspace(tmp_path / "nope.yaml")
    assert ws.is_enabled(_m("a-tool")) and not ws.is_enabled(_m("b-tool", default=False)) and not ws.errors


def test_workspace_overrides_and_unknown_names(tmp_path):
    p = tmp_path / "workspace.yaml"
    p.write_text("enabled:\n  a-tool: false\n  ghost: true\n", encoding="utf-8")
    ws = load_workspace(p, known={"a-tool"})
    assert not ws.is_enabled(_m("a-tool")) and ws.warnings == [f"{p}: unknown tool 'ghost' ignored"]


@pytest.mark.parametrize("body", ["enabled: [unclosed", "enabled: [a, b]", "enabled:\n  a-tool: maybe\n", "- x\n"])
def test_workspace_broken_file_falls_back_to_defaults(tmp_path, body):
    p = tmp_path / "workspace.yaml"
    p.write_text(body, encoding="utf-8")
    ws = load_workspace(p)
    assert ws.errors and ws.enabled == {} and ws.is_enabled(_m("a-tool"))


def test_workspace_save_roundtrip(tmp_path):
    p = tmp_path / "sub" / "workspace.yaml"
    ws = load_workspace(p)
    ws.set_enabled("latex-pdf", False)
    ws.save()
    assert load_workspace(p).enabled == {"latex-pdf": False}
    assert not p.with_suffix(".yaml.tmp").exists()
