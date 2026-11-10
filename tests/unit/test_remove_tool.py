"""
Roadmap P3 — scripts/remove_tool.py (the mirror of scripts/new_tool.py).

The promise (the roadmap's "done when"): add a tool from the template, remove it with the script, and the repo is byte-for-byte what it was.
Plus the safety rules: dry run by default, typed confirmation when the tool is enabled / unknown / has data, refuses while other code
uses the tool, never touches Postgres / Vault / S3 / workspace.yaml, deletes Docker volumes only on request, all-or-nothing.
"""

from __future__ import annotations

import ast
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import new_tool  # noqa: E402
import remove_tool  # noqa: E402


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    (tmp_path / "tests/smoke").mkdir(parents=True)
    (tmp_path / "tests/unit").mkdir(parents=True)
    for rel in ("Dockerfile", "KNOWLEDGE_MAP.md", "tests/smoke/test_api.py", "docker-compose.yml"):
        shutil.copy(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "tools" / "_template", tmp_path / "tools" / "_template")
    monkeypatch.setattr(remove_tool, "fetch_enabled", lambda url, name: False)        # deterministic: never ask a real stack
    return tmp_path


def tree(repo: Path) -> dict[str, str]:
    return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(repo.rglob("*")) if p.is_file()}


def scaffold(repo, name="demo-tool", title="Demo Tool"):
    assert new_tool.main([name, title, "--repo", str(repo)]) == 0


def remove(repo, *args):
    return remove_tool.main([*args, "--repo", str(repo)])


# ------------------------------------------------------------------------------------------------------------ the "done when"

def test_scaffold_then_remove_leaves_the_repo_exactly_as_it_was(repo, capsys):
    before = tree(repo)
    scaffold(repo)
    assert tree(repo) != before
    assert remove(repo, "demo-tool", "--apply") == 0
    assert tree(repo) == before, sorted(set(tree(repo).items()) ^ set(before.items()))
    assert "Removed 'demo-tool'" in capsys.readouterr().out


def test_the_round_trip_also_works_with_data_runtime_and_awkward_titles(repo):
    before = tree(repo)
    assert new_tool.main(["crunch-it", 'A: "B" & <c>', "--runtime", "data", "--description", "x: y # z", "--repo", str(repo)]) == 0
    assert remove(repo, "crunch-it", "--apply") == 0 and tree(repo) == before


def test_two_tools_added_then_removed_in_any_order_restore_the_original(repo):
    before = tree(repo)
    scaffold(repo, "first-tool", "First")
    scaffold(repo, "second-tool", "Second")
    assert remove(repo, "first-tool", "--apply") == 0
    assert (repo / "second-tool").exists() and "second_tool/__init__.py" in (repo / "Dockerfile").read_text() and "first_tool" not in (repo / "Dockerfile").read_text()
    assert remove(repo, "second-tool", "--apply") == 0
    assert tree(repo) == before


# ------------------------------------------------------------------------------------------------------------ dry run + confirmation

def test_the_default_is_a_dry_run_that_changes_nothing_and_says_what_it_would_do(repo, capsys):
    scaffold(repo)
    before = tree(repo)
    assert remove(repo, "demo-tool") == 0 and tree(repo) == before
    out = capsys.readouterr().out
    for must in ("WILL DELETE / EDIT", "delete  demo-tool/", "tests/smoke/test_demo_tool.py", "edit    Dockerfile", "edit    KNOWLEDGE_MAP.md", "DRY RUN", "REVIEW BY HAND"):
        assert must in out, must


@pytest.mark.parametrize("enabled,has_data,confirm_needed", [(True, False, True), (None, False, True), (False, True, True), (False, False, False), (True, True, True)])
def test_a_typed_confirmation_is_needed_when_enabled_unknown_or_holding_data(repo, monkeypatch, enabled, has_data, confirm_needed, capsys):
    scaffold(repo)
    if has_data:
        (repo / "demo-tool" / "store.py").write_text('from core.state.sqlstore import SqlStore\nSTORE = SqlStore("demo_tool", sqlite_path=None, ddl="")\n')
    monkeypatch.setattr(remove_tool, "fetch_enabled", lambda url, name: enabled)
    before = tree(repo)
    rc = remove(repo, "demo-tool", "--apply")
    if confirm_needed:
        assert rc == 1 and tree(repo) == before and "--confirm demo-tool" in capsys.readouterr().err
        assert remove(repo, "demo-tool", "--apply", "--confirm", "wrong-name") == 1 and tree(repo) == before     # must be the exact name
        assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0 and not (repo / "demo-tool").exists()
    else:
        assert rc == 0 and not (repo / "demo-tool").exists()


