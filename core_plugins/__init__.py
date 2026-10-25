"""
core_plugins — the workspace's plugin model and discovery (roadmap A1).

Spec: docs/architecture/plugin-manifest.md. Named `core_plugins` (not `core`) because every tool needs a
uniquely-named top-level package — see "Adding a new tool" in the root CLAUDE.md.
"""

from core_plugins.lazy import DisabledApp, ExternalApp, LazyApp, Slot, StaticApp
from core_plugins.loader import Registry, discover
from core_plugins.manifest import Manifest
from core_plugins.proxy import ProxyApp
from core_plugins.workspace import Workspace, default_path, load_workspace

__all__ = ["DisabledApp", "ExternalApp", "LazyApp", "Manifest", "ProxyApp", "Registry", "Slot", "StaticApp", "Workspace", "default_path", "discover",
           "load_workspace"]
