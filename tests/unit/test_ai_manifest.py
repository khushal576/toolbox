"""
Roadmap H3 — the `ai:` section of a manifest (core_plugins/manifest.py) and the checks on its inputs (core_plugins/ai.py).

The AI chooses the inputs of an action, so: only read GETs can be declared, the path can only be the declared template, unknown inputs are
refused, values are typed and limited, and a value that goes into the address can never leave the tool's own prefix.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import discover  # noqa: E402
from core_plugins.ai import AiInputError, build_request, validate_inputs  # noqa: E402
from core_plugins.manifest import Manifest  # noqa: E402

BASE = {"name": "demo-tool", "title": "Demo", "kind": "python", "entry": "demo_tool.server:app", "runtime": "light"}


def mani(*actions, **extra):
    return Manifest.model_validate({**BASE, "ai": {"actions": list(actions)}, **extra})


def act(**kw):
    return {"name": "do_it", "summary": "Does the thing", "path": "things", **kw}


ITEM = act(name="get_item", path="items/{id}", inputs={"id": {"type": "string", "max_length": 40}, "verbose": {"type": "boolean", "default": False},
                                                       "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                                                       "kind": {"type": "string", "enum": ["a", "b"]}, "ratio": {"type": "number", "minimum": 0, "maximum": 1}},
           required=["id"])


# ------------------------------------------------------------------------------------------------------------ the manifest model

def test_a_valid_action_loads_and_the_section_is_optional():
    m = mani(ITEM)
    a = m.ai.actions[0]
    assert (a.name, a.effect, a.method, a.path) == ("get_item", "read", "GET", "items/{id}") and a.inputs["limit"].default == 10
    assert Manifest.model_validate(BASE).ai is None                                            # existing manifests are untouched


@pytest.mark.parametrize("bad,why", [
    (act(effect="write"), "read"), (act(effect="delete"), "read"), (act(method="POST"), "GET"), (act(method="DELETE"), "GET"),
    (act(path="../other/x"), "relative API path"), (act(path="/other/x"), "relative API path"), (act(path="a//b"), "relative API path"),
    (act(path="x?y=1"), "relative API path"), (act(path="x#frag"), "relative API path"), (act(path="http://evil/x"), "relative API path"),
    (act(path="a/../b"), "relative API path"), (act(path=""), "relative API path"), (act(path="a b"), "relative API path"),
    (act(path="items/{id}"), "must be a required input"),                                      # placeholder without an input
    (act(path="items/{id}", inputs={"id": {"type": "string"}}, required=["id"]), "max_length or enum"),   # unbounded text in the address
    (act(path="items/{id}", inputs={"id": {"type": "boolean"}}, required=["id"]), "integer, or a string"),
    (act(path="items/{id}", inputs={"id": {"type": "integer"}}), "must be a required input"),               # not required
    (act(inputs={"q": {"type": "object"}}), "string"), (act(inputs={"q": {"type": "array"}}), "string"),
    (act(inputs={"Q": {"type": "string"}}), "lowercase"), (act(inputs={"q": {"type": "string"}}, required=["z"]), "not declared"),
    (act(headers={"a": "b"}), "Extra inputs"), (act(body={"a": 1}), "Extra inputs"), (act(inputs={"q": {"type": "string", "pattern": ".*"}}), "Extra inputs"),
    (act(name="X"), "lowercase"), (act(name="a"), "lowercase"), (act(name="has space"), "lowercase"), (act(name="1abc"), "lowercase"),
    (act(summary="ab"), "at least 3"), (act(summary="x" * 201), "at most 200"),
])
def test_what_a_manifest_may_not_declare(bad, why):
    with pytest.raises(ValidationError) as e:
        mani(bad)
    assert why in str(e.value), str(e.value)[:300]


def test_names_are_unique_and_the_count_is_limited():
    with pytest.raises(ValidationError):
        mani(act(), act())
    with pytest.raises(ValidationError):
        mani(*[act(name=f"act_{i:02d}") for i in range(21)])
    assert len(mani(*[act(name=f"act_{i:02d}") for i in range(20)]).ai.actions) == 20


def test_only_python_tools_have_an_api_to_describe():
    for kind, extra in (("static", {"entry": "ui/index.html", "runtime": None}), ("external", {"entry": "https://example.com", "runtime": None})):
        with pytest.raises(ValidationError) as e:
            Manifest.model_validate({**BASE, "kind": kind, **extra, "ai": {"actions": [act()]}})
        assert "no server API" in str(e.value)


# ------------------------------------------------------------------------------------------------------------ validating the inputs

def a_():
    return mani(ITEM).ai.actions[0]


def test_inputs_are_checked_and_defaults_applied():
    assert validate_inputs(a_(), {"id": "abc"}) == {"id": "abc", "verbose": False, "limit": 10}
    assert validate_inputs(a_(), {"id": "abc", "limit": 5, "kind": "b", "ratio": 0.5, "verbose": True}) == {"id": "abc", "verbose": True, "limit": 5, "kind": "b", "ratio": 0.5}
    assert validate_inputs(a_(), {"id": "abc", "limit": None})["limit"] == 10                          # null = not given


@pytest.mark.parametrize("inputs,msg", [
    (None, "missing required"), ({}, "missing required"), ("x", "must be an object"), (["x"], "must be an object"),
    ({"id": "a", "nope": 1}, "unknown input"), ({"id": "a", "limit": "5"}, "whole number"), ({"id": "a", "limit": 5.5}, "whole number"),
    ({"id": "a", "limit": True}, "whole number"), ({"id": "a", "limit": 0}, "at least 1"), ({"id": "a", "limit": 101}, "at most 100"),
    ({"id": 5}, "must be text"), ({"id": "x" * 41}, "longer than 40"), ({"id": "a\x00b"}, "control characters"), ({"id": "a\nb"}, "control characters"),
    ({"id": "a", "verbose": "yes"}, "true or false"), ({"id": "a", "verbose": 1}, "true or false"), ({"id": "a", "kind": "c"}, "one of"),
    ({"id": "a", "ratio": float("nan")}, "must be a number"), ({"id": "a", "ratio": float("inf")}, "must be a number"), ({"id": "a", "ratio": 1.5}, "at most"),
    ({"id": "a", "ratio": True}, "must be a number"),
])
def test_bad_inputs_are_refused_with_a_plain_sentence(inputs, msg):
    with pytest.raises(AiInputError) as e:
        validate_inputs(a_(), inputs)
    assert msg in str(e.value)


# ------------------------------------------------------------------------------------------------------------ building the request

def test_the_address_is_always_below_the_tools_own_prefix():
    path, query = build_request("demo-tool", a_(), validate_inputs(a_(), {"id": "abc-1.2_x", "limit": 7, "verbose": True}))
    assert path == "/tools/demo-tool/items/abc-1.2_x" and query == {"limit": "7", "verbose": "true"}        # path values are not repeated in the query
    path, query = build_request("demo-tool", mani(act()).ai.actions[0], {})
    assert (path, query) == ("/tools/demo-tool/things", {})


@pytest.mark.parametrize("evil", ["../x", "a/b", "a?b=1", "a#b", "%2e%2e", "..", ".", "a b", "a\\b", "x/../y", "id;rm", "a%2Fb", "é"])
def test_a_value_that_would_leave_the_declared_address_is_refused(evil):
    a = a_()
    with pytest.raises(AiInputError):
        build_request("demo-tool", a, validate_inputs(a, {"id": evil}))


def test_integers_in_the_path_are_fine_and_cannot_carry_anything_else():
    a = mani(act(path="rows/{row}", inputs={"row": {"type": "integer", "minimum": 0}}, required=["row"])).ai.actions[0]
    assert build_request("demo-tool", a, validate_inputs(a, {"row": 12}))[0] == "/tools/demo-tool/rows/12"
    with pytest.raises(AiInputError):
        validate_inputs(a, {"row": "12/../x"})


# ------------------------------------------------------------------------------------------------------------ the real manifests

def _routes(folder: Path) -> set[str]:
    found = set()
    for py in folder.rglob("*.py"):
        for m in re.finditer(r'@\w+\.get\(\s*["\']([^"\']*)["\']', py.read_text(encoding="utf-8", errors="replace")):
            found.add(re.sub(r"\{[^}]*\}", "{}", m.group(1)).lstrip("/"))
    return found


def test_every_declared_real_action_exists_as_a_get_route_in_its_tool():
    """Drift guard: a manifest must not describe an endpoint the tool no longer has."""
    reg = discover(REPO)
    assert reg.errors == []
    declared = [(m, a) for m in reg.ordered() if m.ai for a in m.ai.actions]
    assert len(declared) >= 3
    for m, a in declared:
        folder = Path(m.source).parent
        want = re.sub(r"\{[^}]*\}", "{}", a.path)
        assert want in _routes(folder), f"{m.name}.{a.name}: GET /{a.path} is not a route in {folder.name}/"


def test_real_summaries_are_short_and_unique_enough_to_search():
    seen = {}
    for m in discover(REPO).ordered():
        for a in (m.ai.actions if m.ai else []):
            assert 10 <= len(a.summary) <= 200
            seen.setdefault(a.summary, []).append(f"{m.name}.{a.name}")
    assert all(len(v) == 1 for v in seen.values()), seen