def test_apply_without_the_flag_never_removes_anything_even_with_confirm(repo):
    scaffold(repo)
    before = tree(repo)
    assert remove(repo, "demo-tool", "--confirm", "demo-tool") == 0 and tree(repo) == before


# ------------------------------------------------------------------------------------------------------------ what may be removed at all

def test_core_tools_are_never_removed_even_with_every_override(repo, capsys):
    for name in ("vault", "datadiff-pro"):
        (repo / name).mkdir(exist_ok=True)
        (repo / name / "manifest.yaml").write_text(f"name: {name}\n")
        before = tree(repo)
        assert remove(repo, name, "--apply", "--confirm", name, "--ignore-references") == 1 and tree(repo) == before
        assert "core part of the platform" in capsys.readouterr().err


def test_unknown_and_ambiguous_names_are_refused(repo, capsys):
    scaffold(repo)
    assert remove(repo, "no-such-tool", "--apply") == 1
    (repo / "twin").mkdir()
    (repo / "twin" / "manifest.yaml").write_text("name: demo-tool\n")                 # same manifest name in two folders
    assert remove(repo, "demo-tool", "--apply") == 1 and "ambiguous" in capsys.readouterr().err


def test_a_tool_is_found_by_manifest_name_or_by_folder_name(repo):
    (repo / "sp-lab").mkdir()
    (repo / "sp-lab" / "manifest.yaml").write_text("name: sharepoint\nkind: python\n")
    assert remove_tool.resolve(repo, "sharepoint")[1].name == "sp-lab" and remove_tool.resolve(repo, "sp-lab")[0] == "sharepoint"


# ------------------------------------------------------------------------------------------------------------ references block the removal

def test_other_code_that_uses_the_tool_blocks_the_removal(repo, capsys):
    scaffold(repo)
    (repo / "other").mkdir()
    (repo / "other" / "x.py").write_text("from demo_tool.server import app\n")
    (repo / "other" / "page.js").write_text('fetch("/tools/demo-tool/echo")\n')
    (repo / "other" / "manifest.yaml").write_text("name: other\ndepends_on: [demo-tool]\n")
    before = tree(repo)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 1 and tree(repo) == before
    err_out = capsys.readouterr()
    for must in ("other/x.py:1: imports the tool's package", "other/page.js:1: calls /tools/demo-tool/", "depends_on lists 'demo-tool'"):
        assert must in err_out.out, must
    assert remove(repo, "demo-tool") == 1                                              # a dry run reports blockers with a non-zero exit
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool", "--ignore-references") == 0 and not (repo / "demo-tool").exists()


def test_comments_and_the_tools_own_files_are_not_blockers(repo):
    scaffold(repo)
    (repo / "other").mkdir()
    (repo / "other" / "x.py").write_text("# from demo_tool import x   (old idea)\n# see /tools/demo-tool/\n")
    plan = remove_tool.make_plan(repo, "demo-tool")
    assert plan.blockers == []


# ------------------------------------------------------------------------------------------------------------ data is never touched

def test_data_left_behind_is_listed_and_nothing_outside_the_repo_is_touched(repo, monkeypatch, capsys):
    scaffold(repo)
    (repo / "demo-tool" / "store.py").write_text(
        'STORE = SqlStore("demo_schema", sqlite_path=None, ddl="")\nCACHE = FileCache("demo-files", None)\n')
    (repo / "demo-tool" / "manifest.yaml").write_text(
        (repo / "demo-tool" / "manifest.yaml").read_text() + "vault: {read: [postgres_connection], write: [demo_kind]}\n")
    calls = []
    monkeypatch.setattr(remove_tool.subprocess, "run", lambda *a, **k: calls.append(a) or None)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0
    out = capsys.readouterr().out
    assert "Postgres schema `demo_schema`" in out and "DROP SCHEMA demo_schema CASCADE" in out and "NOT run by this script" in out
    assert "`demo-files` prefix" in out and "Vault entries of kind demo_kind, postgres_connection" in out
    assert calls == []                                                                  # no docker, no psql, no network: only files in the repo


