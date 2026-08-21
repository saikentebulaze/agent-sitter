from __future__ import annotations

from pathlib import Path

import yaml

from production_snapshot import production_snapshot_sha256
from project_context import ProjectContext
from readiness import ReadinessError, validate_readiness_contract
from reference_resolver import resolve_change_ref
from review_evidence_guard import (
    ReviewEvidenceError,
    validate_current_protocol2_review,
)
from review_transaction import atomic_write_yaml
from work_graph import now_iso


V62_STATUSES = {
    "proposed",
    "designed",
    "approved",
    "implementing",
    "candidate-review",
    "verifying",
    "syncing",
    "ready-to-archive",
    "archived",
}
USER_REVIEW_DECISIONS = {"approved", "changes-requested", "not-required"}
REVISION_ARCHIVE_BLOCKER = "change revised after investigation"


class ChangeLifecycleError(ValueError):
    pass


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ChangeLifecycleError(f"expected YAML mapping: {path}")
    return data


def _current_production(context: ProjectContext) -> str:
    return production_snapshot_sha256(context.project_root)


def _require_current_readiness(context: ProjectContext, data: dict) -> None:
    try:
        validate_readiness_contract(data)
    except ReadinessError as error:
        raise ChangeLifecycleError(str(error)) from error
    readiness = data.get("readiness") or {}
    if readiness.get("status") != "pass":
        raise ChangeLifecycleError("Candidate Readiness has not passed")
    expected = str((readiness.get("production_snapshot") or {}).get("sha256") or "")
    actual = _current_production(context)
    if not expected or expected != actual:
        raise ChangeLifecycleError(
            "Candidate Readiness is stale because production/test files changed"
        )


def _require_current_review(context: ProjectContext, data: dict) -> None:
    review = data.get("review") or {}
    if review.get("status") not in {"pass", "warn"}:
        raise ChangeLifecycleError("independent readiness review has not passed")
    execution = review.get("execution") or {}
    snapshot = execution.get("input_snapshot") or {}
    if int(snapshot.get("snapshot_protocol") or 1) != 2:
        raise ChangeLifecycleError("V6.2 automatic closure requires review snapshot protocol 2")
    actual = _current_production(context)
    if str(snapshot.get("production_sha256") or "") != actual:
        raise ChangeLifecycleError(
            "independent review is stale because production/test files changed"
        )
    readiness = data.get("readiness") or {}
    if str(snapshot.get("readiness_contract_sha256") or "") != str(
        readiness.get("contract_sha256") or ""
    ):
        raise ChangeLifecycleError("independent review does not match the current Readiness Contract")
    if str(snapshot.get("readiness_evidence_sha256") or "") != str(
        readiness.get("evidence_sha256") or ""
    ):
        raise ChangeLifecycleError("independent review does not match current Readiness evidence")


def _require_candidate_review_preflight(context: ProjectContext, data: dict) -> None:
    _require_current_readiness(context, data)
    methodology = data.get("methodology") or {}
    if methodology.get("test_cleanup_protocol") == 1:
        if methodology.get("test_cleanup_complete") is not True:
            raise ChangeLifecycleError("test finalization is incomplete")
        if not str(methodology.get("test_cleanup_evidence") or "").strip():
            raise ChangeLifecycleError("test finalization evidence is missing")
    _require_current_review(context, data)
    human = data.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    if str(assessment.get("status") or "pending") in {"pending", "required"}:
        raise ChangeLifecycleError("material human design decisions remain unresolved")


def _require_final_verification(data: dict) -> None:
    verification = data.get("verification") or {}
    if verification.get("status") not in {"pass", "partial"}:
        raise ChangeLifecycleError("final verification must pass or be explicitly partial")
    latest = verification.get("latest_results") or []
    if not isinstance(latest, list) or not latest:
        raise ChangeLifecycleError("final verification requires structured evidence")


