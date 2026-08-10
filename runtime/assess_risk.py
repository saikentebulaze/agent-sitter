from __future__ import annotations
import argparse
from pathlib import Path
from common import load_json_or_yaml_like, fail

LEVELS = ["low", "medium", "high", "critical"]

PLUS_ONE = {
    "public_interface_changed", "member_state_added", "state_update_order_changed",
    "lifecycle_changed", "cache_changed", "existing_test_assertion_changed",
    "numeric_tolerance_changed", "error_strategy_changed", "legacy_patch_area"
}
AT_LEAST_HIGH = {
    "dependency_direction_changed", "new_core_abstraction",
    "requirement_assumption_wrong", "state_ownership_changed",
    "core_responsibility_changed"
}
SEMANTIC_CRITICAL = {
    "nonlinear_iteration_changed", "trial_commit_semantics_changed",
    "core_element_theory_changed", "dof_coordinate_sign_unit_changed",
    "assembly_condense_release_constraint_order_changed",
    "path_dependency_changed", "cross_case_state_reuse_changed",
    "core_numeric_infrastructure_changed"
}

def bump(level: str, count: int = 1) -> str:
    return LEVELS[min(LEVELS.index(level) + count, len(LEVELS) - 1)]

def read_level(risk: dict, dimension: str) -> str:
    value = risk.get(dimension, {})
    if isinstance(value, dict):
        value = value.get("initial", "low")
    value = str(value or "low").lower()
    if value not in LEVELS:
        fail(f"invalid {dimension} risk: {value}")
    return value

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", type=Path)
    args = ap.parse_args()
    if not args.task.exists():
        fail(f"task file not found: {args.task}")

    data = load_json_or_yaml_like(args.task)
    risk = data.get("risk", {}) or {}
    semantic = read_level(risk, "semantic")
    repository = read_level(risk, "repository_change")

    # Backward compatibility
    if "semantic" not in risk and "repository_change" not in risk:
        legacy = str(risk.get("initial", "low")).lower()
        semantic = repository = legacy if legacy in LEVELS else "low"

    flags = data.get("risk_flags", {}) or {}
    semantic_reasons, repository_reasons = [], []

    for key, enabled in flags.items():
        if not enabled:
            continue
        if key in SEMANTIC_CRITICAL:
            semantic = "critical"
            semantic_reasons.append(f"{key}: semantic CRITICAL")
        if key in AT_LEAST_HIGH:
            if LEVELS.index(repository) < LEVELS.index("high"):
                repository = "high"
            repository_reasons.append(f"{key}: repository at least HIGH")
        elif key in PLUS_ONE:
            repository = bump(repository)
            repository_reasons.append(f"{key}: repository +1")

    print(f"minimum_semantic_risk: {semantic}")
    for r in semantic_reasons:
        print(f"- {r}")
    print(f"minimum_repository_change_risk: {repository}")
    for r in repository_reasons:
        print(f"- {r}")
    print("note: this tool reports only minimum risk triggers; model judgment may raise risk and must not lower it")

if __name__ == "__main__":
    main()