def test_docs_mentions_are_listed_but_prose_is_never_rewritten(repo, capsys):
    scaffold(repo)
    (repo / "NOTES.md").write_text("We use `demo-tool/` for demos, see /tools/demo-tool/ too.\n")
    before = (repo / "NOTES.md").read_bytes()
    remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool")
    assert (repo / "NOTES.md").read_bytes() == before and "NOTES.md:1:" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------------------ docker volumes

def with_volume(repo, name="demo-tool", vol="demo_tool_data", services=2, shared_elsewhere=False):
    c = (repo / "docker-compose.yml").read_text().split("\n")
    out, added = [], 0
    for l in c:
        out.append(l)
        if l.strip() == "- vault_data:/app/data/vault" and added < services:
            out.append(f"      - {vol}:/app/data/{name}")
            added += 1
    text = "\n".join(out).replace("\nvolumes:\n  schema_map_data:\n", f"\nvolumes:\n  {vol}:\n  schema_map_data:\n", 1)
    if shared_elsewhere:
        text = text.replace("      - redis_data:/data", f"      - redis_data:/data\n      - {vol}:/somewhere/else", 1)
    (repo / "docker-compose.yml").write_text(text)
    assert added == services and f"  {vol}:" in text


def test_compose_mounts_and_the_volume_key_go_but_other_volumes_stay(repo):
    before_compose = (repo / "docker-compose.yml").read_text()
    scaffold(repo)
    with_volume(repo)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0                 # has data (a volume) → typed confirmation needed
    assert (repo / "docker-compose.yml").read_text() == before_compose                            # exactly the original again
    import yaml
    yaml.safe_load((repo / "docker-compose.yml").read_text())


def test_a_volume_still_mounted_elsewhere_keeps_its_declaration(repo):
    scaffold(repo)
    with_volume(repo, shared_elsewhere=True)
    text_before = (repo / "docker-compose.yml").read_text()
    if "somewhere/else" not in text_before:
        pytest.skip("this compose has no redis_data mount to attach the extra reference to")
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0
    after = (repo / "docker-compose.yml").read_text()
    assert "/app/data/demo-tool" not in after and "  demo_tool_data:" in after and "demo_tool_data:/somewhere/else" in after


