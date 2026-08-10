from __future__ import annotations

from pathlib import Path

from core.work_risk import RiskLevel, vector_from_mapping
from delegation_validation import validate_delegation_state
from project_context import ProjectContext
from work_graph import (
    WorkGraph,
    WorkGraphError,
    load_work_graph,
    validate_investigation_shape,
    validate_work_graph as validate_base_work_graph,
)


ACTIVE_ESCALATIONS = {"stronger-model", "human-checkpoint", "blocked"}
EXPLORATION_ROLES = {
    "source_locator",
    "context_scout",
    "test_scout",
    "framework_scout",
}
ADVANCED_CHANGE_STATUSES = {
    "implementing",
    "verifying",
    "syncing",
    "ready-to-archive",
    "archived",
}


def validate_investigation_policy(data: dict) -> None:
    validate_investigation_shape(data)
    evidence_ids = {str(item["id"]) for item in data.get("evidence") or []}
    claims = {str(item["id"]): item for item in data.get("claims") or []}

    for claim_id, claim in claims.items():
        status = str(claim.get("status", "open"))
        supporting = [str(value) for value in claim.get("supporting_evidence") or []]
        contradicting = [str(value) for value in claim.get("contradicting_evidence") or []]
        if status == "supported" and not supporting:
            raise WorkGraphError(f"supported claim {claim_id} requires supporting evidence")
        if status == "refuted" and not contradicting:
            raise WorkGraphError(f"refuted claim {claim_id} requires contradicting evidence")
        unknown = (set(supporting) | set(contradicting)) - evidence_ids
        if unknown:
            raise WorkGraphError(
                f"claim {claim_id} references unknown evidence: "
                + ", ".join(sorted(unknown))
            )

    for decision in data.get("decisions") or []:
        if decision.get("status") != "accepted":
            continue
        decision_id = str(decision.get("id"))
        basis = decision.get("basis") or {}
        basis_claims = [str(value) for value in basis.get("claims") or []]
        for claim_id in basis_claims:
            claim = claims.get(claim_id)
            if claim is None:
                raise WorkGraphError(
                    f"accepted decision {decision_id} references unknown claim {claim_id}"
                )
            if claim.get("status") != "supported":
                raise WorkGraphError(
                    f"accepted decision {decision_id} depends on non-supported claim {claim_id}"
                )
        if bool(decision.get("requires_human", False)) and not decision.get("evidence_ref"):
            raise WorkGraphError(
                f"accepted decision {decision_id} requires durable human-decision evidence"
            )


def validate_work_risk(task: dict) -> None:
    """Validate dynamic execution risk while accepting legacy Tasks."""

    if "work_risk" not in task:
        return
    work_risk = task.get("work_risk")
    if not isinstance(work_risk, dict):
        raise WorkGraphError("task.work_risk must be a mapping")
    try:
        current = vector_from_mapping(work_risk.get("current"))
        peak = vector_from_mapping(work_risk.get("peak"))
    except ValueError as error:
        raise WorkGraphError(str(error)) from error
    if not peak.dominates(current):
        raise WorkGraphError("task.work_risk.peak must dominate current risk")

    history = work_risk.get("history") or []
    if not isinstance(history, list):
        raise WorkGraphError("task.work_risk.history must be a list")
    previous_to = None
    for index, entry in enumerate(history):
        label = f"task.work_risk.history[{index}]"
        if not isinstance(entry, dict):
            raise WorkGraphError(f"{label} must be a mapping")
        if not isinstance(entry.get("at"), str) or not entry["at"].strip():
            raise WorkGraphError(f"{label}.at must be a non-empty string")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise WorkGraphError(f"{label}.reason must be a non-empty string")
        try:
            before = vector_from_mapping(entry.get("from"))
            after = vector_from_mapping(entry.get("to"))
        except ValueError as error:
            raise WorkGraphError(f"{label}: {error}") from error
        if before == after:
            raise WorkGraphError(f"{label} must describe an actual risk transition")
        if previous_to is not None and before != previous_to:
            raise WorkGraphError(f"{label}.from must match the previous transition target")
        previous_to = after
    if history and previous_to != current:
        raise WorkGraphError("task.work_risk history must end at current risk")


def _relevant_exploration_refs(graph: WorkGraph, change_id: str, change: dict) -> set[str]:
    refs = {str(graph.task.get("id") or ""), change_id}
    derived = (change.get("relations") or {}).get("derived_from") or {}
    refs.update(map(str, derived.get("investigations") or []))
    for investigation_id, investigation in graph.investigations.items():
        source = investigation.get("source") or {}
        if source.get("type") == "change" and str(source.get("ref") or "") == change_id:
            refs.add(investigation_id)
    return {value for value in refs if value}


