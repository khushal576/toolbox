"""Unit tests for core_plugins (roadmap A1). Run: python3 -m pytest tests/unit -q"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import Manifest, discover  # noqa: E402
from core_plugins.loader import load_manifest  # noqa: E402

BASE = {"name": "demo-tool", "title": "Demo"}


def mk(**kw):
    return Manifest.model_validate({**BASE, **kw})


def write(tmp: Path, folder: str, data) -> Path:
    d = tmp / folder
    d.mkdir(parents=True, exist_ok=True)
    p = d / "manifest.yaml"
    p.write_text(data if isinstance(data, str) else yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


# --- model -------------------------------------------------------------------------------------------

def test_python_kind_valid():
    m = mk(kind="python", entry="api.app:app", runtime="data", tier=3)
    assert m.module == "api.app" and m.mount_path == "/tools/demo-tool"


@pytest.mark.parametrize("entry", [None, "api.app", "api.app:", ":app", "api app:app"])
def test_python_kind_needs_module_colon_attr(entry):
    with pytest.raises(ValueError, match="module.path:attribute"):
        mk(kind="python", entry=entry, runtime="light")


def test_python_kind_needs_runtime():
    with pytest.raises(ValueError, match="needs a runtime"):
        mk(kind="python", entry="x.y:app")


def test_static_kind_defaults_entry_and_forbids_runtime_and_state():
    assert mk(kind="static", tier=1).entry == "ui/index.html"
    with pytest.raises(ValueError, match="runtime must be empty"):
        mk(kind="static", runtime="light")
    with pytest.raises(ValueError, match="cannot keep server state"):
        mk(kind="static", state=["session"])


@pytest.mark.parametrize("entry", ["/etc/passwd", "../other/index.html", "file:///x.html"])
def test_static_entry_must_stay_inside_folder(entry):
    with pytest.raises(ValueError, match="relative path"):
        mk(kind="static", entry=entry)


@pytest.mark.parametrize("kind,runtime", [("external", None), ("service", "data")])
def test_url_kinds(kind, runtime):
    assert mk(kind=kind, entry="https://example.com/app", runtime=runtime).entry.startswith("https://")
    with pytest.raises(ValueError, match="http"):
        mk(kind=kind, entry="example.com", runtime=runtime)


@pytest.mark.parametrize("name", ["Demo", "-x", "a", "has space", "under_score", "x" * 64])
def test_bad_names(name):
    with pytest.raises(ValueError):
        Manifest.model_validate({"name": name, "title": "t", "kind": "static"})


def test_unknown_keys_rejected():
    with pytest.raises(ValueError):
        mk(kind="static", ttile="typo")


def test_scaling_min_le_max_and_self_dependency():
    with pytest.raises(ValueError, match="scaling.min"):
        mk(kind="static", scaling={"min": 3, "max": 2})
    with pytest.raises(ValueError, match="depend on itself"):
        mk(kind="static", depends_on=["demo-tool"])


def test_stateful_with_replicas_is_a_warning_not_an_error():
    m = mk(kind="python", entry="x:app", runtime="data", state=["session"], scaling={"max": 3})
    assert m.warnings() and "B9" in m.warnings()[0]


# --- loader ------------------------------------------------------------------------------------------

def test_loader_isolates_broken_manifests(tmp_path):
    write(tmp_path, "good", {**BASE, "kind": "static"})
    write(tmp_path, "badyaml", "name: [unclosed")
    write(tmp_path, "badfield", {"name": "x-tool", "title": "X", "kind": "python"})
    reg = discover(tmp_path)
    assert list(reg.plugins) == ["demo-tool"]
    assert len(reg.errors) == 2 and any("invalid YAML" in e for e in reg.errors)


def test_loader_rejects_duplicates_and_unknown_dependencies(tmp_path):
    write(tmp_path, "a", {**BASE, "kind": "static"})
    write(tmp_path, "b", {**BASE, "kind": "static", "title": "Copy"})
    write(tmp_path, "c", {"name": "needs-vault", "title": "N", "kind": "static", "depends_on": ["vault"]})
    reg = discover(tmp_path)
    assert list(reg.plugins) == ["demo-tool"]
    assert any("duplicate plugin name" in e for e in reg.errors)
    assert any("unknown plugin(s): vault" in e for e in reg.errors)


def test_extra_dirs_are_scanned(tmp_path):
    write(tmp_path / "plugins", "custom", {"name": "my-app", "title": "Mine", "kind": "external",
                                           "entry": "http://localhost:9000"})
    reg = discover(tmp_path, extra_dirs=[tmp_path / "plugins"])
    assert "my-app" in reg.plugins


def test_load_manifest_records_source(tmp_path):
    p = write(tmp_path, "t", {**BASE, "kind": "static"})
    assert load_manifest(p).source == str(p)


def test_order_then_title(tmp_path):
    write(tmp_path, "z", {"name": "zeta", "title": "Zeta", "kind": "static", "order": 5})
    write(tmp_path, "a", {"name": "alpha", "title": "Alpha", "kind": "static"})
    write(tmp_path, "b", {"name": "beta", "title": "Beta", "kind": "static"})
    assert list(discover(tmp_path).plugins) == ["zeta", "alpha", "beta"]


# --- against the real repo (A2 "done when": same 20 tools, same order as the old registry.yaml) ------------

EXPECTED = [
    "datadiff-pro", "encode-decode", "subnet-calc", "dns-lookup", "vlan-designer", "packet-journey",
    "curl-builder", "header-reference", "http-methods-status", "cookie-lab", "df-studio", "sql-studio",
    "schema-map", "duck-lab", "vault", "data-syncer", "schema-copy", "data-dumper", "ssh-sftp", "latex-pdf",
]


def test_repo_manifests_cover_all_tools_in_order():
    reg = discover(REPO)
    assert reg.errors == [], reg.errors
    assert reg.warnings == [], reg.warnings
    assert list(reg.plugins)[: len(EXPECTED)] == EXPECTED  # new tools may follow; these keep their order


def test_repo_python_entries_point_at_existing_source():
    for m in discover(REPO).ordered():
        if m.kind == "python":
            pkg = m.module.split(".")[0]
            # image layout renames folders (encode-decode/ → encode_decode/); 'api' stays as is
            folder = REPO / ("api" if pkg == "api" else pkg.replace("_", "-"))
            assert (folder / (m.module.split(".", 1)[1].replace(".", "/") + ".py")).is_file(), m.name


def test_dockerfile_ships_every_manifest():
    """The loader runs inside the image: every manifest must be copied there (whole folder or explicitly)."""
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    for m in discover(REPO).ordered():
        folder = Path(m.source).parent.name
        assert f"COPY {folder}/ " in dockerfile or f"COPY {folder}/manifest.yaml " in dockerfile, \
            f"{m.name}: add `COPY {folder}/manifest.yaml ./<pkg>/manifest.yaml` to the Dockerfile"


def test_singleton_requires_single_replica():
    assert mk(kind="python", entry="x:app", runtime="data", singleton=True).singleton
    with pytest.raises(ValueError, match="singleton"):
        mk(kind="python", entry="x:app", runtime="data", singleton=True, scaling={"max": 2})


def test_repo_singletons_are_the_live_db_pool_tools():
    assert sorted(m.name for m in discover(REPO).ordered() if m.singleton) == ["schema-map", "sql-studio"]


def test_vault_scope_field():
    m = mk(kind="python", entry="x:app", runtime="data", vault={"read": ["postgres_connection"], "datasets": "read"})
    assert m.vault.read == ["postgres_connection"] and m.vault.datasets == "read"
    with pytest.raises(ValueError, match="Vault access"):
        mk(kind="static", vault={"read": ["x"]})
    with pytest.raises(ValueError):
        mk(kind="python", entry="x:app", runtime="data", vault={"datasets": "all"})


def test_repo_vault_scopes():
    scopes = {m.name: m.vault for m in discover(REPO).ordered() if m.vault}
    assert scopes["data-syncer"].read == ["postgres_connection"] and scopes["ssh-sftp"].write == ["ssh_server"]
    assert scopes["df-studio"].datasets == "read" and "vault" not in scopes  # the Vault tool itself is the store


def test_tools_never_use_the_unscoped_vault():
    """Roadmap B7: plugin code reaches secrets only via core.vault.scoped()/ScopedVault."""
    import re

    allowed = {"vault", "core", "orchestrator", "tests"}
    for py in REPO.glob("*/**/*.py"):
        top = py.relative_to(REPO).parts[0]
        if top in allowed:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if re.search(r"from core import [^\n]*\bvault\b(?! as vault_store)", text):
            raise AssertionError(f"{py}: import core.vault as vault_store and use vault_store.scoped(...)")
        bad = set(re.findall(r"vault_store\.(\w+)", text)) - {"scoped", "ScopedVault", "Scope"}
        assert not bad, f"{py}: unscoped Vault calls {bad}"
