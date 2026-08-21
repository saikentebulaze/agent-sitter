from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json_or_yaml_like, fail
from governance_checks import validate_change_closure, validate_human_in_loop
from production_snapshot import ProductionSnapshotError, production_snapshot_sha256
from readiness import (
    ReadinessError,
    readiness_contract_digest,
    validate_readiness_contract,
)
from work_graph import WorkGraphError, validate_change_graph_shape

REQUIRED = [
    "change.yaml", "proposal.md", "design.md", "tasks.md",
    "verification.md", "knowledge-sync.md", "archive-summary.md",
]
STATUSES = {
    "proposed", "designed", "approved", "implementing", "candidate-review",
    "verifying", "syncing", "ready-to-archive", "archived",
}
REVIEW_STATUS = {"pending", "pass", "warn", "block"}
REMEDIATION_ROUTES = {"implementation", "awaiting-production-design"}
RISK_LEVELS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
PLANNING_LEVELS = {"none", "brief", "full"}
TDD_MODES = {"not-applicable", "targeted", "required"}
LEGACY_MODEL_TIERS = {"luna", "terra", "sol"}
PROVIDER_MODEL_GRADES = {"low", "medium", "high"}
REVIEW_AGENTS = {"maintainer_reviewer", "deep_reviewer"}
SEVERITY = {"pending": -1, "pass": 0, "warn": 1, "block": 2}
V2_SNAPSHOT_KEYS = (
    "production_sha256",
    "design_sha256",
    "tasks_sha256",
    "change_budget_sha256",
    "human_decisions_sha256",
    "readiness_contract_sha256",
    "readiness_evidence_sha256",
    "test_finalization_sha256",
)


def non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    return value.strip()


def _require_digest(snapshot: dict, key: str, label: str) -> None:
    value = str(snapshot.get(key) or "").strip()
    if not value:
        fail(f"{label}.{key} must be a non-empty value")
    if len(value) < 12:
        fail(f"{label}.{key} is too short to identify a frozen input")


def validate_input_snapshot(snapshot: object, label: str) -> None:
    if not isinstance(snapshot, dict):
        fail(f"{label} must be a mapping")
    protocol = int(snapshot.get("snapshot_protocol") or 1)
    if protocol == 1:
        for key in ("design_sha256", "tasks_sha256", "diff_sha256", "verification_sha256"):
            _require_digest(snapshot, key, label)
        return
    if protocol != 2:
        fail(f"unsupported {label}.snapshot_protocol: {protocol}")
    for key in V2_SNAPSHOT_KEYS:
        _require_digest(snapshot, key, label)


