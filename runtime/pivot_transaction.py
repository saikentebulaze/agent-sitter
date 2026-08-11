from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from project_context import ProjectContext
from review_transaction import atomic_write_text
from work_graph import (
    INVESTIGATION_DISPOSITIONS,
    WorkGraphError,
    dump_yaml,
    investigation_markdown_path,
    investigation_path,
    load_yaml,
    next_investigation_id,
    now_iso,
    resolve_change_root,
    resolve_task_root,
    valid_id,
    validate_work_graph,
)


class PivotTransactionError(WorkGraphError):
    pass


def _template(context: ProjectContext, name: str) -> dict:
    path = context.adapter_root / "skills" / "change-governor" / "assets" / name
    return load_yaml(path)


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshots: dict[Path, bytes | None]) -> None:
    for path, content in snapshots.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content.decode("utf-8"))


def _transaction(
    writes: dict[Path, str],
    *,
    validator: Callable[[], None],
    cleanup_dirs: list[Path] | None = None,
) -> None:
    snapshots = _snapshot(list(writes))
    try:
        for path, content in writes.items():
            atomic_write_text(path, content)
        validator()
    except BaseException:
        _restore(snapshots)
        for directory in cleanup_dirs or []:
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        raise


def _append_timeline(task: dict, event_type: str, **values: object) -> None:
    task.setdefault("timeline", []).append({"type": event_type, "at": now_iso(), **values})


def _register_signature(task: dict, signature: str, investigation_id: str) -> int:
    registry = task.setdefault("pivot_control", {}).setdefault("repeated_signatures", {})
    record = registry.setdefault(signature, {"occurrences": 0, "investigations": []})
    investigations = record.setdefault("investigations", [])
    if investigation_id not in investigations:
        investigations.append(investigation_id)
        record["occurrences"] = int(record.get("occurrences", 0)) + 1
    return int(record["occurrences"])


def _new_investigation(
    context: ProjectContext,
    *,
    task_id: str,
    investigation_id: str,
    title: str,
    question: str,
    signature: str,
    source_type: str,
    source_ref: str,
    discrimination_rationale: str | None = None,
    paused: bool = False,
) -> dict:
    data = _template(context, "investigation.yaml.template")
    data.update({
        "id": investigation_id,
        "task_id": task_id,
        "title": title,
        "status": "blocked" if paused else "investigating",
        "execution_state": "paused" if paused else "active",
    })
    data["source"] = {"type": source_type, "ref": source_ref, "evidence_ref": None}
    data["problem"] = {
        "question": question,
        "signature": signature,
        "scope": {"models": [], "subsystems": []},
    }
    data.setdefault("discrimination_gain", {})["rationale"] = discrimination_rationale
    return data


