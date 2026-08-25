from __future__ import annotations

from pathlib import Path
from typing import Callable

from change_budget_preflight import (
    ChangeBudgetPreflightError,
    validate_change_budget_preflight,
)
from change_lifecycle import (
    ChangeLifecycleError,
    _load as _load_lifecycle,
    _reprove_current_review,
    _require_candidate_review_preflight,
    advance_change,
)
from evidence_projection import EvidenceProjectionError, render_evidence
from finalize_tests import (
    TestHygieneError,
    _parse_classifications,
    finalize_tests,
)
from project_context import ProjectContext
from readiness import (
    ReadinessError,
    finalize_readiness,
    record_readiness_batch,
)
from reference_resolver import resolve_change_ref
from review_runner import AtomicReviewError, run_atomic_review


class PrepareCandidateError(RuntimeError):
    pass


_POST_CANDIDATE_STATUSES = {"verifying", "syncing", "ready-to-archive", "archived"}


def _resume_existing_candidate(context: ProjectContext, ref, data: dict) -> dict:
    """Re-prove an unchanged Candidate Human Stop without launching another Reviewer."""

    try:
        _reprove_current_review(ref.root, data)
        _require_candidate_review_preflight(context, data)
    except ChangeLifecycleError as error:
        raise PrepareCandidateError(str(error)) from error

    user_status = str((data.get("user_review") or {}).get("status") or "pending")
    if user_status in {"approved", "not-required"}:
        raise PrepareCandidateError(
            "Candidate is already accepted; continue with complete-after-approval"
        )
    if user_status != "pending":
        raise PrepareCandidateError(
            f"Candidate Human Stop has unexpected user_review status: {user_status}"
        )

    readiness = data.get("readiness") or {}
    methodology = data.get("methodology") or {}
    render_evidence(context, ref.root)
    return {
        "change": ref.id,
        "readiness": {
            "status": readiness.get("status"),
            "production_snapshot_sha256": (
                readiness.get("production_snapshot") or {}
            ).get("sha256"),
            "criteria": sorted(
                str(item.get("criterion_id") or "")
                for item in readiness.get("latest_results") or []
                if isinstance(item, dict)
            ),
        },
        "test_finalization_ref": methodology.get("test_cleanup_evidence"),
        "review": data.get("review") or {},
        "status": "candidate-review",
        "idempotent": True,
    }


def prepare_candidate(
    context: ProjectContext,
    change_value: str | Path,
    *,
    readiness_batch: list[dict] | None = None,
    retained: list[str] | None = None,
    preexisting: list[str] | None = None,
    role: str = "maintainer_reviewer",
    elevated_authorization_ref: str | None = None,
    executor_factory: Callable[[str], Callable] | None = None,
    role_runner=None,  # deterministic test seam; production leaves this unset
) -> dict:
    ref = resolve_change_ref(context, change_value)
    current = _load_lifecycle(ref.yaml_path)
    current_status = str(current.get("status") or "")
    if current_status == "candidate-review":
        if readiness_batch is not None:
            raise PrepareCandidateError(
                "Candidate is already prepared; do not resubmit readiness evidence at the Human Stop"
            )
        return _resume_existing_candidate(context, ref, current)
    if current_status in _POST_CANDIDATE_STATUSES:
        raise PrepareCandidateError(
            f"Candidate already progressed to {current_status}; use complete-after-approval or recovery commands"
        )

    try:
        if readiness_batch is not None:
            record_readiness_batch(context, ref.root, readiness_batch)
        readiness = finalize_readiness(context, ref.root)
        retained_map = _parse_classifications(
            context,
            list(retained or []),
            "--retain",
        )
        preexisting_map = _parse_classifications(
            context,
            list(preexisting or []),
            "--preexisting",
        )
        evidence = finalize_tests(
            context,
            ref.root,
            retained=retained_map,
            preexisting=preexisting_map,
        )
        # Scope mistakes are deterministic facts. Reject them before spending an
        # independent Reviewer round.
        validate_change_budget_preflight(context, ref.root)
        # Refresh human-readable projections before the reviewer starts. The
        # projection lives under `changes/` and therefore cannot mutate the
        # Production Snapshot that the review freezes.
        render_evidence(context, ref.root)
        review = run_atomic_review(
            context,
            ref.root,
            role=role,
            elevated_authorization_ref=elevated_authorization_ref,
            executor_factory=executor_factory,
            role_runner=role_runner,
        )
    except (
        ReadinessError,
        TestHygieneError,
        ChangeBudgetPreflightError,
        EvidenceProjectionError,
        AtomicReviewError,
        ValueError,
    ) as error:
        raise PrepareCandidateError(str(error)) from error

    result = {
        "change": ref.id,
        "readiness": readiness,
        "test_finalization_ref": evidence.relative_to(context.project_root).as_posix(),
        "review": review,
        "status": None,
        "idempotent": False,
    }
    if review.get("status") == "block":
        result["status"] = (
            "implementation-blocked"
            if review.get("remediation_route") == "implementation"
            else "awaiting-production-design"
        )
        return result

    try:
        result["status"] = advance_change(context, ref.root)
    except ChangeLifecycleError as error:
        raise PrepareCandidateError(str(error)) from error
    return result
