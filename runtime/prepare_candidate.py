from __future__ import annotations

from pathlib import Path
from typing import Callable

from change_budget_preflight import (
    ChangeBudgetPreflightError,
    validate_change_budget_preflight,
)
from change_lifecycle import ChangeLifecycleError, advance_change
from evidence_projection import EvidenceProjectionError, render_evidence
from finalize_tests import (
    TestHygieneError,
    _parse_classifications,
    finalize_tests,
)
from project_context import ProjectContext
from readiness import ReadinessError, finalize_readiness
from reference_resolver import resolve_change_ref
from review_runner import AtomicReviewError, run_atomic_review


class PrepareCandidateError(RuntimeError):
    pass


def prepare_candidate(
    context: ProjectContext,
    change_value: str | Path,
    *,
    retained: list[str] | None = None,
    preexisting: list[str] | None = None,
    role: str = "maintainer_reviewer",
    elevated_authorization_ref: str | None = None,
    executor_factory: Callable[[str], Callable] | None = None,
    role_runner=None,  # deterministic test seam; production leaves this unset
) -> dict:
    ref = resolve_change_ref(context, change_value)
    try:
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
        # Scope mistakes such as generated XLSX/CSV/binaries outside the
        # approved Change Budget are mechanical facts. Reject them before
        # spending an independent Reviewer round.
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