def validate_review_execution(execution: object, *, expected_round: int | None = None) -> None:
    if not isinstance(execution, dict):
        fail("review.execution must be a mapping")

    agent = non_empty_string(execution.get("agent"), "review.execution.agent")
    model = non_empty_string(execution.get("model"), "review.execution.model")
    tier = non_empty_string(execution.get("tier"), "review.execution.tier").lower()
    method = non_empty_string(execution.get("method"), "review.execution.method")
    non_empty_string(execution.get("output_ref"), "review.execution.output_ref")
    evidence_ref = non_empty_string(execution.get("evidence_ref"), "review.execution.evidence_ref")

    if agent not in REVIEW_AGENTS:
        fail(f"unrecognized reviewer agent: {agent}")

    round_number = execution.get("round")
    if not isinstance(round_number, int) or round_number < 1:
        fail("review.execution.round must be a positive integer")
    if expected_round is not None and round_number != expected_round:
        fail("review execution round does not match review history")

    protocol = int(execution.get("review_protocol") or 1)
    if protocol == 1:
        if tier not in LEGACY_MODEL_TIERS:
            fail(f"invalid reviewer tier: {tier}")
        if method != "native-subagent":
            fail("review.execution.method must be native-subagent")
        if agent == "maintainer_reviewer":
            if model != "gpt-5.6-terra" or tier != "terra":
                fail("normal maintainer reviewer must use the configured Terra role")
        elif agent == "deep_reviewer":
            if model != "gpt-5.6-sol" or tier != "sol":
                fail("deep reviewer must use the configured Sol role")
            non_empty_string(
                execution.get("elevated_authorization_ref"),
                "review.execution.elevated_authorization_ref",
            )
        validate_input_snapshot(execution.get("input_snapshot"), "review.execution.input_snapshot")
        return

    if protocol != 2:
        fail(f"unsupported review.execution.review_protocol: {protocol}")
    if tier not in PROVIDER_MODEL_GRADES:
        fail(f"invalid provider reviewer grade: {tier}")
    if method != "provider-managed-readonly":
        fail("review protocol 2 must use provider-managed-readonly")
    provider = non_empty_string(execution.get("provider"), "review.execution.provider")
    if provider not in {"codex", "claude"}:
        fail(f"unsupported review Provider: {provider}")
    runtime_method = non_empty_string(
        execution.get("runtime_method"), "review.execution.runtime_method"
    )
    expected_runtime = {
        "codex": "app-server-isolated-agent",
        "claude": "claude-managed-agent",
    }[provider]
    if runtime_method != expected_runtime:
        fail(
            f"review runtime method does not match Provider {provider}: {runtime_method}"
        )
    session_ref = non_empty_string(execution.get("session_ref"), "review.execution.session_ref")
    if evidence_ref != session_ref:
        fail("review.execution.evidence_ref must match the attested runtime session")
    non_empty_string(execution.get("attestation_ref"), "review.execution.attestation_ref")
    non_empty_string(
        execution.get("runtime_evidence_ref"), "review.execution.runtime_evidence_ref"
    )
    if agent == "maintainer_reviewer" and tier != "medium":
        fail("maintainer reviewer must use the configured medium model grade")
    if agent == "deep_reviewer":
        if tier != "high":
            fail("deep reviewer must use the configured high model grade")
        non_empty_string(
            execution.get("elevated_authorization_ref"),
            "review.execution.elevated_authorization_ref",
        )
    snapshot = execution.get("input_snapshot") or {}
    if int(snapshot.get("snapshot_protocol") or 1) != 2:
        fail("review protocol 2 requires input snapshot protocol 2")
    validate_input_snapshot(snapshot, "review.execution.input_snapshot")


def validate_methodology(data: dict, review: dict, status: str) -> None:
    methodology = data.get("methodology") or {}
    planning = str(methodology.get("planning_level", "none"))
    if planning not in PLANNING_LEVELS:
        fail(f"invalid methodology.planning_level: {planning}")

    tdd_mode = str(methodology.get("tdd_mode", "not-applicable"))
    if tdd_mode not in TDD_MODES:
        fail(f"invalid methodology.tdd_mode: {tdd_mode}")

    skills = methodology.get("superpowers_skills") or []
    if not isinstance(skills, list) or any(not isinstance(item, str) or not item for item in skills):
        fail("methodology.superpowers_skills must be a list of non-empty names")

    temporary = methodology.get("temporary_tests") or []
    if not isinstance(temporary, list):
        fail("methodology.temporary_tests must be a list")
    retained = methodology.get("retained_test_rationale") or []
    if not isinstance(retained, list):
        fail("methodology.retained_test_rationale must be a list")

    protocol = methodology.get("test_cleanup_protocol")
    if protocol not in {None, 1}:
        fail("unsupported methodology.test_cleanup_protocol")

    review_started = str(review.get("status", "pending")) != "pending"
    if review_started or status in {"candidate-review", "syncing", "ready-to-archive", "archived"}:
        if temporary:
            fail("temporary/development-only tests must be removed or merged before review")
        if not bool(methodology.get("test_cleanup_complete", False)):
            fail("test cleanup assessment is incomplete")


