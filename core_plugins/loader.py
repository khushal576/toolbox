"""
Plugin discovery (spec: docs/architecture/plugin-manifest.md, section "Discovery").

    reg = discover(repo_root)               # scans <repo>/*/manifest.yaml (+ extra plugin dirs)
    reg.plugins["datadiff-pro"].entry       # "api.app:app"
    reg.errors / reg.warnings               # never raised: one broken plugin must not hide the others
"""

from __future__ import annotations

import keyword
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml
from pydantic import ValidationError

from core_plugins.manifest import Manifest

MANIFEST_FILE = "manifest.yaml"


@dataclass
class Registry:
    plugins: dict[str, Manifest] = field(default_factory=dict)  # insertion order = display order
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ordered(self) -> list[Manifest]:
        return list(self.plugins.values())

    def enabled_default(self) -> list[Manifest]:
        return [m for m in self.plugins.values() if m.enabled_by_default]


def _fmt(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'manifest'}: {err['msg']}" for err in e.errors())


def load_manifest(path: Path) -> Manifest:
    """Parse and validate one manifest file. Raises ValueError with a readable message."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("manifest must be a YAML mapping")
    try:
        m = Manifest.model_validate(data)
    except ValidationError as e:
        raise ValueError(_fmt(e)) from None
    m.source = str(path)
    return m


# Custom-app folders (plugins/, roadmap A5) hold kinds that run no server code. A PYTHON plugin runs with the full access of the
# runtime it lands in (database, Redis, S3 and the Vault key: every runtime gets them), so it is allowed there only when the owner opts in with
# TOOLBOX_TRUSTED_PLUGINS=1 (roadmap P1, default OFF). `service` plugins are never accepted from a folder.
EXTRA_DIR_KINDS = ("static", "external")
TRUSTED_ENV = "TOOLBOX_TRUSTED_PLUGINS"
# Only the two general-purpose runtimes mount plugins/ (docker-compose.yml). The on-demand tier-4 runtimes, the DataDiff pool and the
# credential-free notebook runtime never run custom code.
TRUSTED_PLUGIN_RUNTIMES = ("light", "data")


def trusted_plugins_enabled(env: Optional[dict] = None) -> bool:
    """True only for an explicit 1 / true / yes / on. Anything else (unset, 0, empty, typos) is OFF."""
    v = str((os.environ if env is None else env).get(TRUSTED_ENV, "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def extra_dir_kinds_for(env: Optional[dict] = None) -> tuple[str, ...]:
    return EXTRA_DIR_KINDS + (("python",) if trusted_plugins_enabled(env) else ())


def _refusal(path: Path, m: Manifest) -> str:
    if m.kind == "python":
        return (f"{path}: kind 'python' is not allowed in a custom-app folder because trusted Python plugins are OFF. A Python plugin runs "
                f"with full access inside Toolbox (database, Redis, S3 and the Vault key, so it can read every saved secret). To allow it: set "
                f"{TRUSTED_ENV}=1 in .env and run `docker compose up -d` — or build the plugin into the image like a built-in tool "
                f"(CLAUDE.md, 'Adding a new tool'). Only do this for code you wrote or fully trust.")
    return (f"{path}: kind '{m.kind}' is not allowed in a custom-app folder (only static, external"
            f"{' and python' if trusted_plugins_enabled() else ''} are); service plugins must be built into the image")


# Names a custom plugin's top-level package must never shadow: Toolbox's own packages and the standard library.
def _reserved_names(repo: Path) -> set[str]:
    names = {p.name for p in repo.iterdir() if p.is_dir() or p.suffix == ".py"} | {p.stem for p in repo.glob("*.py")}
    names |= {n.replace("-", "_") for n in list(names)}
    return names | set(getattr(sys, "stdlib_module_names", ())) | {"pip", "setuptools", "yaml", "fastapi", "starlette", "pydantic", "uvicorn"}


def _check_trusted_python(path: Path, m: Manifest, repo: Path) -> Optional[str]:
    """Extra rules for a python plugin that comes from plugins/ (it is imported by NAME, so the name must be safe and unique)."""
    folder = path.parent.name
    if not folder.isidentifier() or keyword.iskeyword(folder) or folder.startswith("_") or folder != folder.lower():
        return (f"{path}: a Python plugin's folder name is its import name, so it must be a plain lowercase identifier "
                f"(letters, digits, underscore; not starting with '_' or a digit) — rename '{folder}'")
    if folder in _reserved_names(repo):
        return f"{path}: folder name '{folder}' would shadow a Toolbox or standard-library package — pick another name"
    top = (m.module or "").split(".")[0]
    if top != folder:
        return f"{path}: entry must start with the folder name ('{folder}.<module>:app'), but it is '{m.entry}'"
    if m.runtime not in TRUSTED_PLUGIN_RUNTIMES:
        return f"{path}: custom Python plugins may only run in the {' or '.join(TRUSTED_PLUGIN_RUNTIMES)} runtime (manifest says '{m.runtime}')"
    if m.singleton:
        return f"{path}: `singleton: true` is not supported for custom Python plugins"
    return None


def discover(repo: Path | str, extra_dirs: Iterable[Path | str] = (),
             extra_dir_kinds: Optional[Iterable[str]] = None) -> Registry:
    """Find, validate and order all plugins. Never raises for a bad plugin; see Registry.errors.
    extra_dir_kinds: which kinds the custom-app folders may hold; default = static + external (+ python when TOOLBOX_TRUSTED_PLUGINS=1)."""
    repo = Path(repo)
    reg = Registry()
    found: list[Manifest] = []
    allowed_extra = set(extra_dir_kinds_for() if extra_dir_kinds is None else extra_dir_kinds)

    paths = [(p, False) for p in sorted(repo.glob(f"*/{MANIFEST_FILE}"))]
    for d in extra_dirs:
        paths += [(p, True) for p in sorted(Path(d).glob(f"*/{MANIFEST_FILE}"))]

    seen: dict[str, str] = {}
    for p, from_extra in paths:
        try:
            m = load_manifest(p)
        except ValueError as e:
            reg.errors.append(f"{p}: {e}")
            continue
        if from_extra and m.kind not in allowed_extra:
            reg.errors.append(_refusal(p, m))
            continue
        if from_extra and m.kind == "python":
            problem = _check_trusted_python(p, m, repo)
            if problem:
                reg.errors.append(problem)
                continue
            reg.warnings.append(f"{m.name}: custom Python plugin from {p.parent} — trusted code, runs with the access of the '{m.runtime}' runtime")
        if m.name in seen:
            reg.errors.append(f"{p}: duplicate plugin name '{m.name}' (already defined in {seen[m.name]})")
            continue
        seen[m.name] = str(p)
        found.append(m)

    ordered = sorted(found, key=lambda m: (m.order, m.title.lower()))

    names = {m.name for m in ordered}
    for m in ordered:
        missing = [d for d in m.depends_on if d not in names]
        if missing:
            reg.errors.append(f"{m.source}: '{m.name}' depends on unknown plugin(s): {', '.join(missing)}")
            continue
        reg.plugins[m.name] = m
        reg.warnings += m.warnings()
    return reg
