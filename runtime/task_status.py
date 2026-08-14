from __future__ import annotations

from core.work_risk import vector_mapping, vector_from_mapping
from governed_validation import investigation_exploration_status
from work_graph import WorkGraph


def _delegation_summary(task: dict) -> dict:
    delegation = task.get("delegation") or {}
    planned = [item for item in delegation.get("planned") or [] if isinstance(item, dict)]
    completed = [item for item in delegation.get("completed") or [] if isinstance(item, dict)]
    failed = [item for item in delegation.get("failed") or [] if isinstance(item, dict)]
    completed_ids = {str(item.get("id")) for item in completed if item.get("id")}
    failed_ids = {str(item.get("id")) for item in failed if item.get("id")}
    planned_ids = [str(item.get("id")) for item in planned if item.get("id")]
    outstanding = [
        value for value in planned_ids
        if value not in completed_ids and value not in failed_ids
    ]
    return {
        "decision": str(delegation.get("decision", "not-needed")),
        "authorization": str(
            (delegation.get("authorization") or {}).get("status", "not-required")
        ),
        "planned": planned_ids,
        "completed": sorted(completed_ids),
        "failed": sorted(failed_ids),
        "outstanding": outstanding,
    }


def _risk_summary(task: dict) -> dict:
    work_risk = task.get("work_risk")
    if not isinstance(work_risk, dict):
        return {"current": None, "peak": None}
    current = vector_from_mapping(work_risk.get("current"))
    peak = vector_from_mapping(work_risk.get("peak"))
    return {
        "current": vector_mapping(current),
        "peak": vector_mapping(peak),
    }


def build_action_dashboard(graph: WorkGraph) -> dict:
    """Build a pure, read-only action view over one governed Task."""

    task = graph.task
    focus = task.get("current_focus") or {"type": "none", "ref": None}
    delegation = _delegation_summary(task)
    action_required: list[str] = []
    allowed_next: list[str] = []
    blocked_next: list[str] = []
    exploration: dict | None = None

    escalation = task.get("escalation") or {}
    escalation_level = str(escalation.get("level", "none"))
    human = task.get("human_in_loop") or {}
    human_assessment = human.get("decision_assessment") or {}

    if escalation_level == "human-checkpoint":
        action_required.append("resolve the pending human checkpoint")
        blocked_next.append("production advancement")
    elif escalation_level in {"stronger-model", "blocked"}:
        action_required.append(f"resolve {escalation_level} escalation")
        blocked_next.append("ordinary governed advancement")

    focus_type = str(focus.get("type", "none"))
    focus_ref = str(focus.get("ref") or "")
    if focus_type == "investigation" and focus_ref in graph.investigations:
        investigation = graph.investigations[focus_ref]
        allowed_next.extend(
            [
                "record-evidence",
                "record-claim",
                "record-decision:proposed",
                "run/record experiment",
            ]
        )
        exploration = investigation_exploration_status(graph, focus_ref)
        if exploration["required"] and not exploration["satisfied"]:
            action_required.append(
                "complete one relevant independent read-only exploration before governed final truth"
            )
            blocked_next.extend(
                [
                    "record-decision:accepted",
                    "conclude-investigation",
                    "pivot-to-change",
                ]
            )
        elif investigation.get("execution_state") == "active":
            allowed_next.extend(
                [
                    "record-decision:accepted",
                    "conclude-investigation",
                    "pivot-to-change",
                ]
            )

        if str(human_assessment.get("status", "not-required")) == "required":
            action_required.append("obtain the user's material engineering decision")
            blocked_next.append("human-required production decision")

    elif focus_type == "change" and focus_ref in graph.changes:
        _, change = graph.changes[focus_ref]
        if change.get("execution_state") == "paused":
            hold = change.get("hold") or {}
            action_required.append(
                "resolve the linked Investigation before resuming the paused Change"
            )
            blocked_next.append("Change implementation / verification")
        else:
            allowed_next.extend(["continue approved Change work", "investigate-change"])
    elif focus_type == "none":
        allowed_next.append("complete task or create the next governed work item")

    if delegation["decision"] == "required" and delegation["authorization"] != "granted":
        action_required.append("grant or resolve required delegation authorization")
    if delegation["outstanding"]:
        action_required.append(
            "complete or disposition planned delegation: "
            + ", ".join(delegation["outstanding"])
        )

    return {
        "task": {
            "id": task.get("id"),
            "title": task.get("title"),
            "status": task.get("status"),
            "current_focus": focus,
        },
        "risk": _risk_summary(task),
        "delegation": delegation,
        "exploration": exploration,
        "escalation": escalation_level,
        "ACTION REQUIRED": list(dict.fromkeys(action_required)),
        "allowed_next": list(dict.fromkeys(allowed_next)),
        "blocked_next": list(dict.fromkeys(blocked_next)),
    }