def validate_test_cleanup_evidence(path: Path, data: dict, review: dict, status: str) -> None:
    methodology = data.get("methodology") or {}
    if methodology.get("test_cleanup_protocol") != 1:
        return
    review_started = str(review.get("status", "pending")) != "pending"
    if not review_started and status not in {
        "candidate-review", "syncing", "ready-to-archive", "archived"
    }:
        return

    ref = non_empty_string(
        methodology.get("test_cleanup_evidence"),
        "methodology.test_cleanup_evidence",
    )
    project_root = path.resolve().parents[2]
    evidence = (project_root / ref).resolve()
    try:
        evidence.relative_to(path.resolve())
    except ValueError:
        fail("test cleanup evidence must remain inside the Change directory")
    if evidence != (path / "test-finalization.yaml").resolve():
        fail("test cleanup evidence must be the Harness test-finalization artifact")
    if not evidence.is_file():
        fail("test cleanup evidence is missing")
    payload = load_json_or_yaml_like(evidence)
    if payload.get("schema_version") != 1:
        fail("test cleanup evidence has unsupported schema_version")
    if str(payload.get("change_id") or "") != str(data.get("id") or path.name):
        fail("test cleanup evidence change_id does not match Change")
    decisions = payload.get("decisions") or []
    if not isinstance(decisions, list):
        fail("test cleanup evidence decisions must be a list")
    allowed = {
        "permanent-regression",
        "development-only-removed",
        "pre-existing-not-owned",
    }
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            fail(f"test cleanup evidence decisions[{index}] must be a mapping")
        non_empty_string(decision.get("path"), f"test cleanup decisions[{index}].path")
        classification = non_empty_string(
            decision.get("classification"),
            f"test cleanup decisions[{index}].classification",
        )
        if classification not in allowed:
            fail(f"invalid test cleanup classification: {classification}")
        non_empty_string(decision.get("reason"), f"test cleanup decisions[{index}].reason")


def validate_review_summary(review: dict) -> None:
    for key in ("status", "architecture", "scope", "numerical_evidence"):
        value = str(review.get(key, "pending"))
        if value not in REVIEW_STATUS:
            fail(f"invalid review {key}: {value}")

    dimensions = [
        str(review.get("architecture", "pending")),
        str(review.get("scope", "pending")),
        str(review.get("numerical_evidence", "pending")),
    ]
    overall = str(review.get("status", "pending"))
    if all(value != "pending" for value in dimensions):
        worst = max(dimensions, key=lambda value: SEVERITY[value])
        if overall != worst:
            fail(f"review.status must match the most severe dimension: {worst}")
    elif overall != "pending":
        fail("review dimensions must all be decided when review.status is not pending")

    if overall != "pending":
        validate_review_execution(review.get("execution"))


def validate_review_history(history: object, review: dict, status: str) -> None:
    if not isinstance(history, list):
        fail("review_history must be a list")

    for index, round_data in enumerate(history, start=1):
        if not isinstance(round_data, dict) or round_data.get("round") != index:
            fail("review_history rounds must be ordered from 1")
        for key in ("status", "architecture", "scope", "numerical_evidence"):
            value = str(round_data.get(key, ""))
            if value not in REVIEW_STATUS - {"pending"}:
                fail(f"invalid review_history {key}")
        dimensions = [
            round_data["architecture"],
            round_data["scope"],
            round_data["numerical_evidence"],
        ]
        worst = max(dimensions, key=lambda value: SEVERITY[value])
        if round_data["status"] != worst:
            fail("review_history status must match the most severe dimension")

        validate_review_execution(round_data.get("execution"), expected_round=index)

        round_blocked = "block" in dimensions
        if round_blocked and round_data.get("remediation_route") not in REMEDIATION_ROUTES:
            fail("blocked review_history round requires a remediation route")

    if history:
        latest = history[-1]
        for key in ("status", "architecture", "scope", "numerical_evidence"):
            if latest.get(key) != review.get(key):
                fail("latest review_history round must match the review summary")
        if (review.get("execution") or {}).get("round") != len(history):
            fail("review execution round must match review_history length")

        blocked_rounds = [
            index for index, item in enumerate(history)
            if "block" in {
                item.get("architecture"), item.get("scope"), item.get("numerical_evidence")
            }
        ]
        if blocked_rounds and blocked_rounds[-1] == len(history) - 1:
            if status in {"candidate-review", "verifying", "syncing", "ready-to-archive", "archived"}:
                fail("blocked review requires a later review round before completion")
    elif review.get("status") != "pending":
        fail("completed review requires review_history provenance")