def _new_change(
    context: ProjectContext,
    *,
    task_id: str,
    change_id: str,
    title: str,
    derived_investigations: list[str] | None = None,
    claims: list[str] | None = None,
    decisions: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict:
    data = _template(context, "change.yaml.template")
    data.update({
        "id": change_id,
        "task_id": task_id,
        "title": title,
        "status": "proposed",
        "execution_state": "active",
    })
    derived = data.setdefault("relations", {}).setdefault("derived_from", {})
    derived["investigations"] = list(derived_investigations or [])
    derived["claims"] = list(claims or [])
    derived["decisions"] = list(decisions or [])
    derived["evidence"] = list(evidence or [])
    return data


def _change_artifacts(title: str) -> dict[str, str]:
    return {
        "proposal.md": f"# Proposal\n\n{title}\n\nThis production change was created by the v4 work graph.\n",
        "design.md": f"# Design\n\nDesign for {title}.\n\nPending detailed engineering decisions.\n",
        "tasks.md": f"# Tasks\n\n- [ ] Implement {title}.\n- [ ] Verify the approved behavior.\n",
        "verification.md": "# Verification\n\nNo verification result has been recorded yet.\n",
        "knowledge-sync.md": "# Knowledge Sync\n\nKnowledge impact has not been assessed yet.\n",
        "archive-summary.md": "# Archive Summary\n\nThe change is not ready for archive.\n",
    }


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
    if entry not in {"investigation", "change"}:
        raise PivotTransactionError("entry must be investigation or change")
    task_root = context.project_root / ".agent-work" / task_id
    if task_root.exists():
        raise PivotTransactionError(f"task exists: {task_root}")

    task = _template(context, "task.yaml.template")
    task["id"] = task_id
    task["title"] = title
    task["status"] = "active"
    writes: dict[Path, str] = {}

    if entry == "investigation":
        investigation_id = "inv-001"
        investigation = _new_investigation(
            context,
            task_id=task_id,
            investigation_id=investigation_id,
            title=title,
            question=question or title,
            signature=valid_id(signature or task_id, "signature"),
            source_type="task",
            source_ref=task_id,
        )
        task["current_focus"] = {"type": "investigation", "ref": investigation_id}
        task["work_items"] = {"investigations": [investigation_id], "changes": []}
        _register_signature(task, investigation["problem"]["signature"], investigation_id)
        _append_timeline(task, "investigation-created", ref=investigation_id, source=task_id)
        writes[investigation_path(task_root, investigation_id)] = dump_yaml(investigation)
        writes[investigation_markdown_path(task_root, investigation_id)] = (
            f"# {title}\n\n## Question\n\n{investigation['problem']['question']}\n\n## Findings\n\n"
        )
    else:
        resolved_change_id = valid_id(change_id or task_id, "change_id")
        resolved_change_title = change_title or title
        change = _new_change(
            context,
            task_id=task_id,
            change_id=resolved_change_id,
            title=resolved_change_title,
        )
        task["current_focus"] = {"type": "change", "ref": resolved_change_id}
        task["work_items"] = {"investigations": [], "changes": [resolved_change_id]}
        _append_timeline(task, "change-created", ref=resolved_change_id, source=task_id)
        change_root = context.project_root / "changes" / "active" / resolved_change_id
        writes[change_root / "change.yaml"] = dump_yaml(change)
        for name, content in _change_artifacts(resolved_change_title).items():
            writes[change_root / name] = content

    writes[task_root / "task.yaml"] = dump_yaml(task)
    writes[task_root / "status.md"] = "# Task status\n\nRun `work.py task-status` to refresh.\n"
    for directory in ("investigations", "evidence", "experiments", "scouts"):
        (task_root / directory).mkdir(parents=True, exist_ok=True)

    _transaction(
        writes,
        validator=lambda: validate_work_graph(context, task_root),
        cleanup_dirs=[task_root],
    )
    return task_root


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
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    if task.get("status") == "completed":
        raise PivotTransactionError("cannot add work to a completed task")
    human = ((task.get("escalation") or {}).get("human_checkpoint") or {})
    if human.get("status") == "pending":
        raise PivotTransactionError("human checkpoint is pending; new investigations are blocked")

    investigation_id = next_investigation_id(task)
    source_ref = source_ref or str(task["id"])
    signature = valid_id(signature, "signature")
    active_same = []
    for existing_id in (task.get("work_items") or {}).get("investigations") or []:
        existing = load_yaml(investigation_path(task_root, existing_id))
        if (
            (existing.get("problem") or {}).get("signature") == signature
            and existing.get("status") not in {"concluded", "closed"}
        ):
            active_same.append(existing_id)
    if active_same:
        raise PivotTransactionError(
            "an active investigation already uses this signature: " + ", ".join(active_same)
        )

    investigation = _new_investigation(
        context,
        task_id=str(task["id"]),
        investigation_id=investigation_id,
        title=title,
        question=question,
        signature=signature,
        source_type=source_type,
        source_ref=source_ref,
        discrimination_rationale=discrimination_rationale,
    )
    task.setdefault("work_items", {}).setdefault("investigations", []).append(investigation_id)
    task["current_focus"] = {"type": "investigation", "ref": investigation_id}
    _register_signature(task, signature, investigation_id)
    _append_timeline(task, "investigation-created", ref=investigation_id, source=source_ref)

    writes = {
        task_path: dump_yaml(task),
        investigation_path(task_root, investigation_id): dump_yaml(investigation),
        investigation_markdown_path(task_root, investigation_id): (
            f"# {title}\n\n## Question\n\n{question}\n\n## Findings\n\n"
        ),
    }
    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))
    return investigation_id


