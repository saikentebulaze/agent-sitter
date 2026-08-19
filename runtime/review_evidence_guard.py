from __future__ import annotations

from pathlib import Path

import yaml

from provider_attestation import validate_provider_attestation


class ReviewEvidenceError(ValueError):
    pass


def _load_yaml(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ReviewEvidenceError(f"{label} is missing: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ReviewEvidenceError(f"cannot read {label}: {path}: {error}") from error
    if not isinstance(data, dict):
        raise ReviewEvidenceError(f"{label} must be a YAML mapping: {path}")
    return data


def _project_path(project_root: Path, value: object, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ReviewEvidenceError(f"{label} is required")
    raw = Path(text)
    path = raw.resolve() if raw.is_absolute() else (project_root / raw).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise ReviewEvidenceError(f"{label} escapes the project: {text}") from error
    return path


def validate_current_protocol2_review(change: Path, data: dict) -> None:
    """Re-prove the current Protocol-2 review from persisted runtime evidence.

    Shape validation in ``change.yaml`` is not sufficient for a V6.2 closure
    gate: a user or Agent could otherwise fabricate plausible Provider/session
    metadata by hand.  The current review must point back to the archived frozen
    request and to a real Provider attestation that validates against that exact
    request.

    Historical superseded rounds are not revalidated here.  The current review
    is the assurance artifact used by Candidate/final lifecycle gates; older
    rounds remain immutable provenance but need not keep runtime staging alive
    forever.
    """

    review = data.get("review") or {}
    execution = review.get("execution") or {}
    if int(execution.get("review_protocol") or 1) != 2:
        return

    round_number = execution.get("round")
    if not isinstance(round_number, int) or round_number < 1:
        raise ReviewEvidenceError("Protocol 2 review has an invalid round")

    project_root = change.resolve().parents[2]
    request_path = change / "reviews" / f"round-{round_number}.request.yaml"
    request = _load_yaml(request_path, "archived Protocol 2 review request")
    if int(request.get("review_protocol") or 1) != 2:
        raise ReviewEvidenceError("archived review request is not Protocol 2")
    if request.get("round") != round_number:
        raise ReviewEvidenceError("archived review request round does not match current review")
    if str(request.get("change_id") or "") != str(data.get("id") or change.name):
        raise ReviewEvidenceError("archived review request change_id does not match current Change")

    provider = str(execution.get("provider") or "")
    request_provider = str((request.get("runtime") or {}).get("provider") or "")
    if provider != request_provider:
        raise ReviewEvidenceError("current review Provider differs from the archived request")

    requested = request.get("requested_profile") or {}
    requested_role = str(requested.get("role_id") or requested.get("agent") or "")
    if str(execution.get("agent") or "") != requested_role:
        raise ReviewEvidenceError("current reviewer role differs from the archived request")

    runtime_execution = request.get("runtime_execution") or {}
    for key, execution_key in (
        ("session_ref", "session_ref"),
        ("attestation_ref", "attestation_ref"),
        ("evidence_ref", "runtime_evidence_ref"),
        ("execution_method", "runtime_method"),
        ("execution_request_sha256", "execution_request_sha256"),
    ):
        if str(runtime_execution.get(key) or "") != str(execution.get(execution_key) or ""):
            raise ReviewEvidenceError(
                f"current review {execution_key} differs from the archived runtime execution"
            )

    session_ref = str(execution.get("session_ref") or "")
    if not session_ref or str(execution.get("evidence_ref") or "") != session_ref:
        raise ReviewEvidenceError("Protocol 2 review has an invalid session/evidence binding")

    attestation_path = _project_path(
        project_root, execution.get("attestation_ref"), "review attestation_ref"
    )
    evidence_path = _project_path(
        project_root, execution.get("runtime_evidence_ref"), "review runtime_evidence_ref"
    )
    output_path = _project_path(
        project_root, execution.get("output_ref"), "review output_ref"
    )
    if not evidence_path.is_file():
        raise ReviewEvidenceError(f"review runtime evidence is missing: {evidence_path}")
    if not output_path.is_file():
        raise ReviewEvidenceError(f"review output is missing: {output_path}")

    attestation = _load_yaml(attestation_path, "Protocol 2 runtime attestation")
    attested_execution = attestation.get("execution") or {}
    if str(attested_execution.get("session_ref") or "") != session_ref:
        raise ReviewEvidenceError("runtime attestation session does not match current review")
    if str(attested_execution.get("method") or "") != str(execution.get("runtime_method") or ""):
        raise ReviewEvidenceError("runtime attestation method does not match current review")

    try:
        normalized = validate_provider_attestation(request, attestation)
    except (ValueError, RuntimeError, OSError) as error:
        raise ReviewEvidenceError(f"Protocol 2 runtime attestation is invalid: {error}") from error
    if normalized.provider != provider:
        raise ReviewEvidenceError("normalized runtime Provider does not match current review")
    if normalized.role_id != requested_role:
        raise ReviewEvidenceError("normalized runtime role does not match the frozen reviewer")
    if normalized.raw_evidence_ref and normalized.raw_evidence_ref != session_ref:
        raise ReviewEvidenceError("normalized runtime session does not match current review")
