"""
Roadmap P1 — trusted Python plugins in plugins/ (core_plugins/loader.py, docs/architecture/plugin-manifest.md).

Two modes, both tested: OFF (default — `kind: python` is refused with a message that says how to enable it) and ON
(TOOLBOX_TRUSTED_PLUGINS=1 — accepted, but only under rules that keep the import name safe and the plugin in a runtime that mounts plugins/).
Static and external apps behave the same in both modes; built-in tools are never subject to these rules.
"""

import importlib
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import discover  # noqa: E402
from core_plugins.loader import (TRUSTED_ENV, TRUSTED_PLUGIN_RUNTIMES, extra_dir_kinds_for, trusted_plugins_enabled)  # noqa: E402

PY = {"name": "my-tool", "title": "My tool", "kind": "python", "entry": "my_tool.server:app", "runtime": "light"}
STATIC = {"name": "page", "title": "Page", "kind": "static"}
EXTERNAL = {"name": "link", "title": "Link", "kind": "external", "entry": "https://example.com"}


def make(plugins: Path, folder: str, manifest: dict, files: dict | None = None) -> Path:
    d = plugins / folder
    d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    for rel, body in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(body, encoding="utf-8")
    return d


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(TRUSTED_ENV, raising=False)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(TRUSTED_ENV, "1")


# ------------------------------------------------------------------------------------------------------------ the switch