def validate_verification_evidence(verification: dict, status: str) -> None:
    if not isinstance(verification, dict):
        fail("verification must be a mapping")
    latest = verification.get("latest_results") or []
    if not isinstance(latest, list):
        fail("verification.latest_results must be a list")
    ids: set[str] = set()
    for index, result in enumerate(latest):
        label = f"verification.latest_results[{index}]"
        if not isinstance(result, dict):
            fail(f"{label} must be a mapping")
        result_id = non_empty_string(result.get("id"), f"{label}.id")
        if result_id in ids:
            fail(f"duplicate verification result id: {result_id}")
        ids.add(result_id)
        for key in ("kind", "command_or_entry", "result", "checked_at", "evidence"):
            non_empty_string(result.get(key), f"{label}.{key}")
    if status in {"ready-to-archive", "archived"} and not latest:
        fail("ready-to-archive change requires structured verification evidence")


def validate_candidate_readiness(path: Path, data: dict, status: str, review: dict) -> None:
    if data.get("candidate_readiness_protocol") != 1:
        return
    try:
        validate_readiness_contract(data)
    except ReadinessError as error:
        fail(str(error))
    readiness = data.get("readiness") or {}
    if status in {"implementing", "candidate-review", "verifying", "syncing", "ready-to-archive", "archived"}:
        frozen = str(readiness.get("contract_sha256") or "")
        if not frozen:
            fail("V6.2 Readiness Contract must be frozen before implementation")
        if frozen != readiness_contract_digest(data):
            fail("V6.2 Readiness Contract changed after it was frozen")
    if status not in {"candidate-review", "verifying", "syncing", "ready-to-archive", "archived"}:
        return
    if readiness.get("status") != "pass":
        fail("Candidate Readiness must pass before candidate/final verification states")
    if review.get("status") not in {"pass", "warn"}:
        fail("independent Candidate Readiness Review has not passed")
    project_root = path.resolve().parents[2]
    try:
        current = production_snapshot_sha256(project_root)
    except ProductionSnapshotError as error:
        fail(str(error))
    readiness_snapshot = str((readiness.get("production_snapshot") or {}).get("sha256") or "")
    if readiness_snapshot != current:
        fail("Candidate Readiness is stale because production/test files changed")
    execution = review.get("execution") or {}
    snapshot = execution.get("input_snapshot") or {}
    if int(snapshot.get("snapshot_protocol") or 1) == 2:
        if str(snapshot.get("production_sha256") or "") != current:
            fail("independent review is stale because production/test files changed")
        if str(snapshot.get("readiness_contract_sha256") or "") != str(
            readiness.get("contract_sha256") or ""
        ):
            fail("independent review does not match the current Readiness Contract")
        if str(snapshot.get("readiness_evidence_sha256") or "") != str(
            readiness.get("evidence_sha256") or ""
        ):
            fail("independent review does not match the current Readiness evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    path = args.path

    missing = [name for name in REQUIRED if not (path / name).exists()]
    if missing:
        fail("missing: " + ", ".join(missing))

    data = load_json_or_yaml_like(path / "change.yaml")
    try:
        validate_change_graph_shape(data)
    except WorkGraphError as error:
        fail(str(error))

    status = str(data.get("status", ""))
    if status not in STATUSES:
        fail(f"invalid status: {status}")
    execution_state = str(data.get("execution_state", ""))
    if execution_state == "paused" and status in {
        "candidate-review", "verifying", "syncing", "ready-to-archive", "archived",
    }:
        fail("paused change cannot enter candidate review, verify, sync, or archive")
    if execution_state == "abandoned" and status in {
        "approved", "implementing", "candidate-review", "verifying", "syncing",
        "ready-to-archive", "archived",
    }:
        fail("abandoned change cannot remain in an advancing lifecycle state")

    approval = data.get("approval") or {}
    review = data.get("review") or {}
    verification = data.get("verification") or {}
    archive = data.get("archive") or {}
    risk = data.get("risk") or {}
    budget = data.get("change_budget") or {}
    repository_risk = str(risk.get("repository_change", "low")).lower()

    critical_surfaces = data.get("critical_surfaces") or []
    if not isinstance(critical_surfaces, list):
        fail("critical_surfaces must be a list")
    semantic_risk = str(risk.get("semantic", "")).lower()
    if semantic_risk not in RISK_LEVELS:
        fail(f"invalid semantic risk: {semantic_risk}")
    for surface in critical_surfaces:
        if not isinstance(surface, dict):
            fail("each critical surface must be a mapping")
        surface_id = surface.get("id")
        risk_floor = str(surface.get("risk_floor", "")).lower()
        required_validation = surface.get("required_validation")
        if (
            not surface_id
            or risk_floor not in RISK_LEVELS
            or not isinstance(required_validation, list)
            or not required_validation
        ):
            fail("critical surface requires id, risk_floor, and required_validation")
        if RISK_LEVELS[semantic_risk] < RISK_LEVELS[risk_floor]:
            fail(f"change semantic risk is below critical-surface risk floor: {surface_id}")

    if "explicit_non_goals" not in budget:
        fail("change budget has no explicit_non_goals field")
    if "adjacent_issues" not in budget:
        fail("change budget has no adjacent_issues field")

    validate_review_summary(review)
    validate_review_history(data.get("review_history") or [], review, status)
    validate_methodology(data, review, status)
    validate_test_cleanup_evidence(path, data, review, status)
    validate_verification_evidence(verification, status)
    validate_candidate_readiness(path, data, status, review)
    validate_human_in_loop(
        data,
        semantic_risk=semantic_risk,
        advanced=status in {
            "approved", "implementing", "candidate-review", "verifying", "syncing",
            "ready-to-archive", "archived",
        },
    )
    validate_change_closure(data, status)

    blocked_dimensions = [
        key for key in ("architecture", "scope", "numerical_evidence")
        if review.get(key) == "block"
    ]
    if review.get("status") == "block" or blocked_dimensions:
        if status in {"candidate-review", "verifying", "syncing", "ready-to-archive", "archived"}:
            fail("review is BLOCK; remediation is required before verification can continue")
        remediation = data.get("remediation") or {}
        route = remediation.get("route")
        if route not in REMEDIATION_ROUTES:
            fail("review is BLOCK; remediation route is required")
        within = bool(remediation.get("within_approved_scope", False))
        if route == "implementation" and not within:
            fail("implementation remediation must stay within the approved scope")
        if route == "awaiting-production-design" and within:
            fail("design remediation must not claim to remain within approved scope")
        if status == "implementing" and route != "implementation":
            fail("implementation remediation must route to implementation")
        if status == "designed" and route != "awaiting-production-design":
            fail("design remediation must route to awaiting-production-design")

    if (
        status in {
            "approved", "implementing", "candidate-review", "verifying",
            "syncing", "ready-to-archive", "archived",
        }
        and repository_risk in {"high", "critical"}
        and approval.get("status") != "approved"
    ):
        fail("HIGH/CRITICAL change is not approved")

    if status in {"ready-to-archive", "archived"}:
        if execution_state != "active":
            fail("only an active change can reach archive")
        if review.get("status") not in {"pass", "warn"}:
            fail("independent reviewer has not completed")
        if verification.get("status") not in {"pass", "partial"}:
            fail("verification not complete")
        if archive.get("blockers"):
            fail("archive blockers remain")
        if archive.get("temporary_production_files"):
            fail("temporary production files remain")
        if not archive.get("experiment_cleanup_complete", False):
            fail("experiment cleanup incomplete")

    for name in REQUIRED[1:]:
        text = (path / name).read_text(encoding="utf-8").strip()
        if len(text) < 20:
            fail(f"{name} is empty")

    print("change_state: valid")


if __name__ == "__main__":
    main()