def validate_high_risk_exploration(graph: WorkGraph) -> None:
    """Require independent exploration before active HIGH production execution.

    A paused Change is deliberately exempt while its Investigation is resolving
    the newly discovered risk. The obligation becomes enforceable again before
    the Change can resume active implementation/verification.
    """

    task = graph.task
    if "work_risk" not in task:
        return
    try:
        peak = vector_from_mapping((task.get("work_risk") or {}).get("peak"))
    except ValueError as error:
        raise WorkGraphError(str(error)) from error
    if peak.maximum() < RiskLevel.HIGH:
        return

    delegation = task.get("delegation") or {}
    planned = delegation.get("planned") or []
    completed_ids = {
        str(item.get("id"))
        for item in (delegation.get("completed") or [])
        if isinstance(item, dict) and item.get("id")
    }

    for change_id, (_, change) in graph.changes.items():
        if change.get("execution_state") != "active":
            continue
        if str(change.get("status")) not in ADVANCED_CHANGE_STATUSES:
            continue
        refs = _relevant_exploration_refs(graph, change_id, change)
        satisfied = False
        for entry in planned:
            if not isinstance(entry, dict) or str(entry.get("id")) not in completed_ids:
                continue
            if str(entry.get("agent")) not in EXPLORATION_ROLES:
                continue
            target = entry.get("target") or {}
            if str(target.get("ref") or "") in refs:
                satisfied = True
                break
        if not satisfied:
            raise WorkGraphError(
                f"HIGH/CRITICAL Task requires completed independent exploration before "
                f"implementing Change {change_id}"
            )


def _target_investigation(task: dict) -> str | None:
    escalation = task.get("escalation") or {}
    target = escalation.get("target_investigation_ref")
    return str(target) if isinstance(target, str) and target else None


def validate_governed_work_graph(
    context: ProjectContext, task_root: Path
) -> WorkGraph:
    raw_task = load_work_graph(context, task_root).task
    if raw_task.get("status") == "completed":
        graph = load_work_graph(context, task_root)
        if (graph.task.get("current_focus") or {}).get("type") != "none":
            raise WorkGraphError("completed task must not have a current focus")
        if (graph.task.get("escalation") or {}).get("level") != "none":
            raise WorkGraphError("completed task cannot retain an escalation")
        open_investigations = [
            key
            for key, value in graph.investigations.items()
            if value.get("status") not in {"concluded", "closed"}
        ]
        incomplete_changes = [
            key
            for key, (_, value) in graph.changes.items()
            if value.get("status") != "archived"
            and value.get("execution_state") != "abandoned"
        ]
        if open_investigations or incomplete_changes:
            raise WorkGraphError("completed task still has open work items")
    else:
        graph = validate_base_work_graph(context, task_root)
    task = graph.task

    validate_work_risk(task)
    validate_delegation_state(
        context,
        task_root,
        task,
        require_resolved=task.get("status") == "completed",
    )
    for investigation in graph.investigations.values():
        validate_investigation_policy(investigation)
    validate_high_risk_exploration(graph)

    escalation = task.get("escalation") or {}
    level = str(escalation.get("level", "none"))
    target = _target_investigation(task)
    if level in ACTIVE_ESCALATIONS:
        if not target:
            raise WorkGraphError(f"{level} escalation requires target_investigation_ref")
        if target not in graph.investigations:
            raise WorkGraphError(f"escalation target investigation does not exist: {target}")
        focus = task.get("current_focus") or {}
        if focus.get("type") != "investigation" or focus.get("ref") != target:
            raise WorkGraphError("current focus must remain on the escalated investigation")
        target_data = graph.investigations[target]
        if level == "stronger-model":
            review = escalation.get("model_review") or {}
            if review.get("status") != "pending":
                raise WorkGraphError("stronger-model escalation requires a pending model review")
            if target_data.get("execution_state") != "paused":
                raise WorkGraphError("escalated investigation must remain paused until review completes")
        elif level == "human-checkpoint":
            human = escalation.get("human_checkpoint") or {}
            if human.get("status") != "pending":
                raise WorkGraphError("human-checkpoint escalation requires a pending checkpoint")
        elif level == "blocked" and target_data.get("execution_state") != "blocked":
            raise WorkGraphError("blocked escalation requires a blocked target investigation")

    return graph
