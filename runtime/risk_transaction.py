from __future__ import annotations

from pathlib import Path

from core.work_risk import (
    RiskLevel,
    RiskVector,
    can_reduce_current_risk,
    max_vector,
    vector_from_mapping,
    vector_mapping,
)
from governed_validation import ACTIVE_ESCALATIONS, validate_governed_work_graph
from project_context import ProjectContext
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import WorkGraph, WorkGraphError, load_yaml, now_iso, resolve_task_root


class RiskTransactionError(WorkGraphError):
    pass


LEGACY_DEFAULT_RISK = RiskVector(RiskLevel.MEDIUM, RiskLevel.MEDIUM)


def current_work_risk(task: dict) -> RiskVector:
    work_risk = task.get("work_risk")
    if not isinstance(work_risk, dict):
        return LEGACY_DEFAULT_RISK
    try:
        return vector_from_mapping(
            work_risk.get("current"),
            default=LEGACY_DEFAULT_RISK,
        )
    except ValueError as error:
        raise RiskTransactionError(str(error)) from error


def peak_work_risk(task: dict) -> RiskVector:
    work_risk = task.get("work_risk")
    current = current_work_risk(task)
    if not isinstance(work_risk, dict):
        return current
    try:
        peak = vector_from_mapping(work_risk.get("peak"), default=current)
    except ValueError as error:
        raise RiskTransactionError(str(error)) from error
    if not peak.dominates(current):
        raise RiskTransactionError("task work_risk.peak must dominate current risk")
    return peak


def _has_unresolved_human_decision(task: dict) -> bool:
    human = task.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    return str(assessment.get("status", "not-required")) in {"pending", "required"}


def _has_open_investigation(graph: WorkGraph) -> bool:
    return any(
        value.get("status") not in {"concluded", "closed"}
        for value in graph.investigations.values()
    )


def _focused_change_id(graph: WorkGraph) -> str | None:
    focus = graph.task.get("current_focus") or {}
    focus_type = str(focus.get("type", "none"))
    focus_ref = focus.get("ref")
    if focus_type == "change" and isinstance(focus_ref, str):
        return focus_ref
    if focus_type != "investigation" or not isinstance(focus_ref, str):
        return None
    investigation = graph.investigations.get(focus_ref) or {}
    source = investigation.get("source") or {}
    if source.get("type") == "change" and isinstance(source.get("ref"), str):
        return str(source["ref"])
    return None


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write_text(path, content.decode("utf-8"))


def _raise_change_assurance(change: dict, target: RiskVector) -> bool:
    raw = change.get("risk") or {}
    try:
        current = vector_from_mapping(raw, default=LEGACY_DEFAULT_RISK)
    except ValueError as error:
        raise RiskTransactionError(f"invalid Change risk: {error}") from error
    raised = max_vector(current, target)
    if raised == current:
        return False
    change["risk"] = vector_mapping(raised)
    return True


def _retain_high_risk_delegation_obligation(
    task: dict,
    peak: RiskVector,
    timestamp: str,
) -> None:
    if peak.maximum() < RiskLevel.HIGH:
        return
    delegation = task.setdefault("delegation", {})
    if str(delegation.get("decision", "not-needed")) != "not-needed":
        return
    delegation["decision"] = "required"
    task.setdefault("timeline", []).append(
        {
            "type": "delegation-obligation-raised",
            "at": timestamp,
            "scope": "readonly-exploration",
            "reason": "Task work risk reached HIGH/CRITICAL",
        }
    )


def reassess_task_risk(
    context: ProjectContext,
    task_value: str | Path,
    *,
    target: RiskVector,
    reason: str,
    evidence_ref: str | None = None,
    remaining_work_bounded: bool = False,
    raise_assurance: bool = False,
) -> tuple[RiskVector, RiskVector, str | None]:
    """Transactionally change current work risk without weakening assurance.

    Risk increases are cheap and immediate. Any decrease requires the task to
    have no open investigation, escalation, or unresolved material decision and
    requires the caller to assert that the remaining work is bounded. Raising
    Change assurance is explicit; lowering current risk never lowers it.
    """

    if not reason.strip():
        raise RiskTransactionError("risk reassessment reason is required")

    task_root = resolve_task_root(context, task_value)
    graph = validate_governed_work_graph(context, task_root)
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    previous = current_work_risk(task)
    previous_peak = peak_work_risk(task)

    if target.is_lower_than(previous):
        escalation_level = str((task.get("escalation") or {}).get("level", "none"))
        allowed = can_reduce_current_risk(
            has_open_investigation=_has_open_investigation(graph),
            has_active_escalation=escalation_level in ACTIVE_ESCALATIONS,
            has_unresolved_decision=_has_unresolved_human_decision(task),
            remaining_work_bounded=remaining_work_bounded,
        )
        if not allowed:
            raise RiskTransactionError(
                "current work risk cannot be reduced until investigations, escalation, "
                "material decisions, and remaining-work bounds are resolved"
            )

    next_peak = max_vector(previous_peak, target)
    work_risk = task.setdefault("work_risk", {})
    history = work_risk.setdefault("history", [])
    if not isinstance(history, list):
        raise RiskTransactionError("task work_risk.history must be a list")

    changed = target != previous
    timestamp = now_iso()
    if changed:
        history.append(
            {
                "at": timestamp,
                "from": vector_mapping(previous),
                "to": vector_mapping(target),
                "reason": reason.strip(),
                "evidence_ref": evidence_ref,
            }
        )
        task.setdefault("timeline", []).append(
            {
                "type": "work-risk-reassessed",
                "at": timestamp,
                "from": vector_mapping(previous),
                "to": vector_mapping(target),
                "reason": reason.strip(),
                "evidence_ref": evidence_ref,
            }
        )
    work_risk["current"] = vector_mapping(target)
    work_risk["peak"] = vector_mapping(next_peak)
    _retain_high_risk_delegation_obligation(task, next_peak, timestamp)

    change_id: str | None = None
    change_path: Path | None = None
    change: dict | None = None
    assurance_raised = False
    if raise_assurance:
        change_id = _focused_change_id(graph)
        if not change_id or change_id not in graph.changes:
            raise RiskTransactionError(
                "--raise-assurance requires the current focus to be a Change or an "
                "Investigation sourced from a Change"
            )
        change_path = graph.changes[change_id][0] / "change.yaml"
        change = load_yaml(change_path)
        assurance_raised = _raise_change_assurance(change, target)
        if assurance_raised:
            task.setdefault("timeline", []).append(
                {
                    "type": "change-assurance-raised",
                    "at": timestamp,
                    "change": change_id,
                    "risk": dict(change["risk"]),
                    "reason": reason.strip(),
                    "evidence_ref": evidence_ref,
                }
            )

    writes = [task_path]
    if change_path is not None and assurance_raised:
        writes.append(change_path)
    snapshot = _snapshot(writes)
    try:
        atomic_write_yaml(task_path, task)
        if change_path is not None and change is not None and assurance_raised:
            atomic_write_yaml(change_path, change)
        validate_governed_work_graph(context, task_root)
    except BaseException:
        _restore(snapshot)
        raise

    return target, next_peak, change_id if assurance_raised else None
