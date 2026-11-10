"""
Roadmap P2 — tools/_template + scripts/new_tool.py.

Promise: copy the template (with the script), edit nothing, and you get a working empty tool that Toolbox discovers, whose Dockerfile /
smoke / index wiring is complete — and the template itself can never be mistaken for a tool. The script is all-or-nothing.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import new_tool  # noqa: E402
from core_plugins import discover  # noqa: E402
from core_plugins.loader import load_manifest  # noqa: E402

TOKENS = {"__TOOL_NAME__", "__TOOL_PACKAGE__", "__TOOL_TITLE__", "__TOOL_DESCRIPTION__", "__TOOL_ICON__", "__TOOL_RUNTIME__", "__TOOL_ORDER__", "__TOOL_DATE__"}


@pytest.fixture()
def repo(tmp_path):
    """A small Toolbox: the REAL Dockerfile, smoke test_api.py and KNOWLEDGE_MAP.md plus the template — what the script edits."""
    (tmp_path / "tests/smoke").mkdir(parents=True)
    for rel in ("Dockerfile", "KNOWLEDGE_MAP.md", "tests/smoke/test_api.py"):
        shutil.copy(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "tools" / "_template", tmp_path / "tools" / "_template")
    return tmp_path


def run(repo, *args):
    return new_tool.main([*args, "--repo", str(repo)])


def tree(repo: Path) -> dict[str, str]:
    return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(repo.rglob("*")) if p.is_file()}


def load_app(folder: Path, package: str):
    spec = importlib.util.spec_from_file_location(f"{package}_under_test", folder / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


# ------------------------------------------------------------------------------------------------------------ the template itself

def test_the_template_is_never_a_tool():
    assert "__TOOL_NAME__" not in discover(REPO).plugins and not [e for e in discover(REPO).errors if "_template" in e]
    assert not list(REPO.glob("*/manifest.yaml")) == [] and not (REPO / "tools" / "manifest.yaml").exists()
    assert not any(p.parent.name == "_template" for p in REPO.glob("*/manifest.yaml"))          # the loader only scans one level down
    with pytest.raises(ValueError):
        load_manifest(REPO / "tools" / "_template" / "manifest.yaml")                              # invalid on purpose: even a stray copy cannot be mounted


def test_the_template_only_uses_known_placeholders_and_every_one_is_used():
    used = set()
    for f in (REPO / "tools" / "_template").rglob("*"):
        if f.is_file():
            used |= set(re.findall(r"__TOOL_[A-Z]+__", f.read_text(encoding="utf-8")))
    assert used == TOKENS
    readme = (REPO / "tools" / "_template" / "README.md").read_text()
    assert all(t in readme for t in TOKENS)


def test_the_dockerfile_marker_exists_once_and_sits_before_the_touch_line():
    d = (REPO / "Dockerfile").read_text()
    assert d.count(new_tool.DOCKERFILE_MARKER) == 1
    assert d.index(new_tool.DOCKERFILE_MARKER) < d.index("\nRUN touch ")


# ------------------------------------------------------------------------------------------------------------ the happy path (the "done when")

def test_copy_rename_and_you_have_a_working_empty_tool(repo):
    assert run(repo, "demo-tool", "Demo Tool", "--icon", "🧪", "--description", "A demo.", "--order", "321") == 0
    new = repo / "demo-tool"
    assert sorted(p.name for p in new.iterdir()) == ["CLAUDE.md", "KNOWLEDGE_MAP.md", "__init__.py", "manifest.yaml", "server.py", "ui"]
    # nothing left to fill in
    for f in list(new.rglob("*")) + [repo / "tests/smoke/test_demo_tool.py"]:
        if f.is_file():
            assert not re.search(r"__TOOL_[A-Z]+__", f.read_text(encoding="utf-8")), f
    # discovered by the real loader, with the values we passed
    reg = discover(repo)
    m = reg.plugins["demo-tool"]
    assert reg.errors == [] and (m.title, m.icon, m.runtime, m.order, m.entry, m.description) == ("Demo Tool", "🧪", "light", 321, "demo_tool.server:app", "A demo.")
    # its app works: page, health (what the smoke test calls), echo
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    c = TestClient(load_app(new, "demo_tool"))
    page = c.get("/")
    assert page.status_code == 200 and "Demo Tool" in page.text and "fetch(\"echo\"" in page.text                  # relative paths
    assert c.get("/health").json() == {"ok": True, "tool": "demo-tool"}
    assert c.post("/echo", json={"text": "hello"}).json() == {"ok": True, "echo": "hello", "length": 5}
    assert c.post("/echo", json={"text": 5}).status_code == 422


def test_dockerfile_gets_three_copy_lines_above_the_marker_and_the_package_init(repo):
    before = (repo / "Dockerfile").read_text()
    run(repo, "demo-tool", "Demo Tool")
    after = (repo / "Dockerfile").read_text()
    copies = [l for l in after.split("\n") if l.startswith("COPY demo-tool/")]
    assert copies == ["COPY demo-tool/server.py ./demo_tool/server.py", "COPY demo-tool/manifest.yaml ./demo_tool/manifest.yaml", "COPY demo-tool/ui/ ./demo_tool/ui/"]
    assert after.index(copies[-1]) < after.index(new_tool.DOCKERFILE_MARKER) < after.index("\nRUN touch ")
    touch = next(l for l in after.split("\n") if l.startswith("RUN touch "))
    assert touch.endswith(" demo_tool/__init__.py") and touch.count("demo_tool/__init__.py") == 1
    assert after.replace("\n".join(copies) + "\n\n", "").replace(" demo_tool/__init__.py", "").strip() == before.strip()     # nothing else changed (the block ends with one blank line)


def test_smoke_and_index_wiring(repo):
    run(repo, "demo-tool", "Demo Tool")
    api = (repo / "tests/smoke/test_api.py").read_text()
    ast.parse(api)                                                                                    # still valid Python
    lines = api.split("\n")
    i = lines.index("API_CHECKS = [")
    assert lines[i + 1].startswith('    ("demo-tool", "GET", "/health", None, "application/json"),') and api.count('"demo-tool"') == 1
    smoke = ast.parse((repo / "tests/smoke/test_demo_tool.py").read_text())
    assert [n.name for n in smoke.body if isinstance(n, ast.FunctionDef)] == ["test_health", "test_echo"]
    k = (repo / "KNOWLEDGE_MAP.md").read_text()
    row = "| Demo Tool | `/tools/demo-tool/` | [`demo-tool/KNOWLEDGE_MAP.md`](demo-tool/KNOWLEDGE_MAP.md) | [`demo-tool/CLAUDE.md`](demo-tool/CLAUDE.md) |"
    assert k.count(row) == 1
    lines = k.split("\n")
    i = lines.index(row)
    assert lines[i - 1].startswith("|") and not lines[i + 1].startswith("| Demo")                                   # inside the table, not after it


def test_runtime_data_and_default_description(repo):
    assert run(repo, "crunch", "Crunch", "--runtime", "data") == 0
    m = discover(repo).plugins["crunch"]
    assert m.runtime == "data" and m.description.startswith("TODO")


# ------------------------------------------------------------------------------------------------------------ hostile text cannot break any file

def test_awkward_titles_and_descriptions_survive_every_file_type(repo):
    title = 'Tom & "Jerry": <b>x</b> # not a comment'
    desc = "It's a: test, with #hash, 'quotes' and \"double\" <script>alert(1)</script> & more"
    assert run(repo, "odd-tool", title, "--description", desc, "--icon", "🐍") == 0
    m = discover(repo).plugins["odd-tool"]
    assert m.title == title and m.description == desc                                                 # YAML: exact round trip
    ast.parse((repo / "odd-tool/server.py").read_text())                                              # python docstring still valid
    ui = (repo / "odd-tool/ui/index.html").read_text()
    assert "<script>alert(1)</script>" not in ui and "&lt;script&gt;alert(1)&lt;/script&gt;" in ui and "Tom &amp; &quot;Jerry&quot;" in ui


@pytest.mark.parametrize("name", ["", "a", "Bad Name", "bad_name", "1tool", "tool-", "my--tool", "tool_", "x" * 60, "tool name", "tool/../x", "my.tool", "ÅÄÖ"])
def test_bad_names_are_refused_and_change_nothing(repo, name, capsys):
    before = tree(repo)
    assert run(repo, name, "T") == 1
    assert tree(repo) == before and "Nothing was changed" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["core", "api", "core-plugins", "tools", "json", "os", "fastapi", "tests", "docs", "scripts"])
def test_names_that_would_shadow_something_are_refused(repo, name):
    (repo / "api").mkdir(exist_ok=True)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "core").mkdir(exist_ok=True)
    (repo / "core_plugins").mkdir(exist_ok=True)
    (repo / "scripts").mkdir(exist_ok=True)
    before = tree(repo)
    assert run(repo, name, "T") == 1 and tree(repo) == before


@pytest.mark.parametrize("kwargs", [["--description", "two\nlines"], ["--description", "back\\slash"], ["--description", 'tri"""ple'], ["--description", "x" * 301],
                                    ["--icon", "too long icon!"], ["--runtime", "ssh"], ["--runtime", "datadiff"], ["--runtime", "notebook"]])
