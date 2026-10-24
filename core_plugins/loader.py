"""
Plugin discovery (spec: docs/architecture/plugin-manifest.md, section "Discovery").

    reg = discover(repo_root)               # scans <repo>/*/manifest.yaml (+ extra plugin dirs)
    reg.plugins["datadiff-pro"].entry       # "api.app:app"
    reg.errors / reg.warnings               # never raised: one broken plugin must not hide the others
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

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


# Custom-app folders (plugins/, roadmap A5) may only hold kinds that run no server code: a python plugin runs
# with full access inside the container (Vault included), so it must be added to the image on purpose.
EXTRA_DIR_KINDS = ("static", "external")


def discover(repo: Path | str, extra_dirs: Iterable[Path | str] = (),
             extra_dir_kinds: Iterable[str] = EXTRA_DIR_KINDS) -> Registry:
    """Find, validate and order all plugins. Never raises for a bad plugin; see Registry.errors."""
    repo = Path(repo)
    reg = Registry()
    found: list[Manifest] = []
    allowed_extra = set(extra_dir_kinds)

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
            reg.errors.append(f"{p}: kind '{m.kind}' is not allowed in a custom-app folder (only "
                              f"{', '.join(sorted(allowed_extra))}); python/service plugins must be built into the image")
            continue
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
