from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path

from active_task_index import index_path, unregister_active_task
from governed_validation import (
    ACTIVE_ESCALATIONS,
    investigation_exploration_status,
    validate_governed_work_graph,
    validate_investigation_policy,
)
from pivot_transaction import (
    PivotTransactionError,
    conclude_investigation as _base_conclude_investigation,
    create_investigation as _base_create_investigation,
    initialize_task as _base_initialize_task,
    investigate_change as _base_investigate_change,
    pivot_to_change as _base_pivot_to_change,
    record_claim as _base_record_claim,
    record_decision as _base_record_decision,
    record_evidence as _base_record_evidence,
    record_model_review as _base_record_model_review,
    refresh_status,
    resolve_human_checkpoint as _base_resolve_human_checkpoint,
)
from project_context import ProjectContext
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import (
    WorkGraphError,
    dump_yaml,
    investigation_path,
    load_yaml,
    now_iso,
    resolve_change_root,
    resolve_task_root,
    valid_id,
)


MODEL_PROFILES = {
    "framework_scout": ("gpt-5.6-terra", "terra"),
    "maintainer_reviewer": ("gpt-5.6-terra", "terra"),
    "deep_reviewer": ("gpt-5.6-sol", "sol"),
}


def _bytes_snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.restore")
            temporary.write_bytes(content)
            temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_task(context: ProjectContext, task_value: str | Path) -> tuple[Path, Path, dict]:
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    return task_root, task_path, load_yaml(task_path)


def _load_investigation(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
) -> tuple[Path, Path, dict, dict]:
    task_root, task_path, task = _load_task(context, task_value)
    inv_path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    investigation = load_yaml(inv_path)
    return task_root, inv_path, task, investigation


def _ensure_no_escalation(task: dict) -> None:
    escalation = task.get("escalation") or {}
    level = str(escalation.get("level", "none"))
    if level in ACTIVE_ESCALATIONS:
        raise PivotTransactionError(
            f"task is under {level} escalation; only the requested model or human resolution may proceed"
        )


def _ensure_investigation_mutable(investigation: dict) -> None:
    if investigation.get("status") in {"concluded", "closed"}:
        raise PivotTransactionError("concluded or closed investigation is immutable")
    if investigation.get("execution_state") != "active":
        raise PivotTransactionError("investigation must be active before recording evidence or decisions")


def _ensure_investigation_explored(
    context: ProjectContext,
    task_root: Path,
    investigation_id: str,
    action: str,
) -> None:
    graph = validate_governed_work_graph(context, task_root)
    status = investigation_exploration_status(graph, investigation_id)
    if status["required"] and not status["satisfied"]:
        raise PivotTransactionError(
            "HIGH/CRITICAL Investigation requires completed independent exploration before "
            f"{action}; evidence, claims, and experiments may continue"
        )


def _global_change_root(context: ProjectContext, change_id: str) -> Path | None:
    for parent in ("active", "archive"):
        root = context.project_root / "changes" / parent / change_id
        if root.exists():
            return root
    return None


def _human_decision_resolved(task: dict) -> bool:
    human = task.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    return assessment.get("status") == "resolved" and bool(human.get("decisions"))


def _validate_actionable_decisions(task: dict, investigation: dict) -> None:
    claims = {str(item["id"]): item for item in investigation.get("claims") or []}
    accepted = [
        item for item in investigation.get("decisions") or []
        if item.get("status") == "accepted"
    ]
    if not accepted:
        raise PivotTransactionError("production action requires at least one accepted decision")
    for decision in accepted:
        decision_id = str(decision.get("id"))
        basis = decision.get("basis") or {}
        for claim_id in map(str, basis.get("claims") or []):
            claim = claims.get(claim_id)
            if claim is None or claim.get("status") != "supported":
                raise PivotTransactionError(
                    f"accepted decision {decision_id} depends on non-supported claim {claim_id}"
                )
        if bool(decision.get("requires_human", False)):
            if not decision.get("evidence_ref") or not _human_decision_resolved(task):
                raise PivotTransactionError(
                    f"accepted decision {decision_id} requires a resolved human decision and evidence"
                )


