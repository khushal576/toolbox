"""
Workspace settings: which plugins are turned on (roadmap A3; edited by the settings page in A4).

File: $TOOLBOX_WORKSPACE_FILE, default <repo>/data/workspace/workspace.yaml (a Docker volume in compose).

    # Missing tools use their manifest's enabled_by_default.
    enabled:
      latex-pdf: false

A missing file means "all defaults". A broken file is reported and ignored (defaults used) — a typo in
settings must never take the whole workspace down.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core_plugins.manifest import Manifest

ENV_VAR = "TOOLBOX_WORKSPACE_FILE"


def default_path(repo: Path) -> Path:
    return Path(os.environ.get(ENV_VAR) or repo / "data" / "workspace" / "workspace.yaml")


@dataclass
class Workspace:
    path: Path
    enabled: dict[str, bool] = field(default_factory=dict)  # explicit overrides only
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_enabled(self, m: Manifest) -> bool:
        return self.enabled.get(m.name, m.enabled_by_default)

    def set_enabled(self, name: str, value: bool) -> None:
        self.enabled[name] = bool(value)

    def save(self) -> None:
        """Write atomically (temp file + rename) so a crash never leaves half a file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = ("# Toolbox workspace settings — written by the workspace (roadmap A3/A4).\n"
                "# Missing tools use their manifest's enabled_by_default.\n"
                + yaml.safe_dump({"enabled": dict(sorted(self.enabled.items()))}, sort_keys=False))
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.path)


def load_workspace(path: Path, known: set[str] | None = None) -> Workspace:
    ws = Workspace(path=path)
    if not path.exists():
        return ws
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not isinstance(data.get("enabled", {}), dict):
            raise ValueError("expected a mapping with an 'enabled:' mapping of tool-name: true|false")
        for name, val in (data.get("enabled") or {}).items():
            if not isinstance(val, bool):
                raise ValueError(f"enabled.{name} must be true or false, got {val!r}")
            ws.enabled[str(name)] = val
    except (yaml.YAMLError, ValueError, OSError) as e:
        ws.enabled = {}
        ws.errors.append(f"{path}: {e} — using defaults (all tools at their manifest default)")
        return ws
    if known is not None:
        for name in sorted(set(ws.enabled) - known):
            ws.warnings.append(f"{path}: unknown tool '{name}' ignored")
    return ws
