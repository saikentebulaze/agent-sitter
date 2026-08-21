from __future__ import annotations

import contextlib
import io
from pathlib import Path

import yaml

from _learning_impl import command_closeout, command_intake
from archive_change import ArchiveChangeError, archive_change
from archive_lifecycle import ArchiveLifecycleError, finalize_archive_cleanup
from change_lifecycle import ChangeLifecycleError, advance_change
from evidence_projection import (
    EvidenceProjectionError,
    record_verification_batch,
    render_evidence,
    validate_verification_batch,
)
from governed_work import PivotTransactionError, complete_task
from knowledge_lifecycle import KnowledgeLifecycleError, defer_knowledge
from project_context import ProjectContext
from reference_resolver import resolve_change_ref, resolve_task_ref


class CompleteAfterApprovalError(RuntimeError):
    pass


_NO_KNOWLEDGE_REASON = (
    "V6.3 complete-after-approval assessment found no durable Project Knowledge candidates"
)
_NO_LEARNING_REASON = (
    "V6.3 complete-after-approval assessed the Task with no reusable Learning observations"
)
_CLEANUP_EVIDENCE = (
    "V6.3 complete-after-approval inspected the owning Task experiments and declared temporary "
    "production artifacts; no closure residue remains"
)


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CompleteAfterApprovalError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise CompleteAfterApprovalError(f"expected YAML mapping: {path}")
    return data


def _quiet(callable_, *args, **kwargs):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        return callable_(*args, **kwargs)


def _result(change_id: str, *, status: str, engineering_complete: bool, **extra) -> dict:
    return {
        "change": change_id,
        "status": status,
        "engineering_complete": engineering_complete,
        **extra,
    }


def _learning_closeout(context: ProjectContext, task_id: str) -> dict:
    task_ref = resolve_task_ref(context, task_id)
    task = _load(task_ref.yaml_path)
    learning = task.get("learning") or {}
    if (learning.get("intake") or {}).get("status") != "completed":
        _quiet(command_intake, context, task_ref.yaml_path, [], 5)
        task = _load(task_ref.yaml_path)
        learning = task.get("learning") or {}
    if (learning.get("closeout") or {}).get("status") != "assessed":
        observations = learning.get("observations") or []
        reason = _NO_LEARNING_REASON if not observations else None
        _quiet(command_closeout, context, task_ref.yaml_path, reason)
        task = _load(task_ref.yaml_path)
        learning = task.get("learning") or {}
    return learning