def record_evidence(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    evidence_id: str,
    kind: str,
    source_ref: str,
    provenance: str,
    reliability: str,
    supports: list[str],
    contradicts: list[str],
    limitations: list[str],
) -> None:
    task_root = resolve_task_root(context, task_value)
    path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    data = load_yaml(path)
    evidence_id = valid_id(evidence_id, "evidence_id")
    if any(item.get("id") == evidence_id for item in data.get("evidence") or []):
        raise PivotTransactionError(f"evidence already exists: {evidence_id}")
    data.setdefault("evidence", []).append({
        "id": evidence_id,
        "kind": kind,
        "source_ref": source_ref,
        "provenance": provenance,
        "supports": supports,
        "contradicts": contradicts,
        "reliability": reliability,
        "limitations": limitations,
    })
    _transaction({path: dump_yaml(data)}, validator=lambda: validate_work_graph(context, task_root))


def record_claim(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    claim_id: str,
    statement: str,
    status: str,
    confidence: str,
    supporting_evidence: list[str],
    contradicting_evidence: list[str],
) -> None:
    task_root = resolve_task_root(context, task_value)
    path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    data = load_yaml(path)
    claim_id = valid_id(claim_id, "claim_id")
    claims = data.setdefault("claims", [])
    existing = next((item for item in claims if item.get("id") == claim_id), None)
    value = {
        "id": claim_id,
        "statement": statement,
        "status": status,
        "confidence": confidence,
        "scope": {"models": [], "result_types": []},
        "supporting_evidence": supporting_evidence,
        "contradicting_evidence": contradicting_evidence,
        "decision_impact": [],
        "next_discriminating_experiment": None,
    }
    if existing is None:
        claims.append(value)
    else:
        existing.clear()
        existing.update(value)
    _transaction({path: dump_yaml(data)}, validator=lambda: validate_work_graph(context, task_root))


