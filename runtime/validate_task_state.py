from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json_or_yaml_like, fail
from core.task_runtime import orchestrator_provider
from delegation_validation import validate_delegation_state
from governance_checks import validate_human_in_loop
from project_context import PACKAGE_ROOT, ProjectContext
from work_graph import WorkGraphError, validate_task_shape


def non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    return value.strip()


def validate_learning(data: dict, status: str) -> None:
    learning = data.get("learning") or {}
    if not isinstance(learning, dict):
        fail("learning must be a mapping")
    intake = learning.get("intake") or {}
    intake_status = str(intake.get("status", "pending"))
    if intake_status not in {"pending", "completed", "not-applicable"}:
        fail(f"invalid learning.intake.status: {intake_status}")
    for key in ("relevant_entries", "recommended_tools"):
        values = intake.get(key) or []
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            fail(f"learning.intake.{key} must be a list of non-empty strings")
    if status != "intake":
        if intake_status != "completed":
            fail("learning intake must be completed before active work")
        non_empty_string(intake.get("evidence"), "learning intake evidence")

    observations = learning.get("observations") or []
    if not isinstance(observations, list):
        fail("learning.observations must be a list")
    closeout = learning.get("closeout") or {}
    closeout_status = str(closeout.get("status", "pending"))
    if closeout_status not in {"pending", "assessed", "not-applicable"}:
        fail(f"invalid learning.closeout.status: {closeout_status}")
    ready = closeout.get("candidates_ready_for_review") or []
    if not isinstance(ready, list) or any(
        not isinstance(item, str) or not item for item in ready
    ):
        fail("learning.closeout.candidates_ready_for_review must be a list of non-empty strings")

    attention = learning.get("user_attention") or {}
    decision = str(attention.get("decision", "not-required"))
    if decision not in {
        "not-required", "pending", "approved", "deferred", "dismissed", "resolved"
    }:
        fail(f"invalid learning.user_attention.decision: {decision}")
    candidate_decisions = attention.get("candidate_decisions") or {}
    if not isinstance(candidate_decisions, dict):
        fail("learning.user_attention.candidate_decisions must be a mapping")
    for candidate_id, value in candidate_decisions.items():
        if candidate_id not in ready:
            fail(f"learning user-attention decision references unknown closeout candidate: {candidate_id}")
        if not isinstance(value, dict):
            fail(f"learning candidate decision for {candidate_id} must be a mapping")
        candidate_decision = str(value.get("decision") or "")
        if candidate_decision not in {"approved", "deferred", "dismissed"}:
            fail(f"invalid learning candidate decision for {candidate_id}: {candidate_decision}")
        non_empty_string(value.get("evidence"), f"learning candidate decision evidence for {candidate_id}")

    if status == "completed":
        if closeout_status != "assessed":
            fail("learning closeout must be assessed before task completion")
        if not observations and not ready:
            non_empty_string(closeout.get("reason"), "learning closeout reason")
        if ready:
            if not bool(attention.get("required", False)):
                fail("mature learning candidates require user attention")
            if not bool(attention.get("presented", False)):
                fail("mature learning candidates must be presented")
            if len(ready) == 1 and not candidate_decisions:
                # Legacy one-candidate closeout remains valid.
                if decision not in {"approved", "deferred", "dismissed"}:
                    fail("user must decide how to handle mature learning candidates")
                non_empty_string(
                    attention.get("evidence"), "learning user-attention evidence"
                )
            else:
                unresolved = [value for value in ready if value not in candidate_decisions]
                if unresolved:
                    fail(
                        "each mature learning candidate requires an individual user decision: "
                        + ", ".join(unresolved)
                    )
                if decision not in {"approved", "deferred", "dismissed", "resolved"}:
                    fail("learning candidate curation is not resolved")
                non_empty_string(
                    attention.get("evidence"), "learning user-attention evidence"
                )


def _project_context(task_path: Path) -> tuple[ProjectContext, Path]:
    resolved = task_path.resolve()
    task_root = resolved.parent
    project_root = (
        task_root.parent.parent
        if task_root.parent.name == ".agent-work"
        else task_root
    )
    return (
        ProjectContext(
            package_root=PACKAGE_ROOT,
            project_root=project_root,
            adapter_root=PACKAGE_ROOT / "adapters" / "default",
        ),
        task_root,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", type=Path)
    args = parser.parse_args()

    data = load_json_or_yaml_like(args.task)
    try:
        validate_task_shape(data)
        orchestrator_provider(data)
        context, task_root = _project_context(args.task)
        validate_delegation_state(context, task_root, data)
    except (WorkGraphError, ValueError) as error:
        fail(str(error))

    status = str(data.get("status"))
    validate_learning(data, status)
    advanced = status in {"active", "blocked", "completed"}
    validate_human_in_loop(
        data,
        semantic_risk=(
            "high"
            if (data.get("escalation") or {}).get("level") != "none"
            else "low"
        ),
        advanced=advanced,
    )

    escalation = data.get("escalation") or {}
    human = escalation.get("human_checkpoint") or {}
    if status == "completed":
        if (data.get("current_focus") or {}).get("type") != "none":
            fail("completed task must not have a current focus")
        if escalation.get("level") != "none":
            fail("completed task cannot retain an unresolved escalation")
    if human.get("status") == "pending" and status != "blocked":
        fail("task must be blocked while human checkpoint is pending")

    print("task_state: valid")


if __name__ == "__main__":
    main()