def test_docker_volumes_are_only_deleted_with_the_flag_and_the_typed_confirmation(repo, monkeypatch, capsys):
    scaffold(repo)
    with_volume(repo)
    calls = []

    class R:
        def __init__(self, out="", rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc

    def fake(cmd, **kw):
        calls.append(cmd)
        return R("toolbox_demo_tool_data\n") if cmd[:3] == ["docker", "volume", "ls"] else R()

    monkeypatch.setattr(remove_tool.subprocess, "run", fake)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0
    assert calls == [] and "Docker volume `demo_tool_data`" in capsys.readouterr().out            # default: kept, reported
    # now again, deleting volumes: needs the confirmation
    scaffold(repo)
    with_volume(repo)
    assert remove(repo, "demo-tool", "--apply", "--remove-volumes") == 1 and calls == [] and (repo / "demo-tool").exists()
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool", "--remove-volumes") == 0
    assert ["docker", "volume", "rm", "toolbox_demo_tool_data"] in calls
    assert all(c[:3] in (["docker", "volume", "ls"], ["docker", "volume", "rm"]) for c in calls) and len([c for c in calls if c[2] == "rm"]) == 1


# ------------------------------------------------------------------------------------------------------------ smoke file edits

def test_smoke_edits_touch_only_this_tools_entries(repo):
    scaffold(repo)
    api = repo / "tests/smoke/test_api.py"
    text = api.read_text()
    text = text.replace('    "encode-decode", "text-editor",', '    "encode-decode", "demo-tool", "text-editor",', 1)
    text += '\n# unrelated mention: "demo-tool", stays\n'
    api.write_text(text)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0
    after = api.read_text()
    ast.parse(after)
    assert '"demo-tool", "text-editor"' not in after and '"encode-decode", "text-editor"' in after       # the PAGE_ONLY entry went, neighbours stayed
    assert '# unrelated mention: "demo-tool", stays' in after                                              # outside the set: untouched
    assert '("demo-tool", "GET", "/health"' not in after


def test_a_multi_line_api_check_is_refused_before_anything_is_written(repo, capsys):
    scaffold(repo)
    api = repo / "tests/smoke/test_api.py"
    api.write_text(api.read_text().replace("API_CHECKS = [\n", 'API_CHECKS = [\n    ("demo-tool", "POST", "/x", {\n        "a": 1}, "application/json"),\n', 1))
    before = tree(repo)
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 1 and tree(repo) == before
    assert "multi-line" in capsys.readouterr().err


def test_the_tools_own_tests_go_and_other_tests_stay(repo):
    scaffold(repo)
    (repo / "tests/unit/test_demo_tool_logic.py").write_text("def test_x(): pass\n")
    (repo / "tests/unit/test_demo_tool.py").write_text("def test_y(): pass\n")
    (repo / "tests/unit/test_other_thing.py").write_text("def test_z(): pass\n")
    (repo / "tests/unit/test_demo_toolbox_unrelated.py").write_text("def test_w(): pass\n")      # shares a prefix: the plan lists it so the owner SEES it
    plan = remove_tool.make_plan(repo, "demo-tool")
    listed = sorted(p.name for p in plan.deletes)
    assert "test_demo_tool_logic.py" in listed and "test_demo_tool.py" in listed and "test_demo_tool.py" in listed and "test_other_thing.py" not in listed
    assert remove(repo, "demo-tool", "--apply", "--confirm", "demo-tool") == 0
    assert (repo / "tests/unit/test_other_thing.py").exists() and not (repo / "tests/unit/test_demo_tool_logic.py").exists()


# ------------------------------------------------------------------------------------------------------------ all-or-nothing, custom apps

def test_if_the_self_check_fails_everything_is_put_back(repo, monkeypatch, capsys):
    scaffold(repo)
    (repo / "tests/unit/test_demo_tool_logic.py").write_text("def test_x(): pass\n")
    before = tree(repo)
    real = remove_tool.resolve
    state = {"n": 0}

    def flaky(r, ident):
        state["n"] += 1
        return real(r, ident) if state["n"] == 1 else (ident, r / "demo-tool", False)        # claims the tool is still there after removal

    monkeypatch.setattr(remove_tool, "resolve", flaky)
    assert remove(repo, "demo-tool", "--apply") == 1
    assert tree(repo) == before and "everything was put back" in capsys.readouterr().err


def test_a_custom_app_in_plugins_is_just_a_folder_delete(repo):
    app = repo / "plugins" / "my-page"
    app.mkdir(parents=True)
    (app / "manifest.yaml").write_text("name: my-page\ntitle: P\nkind: static\n")
    (app / "ui").mkdir()
    (app / "ui" / "index.html").write_text("<p>hi</p>")
    before_files = {k: v for k, v in tree(repo).items() if not k.startswith("plugins/")}
    assert remove(repo, "my-page", "--apply", "--confirm", "my-page") == 0
    assert not app.exists() and {k: v for k, v in tree(repo).items() if not k.startswith("plugins/")} == before_files      # nothing else changed


# ------------------------------------------------------------------------------------------------------------ the real repo

def test_a_dry_run_on_every_real_tool_runs_clean_and_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(remove_tool, "fetch_enabled", lambda url, name: None)
    watched = [REPO / f for f in ("Dockerfile", "KNOWLEDGE_MAP.md", "docker-compose.yml", "tests/smoke/test_api.py")]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in watched]
    names = sorted({remove_tool._manifest_name(m) for m in REPO.glob("*/manifest.yaml")} - {""})
    assert len(names) > 20
    for n in names:
        rc = remove_tool.main([n, "--repo", str(REPO)])
        assert rc in (0, 1), n
    out = capsys.readouterr()
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in watched] == before
    assert "core part of the platform" in out.err and "BLOCKERS" in out.out                      # vault refused; tools that others depend on are blocked


def test_a_real_tool_with_dependents_is_blocked_and_a_leaf_tool_is_not(monkeypatch):
    monkeypatch.setattr(remove_tool, "fetch_enabled", lambda url, name: False)
    assert remove_tool.make_plan(REPO, "data-lake").blockers                                       # the Vault page and the MCP server use it
    assert remove_tool.make_plan(REPO, "header-reference").blockers == []                          # a leaf tool