def _resolve_revision_archive_blocker(data: dict) -> None:
    """Treat a completed post-revision assurance cycle as resolving its hold."""

    archive = data.setdefault("archive", {})
    blockers = archive.get("blockers") or []
    if not isinstance(blockers, list):
        raise ChangeLifecycleError("archive.blockers must be a list")
    archive["blockers"] = [
        blocker for blocker in blockers if str(blocker) != REVISION_ARCHIVE_BLOCKER
    ]


def _require_archive_readiness(data: dict) -> None:
    knowledge = data.get("knowledge_sync") or {}
    if knowledge.get("status") not in {"promoted", "deferred"}:
        raise ChangeLifecycleError(
            "Knowledge must be promoted or explicitly deferred before archive readiness"
        )
    archive = data.get("archive") or {}
    if archive.get("blockers"):
        raise ChangeLifecycleError("archive blockers remain")
    if archive.get("temporary_production_files"):
        raise ChangeLifecycleError("temporary production files remain")
    if archive.get("experiment_cleanup_complete") is not True:
        raise ChangeLifecycleError("experiment cleanup is incomplete")


def build_change_dashboard(context: ProjectContext, change_value: str | Path) -> dict:
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    status = str(data.get("status") or "")
    readiness = data.get("readiness") or {}
    user_review = data.get("user_review") or {}
    review = data.get("review") or {}
    verification = data.get("verification") or {}
    knowledge = data.get("knowledge_sync") or {}
    archive = data.get("archive") or {}
    action_required: list[str] = []
    allowed_next: list[str] = []
    blocked_next: list[str] = []

    if data.get("candidate_readiness_protocol") == 1:
        if status == "implementing":
            if readiness.get("status") != "pass":
                action_required.append(
                    "complete Candidate Readiness evidence and finalize readiness"
                )
            elif review.get("status") not in {"pass", "warn"}:
                action_required.append(
                    "complete test finalization and independent readiness review"
                )
            else:
                allowed_next.append("advance to candidate-review")
        elif status == "candidate-review":
            if user_review.get("status") == "pending":
                action_required.append(
                    "present Candidate Readiness evidence to the user and obtain acceptance"
                )
                allowed_next.append("user-review")
                blocked_next.extend(
                    [
                        "final verification",
                        "knowledge sync",
                        "learning closeout",
                        "archive",
                        "additional reviewer work",
                    ]
                )
            elif user_review.get("status") in {"approved", "not-required"}:
                allowed_next.append("advance to verifying")
            elif user_review.get("status") == "changes-requested":
                allowed_next.append("resume implementation")
        elif status == "verifying":
            if verification.get("status") not in {"pass", "partial"}:
                action_required.append("record structured final verification evidence")
            else:
                allowed_next.append("advance to syncing")
        elif status == "syncing":
            knowledge_status = str(knowledge.get("status") or "pending")
            entries = knowledge.get("entries") or []
            if knowledge_status not in {"promoted", "deferred"}:
                if knowledge_status == "pending" and isinstance(entries, list) and not entries:
                    action_required.append(
                        "explicitly defer Knowledge because no durable candidates are recorded"
                    )
                    allowed_next.append("defer-knowledge")
                else:
                    action_required.append("review and promote durable Knowledge")
                    allowed_next.append("render-knowledge-diff")
            elif archive.get("experiment_cleanup_complete") is not True:
                action_required.append(
                    "finalize archive cleanup after removing development experiments and temporary production files"
                )
                allowed_next.append("finalize-archive-cleanup")
            else:
                allowed_next.append("advance to ready-to-archive")
        elif status == "ready-to-archive":
            allowed_next.append("archive")
    return {
        "id": data.get("id") or ref.id,
        "status": status,
        "candidate_readiness_protocol": data.get("candidate_readiness_protocol"),
        "readiness": readiness.get("status"),
        "review": review.get("status"),
        "user_review": user_review.get("status"),
        "verification": verification.get("status"),
        "knowledge": knowledge.get("status"),
        "archive_cleanup": archive.get("experiment_cleanup_complete"),
        "ACTION REQUIRED": action_required,
        "allowed_next": allowed_next,
        "blocked_next": blocked_next,
    }


