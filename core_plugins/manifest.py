"""
Plugin manifest model (spec: docs/architecture/plugin-manifest.md).

A manifest says what a tool is (name, title, icon), how the workspace loads it (kind + entry), where it
runs (runtime, tier) and what it needs (state, resources, scaling, depends_on, requires).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["static", "python", "external", "service"]
Runtime = Literal["light", "data", "pgtools", "latex", "ssh", "datadiff"]
StateKind = Literal["session", "durable", "jobs"]

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
ENTRY_PY_RE = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*:[A-Za-z_]\w*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos in manifests must fail, not pass silently


class Resources(_Strict):
    cpu: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)


class Scaling(_Strict):
    min: int = Field(default=0, ge=0)
    max: int = Field(default=1, ge=1)
    idle_timeout_s: int = Field(default=900, ge=0)

    @model_validator(mode="after")
    def _min_le_max(self) -> "Scaling":
        if self.min > self.max:
            raise ValueError(f"scaling.min ({self.min}) must be <= scaling.max ({self.max})")
        return self


class VaultAccess(_Strict):
    """What a plugin's server code may do in the Vault (roadmap B7; enforced by core.vault.scoped())."""
    read: list[str] = Field(default_factory=list)       # secret kinds it may decrypt
    write: list[str] = Field(default_factory=list)      # kinds it may create/update (implies read)
    datasets: Literal["none", "read", "write"] = "none"  # load any saved dataset / also save datasets


class Manifest(_Strict):
    schema_version: Literal[1] = 1
    name: str
    title: str = Field(min_length=1)
    description: str = ""
    icon: str = ""
    category: Literal["tool", "learn"] = "tool"
    kind: Kind
    entry: str | None = None
    runtime: Runtime | None = None
    tier: int = Field(default=2, ge=1, le=4)
    state: list[StateKind] = Field(default_factory=list)
    resources: Resources = Field(default_factory=Resources)
    scaling: Scaling = Field(default_factory=Scaling)
    depends_on: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    enabled_by_default: bool = True
    order: int = Field(default=1000, ge=0)  # display order (lower first); ties sorted by title
    # Must run in exactly ONE process (e.g. a single live DB pool + "password never stored"): B9 routes all its
    # requests to one dedicated process when the rest of the workspace runs several workers.
    singleton: bool = False
    vault: VaultAccess | None = None  # no entry = no Vault access from server code

    # Filled by the loader, not by authors (excluded from the YAML contract).
    source: str = Field(default="", exclude=True)

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("name must be a lowercase slug: letters, digits, '-'; 2-63 chars; start with a letter/digit")
        return v

    @field_validator("state", "depends_on", "requires")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("list must not contain duplicates")
        return v

    @model_validator(mode="after")
    def _kind_rules(self) -> "Manifest":
        k = self.kind
        if k == "python":
            if not self.entry or not ENTRY_PY_RE.match(self.entry):
                raise ValueError("kind 'python' needs entry 'module.path:attribute' (an ASGI app), e.g. api.app:app")
        if k in ("external", "service"):
            if not self.entry or not re.match(r"^https?://", self.entry):
                raise ValueError(f"kind '{k}' needs entry as an http:// or https:// URL")
        if k == "static":
            self.entry = self.entry or "ui/index.html"
            if re.match(r"^\w+://", self.entry) or self.entry.startswith("/") or ".." in self.entry.split("/"):
                raise ValueError("kind 'static' needs entry as a relative path inside the plugin folder")
        if k in ("python", "service") and self.runtime is None:
            raise ValueError(f"kind '{k}' needs a runtime (light | data | pgtools | latex | ssh | datadiff)")
        if k in ("static", "external"):
            if self.runtime is not None:
                raise ValueError(f"kind '{k}' runs no server code, so runtime must be empty")
            if self.state:
                raise ValueError(f"kind '{k}' cannot keep server state")
            if self.vault is not None:
                raise ValueError(f"kind '{k}' runs no server code, so it cannot have Vault access")
        if self.name in self.depends_on:
            raise ValueError("a plugin cannot depend on itself")
        if self.singleton and (self.scaling.max != 1 or self.scaling.min > 1):
            raise ValueError("a singleton plugin must keep scaling.max: 1")
        return self

    @property
    def mount_path(self) -> str:
        return f"/tools/{self.name}"

    @property
    def module(self) -> str | None:
        """For kind 'python': the module part of entry (what main.py imports)."""
        return self.entry.split(":", 1)[0] if self.kind == "python" and self.entry else None

    def warnings(self) -> list[str]:
        """Soft checks: reported, never blocking."""
        out = []
        if self.state and self.scaling.max > 1:
            out.append(f"{self.name}: stateful plugin with scaling.max={self.scaling.max}; keep 1 until roadmap B9 "
                       f"moves its state out of process")
        return out
