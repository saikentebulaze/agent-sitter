from __future__ import annotations

from pathlib import Path

import yaml

from change_validation import ChangeValidationError, validate_change_in_process
from project_context import ProjectContext
from readiness import ReadinessError, freeze_readiness_contract
from reference_resolver import resolve_change_ref
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import now_iso


class ImplementationEntryError(RuntimeError):
    pass


_ENTRY_STATUSES = {"proposed", "designed", "approved", "implementing"}


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ImplementationEntryError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ImplementationEntryError(f"expected YAML mapping: {path}")
    return data


def _require_planning_scope(data: dict) -> None:
    budget = data.get("change_budget") or {}
    allowed_modules = budget.get("allowed_modules") or []
    allowed_files = budget.get("allowed_files") or []
    if not isinstance(allowed_modules, list) or not isinstance(allowed_files, list):
        raise ImplementationEntryError("Change Budget allowed_modules/allowed_files must be lists")
    if not allowed_modules and not allowed_files:
        raise ImplementationEntryError(
            "Change Budget must define at least one allowed module or file before implementation"
        )


def _require_human_decisions_resolved(data: dict) -> None:
    human = data.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    status = str(assessment.get("status") or "pending")
    if status in {"pending", "required"}:
        raise ImplementationEntryError(
            "material human design decisions must be resolved before implementation"
        )
    if status not in {"not-required", "resolved"}:
        raise ImplementationEntryError(
            f"invalid human decision assessment before implementation: {status}"
        )


def _apply_or_require_approval(data: dict, approved_by: str | None) -> None:
    risk = data.get("risk") or {}
    repository_risk = str(risk.get("repository_change") or "low").strip().lower()
    approval = data.setdefault("approval", {})
    required = bool(approval.get("required", False)) or repository_risk in {
        "high",
        "critical",
    }
    supplied = str(approved_by or "").strip()

    if supplied:
        if not required:
            raise ImplementationEntryError(
                "--approved-by is only valid when Change approval is required"
            )
        approval["required"] = True
        approval["status"] = "approved"
        approval["approved_by"] = supplied
        approval["approved_at"] = now_iso()
        return

    status = str(approval.get("status") or "not-required")
    if required:
        if status != "approved":
            raise ImplementationEntryError(
                "Change approval is required before implementation; after explicit human approval rerun begin-implementation with --approved-by"
            )
        if not str(approval.get("approved_by") or "").strip() or not str(
            approval.get("approved_at") or ""
        ).strip():
            raise ImplementationEntryError(
                "approved Change is missing approved_by/approved_at provenance"
            )
    elif status not in {"not-required", "approved"}:
        raise ImplementationEntryError(
            f"invalid non-required Change approval state: {status}"
        )


def begin_implementation(
    context: ProjectContext,
    change_value: str | Path,
    *,
    approved_by: str | None = None,
) -> dict:
    """Close the pre-implementation planning states without manual YAML edits.

    The transaction owns ``proposed -> designed -> approved -> implementing``
    for a new V6.3 Change. It freezes the Readiness Contract immediately before
    entering implementation so the Agent cannot record implementation evidence
    against an unfrozen contract. HIGH/CRITICAL repository changes still require
    explicit approval provenance; the transaction never invents it.
    """

    ref = resolve_change_ref(context, change_value)
    original = ref.yaml_path.read_bytes()
    data = _load(ref.yaml_path)
    status = str(data.get("status") or "")
    if data.get("candidate_readiness_protocol") != 1:
        raise ImplementationEntryError(
            "begin-implementation requires candidate_readiness_protocol 1"
        )
    if status not in _ENTRY_STATUSES:
        raise ImplementationEntryError(
            f"begin-implementation cannot run from {status or '<missing>'}"
        )

    if status == "implementing":
        if approved_by is not None:
            raise ImplementationEntryError(
                "Change is already implementing; do not resubmit implementation approval"
            )
        try:
            validate_change_in_process(ref.root)
        except ChangeValidationError as error:
            raise ImplementationEntryError(str(error)) from error
        readiness = data.get("readiness") or {}
        return {
            "change": ref.id,
            "status": "implementing",
            "transitions": [],
            "readiness_contract_sha256": readiness.get("contract_sha256"),
            "idempotent": True,
        }

    _require_planning_scope(data)
    _require_human_decisions_resolved(data)
    _apply_or_require_approval(data, approved_by)

    completion = data.get("completion") or {}
    if completion.get("implementation_complete") is True:
        raise ImplementationEntryError(
            "begin-implementation cannot start after implementation was already marked complete"
        )

    transitions: list[str] = []
    try:
        if status == "proposed":
            data["status"] = "designed"
            atomic_write_yaml(ref.yaml_path, data)
            transitions.append("designed")
            status = "designed"
        if status == "designed":
            data["status"] = "approved"
            atomic_write_yaml(ref.yaml_path, data)
            transitions.append("approved")
            status = "approved"

        # Freeze after planning/approval and immediately before implementation.
        contract_sha = freeze_readiness_contract(context, ref.root)
        data = _load(ref.yaml_path)
        data["status"] = "implementing"
        completion = data.setdefault("completion", {})
        completion["implementation_complete"] = False
        completion["ready_for_user_review"] = False
        atomic_write_yaml(ref.yaml_path, data)
        transitions.append("implementing")
        validate_change_in_process(ref.root)
    except (ReadinessError, ChangeValidationError, ValueError, OSError) as error:
        atomic_write_text(ref.yaml_path, original.decode("utf-8"))
        raise ImplementationEntryError(str(error)) from error
    except BaseException:
        atomic_write_text(ref.yaml_path, original.decode("utf-8"))
        raise

    return {
        "change": ref.id,
        "status": "implementing",
        "transitions": transitions,
        "readiness_contract_sha256": contract_sha,
        "idempotent": False,
    }