def record_decision(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    decision_id: str,
    statement: str,
    status: str,
    claims: list[str],
    evidence: list[str],
    requires_human: bool,
    evidence_ref: str | None,
) -> None:
    task_root = resolve_task_root(context, task_value)
    path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    data = load_yaml(path)
    decision_id = valid_id(decision_id, "decision_id")
    decisions = data.setdefault("decisions", [])
    if any(item.get("id") == decision_id for item in decisions):
        raise PivotTransactionError(f"decision already exists: {decision_id}")
    decisions.append({
        "id": decision_id,
        "statement": statement,
        "basis": {"claims": claims, "evidence": evidence},
        "status": status,
        "requires_human": requires_human,
        "evidence_ref": evidence_ref,
    })
    _transaction({path: dump_yaml(data)}, validator=lambda: validate_work_graph(context, task_root))


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
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    inv_path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    task = load_yaml(task_path)
    investigation = load_yaml(inv_path)
    if investigation.get("execution_state") != "active":
        raise PivotTransactionError("investigation must be active before creating a change")
    accepted = [item for item in investigation.get("decisions") or [] if item.get("status") == "accepted"]
    if not accepted:
        raise PivotTransactionError("pivot-to-change requires at least one accepted decision")
    change_id = valid_id(change_id, "change_id")
    change_root = context.project_root / "changes" / "active" / change_id
    if change_root.exists():
        raise PivotTransactionError(f"change exists: {change_id}")

    claims: list[str] = []
    evidence: list[str] = []
    decisions: list[str] = []
    for decision in accepted:
        decisions.append(str(decision["id"]))
        for value in (decision.get("basis") or {}).get("claims") or []:
            if value not in claims:
                claims.append(value)
        for value in (decision.get("basis") or {}).get("evidence") or []:
            if value not in evidence:
                evidence.append(value)

    change = _new_change(
        context,
        task_id=str(task["id"]),
        change_id=change_id,
        title=title,
        derived_investigations=[investigation_id],
        claims=claims,
        decisions=decisions,
        evidence=evidence,
    )
    change["human_in_loop"] = copy.deepcopy(task.get("human_in_loop") or {})

    disposition_type = "supersede-change" if supersede_change else "create-change"
    investigation["status"] = "concluded"
    investigation["execution_state"] = "paused"
    investigation["disposition"] = {
        "type": disposition_type,
        "target": change_id,
        "rationale": rationale,
        "decided_at": now_iso(),
    }
    task.setdefault("work_items", {}).setdefault("changes", []).append(change_id)
    task["current_focus"] = {"type": "change", "ref": change_id}
    _append_timeline(
        task,
        "change-created",
        ref=change_id,
        source=investigation_id,
        disposition=disposition_type,
    )

    writes: dict[Path, str] = {
        task_path: dump_yaml(task),
        inv_path: dump_yaml(investigation),
        change_root / "change.yaml": dump_yaml(change),
    }
    for name, content in _change_artifacts(title).items():
        writes[change_root / name] = content

    if supersede_change:
        old_root = resolve_change_root(context, supersede_change)
        old_path = old_root / "change.yaml"
        old = load_yaml(old_path)
        if old.get("task_id") != task.get("id"):
            raise PivotTransactionError("superseded change belongs to another task")
        old["execution_state"] = "abandoned"
        old.setdefault("relations", {})["superseded_by"] = change_id
        change.setdefault("relations", {}).setdefault("supersedes", []).append(supersede_change)
        writes[old_path] = dump_yaml(old)
        writes[change_root / "change.yaml"] = dump_yaml(change)

    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))
    return change_root


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
    change_path = change_root / "change.yaml"
    change = load_yaml(change_path)
    task_root = resolve_task_root(context, str(change.get("task_id")))
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    if change.get("execution_state") != "active":
        raise PivotTransactionError("only an active change can pivot to investigation")
    if task.get("status") == "completed":
        raise PivotTransactionError("cannot pivot a completed task")
    human = ((task.get("escalation") or {}).get("human_checkpoint") or {})
    if human.get("status") == "pending":
        raise PivotTransactionError("human checkpoint is pending; change execution remains blocked")

    control = task.setdefault("pivot_control", {}).setdefault(
        "automatic_investigations_from_change", {"used": 0, "limit": 1}
    )
    used = int(control.get("used", 0))
    limit = int(control.get("limit", 1))
    escalation_required = used >= limit
    if escalation_required and not (isinstance(discrimination_rationale, str) and discrimination_rationale.strip()):
        raise PivotTransactionError(
            "repeated change-to-investigation pivot requires --discrimination-rationale"
        )

    investigation_id = next_investigation_id(task)
    signature = valid_id(signature, "signature")
    active_same = []
    for existing_id in (task.get("work_items") or {}).get("investigations") or []:
        existing = load_yaml(investigation_path(task_root, existing_id))
        if (
            (existing.get("problem") or {}).get("signature") == signature
            and existing.get("status") not in {"concluded", "closed"}
        ):
            active_same.append(existing_id)
    if active_same:
        raise PivotTransactionError(
            "an active investigation already uses this signature: " + ", ".join(active_same)
        )

    investigation = _new_investigation(
        context,
        task_id=str(task["id"]),
        investigation_id=investigation_id,
        title=title,
        question=question,
        signature=signature,
        source_type="change",
        source_ref=str(change["id"]),
        discrimination_rationale=discrimination_rationale,
        paused=escalation_required,
    )
    control["used"] = used + 1
    task.setdefault("work_items", {}).setdefault("investigations", []).append(investigation_id)
    task["current_focus"] = {"type": "investigation", "ref": investigation_id}
    _register_signature(task, signature, investigation_id)
    change["execution_state"] = "paused"
    change["hold"] = {
        "reason": "investigation-required",
        "investigation_ref": investigation_id,
        "held_at": now_iso(),
    }
    change.setdefault("relations", {}).setdefault("produced", {}).setdefault(
        "investigations", []
    ).append(investigation_id)

    if escalation_required:
        task["status"] = "blocked"
        task["escalation"] = {
            "level": "stronger-model",
            "reason": "automatic change-to-investigation pivot budget exceeded",
            "signature": signature,
            "related_refs": [change["id"], investigation_id],
            "model_review": {
                "required": True,
                "status": "pending",
                "role": "framework_scout",
                "model": None,
                "tier": None,
                "outcome": None,
                "evidence_ref": None,
            },
            "human_checkpoint": {
                "required": False,
                "status": "not-required",
                "question": None,
                "decision": None,
                "evidence": None,
            },
        }
        _append_timeline(
            task,
            "stronger-model-escalation-required",
            signature=signature,
            ref=investigation_id,
        )

    _append_timeline(task, "change-paused", ref=change["id"], investigation=investigation_id)
    _append_timeline(task, "investigation-created", ref=investigation_id, source=change["id"])

    writes = {
        task_path: dump_yaml(task),
        change_path: dump_yaml(change),
        investigation_path(task_root, investigation_id): dump_yaml(investigation),
        investigation_markdown_path(task_root, investigation_id): (
            f"# {title}\n\n## Question\n\n{question}\n\n## Findings\n\n"
        ),
    }
    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))
    return investigation_id