def initialize_task(
    context: ProjectContext,
    *,
    task_id: str,
    title: str,
    entry: str,
    question: str | None = None,
    signature: str | None = None,
    change_id: str | None = None,
    change_title: str | None = None,
) -> Path:
    task_id = valid_id(task_id, "task_id")
    task_root = context.project_root / ".agent-work" / task_id
    change_root: Path | None = None
    if entry == "change":
        resolved_change_id = valid_id(change_id or task_id, "change_id")
        existing = _global_change_root(context, resolved_change_id)
        if existing is not None:
            raise PivotTransactionError(f"change id already exists: {resolved_change_id}")
        change_root = context.project_root / "changes" / "active" / resolved_change_id

    task_existed = task_root.exists()
    change_existed = bool(change_root and change_root.exists())
    try:
        root = _base_initialize_task(
            context,
            task_id=task_id,
            title=title,
            entry=entry,
            question=question,
            signature=signature,
            change_id=change_id,
            change_title=change_title,
        )
        validate_governed_work_graph(context, root)
        return root
    except BaseException:
        if not task_existed and task_root.exists():
            shutil.rmtree(task_root, ignore_errors=True)
        if change_root is not None and not change_existed and change_root.exists():
            shutil.rmtree(change_root, ignore_errors=True)
        raise


def create_investigation(
    context: ProjectContext,
    task_value: str | Path,
    *,
    title: str,
    question: str,
    signature: str,
    source_type: str = "task",
    source_ref: str | None = None,
    discrimination_rationale: str | None = None,
) -> str:
    task_root, _, task = _load_task(context, task_value)
    _ensure_no_escalation(task)
    investigation_id = _base_create_investigation(
        context,
        task_value,
        title=title,
        question=question,
        signature=signature,
        source_type=source_type,
        source_ref=source_ref,
        discrimination_rationale=discrimination_rationale,
    )
    validate_governed_work_graph(context, task_root)
    return investigation_id


def record_evidence(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    **kwargs: object,
) -> None:
    task_root, _, task, investigation = _load_investigation(
        context, task_value, investigation_id
    )
    _ensure_no_escalation(task)
    _ensure_investigation_mutable(investigation)
    _base_record_evidence(context, task_value, investigation_id, **kwargs)
    validate_governed_work_graph(context, task_root)


def record_claim(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    **kwargs: object,
) -> None:
    task_root, _, task, investigation = _load_investigation(
        context, task_value, investigation_id
    )
    _ensure_no_escalation(task)
    _ensure_investigation_mutable(investigation)
    candidate = copy.deepcopy(investigation)
    claims = candidate.setdefault("claims", [])
    claim_id = str(kwargs.get("claim_id"))
    value = {
        "id": claim_id,
        "statement": kwargs.get("statement"),
        "status": kwargs.get("status"),
        "confidence": kwargs.get("confidence"),
        "scope": {"models": [], "result_types": []},
        "supporting_evidence": list(kwargs.get("supporting_evidence") or []),
        "contradicting_evidence": list(kwargs.get("contradicting_evidence") or []),
        "decision_impact": [],
        "next_discriminating_experiment": None,
    }
    existing = next((item for item in claims if item.get("id") == claim_id), None)
    if existing is None:
        claims.append(value)
    else:
        existing.clear()
        existing.update(value)
    validate_investigation_policy(candidate)
    _base_record_claim(context, task_value, investigation_id, **kwargs)
    validate_governed_work_graph(context, task_root)


def record_decision(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    **kwargs: object,
) -> None:
    task_root, _, task, investigation = _load_investigation(
        context, task_value, investigation_id
    )
    _ensure_no_escalation(task)
    _ensure_investigation_mutable(investigation)
    if str(kwargs.get("status") or "") == "accepted":
        _ensure_investigation_explored(
            context,
            task_root,
            investigation_id,
            "accepting a decision",
        )
    requires_human = bool(kwargs.get("requires_human", False))
    if requires_human and (
        not kwargs.get("evidence_ref") or not _human_decision_resolved(task)
    ):
        raise PivotTransactionError(
            "human-required decision needs resolved task human_in_loop evidence"
        )
    candidate = copy.deepcopy(investigation)
    candidate.setdefault("decisions", []).append({
        "id": kwargs.get("decision_id"),
        "statement": kwargs.get("statement"),
        "basis": {
            "claims": list(kwargs.get("claims") or []),
            "evidence": list(kwargs.get("evidence") or []),
        },
        "status": kwargs.get("status"),
        "requires_human": requires_human,
        "evidence_ref": kwargs.get("evidence_ref"),
    })
    validate_investigation_policy(candidate)
    _base_record_decision(context, task_value, investigation_id, **kwargs)
    validate_governed_work_graph(context, task_root)


