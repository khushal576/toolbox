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
Runtime = Literal["light", "data", "pgtools", "latex", "ssh", "datadiff", "notebook"]
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
    data: Literal["none", "read", "write"] = "none"      # Vault Data = lake tables (roadmap L1, core/lake.py)


# ---- AI actions (roadmap H3, docs/architecture/ADR-AI-HELPER.md D6) ----------------------------------------------------------------
# A tool may describe what an AI can DO with it. Only stateless READ actions are declared here: they are plain GET requests to the
# tool's own API, run through the gateway. Anything that changes data stays in the MCP server's code, where the owner's grant,
# dry-run, confirm code and read-back live — a manifest can never expose an unguarded write.
AI_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
AI_PATH_RE = re.compile(r"^[A-Za-z0-9_./{}-]{1,120}$")
AI_PARAM_TYPES = ("string", "integer", "number", "boolean")
MAX_AI_ACTIONS = 20


class AiParam(_Strict):
    """One input of an action. Flat on purpose: a string / number / boolean, optionally limited."""
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = Field(default="", max_length=200)
    enum: list[str | int | float] | None = None
    max_length: int | None = Field(default=None, ge=1, le=10000)
    minimum: float | None = None
    maximum: float | None = None
    default: str | int | float | bool | None = None


class AiAction(_Strict):
    name: str
    summary: str = Field(min_length=3, max_length=200)           # one line: what it does, in the user's words (searched by find_actions)
    effect: Literal["read"] = "read"                              # only read actions can be declared in a manifest (see above)
    method: Literal["GET"] = "GET"
    path: str                                                     # relative to /tools/<name>/ ; {param} placeholders allowed
    inputs: dict[str, AiParam] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    returns: str = Field(default="", max_length=200)             # one line: what comes back

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not AI_NAME_RE.match(v):
            raise ValueError("action name must be lowercase letters, digits and _ (2-41 characters, starting with a letter)")
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        parts = v.split("/")
        if not AI_PATH_RE.match(v) or v.startswith("/") or ".." in parts or "" in parts[:-1] or "//" in v or "?" in v or "#" in v:
            raise ValueError("path must be a relative API path like 'template/list' or 'items/{id}' (no leading '/', no '..', no query string)")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "AiAction":
        for ph in re.findall(r"\{([^}]*)\}", self.path):
            spec = self.inputs.get(ph)
            if spec is None or ph not in self.required:
                raise ValueError(f"path placeholder {{{ph}}} must be a required input")
            if spec.type not in ("string", "integer") or (spec.type == "string" and spec.max_length is None and not spec.enum):
                raise ValueError(f"input '{ph}' is used in the path: it must be an integer, or a string with max_length or enum")
        if "{" in self.path.replace("{", "", 0) and not re.fullmatch(r"[^{}]*(\{[A-Za-z_][A-Za-z0-9_]*\}[^{}]*)*", self.path):
            raise ValueError("malformed {placeholder} in path")
        for r in self.required:
            if r not in self.inputs:
                raise ValueError(f"required input '{r}' is not declared under inputs")
        for n in self.inputs:
            if not AI_NAME_RE.match(n):
                raise ValueError(f"input name '{n}' must be lowercase letters, digits and _")
        return self


class AiSpec(_Strict):
    actions: list[AiAction] = Field(default_factory=list, max_length=MAX_AI_ACTIONS)

    @model_validator(mode="after")
    def _unique(self) -> "AiSpec":
        names = [a.name for a in self.actions]
        if len(names) != len(set(names)):
            raise ValueError("action names must be unique within a tool")
        return self


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
    # Mounted and working (its API is used by other pages) but no home card, no sidebar entry, no Settings switch.
    hidden: bool = False
    order: int = Field(default=1000, ge=0)  # display order (lower first); ties sorted by title
    # Must run in exactly ONE process (e.g. a single live DB pool + "password never stored"): B9 routes all its
    # requests to one dedicated process when the rest of the workspace runs several workers.
    singleton: bool = False
    vault: VaultAccess | None = None  # no entry = no Vault access from server code
    ai: AiSpec | None = None          # what an AI can do with this tool (read actions only; roadmap H3)

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
        if self.ai is not None and self.ai.actions and k != "python":
            raise ValueError(f"kind '{k}' has no server API, so it cannot declare ai actions")
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