def _reset_change_for_revision(change: dict, investigation_id: str, rationale: str) -> None:
    change.setdefault("revision_history", []).append({
        "at": now_iso(),
        "investigation_ref": investigation_id,
        "rationale": rationale,
        "previous": {
            "status": change.get("status"),
            "approval": copy.deepcopy(change.get("approval") or {}),
            "review": copy.deepcopy(change.get("review") or {}),
            "review_history": copy.deepcopy(change.get("review_history") or []),
            "verification": copy.deepcopy(change.get("verification") or {}),
        },
    })
    change["status"] = "designed"
    change["execution_state"] = "active"
    change["hold"] = {"reason": None, "investigation_ref": None, "held_at": None}
    approval = change.setdefault("approval", {})
    approval.update({"required": True, "status": "pending", "approved_by": None, "approved_at": None})
    change["completion"] = {"implementation_complete": False, "ready_for_user_review": False}
    change["user_review"] = {"status": "pending", "evidence": None}
    change["review"] = {
        "status": "pending",
        "architecture": "pending",
        "scope": "pending",
        "numerical_evidence": "pending",
        "reasons": [],
        "execution": {},
    }
    change["review_history"] = []
    change["remediation"] = {"route": None, "within_approved_scope": False}
    change["verification"] = {"status": "pending", "commands": [], "benchmarks": [], "latest_results": []}


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
    if disposition not in INVESTIGATION_DISPOSITIONS - {"pending", "create-change", "supersede-change"}:
        raise PivotTransactionError(f"unsupported conclude disposition: {disposition}")
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    inv_path = investigation_path(task_root, valid_id(investigation_id, "investigation_id"))
    task = load_yaml(task_path)
    investigation = load_yaml(inv_path)
    if investigation.get("execution_state") == "blocked":
        raise PivotTransactionError("blocked investigation requires escalation resolution first")
    if investigation.get("status") in {"concluded", "closed"}:
        raise PivotTransactionError("investigation is already concluded")

    writes: dict[Path, str] = {}
    investigation["status"] = "concluded"
    investigation["execution_state"] = "paused"
    investigation["remaining_unknowns"] = remaining_unknowns
    investigation["disposition"] = {
        "type": disposition,
        "target": target,
        "rationale": rationale,
        "decided_at": now_iso(),
    }

    if disposition in {"resume-change", "revise-change"}:
        if not target:
            raise PivotTransactionError(f"{disposition} requires --target")
        change_root = resolve_change_root(context, target)
        change_path = change_root / "change.yaml"
        change = load_yaml(change_path)
        hold = change.get("hold") or {}
        if change.get("execution_state") != "paused" or hold.get("investigation_ref") != investigation_id:
            raise PivotTransactionError("target change is not paused for this investigation")
        accepted = [item for item in investigation.get("decisions") or [] if item.get("status") == "accepted"]
        if not accepted:
            raise PivotTransactionError("resume/revise requires an accepted investigation decision")

        if disposition == "resume-change":
            if not (scope_revalidated and design_revalidated and approval_still_valid):
                raise PivotTransactionError(
                    "resume-change requires scope, design, and approval revalidation"
                )
            change["execution_state"] = "active"
            change["hold"] = {"reason": None, "investigation_ref": None, "held_at": None}
            change.setdefault("resume_history", []).append({
                "investigation_ref": investigation_id,
                "disposition": "resume-change",
                "scope_revalidated": True,
                "design_revalidated": True,
                "approval_still_valid": True,
                "resumed_at": now_iso(),
            })
        else:
            _reset_change_for_revision(change, investigation_id, rationale)

        task["current_focus"] = {"type": "change", "ref": target}
        _append_timeline(task, disposition, ref=target, investigation=investigation_id)
        writes[change_path] = dump_yaml(change)
    elif disposition == "inconclusive":
        if not remaining_unknowns:
            raise PivotTransactionError("inconclusive investigation requires remaining unknowns")
        task["status"] = "blocked"
        task["escalation"] = {
            "level": "stronger-model",
            "reason": "investigation concluded without an executable result",
            "signature": (investigation.get("problem") or {}).get("signature"),
            "related_refs": [investigation_id],
            "model_review": {
                "required": True,
                "status": "pending",
                "role": "framework_scout",
                "model": None,
                "tier": None,
                "outcome": None,
                "evidence_ref": None,
            },
            "human_checkpoint": {
                "required": False,
                "status": "not-required",
                "question": None,
                "decision": None,
                "evidence": None,
            },
        }
        _append_timeline(task, "stronger-model-escalation-required", ref=investigation_id)
    else:
        task["current_focus"] = {"type": "none", "ref": None}
        _append_timeline(task, "investigation-concluded", ref=investigation_id, disposition=disposition)

    writes[task_path] = dump_yaml(task)
    writes[inv_path] = dump_yaml(investigation)
    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))