def pivot_to_change(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    change_id: str,
    title: str,
    rationale: str,
    supersede_change: str | None = None,
) -> Path:
    task_root, _, task, investigation = _load_investigation(
        context, task_value, investigation_id
    )
    _ensure_no_escalation(task)
    _ensure_investigation_mutable(investigation)
    _ensure_investigation_explored(
        context,
        task_root,
        investigation_id,
        "pivoting to production Change",
    )
    change_id = valid_id(change_id, "change_id")
    if _global_change_root(context, change_id) is not None:
        raise PivotTransactionError(f"change id already exists: {change_id}")
    _validate_actionable_decisions(task, investigation)
    root = _base_pivot_to_change(
        context,
        task_value,
        investigation_id,
        change_id=change_id,
        title=title,
        rationale=rationale,
        supersede_change=supersede_change,
    )
    validate_governed_work_graph(context, task_root)
    return root


def investigate_change(
    context: ProjectContext,
    change_value: str | Path,
    *,
    title: str,
    question: str,
    signature: str,
    discrimination_rationale: str | None,
) -> str:
    change_root = resolve_change_root(context, change_value)
    change = load_yaml(change_root / "change.yaml")
    task_root, task_path, task = _load_task(context, str(change.get("task_id")))
    _ensure_no_escalation(task)
    investigation_id = _base_investigate_change(
        context,
        change_value,
        title=title,
        question=question,
        signature=signature,
        discrimination_rationale=discrimination_rationale,
    )
    task = load_yaml(task_path)
    escalation = task.get("escalation") or {}
    if escalation.get("level") == "stronger-model":
        escalation["target_investigation_ref"] = investigation_id
        escalation["target_change_ref"] = str(change["id"])
        task["escalation"] = escalation
        atomic_write_yaml(task_path, task)
    validate_governed_work_graph(context, task_root)
    return investigation_id