def _reprove_current_review(change: Path, data: dict) -> None:
    try:
        validate_current_protocol2_review(change, data)
    except ReviewEvidenceError as error:
        raise ChangeLifecycleError(str(error)) from error


def advance_change(context: ProjectContext, change_value: str | Path) -> str:
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise ChangeLifecycleError(
            "advance is only available for candidate_readiness_protocol 1 Changes"
        )
    status = str(data.get("status") or "")
    if status not in V62_STATUSES:
        raise ChangeLifecycleError(f"invalid V6.2 Change status: {status}")

    _reprove_current_review(ref.root, data)

    if status == "implementing":
        _require_candidate_review_preflight(context, data)
        data["status"] = "candidate-review"
        completion = data.setdefault("completion", {})
        completion["implementation_complete"] = True
        completion["ready_for_user_review"] = True
        user_review = data.setdefault("user_review", {})
        if user_review.get("status") not in {"approved", "not-required"}:
            user_review["status"] = "pending"
            user_review["evidence"] = None
            user_review["reviewed_at"] = None
        atomic_write_yaml(ref.yaml_path, data)
        return "candidate-review"

    if status == "candidate-review":
        user_review = data.get("user_review") or {}
        if user_review.get("status") not in {"approved", "not-required"}:
            raise ChangeLifecycleError(
                "user acceptance is required before final verification"
            )
        _require_current_readiness(context, data)
        _require_current_review(context, data)
        data["status"] = "verifying"
        atomic_write_yaml(ref.yaml_path, data)
        return "verifying"

    if status == "verifying":
        _require_current_readiness(context, data)
        _require_current_review(context, data)
        _require_final_verification(data)
        data["status"] = "syncing"
        atomic_write_yaml(ref.yaml_path, data)
        return "syncing"

    if status == "syncing":
        _require_current_readiness(context, data)
        _require_current_review(context, data)
        _require_final_verification(data)
        _resolve_revision_archive_blocker(data)
        _require_archive_readiness(data)
        data["status"] = "ready-to-archive"
        atomic_write_yaml(ref.yaml_path, data)
        return "ready-to-archive"

    if status == "ready-to-archive":
        raise ChangeLifecycleError(
            "ready-to-archive requires the existing archive transaction; advance does not replace file movement/archival"
        )
    if status == "archived":
        raise ChangeLifecycleError("Change is already archived")

    raise ChangeLifecycleError(
        f"automatic advance from {status} is not allowed; earlier planning/approval transitions remain explicit"
    )


def record_user_review(
    context: ProjectContext,
    change_value: str | Path,
    *,
    decision: str,
    evidence: str,
) -> str:
    if decision not in USER_REVIEW_DECISIONS:
        raise ChangeLifecycleError(
            "user review decision must be approved, changes-requested, or not-required"
        )
    if not evidence.strip():
        raise ChangeLifecycleError("user review evidence is required")
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise ChangeLifecycleError("Change does not use candidate_readiness_protocol 1")
    if str(data.get("status") or "") != "candidate-review":
        raise ChangeLifecycleError(
            "user review can only be recorded in candidate-review state"
        )
    user_review = data.setdefault("user_review", {})
    user_review.update(
        {
            "status": decision,
            "evidence": evidence.strip(),
            "reviewed_at": now_iso(),
        }
    )
    if decision == "changes-requested":
        data["status"] = "implementing"
        completion = data.setdefault("completion", {})
        completion["implementation_complete"] = False
        completion["ready_for_user_review"] = False
        readiness = data.setdefault("readiness", {})
        readiness["status"] = "stale"
    atomic_write_yaml(ref.yaml_path, data)
    return str(data.get("status"))