def record_model_review(
    context: ProjectContext,
    task_value: str | Path,
    *,
    role: str,
    model: str,
    tier: str,
    outcome: str,
    evidence_ref: str,
) -> None:
    if outcome not in {"supported", "inconclusive", "block"}:
        raise PivotTransactionError("model review outcome must be supported, inconclusive, or block")
    expected = {
        "framework_scout": ("gpt-5.6-terra", "terra"),
        "maintainer_reviewer": ("gpt-5.6-terra", "terra"),
        "deep_reviewer": ("gpt-5.6-sol", "sol"),
    }
    if role not in expected:
        raise PivotTransactionError("model escalation must use framework scout or an independent reviewer")
    expected_model, expected_tier = expected[role]
    if model != expected_model or tier != expected_tier:
        raise PivotTransactionError(
            f"{role} must use configured model/tier {expected_model}/{expected_tier}"
        )
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    escalation = task.get("escalation") or {}
    review = escalation.get("model_review") or {}
    if escalation.get("level") != "stronger-model" or review.get("status") != "pending":
        raise PivotTransactionError("no stronger-model review is pending")
    review.update({
        "required": True,
        "status": "completed" if outcome == "supported" else "inconclusive",
        "role": role,
        "model": model,
        "tier": tier,
        "outcome": outcome,
        "evidence_ref": evidence_ref,
        "completed_at": now_iso(),
    })
    writes: dict[Path, str] = {}

    focus = task.get("current_focus") or {}
    if outcome == "supported":
        task["status"] = "active"
        escalation["level"] = "none"
        escalation["reason"] = None
        if focus.get("type") == "investigation" and focus.get("ref"):
            inv_path = investigation_path(task_root, str(focus["ref"]))
            investigation = load_yaml(inv_path)
            investigation["status"] = "evidence-review"
            investigation["execution_state"] = "active"
            writes[inv_path] = dump_yaml(investigation)
        _append_timeline(task, "stronger-model-review-completed", outcome=outcome)
    else:
        task["status"] = "blocked"
        escalation["level"] = "human-checkpoint"
        escalation["human_checkpoint"] = {
            "required": True,
            "status": "pending",
            "question": "The stronger model could not establish a safe executable conclusion. How should the work proceed?",
            "decision": None,
            "evidence": None,
        }
        _append_timeline(task, "human-checkpoint-required", outcome=outcome)

    task["escalation"] = escalation
    writes[task_path] = dump_yaml(task)
    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))


