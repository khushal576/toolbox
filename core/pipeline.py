"""
core/pipeline.py

The comparison pipeline, extracted from api/app.py's /compare endpoint so
it has exactly one copy, callable from two places:
  - api/app.py (DataDiff Pro's web UI) — still owns parsing raw pasted
    text via normalize() before calling this.
  - orchestrator/recipes/compare.py (headless, e.g. DB-to-DB diffs) —
    already has structured Python objects (DB rows, parsed files) and
    calls this directly, skipping normalize() entirely.

run_compare() takes already-normalized Python objects (dict/list/scalar on
each side — whatever normalize() or a DB/file connector produced) and runs
field mapping → deep-expand → equivalence/list-resolver construction →
DiffEngine.compare() → a plain JSON-serializable dict. It raises
PipelineError (not HTTP-shaped) on any input problem; callers translate
that into whatever error shape fits their context (api/app.py wraps it as
a 422 JSON envelope, the orchestrator CLI prints it to stderr).
"""

from __future__ import annotations

from typing import Any

from core.mapper import parse_mapping, apply_mapping, MapTrace
from core.equivalence import EquivalenceEngine
from core.list_resolver import ListResolver
from core.diff_engine import DiffEngine, DiffRecord, DiffResult
from core.deep_expander import deep_expand
from core.validator import validate_transform, ValidationResult


class PipelineError(ValueError):
    pass


def _validate_yaml(yaml_text: str) -> str | None:
    """Return a human-readable error if *yaml_text* doesn't parse, else None."""
    try:
        import yaml
        yaml.safe_load(yaml_text)
        return None
    except ImportError:
        return None  # yaml not installed — skip validation, engines will handle it
    except Exception as exc:
        return (
            f"Invalid YAML: {exc}. "
            f"Check indentation and ensure keys are followed by a colon and space."
        )


def _record_to_dict(record: DiffRecord) -> dict:
    d: dict = {
        "path": record.path,
        "left_value": record.left_value,
        "right_value": record.right_value,
        "status": record.status,
    }
    if record.trace:
        d["trace"] = record.trace
    return d


def _trace_to_dict(trace: MapTrace) -> dict:
    return {
        "rule_index": trace.rule_index,
        "src_path": trace.src_path,
        "tgt_path": trace.tgt_path,
        "resolved_src_paths": trace.resolved_src_paths,
        "action": trace.action,
        "detail": trace.detail,
    }


def _validation_to_dict(v: ValidationResult) -> dict:
    return {
        "passed": v.passed,
        "warnings": v.warnings,
        "errors": v.errors,
        "dropped_paths": v.dropped_paths,
    }


def run_compare(
    left_data: Any,
    right_data: Any,
    *,
    mapper_csv: str | None = None,
    mapper_direction: str = "left_to_right",
    strict_mode: bool = False,
    multi_match_rule: str = "keep_list",
    deep_mode: bool = False,
    environment_yaml: str | None = None,
    null_missing_equivalent: bool = False,
) -> dict:
    """Run field mapping + diff on two already-parsed Python objects.

    Returns a dict shaped like {"summary", "records", "list_strategies",
    "map_traces", "validation", "warnings", "meta"} — the same shape
    api/app.py's /compare returns, minus the "ok"/left_format/right_format
    keys, which are the HTTP layer's own concern, not this pipeline's.
    Raises PipelineError on any input problem (bad direction, bad mapper
    CSV, failed mapping validation, bad environment YAML, or an unexpected
    DiffEngine failure).
    """
    direction = (mapper_direction or "left_to_right").strip().lower()
    if direction not in ("left_to_right", "right_to_left"):
        raise PipelineError(
            f"Invalid mapper_direction '{mapper_direction}'. "
            f"Use 'left_to_right' or 'right_to_left'."
        )

    # Deep Mode expands string-encoded JSON/XML values BEFORE mapping so the
    # mapper can navigate into expanded fields.
    if deep_mode:
        left_data = deep_expand(left_data)
        right_data = deep_expand(right_data)

    map_traces: list[MapTrace] = []
    validation: ValidationResult | None = None

    if mapper_csv and mapper_csv.strip():
        mapping_pairs, map_err = parse_mapping(mapper_csv)
        if map_err:
            raise PipelineError(f"Field mapper — {map_err}")
        if mapping_pairs:
            try:
                if direction == "left_to_right":
                    original_snapshot = left_data
                    left_data, map_traces = apply_mapping(
                        left_data, mapping_pairs,
                        strict_mode=strict_mode,
                        multi_match_rule=multi_match_rule,
                    )
                    validation = validate_transform(
                        original_snapshot, left_data,
                        mapping_pairs, map_traces,
                        strict_mode=strict_mode,
                    )
                else:  # right_to_left
                    original_snapshot = right_data
                    right_data, map_traces = apply_mapping(
                        right_data, mapping_pairs,
                        strict_mode=strict_mode,
                        multi_match_rule=multi_match_rule,
                    )
                    validation = validate_transform(
                        original_snapshot, right_data,
                        mapping_pairs, map_traces,
                        strict_mode=strict_mode,
                    )
            except ValueError as exc:
                raise PipelineError(f"Field mapper (strict mode) — {exc}") from exc

            if validation and not validation.passed:
                raise PipelineError(
                    "Mapping validation failed:\n"
                    + "\n".join(f"  • {e}" for e in validation.errors)
                )

    yaml_text = environment_yaml or ""
    if yaml_text.strip():
        yaml_err = _validate_yaml(yaml_text)
        if yaml_err:
            raise PipelineError(f"Environment YAML — {yaml_err}")

    eq_engine = EquivalenceEngine(yaml_text)
    list_resolver = ListResolver(yaml_text)

    engine = DiffEngine(
        eq_engine, list_resolver,
        deep_mode=deep_mode, null_missing_equivalent=null_missing_equivalent,
    )
    try:
        diff_result: DiffResult = engine.compare(left_data, right_data)
    except Exception as exc:
        raise PipelineError(
            f"Diff engine encountered an unexpected error: {exc}. "
            f"Please check your input data and try again."
        ) from exc

    return {
        "summary": diff_result.summary,
        "records": [_record_to_dict(r) for r in diff_result.records],
        "list_strategies": diff_result.list_strategies,
        "map_traces": [_trace_to_dict(t) for t in map_traces],
        "validation": _validation_to_dict(validation) if validation else None,
        "warnings": validation.warnings if validation else [],
        "meta": {
            "mapping_applied": bool(mapper_csv and mapper_csv.strip()),
            "mapper_direction": direction,
            "strict_mode": strict_mode,
            "multi_match_rule": multi_match_rule,
            "deep_mode": deep_mode,
            "environment_applied": bool(yaml_text.strip()),
        },
    }