def test_bad_options_are_refused(repo, kwargs):
    before = tree(repo)
    assert run(repo, "demo-tool", "Demo", *kwargs) == 1 and tree(repo) == before


def test_empty_or_oversized_titles_are_refused(repo):
    before = tree(repo)
    assert run(repo, "demo-tool", "   ") == 1 and run(repo, "demo-tool", "x" * 61) == 1 and tree(repo) == before


# ------------------------------------------------------------------------------------------------------------ all-or-nothing

def test_a_second_run_for_the_same_name_is_refused_and_changes_nothing(repo):
    assert run(repo, "demo-tool", "Demo") == 0
    before = tree(repo)
    assert run(repo, "demo-tool", "Demo again") == 1 and tree(repo) == before


def test_dry_run_writes_nothing(repo, capsys):
    before = tree(repo)
    assert run(repo, "demo-tool", "Demo", "--dry-run") == 0 and tree(repo) == before
    out = capsys.readouterr().out
    assert "Dry run" in out and "demo-tool/manifest.yaml" in out and "Dockerfile" in out


@pytest.mark.parametrize("break_what", ["marker", "touch", "api_checks", "index"])
def test_a_missing_anchor_stops_everything_before_any_file_is_written(repo, break_what, capsys):
    f, old, new = {"marker": ("Dockerfile", new_tool.DOCKERFILE_MARKER, "# marker removed"), "touch": ("Dockerfile", "RUN touch ", "RUN true "),
                   "api_checks": ("tests/smoke/test_api.py", "API_CHECKS = [", "CHECKS = ["), "index": ("KNOWLEDGE_MAP.md", "| Tool | Mounted at", "| Name | Mounted at")}[break_what]
    p = repo / f
    p.write_text(p.read_text().replace(old, new, 1))
    before = tree(repo)
    assert run(repo, "demo-tool", "Demo") == 1 and tree(repo) == before and "Nothing was changed" in capsys.readouterr().err
    assert not (repo / "demo-tool").exists()


def test_if_the_self_check_fails_everything_is_put_back_exactly(repo, monkeypatch, capsys):
    before = tree(repo)
    monkeypatch.setattr(new_tool, "selfcheck", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert run(repo, "demo-tool", "Demo") == 1
    assert tree(repo) == before and not (repo / "demo-tool").exists() and "put back" in capsys.readouterr().err
    assert not [d for d in repo.rglob("*") if d.is_dir() and d.name in ("demo-tool", "ui") and d.parent != repo / "tools" / "_template"]


def test_the_scaffolded_tool_does_not_disturb_other_tools(repo):
    (repo / "other-tool").mkdir()
    (repo / "other-tool" / "manifest.yaml").write_text(
        "name: other-tool\ntitle: Other\nkind: python\nentry: other_tool.server:app\nruntime: light\n")
    run(repo, "demo-tool", "Demo")
    assert sorted(discover(repo).plugins) == ["demo-tool", "other-tool"]