def resolve_human_checkpoint(
    context: ProjectContext,
    task_value: str | Path,
    *,
    action: str,
    decision: str,
    evidence: str,
) -> None:
    if action not in {"continue", "stop"}:
        raise PivotTransactionError("human checkpoint action must be continue or stop")
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    escalation = task.get("escalation") or {}
    human = escalation.get("human_checkpoint") or {}
    if escalation.get("level") != "human-checkpoint" or human.get("status") != "pending":
        raise PivotTransactionError("no human checkpoint is pending")
    human.update({
        "required": True,
        "status": "resolved",
        "decision": decision,
        "evidence": evidence,
        "resolved_at": now_iso(),
    })
    writes: dict[Path, str] = {}
    if action == "continue":
        task["status"] = "active"
        escalation["level"] = "none"
        escalation["reason"] = None
        focus = task.get("current_focus") or {}
        if focus.get("type") == "investigation" and focus.get("ref"):
            inv_path = investigation_path(task_root, str(focus["ref"]))
            investigation = load_yaml(inv_path)
            if investigation.get("status") in {"blocked", "concluded"}:
                investigation["status"] = "evidence-review"
            investigation["execution_state"] = "active"
            investigation["disposition"] = {
                "type": "pending",
                "target": None,
                "rationale": None,
                "decided_at": None,
            }
            writes[inv_path] = dump_yaml(investigation)
    else:
        task["status"] = "blocked"
        escalation["level"] = "blocked"
        focus = task.get("current_focus") or {}
        if focus.get("type") == "investigation" and focus.get("ref"):
            inv_path = investigation_path(task_root, str(focus["ref"]))
            investigation = load_yaml(inv_path)
            investigation["status"] = "blocked"
            investigation["execution_state"] = "blocked"
            writes[inv_path] = dump_yaml(investigation)
    task["escalation"] = escalation
    _append_timeline(task, "human-checkpoint-resolved", action=action, decision=decision)
    writes[task_path] = dump_yaml(task)
    _transaction(writes, validator=lambda: validate_work_graph(context, task_root))


def refresh_status(context: ProjectContext, task_value: str | Path, markdown: str) -> Path:
    task_root = resolve_task_root(context, task_value)
    output = task_root / "status.md"
    atomic_write_text(output, markdown)
    return output