@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "2", "maybe", "TRUE1", " "])
def test_anything_but_an_explicit_yes_is_off(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(TRUSTED_ENV, raising=False)
    else:
        monkeypatch.setenv(TRUSTED_ENV, value)
    assert trusted_plugins_enabled() is False and "python" not in extra_dir_kinds_for()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 ", "On"])
def test_explicit_yes_values_turn_it_on(monkeypatch, value):
    monkeypatch.setenv(TRUSTED_ENV, value)
    assert trusted_plugins_enabled() is True and "python" in extra_dir_kinds_for()


def test_the_default_is_off_and_the_helper_reads_a_given_mapping():
    assert trusted_plugins_enabled({}) is False and trusted_plugins_enabled({TRUSTED_ENV: "1"}) is True


# ------------------------------------------------------------------------------------------------------------ mode OFF

def test_off_python_is_refused_with_a_message_that_says_how_to_enable_it(tmp_path, off):
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", PY)
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert "my-tool" not in reg.plugins
    (msg,) = reg.errors
    for must in ("not allowed in a custom-app folder", "trusted Python plugins are OFF", f"{TRUSTED_ENV}=1", "docker compose up -d",
                 "Vault key", "built into the image" if False else "build the plugin into the image"):
        assert must in msg, must


def test_off_static_and_external_still_work_and_a_bad_python_plugin_hides_nobody(tmp_path, off):
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", PY)
    make(plugins, "page", STATIC, {"ui/index.html": "<p>hi</p>"})
    make(plugins, "link", EXTERNAL)
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert sorted(reg.plugins) == ["link", "page"] and len(reg.errors) == 1


def test_service_plugins_are_refused_in_both_modes(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    make(plugins, "svc", {"name": "svc", "title": "S", "kind": "service", "entry": "https://x.example", "runtime": "light"})
    for mode in (None, "1"):
        monkeypatch.delenv(TRUSTED_ENV, raising=False)
        if mode:
            monkeypatch.setenv(TRUSTED_ENV, mode)
        reg = discover(tmp_path, extra_dirs=[plugins])
        assert not reg.plugins and "service plugins must be built into the image" in reg.errors[0]


# ------------------------------------------------------------------------------------------------------------ mode ON

def test_on_python_is_accepted_and_flagged_as_trusted_code(tmp_path, on):
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", PY)
    make(plugins, "page", STATIC, {"ui/index.html": "<p>hi</p>"})
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert sorted(reg.plugins) == ["my-tool", "page"] and reg.errors == []
    assert any("custom Python plugin" in w and "trusted code" in w and "'light' runtime" in w for w in reg.warnings)
    assert reg.plugins["my-tool"].module == "my_tool.server"


@pytest.mark.parametrize("folder,manifest,why", [
    ("my-tool", PY, "plain lowercase identifier"),                                              # hyphen: not importable
    ("MyTool", {**PY, "entry": "MyTool.server:app"}, "plain lowercase identifier"),
    ("_private", {**PY, "entry": "_private.server:app"}, "plain lowercase identifier"),
    ("1tool", {**PY, "entry": "1tool.server:app"}, ""),                                         # refused earlier, by the manifest model itself
    ("class", {**PY, "entry": "class.server:app"}, "plain lowercase identifier"),
    ("core", {**PY, "entry": "core.server:app"}, "would shadow"),                              # Toolbox's own package
    ("core_plugins", {**PY, "entry": "core_plugins.server:app"}, "would shadow"),
    ("json", {**PY, "entry": "json.server:app"}, "would shadow"),                               # standard library
    ("os", {**PY, "entry": "os.server:app"}, "would shadow"),
    ("fastapi", {**PY, "entry": "fastapi.server:app"}, "would shadow"),
    ("my_tool", {**PY, "entry": "other_pkg.server:app"}, "entry must start with the folder name"),
    ("my_tool", {**PY, "runtime": "pgtools"}, "only run in the light or data runtime"),
    ("my_tool", {**PY, "runtime": "ssh"}, "only run in the light or data runtime"),
    ("my_tool", {**PY, "runtime": "notebook"}, "only run in the light or data runtime"),
    ("my_tool", {**PY, "runtime": "datadiff"}, "only run in the light or data runtime"),
    ("my_tool", {**PY, "singleton": True, "scaling": {"max": 1}}, "singleton"),
])
def test_on_the_import_name_and_runtime_rules(tmp_path, on, folder, manifest, why):
    plugins = tmp_path / "plugins"
    for pkg in ("core", "core_plugins"):
        (tmp_path / pkg).mkdir()                                                                 # a "repo" that has Toolbox's own packages
    make(plugins, folder, manifest)
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert not reg.plugins and len(reg.errors) == 1 and why in reg.errors[0], reg.errors


def test_on_only_light_and_data_are_allowed_runtimes():
    assert TRUSTED_PLUGIN_RUNTIMES == ("light", "data")


def test_on_a_data_runtime_plugin_is_accepted(tmp_path, on):
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", {**PY, "runtime": "data"})
    assert "my-tool" in discover(tmp_path, extra_dirs=[plugins]).plugins


def test_on_the_entry_is_really_importable_once_the_folder_is_on_the_path(tmp_path, on, monkeypatch):
    """What main.py does: append plugins/ to sys.path, then the manifest's entry resolves to the plugin's ASGI app."""
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", PY, {"__init__.py": "", "server.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    reg = discover(tmp_path, extra_dirs=[plugins])
    monkeypatch.syspath_prepend(str(plugins))
    sys.modules.pop("my_tool", None)
    sys.modules.pop("my_tool.server", None)
    m = reg.plugins["my-tool"]
    mod = importlib.import_module(m.module)
    assert getattr(mod, m.entry.split(":")[1]).__class__.__name__ == "FastAPI"


# ------------------------------------------------------------------------------------------------------------ unchanged behaviour

def test_built_in_tools_are_identical_in_both_modes_and_exempt_from_the_rules(monkeypatch):
    monkeypatch.delenv(TRUSTED_ENV, raising=False)
    a = discover(REPO)
    monkeypatch.setenv(TRUSTED_ENV, "1")
    b = discover(REPO)
    assert list(a.plugins) == list(b.plugins) and a.errors == b.errors == []
    assert any(m.kind == "python" and "-" in m.source.split("/")[-2] for m in a.ordered())     # hyphenated built-in folders (df-studio …) stay valid


def test_an_explicit_extra_dir_kinds_argument_still_wins(tmp_path, off):
    plugins = tmp_path / "plugins"
    make(plugins, "my_tool", PY)
    assert "my-tool" in discover(tmp_path, extra_dirs=[plugins], extra_dir_kinds=("static", "external", "python")).plugins
    assert "my-tool" not in discover(tmp_path, extra_dirs=[plugins], extra_dir_kinds=("static",)).plugins


# ------------------------------------------------------------------------------------------------------------ the shipped sample + wiring

def test_the_shipped_plugins_folder_scans_clean_in_both_modes(monkeypatch):
    """plugins/examples/ holds the sample on purpose: it is never scanned, so a default install logs no 'refused' error."""
    for mode in (None, "1"):
        monkeypatch.delenv(TRUSTED_ENV, raising=False)
        if mode:
            monkeypatch.setenv(TRUSTED_ENV, mode)
        reg = discover(REPO, extra_dirs=[REPO / "plugins"])
        assert reg.errors == [] and "hello-python" not in reg.plugins


def test_the_sample_plugin_works_when_copied_in_and_is_refused_by_default(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    plugins = tmp_path / "plugins"
    shutil.copytree(REPO / "plugins" / "examples" / "hello_python", plugins / "hello_python")
    monkeypatch.delenv(TRUSTED_ENV, raising=False)
    assert "hello-python" not in discover(tmp_path, extra_dirs=[plugins]).plugins
    monkeypatch.setenv(TRUSTED_ENV, "1")
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert "hello-python" in reg.plugins and reg.errors == [] and reg.plugins["hello-python"].enabled_by_default is False
    monkeypatch.syspath_prepend(str(plugins))
    for name in ("hello_python", "hello_python.server"):
        sys.modules.pop(name, None)
    c = TestClient(importlib.import_module("hello_python.server").app)
    assert c.get("/").status_code == 200 and "custom Python plugin" in c.get("/").text
    assert c.get("/info").json() == {"plugin": "hello-python", "runtime": "standalone"}


def test_compose_passes_the_flag_off_by_default_and_mounts_plugins_only_where_allowed():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    svcs = compose["services"]
    with_flag, with_mount = set(), set()
    for name, s in svcs.items():
        env = s.get("environment") or {}
        if isinstance(env, list):
            env = dict(item.split("=", 1) for item in env if "=" in item)
        if env.get("TOOLBOX_TRUSTED_PLUGINS") == "${TOOLBOX_TRUSTED_PLUGINS:-0}":
            with_flag.add(name)
        if any(str(v).startswith("./plugins:/app/plugins") for v in s.get("volumes", [])):
            with_mount.add(name)
            assert str(next(v for v in s["volumes"] if str(v).startswith("./plugins"))).endswith(":ro")      # read-only, always
    assert with_flag == {"toolbox", "rt-light", "rt-data"}
    assert with_mount == {"toolbox", "rt-light", "rt-data"}                       # the gateway (static/external) + the two runtimes custom Python may use
    for name in ("rt-pgtools", "rt-ssh", "rt-latex", "rt-notebook", "rt-datadiff", "worker", "singletons"):
        assert name not in with_mount and name not in with_flag