def _cancel_pending_change_review(change_root: Path, revision_number: int) -> tuple[Path | None, bytes | None]:
    packet = change_root / "review-request.yaml"
    if not packet.exists():
        return None, None
    content = packet.read_bytes()
    archive = change_root / "reviews" / f"revision-{revision_number}-cancelled-review.request.yaml"
    if archive.exists():
        raise PivotTransactionError(f"cancelled review archive already exists: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(archive, content.decode("utf-8"))
    packet.unlink()
    return archive, content


def conclude_investigation(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    disposition: str,
    target: str | None,
    rationale: str,
    remaining_unknowns: list[str],
    scope_revalidated: bool,
    design_revalidated: bool,
    approval_still_valid: bool,
) -> None:
    task_root, inv_path, task, investigation = _load_investigation(
        context, task_value, investigation_id
    )
    _ensure_no_escalation(task)
    _ensure_investigation_mutable(investigation)
    _ensure_investigation_explored(
        context,
        task_root,
        investigation_id,
        "concluding the Investigation",
    )
    if disposition in {"resume-change", "revise-change"}:
        _validate_actionable_decisions(task, investigation)

    if disposition != "revise-change":
        _base_conclude_investigation(
            context,
            task_value,
            investigation_id,
            disposition=disposition,
            target=target,
            rationale=rationale,
            remaining_unknowns=remaining_unknowns,
            scope_revalidated=scope_revalidated,
            design_revalidated=design_revalidated,
            approval_still_valid=approval_still_valid,
        )
        task_after = load_yaml(task_root / "task.yaml")
        escalation = task_after.get("escalation") or {}
        if escalation.get("level") == "stronger-model":
            escalation["target_investigation_ref"] = investigation_id
            source = investigation.get("source") or {}
            if source.get("type") == "change":
                escalation["target_change_ref"] = source.get("ref")
            task_after["escalation"] = escalation
            atomic_write_yaml(task_root / "task.yaml", task_after)
        validate_governed_work_graph(context, task_root)
        return

    if not target:
        raise PivotTransactionError("revise-change requires --target")
    change_root = resolve_change_root(context, target)
    change_path = change_root / "change.yaml"
    old_change = load_yaml(change_path)
    old_history = copy.deepcopy(old_change.get("review_history") or [])
    revision_number = len(old_change.get("revision_history") or []) + 1
    task_path = task_root / "task.yaml"
    snapshot = _bytes_snapshot([task_path, inv_path, change_path, change_root / "review-request.yaml"])
    cancelled_archive: Path | None = None
    try:
        cancelled_archive, _ = _cancel_pending_change_review(change_root, revision_number)
        _base_conclude_investigation(
            context,
            task_value,
            investigation_id,
            disposition=disposition,
            target=target,
            rationale=rationale,
            remaining_unknowns=remaining_unknowns,
            scope_revalidated=scope_revalidated,
            design_revalidated=design_revalidated,
            approval_still_valid=approval_still_valid,
        )
        revised = load_yaml(change_path)
        revised["review_history"] = old_history
        revised["knowledge_sync"] = {"status": "pending", "entries": []}
        revised["archive"] = {
            "experiment_cleanup_complete": False,
            "temporary_production_files": [],
            "blockers": ["change revised after investigation"],
        }
        atomic_write_yaml(change_path, revised)
        validate_governed_work_graph(context, task_root)
    except BaseException:
        _restore_snapshot(snapshot)
        if cancelled_archive is not None:
            cancelled_archive.unlink(missing_ok=True)
        raise


def request_model_review(
    context: ProjectContext,
    task_value: str | Path,
    *,
    role: str | None,
    elevated_authorization_ref: str | None,
) -> Path:
    task_root, task_path, task = _load_task(context, task_value)
    escalation = task.get("escalation") or {}
    review = escalation.get("model_review") or {}
    if escalation.get("level") != "stronger-model" or review.get("status") != "pending":
        raise PivotTransactionError("no stronger-model review is pending")
    target = escalation.get("target_investigation_ref")
    if not isinstance(target, str) or not target:
        raise PivotTransactionError("model escalation has no stable target investigation")
    focus = task.get("current_focus") or {}
    if focus != {"type": "investigation", "ref": target}:
        raise PivotTransactionError("model review target no longer matches current focus")

    selected_role = role or str(review.get("role") or "framework_scout")
    if selected_role not in MODEL_PROFILES:
        raise PivotTransactionError("unsupported model-review role")
    model, tier = MODEL_PROFILES[selected_role]
    if selected_role == "deep_reviewer" and not elevated_authorization_ref:
        raise PivotTransactionError("deep model review requires elevated authorization evidence")

    packet_path = task_root / "model-review-request.yaml"
    if packet_path.exists():
        raise PivotTransactionError("a model review request is already pending")
    inv_path = investigation_path(task_root, target)
    round_number = len(list((task_root / "model-reviews").glob(f"{target}-round-*.request.yaml"))) + 1
    output = task_root / "model-reviews" / f"{target}-round-{round_number}.md"
    packet = {
        "task_id": task["id"],
        "investigation_id": target,
        "round": round_number,
        "reviewer": {"agent": selected_role, "model": model, "tier": tier},
        "method": "native-subagent",
        "output_ref": output.relative_to(context.project_root).as_posix(),
        "elevated_authorization_ref": elevated_authorization_ref,
        "input_snapshot": {
            "task_sha256": _sha256(task_path),
            "investigation_sha256": _sha256(inv_path),
        },
        "instructions": (
            "Run the named native read-only reviewer against the frozen task and investigation. "
            "Save the exact returned text as a temporary project artifact, then use "
            "`work.py record-model-review`; do not edit escalation YAML by hand."
        ),
    }
    atomic_write_yaml(packet_path, packet)
    return packet_path


def record_model_review(
    context: ProjectContext,
    task_value: str | Path,
    *,
    artifact: Path,
    outcome: str,
    evidence_ref: str,
) -> None:
    if outcome not in {"supported", "inconclusive", "block"}:
        raise PivotTransactionError("model review outcome must be supported, inconclusive, or block")
    task_root, task_path, task = _load_task(context, task_value)
    packet_path = task_root / "model-review-request.yaml"
    if not packet_path.exists():
        raise PivotTransactionError("no pending model review request")
    packet = load_yaml(packet_path)
    target = str(packet.get("investigation_id") or "")
    escalation = task.get("escalation") or {}
    if escalation.get("target_investigation_ref") != target:
        raise PivotTransactionError("model review packet target is stale")
    focus = task.get("current_focus") or {}
    if focus != {"type": "investigation", "ref": target}:
        raise PivotTransactionError("model review target no longer matches current focus")
    inv_path = investigation_path(task_root, target)
    expected = packet.get("input_snapshot") or {}
    actual = {
        "task_sha256": _sha256(task_path),
        "investigation_sha256": _sha256(inv_path),
    }
    changed = [key for key, value in actual.items() if expected.get(key) != value]
    if changed:
        raise PivotTransactionError("model review request is stale: " + ", ".join(changed))

    artifact_path = artifact.resolve() if artifact.is_absolute() else (context.project_root / artifact).resolve()
    try:
        artifact_path.relative_to(context.project_root)
    except ValueError as error:
        raise PivotTransactionError("model review artifact is outside project") from error
    if not artifact_path.is_file() or not artifact_path.read_text(encoding="utf-8").strip():
        raise PivotTransactionError("model review artifact is missing or empty")
    if not evidence_ref.strip():
        raise PivotTransactionError("model review evidence_ref is required")

    output = context.project_root / str(packet["output_ref"])
    archive = task_root / "model-reviews" / f"{target}-round-{packet['round']}.request.yaml"
    snapshot = _bytes_snapshot([task_path, inv_path, packet_path, output, archive])
    reviewer = packet["reviewer"]
    try:
        atomic_write_text(output, artifact_path.read_text(encoding="utf-8"))
        _base_record_model_review(
            context,
            task_value,
            role=str(reviewer["agent"]),
            model=str(reviewer["model"]),
            tier=str(reviewer["tier"]),
            outcome=outcome,
            evidence_ref=evidence_ref,
        )
        task_after = load_yaml(task_path)
        review_after = (task_after.get("escalation") or {}).get("model_review") or {}
        if outcome == "block":
            review_after["status"] = "blocked"
            task_after["escalation"]["model_review"] = review_after
            atomic_write_yaml(task_path, task_after)
        archive.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(archive, packet)
        packet_path.unlink()
        validate_governed_work_graph(context, task_root)
    except BaseException:
        _restore_snapshot(snapshot)
        raise


def resolve_human_checkpoint(
    context: ProjectContext,
    task_value: str | Path,
    *,
    action: str,
    decision: str,
    evidence: str,
) -> None:
    task_root, _, task = _load_task(context, task_value)
    escalation = task.get("escalation") or {}
    target = escalation.get("target_investigation_ref")
    if escalation.get("level") != "human-checkpoint" or not target:
        raise PivotTransactionError("no targeted human checkpoint is pending")
    _base_resolve_human_checkpoint(
        context,
        task_value,
        action=action,
        decision=decision,
        evidence=evidence,
    )
    validate_governed_work_graph(context, task_root)


def complete_task(
    context: ProjectContext,
    task_value: str | Path,
    *,
    rationale: str,
) -> None:
    task_root, task_path, task = _load_task(context, task_value)
    graph = validate_governed_work_graph(context, task_root)
    if task.get("status") == "completed":
        raise PivotTransactionError("task is already completed")
    if (task.get("escalation") or {}).get("level") != "none":
        raise PivotTransactionError("task cannot complete with an unresolved escalation")
    learning = task.get("learning") or {}
    if (learning.get("closeout") or {}).get("status") != "assessed":
        raise PivotTransactionError("learning closeout must be assessed before task completion")

    open_investigations = [
        key for key, value in graph.investigations.items()
        if value.get("status") not in {"concluded", "closed"}
    ]
    if open_investigations:
        raise PivotTransactionError(
            "task still has open investigations: " + ", ".join(open_investigations)
        )
    incomplete_changes = [
        key for key, (_, value) in graph.changes.items()
        if value.get("status") != "archived" and value.get("execution_state") != "abandoned"
    ]
    if incomplete_changes:
        raise PivotTransactionError(
            "task still has non-archived changes: " + ", ".join(incomplete_changes)
        )

    writes: dict[Path, str] = {}
    for investigation_id, value in graph.investigations.items():
        if value.get("status") == "concluded":
            updated = copy.deepcopy(value)
            updated["status"] = "closed"
            writes[investigation_path(task_root, investigation_id)] = dump_yaml(updated)
    task["status"] = "completed"
    task["current_focus"] = {"type": "none", "ref": None}
    task.setdefault("timeline", []).append({
        "type": "task-completed",
        "at": now_iso(),
        "rationale": rationale,
    })
    writes[task_path] = dump_yaml(task)

    snapshot = _bytes_snapshot([*writes, index_path(context)])
    try:
        for path, content in writes.items():
            atomic_write_text(path, content)
        validate_governed_work_graph(context, task_root)
        unregister_active_task(context, task_root)
    except BaseException:
        _restore_snapshot(snapshot)
        raise