def complete_after_approval(
    context: ProjectContext,
    change_value: str | Path,
    *,
    verification_batch: list[dict] | None = None,
) -> dict:
    """Continue a Candidate from current user acceptance through safe closure.

    This coordinator is intentionally resumable. A Knowledge, cleanup, Learning,
    or multi-work-item stop preserves already-valid engineering verification and
    a later invocation continues from authoritative state instead of repeating
    Reviewer or verification work.
    """

    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise CompleteAfterApprovalError(
            "complete-after-approval is only available for candidate_readiness_protocol 1 Changes"
        )
    change_id = str(data.get("id") or ref.id)
    user_review = data.get("user_review") or {}
    if user_review.get("status") not in {"approved", "not-required"}:
        raise CompleteAfterApprovalError("current Candidate user acceptance is required")

    try:
        status = str(data.get("status") or "")
        if verification_batch is not None:
            # Parse and validate the whole batch before the first lifecycle mutation.
            validate_verification_batch(verification_batch)
        elif status == "candidate-review":
            current_verification = str((data.get("verification") or {}).get("status") or "pending")
            if current_verification not in {"pass", "partial"}:
                raise CompleteAfterApprovalError(
                    "Final Verification batch is required on the first completion attempt"
                )
        if status == "candidate-review":
            status = advance_change(context, ref.root)

        if status == "verifying":
            if verification_batch is not None:
                record_verification_batch(context, ref.root, verification_batch)
            data = _load(ref.yaml_path)
            verification_status = str((data.get("verification") or {}).get("status") or "pending")
            if verification_status == "fail":
                render_evidence(context, ref.root)
                return _result(
                    change_id,
                    status="verification-failed",
                    engineering_complete=False,
                    verification=verification_status,
                    governance_closure="not-started",
                )
            if verification_status not in {"pass", "partial"}:
                raise CompleteAfterApprovalError(
                    "Final Verification evidence is required before closure"
                )
            status = advance_change(context, ref.root)

        if status == "syncing":
            data = _load(ref.yaml_path)
            knowledge = data.get("knowledge_sync") or {}
            knowledge_status = str(knowledge.get("status") or "pending")
            entries = knowledge.get("entries") or []
            if not isinstance(entries, list):
                raise CompleteAfterApprovalError("knowledge_sync.entries must be a list")
            if knowledge_status not in {"promoted", "deferred"}:
                if entries:
                    render_evidence(context, ref.root)
                    return _result(
                        change_id,
                        status="governance-closure-pending",
                        engineering_complete=True,
                        governance_closure="knowledge-review",
                        knowledge_candidates=[str(item.get("id") or "") for item in entries if isinstance(item, dict)],
                    )
                defer_knowledge(context, ref.root, reason=_NO_KNOWLEDGE_REASON)

            data = _load(ref.yaml_path)
            archive = data.get("archive") or {}
            if archive.get("experiment_cleanup_complete") is not True:
                try:
                    finalize_archive_cleanup(
                        context,
                        ref.root,
                        evidence=_CLEANUP_EVIDENCE,
                    )
                except ArchiveLifecycleError as error:
                    render_evidence(context, ref.root)
                    return _result(
                        change_id,
                        status="governance-closure-pending",
                        engineering_complete=True,
                        governance_closure="cleanup",
                        blocker=str(error),
                    )
            status = advance_change(context, ref.root)

        if status == "ready-to-archive":
            task_id = str(_load(ref.yaml_path).get("task_id") or "").strip()
            archived = archive_change(context, ref.root)
            ref = resolve_change_ref(context, archived)
            status = "archived"
        else:
            data = _load(ref.yaml_path)
            task_id = str(data.get("task_id") or "").strip()

        if status != "archived":
            raise CompleteAfterApprovalError(
                f"complete-after-approval cannot continue from Change status {status}"
            )
        if not task_id:
            raise CompleteAfterApprovalError("archived Change has no owning Task")

        task_ref = resolve_task_ref(context, task_id)
        task_data = _load(task_ref.yaml_path)
        if task_data.get("status") == "completed":
            return _result(
                change_id,
                status="done",
                engineering_complete=True,
                governance_closure="complete",
                archived=True,
                task_completed=True,
                idempotent=True,
            )

        learning = _learning_closeout(context, task_id)
        attention = learning.get("user_attention") or {}
        if attention.get("required") is True and attention.get("decision") == "pending":
            return _result(
                change_id,
                status="governance-closure-pending",
                engineering_complete=True,
                governance_closure="learning-curation",
                archived=True,
                learning_candidates=list((learning.get("closeout") or {}).get("candidates_ready_for_review") or []),
            )

        try:
            complete_task(
                context,
                task_id,
                rationale="Owning Change archived and V6.3 closure evidence is complete",
            )
        except PivotTransactionError as error:
            return _result(
                change_id,
                status="governance-closure-pending",
                engineering_complete=True,
                governance_closure="task-work-remains",
                archived=True,
                blocker=str(error),
            )
        return _result(
            change_id,
            status="done",
            engineering_complete=True,
            governance_closure="complete",
            archived=True,
            task_completed=True,
            idempotent=False,
        )
    except (
        ChangeLifecycleError,
        EvidenceProjectionError,
        KnowledgeLifecycleError,
        ArchiveChangeError,
        ValueError,
    ) as error:
        raise CompleteAfterApprovalError(str(error)) from error
