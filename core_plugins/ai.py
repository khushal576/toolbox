"""
core_plugins/ai.py — checking and building the calls of a manifest's `ai:` actions (roadmap H3). PURE: no network, no file access.

    validate_inputs(action, {"id": "x"}) -> clean inputs (defaults applied)   # raises AiInputError with a plain sentence
    build_request(tool_name, action, clean) -> ("/tools/<name>/items/x", {"q": "y"})   # path + query params

Why it is strict: the AI chooses the inputs. Unknown inputs are refused, every value is checked against the declared type and limits,
and a value that goes into the URL path can never contain a '/', '..', '%', '?' or '#', so an action can never reach another tool or
another endpoint than the one the manifest declared.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from core_plugins.manifest import AiAction

_SAFE_PATH_VALUE = re.compile(r"^[A-Za-z0-9_.@:+=,-]{1,200}$")


class AiInputError(ValueError):
    """The inputs do not fit the action (a sentence for the AI and the owner)."""


def _check_one(name: str, spec: Any, v: Any) -> Any:
    t = spec.type
    if t == "boolean":
        if not isinstance(v, bool):
            raise AiInputError(f"'{name}' must be true or false.")
        return v
    if t == "integer":
        if isinstance(v, bool) or not isinstance(v, int):
            raise AiInputError(f"'{name}' must be a whole number.")
    elif t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
            raise AiInputError(f"'{name}' must be a number.")
    else:
        if not isinstance(v, str):
            raise AiInputError(f"'{name}' must be text.")
        if "\x00" in v or any(ord(c) < 32 and c not in "\t" for c in v):
            raise AiInputError(f"'{name}' contains control characters.")
        if spec.max_length is not None and len(v) > spec.max_length:
            raise AiInputError(f"'{name}' is longer than {spec.max_length} characters.")
    if spec.enum is not None and v not in spec.enum:
        raise AiInputError(f"'{name}' must be one of: {', '.join(str(e) for e in spec.enum)}.")
    if t in ("integer", "number"):
        if spec.minimum is not None and v < spec.minimum:
            raise AiInputError(f"'{name}' must be at least {spec.minimum:g}.")
        if spec.maximum is not None and v > spec.maximum:
            raise AiInputError(f"'{name}' must be at most {spec.maximum:g}.")
    return v


def validate_inputs(action: AiAction, inputs: Any) -> dict[str, Any]:
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise AiInputError("inputs must be an object (key: value).")
    unknown = sorted(set(inputs) - set(action.inputs))
    if unknown:
        raise AiInputError(f"unknown input(s): {', '.join(unknown)}. This action takes: {', '.join(action.inputs) or 'no inputs'}.")
    clean: dict[str, Any] = {}
    for name, spec in action.inputs.items():
        if name in inputs and inputs[name] is not None:
            clean[name] = _check_one(name, spec, inputs[name])
        elif name in action.required:
            raise AiInputError(f"missing required input '{name}'.")
        elif spec.default is not None:
            clean[name] = _check_one(name, spec, spec.default)
    return clean


def build_request(tool_name: str, action: AiAction, clean: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """(URL path below the gateway root, query parameters). Path values are checked again here — this is the last line before the network."""
    path = action.path
    used = set()
    for ph in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path):
        val = str(clean[ph])
        if not _SAFE_PATH_VALUE.match(val) or val in (".", ".."):
            raise AiInputError(f"'{ph}' may only contain letters, digits and _ . @ : + = , - (it becomes part of the address).")
        path = path.replace("{" + ph + "}", quote(val, safe=""))
        used.add(ph)
    query = {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in clean.items() if k not in used}
    return f"/tools/{tool_name}/{path}", query
