from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Callable

import yaml

from decision_authority import authority_projection
from production_snapshot import production_review_diff, production_snapshot_sha256
from provider_role_runner import (
    ProviderRoleRunnerError,
    RoleRunResult,
    build_role_packet,
    run_readonly_packet,
)
from project_context import ProjectContext
from readiness import ReadinessError, validate_readiness_contract
from reference_resolver import resolve_change_ref, resolve_task_ref
from review_transaction import (
    ReviewTransactionError,
    atomic_write_text,
    atomic_write_yaml,
    current_snapshot,
    project_relative,
    record_review,
)
from review_verdict import ReviewVerdictError, parse_review_verdict


class AtomicReviewError(RuntimeError):
    pass


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise AtomicReviewError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise AtomicReviewError(f"expected YAML mapping: {path}")
    return data


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _preflight(change: Path, data: dict) -> None:
    if data.get("candidate_readiness_protocol") != 1:
        raise AtomicReviewError("review --run is only available for activated V6.2 Changes")
    try:
        validate_readiness_contract(data)
    except ReadinessError as error:
        raise AtomicReviewError(str(error)) from error
    readiness = data.get("readiness") or {}
    if readiness.get("status") != "pass":
        raise AtomicReviewError("Candidate Readiness must pass before review --run")
    methodology = data.get("methodology") or {}
    if methodology.get("test_cleanup_protocol") == 1:
        if methodology.get("test_cleanup_complete") is not True:
            raise AtomicReviewError("test finalization is incomplete")
        evidence_ref = str(methodology.get("test_cleanup_evidence") or "").strip()
        if not evidence_ref or not (change / "test-finalization.yaml").is_file():
            raise AtomicReviewError("test finalization evidence is missing")
    human = data.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    if str(assessment.get("status") or "pending") in {"pending", "required"}:
        raise AtomicReviewError("material human design decisions remain unresolved")
    if (change / "review-request.yaml").exists():
        raise AtomicReviewError("pending review request already exists")


def _review_message(context: ProjectContext, change: Path, packet_ref: str) -> str:
    rel = project_relative(context, change)
    return f"""Perform the frozen Sitter Candidate Readiness Review described by {packet_ref}.

Read only what is needed from the frozen request and these inputs under {rel}:
- proposal.md
- design.md
- tasks.md
- verification.md
- change.yaml
- test-finalization.yaml
- `inputs.production_diff` from the request; this is the Harness-frozen readable production/test diff

Judge Architecture, Scope, and Numerical Evidence against the approved Design, Change Budget, authoritative human decisions, and Readiness Contract. Check that representative evidence actually exercises the target business path. Do not write or modify project files.

Return concise findings followed by exactly one final YAML block:
```yaml
sitter_review:
  architecture: pass|warn|block
  scope: pass|warn|block
  numerical_evidence: pass|warn|block
  remediation_route: implementation|awaiting-production-design|null
```
Use `implementation` only when a BLOCK is deterministically repairable inside already approved semantics/scope. Use `awaiting-production-design` when a new semantic, scope, acceptance, or authoritative user decision is required.
"""


def _build_request(
    context: ProjectContext,
    change: Path,
    data: dict,
    *,
    role: str,
    elevated_authorization_ref: str | None,
) -> tuple[dict, str]:
    task_id = str(data.get("task_id") or data.get("source_task_id") or "").strip()
    if not task_id:
        raise AtomicReviewError("V6.2 Change has no task_id for Provider-bound review")
    try:
        role_packet, _ = build_role_packet(context, task_id, role=role)
    except (ProviderRoleRunnerError, ValueError) as error:
        raise AtomicReviewError(str(error)) from error
    requested = role_packet.get("requested_profile") or {}
    if role == "deep_reviewer" and not elevated_authorization_ref:
        raise AtomicReviewError("deep review requires elevated authorization evidence")

    history = data.get("review_history") or []
    if not isinstance(history, list):
        raise AtomicReviewError("review_history must be a list")
    round_number = len(history) + 1
    output = change / "reviews" / f"round-{round_number}.md"
    if output.exists():
        raise AtomicReviewError(f"review output already exists: {output}")

    snapshot = current_snapshot(context, change)
    input_snapshot = {
        "snapshot_protocol": 2,
        **{
            key: snapshot[key]
            for key in (
                "production_sha256",
                "design_sha256",
                "tasks_sha256",
                "change_budget_sha256",
                "human_decisions_sha256",
                "readiness_contract_sha256",
                "readiness_evidence_sha256",
                "test_finalization_sha256",
            )
        },
    }
    missing = [
        key
        for key, value in input_snapshot.items()
        if key != "snapshot_protocol" and not str(value or "").strip()
    ]
    if missing:
        raise AtomicReviewError("review snapshot is incomplete: " + ", ".join(missing))

    # Freeze a readable diff for Providers such as Claude whose governed child
    # deliberately has no Bash tool. Creating the artifact under `changes/`
    # must not affect the Production Snapshot; verify that invariant here.
    production_before = str(input_snapshot["production_sha256"])
    diff_text = production_review_diff(context.project_root)
    diff_path = change / "reviews" / f"round-{round_number}.input.diff"
    atomic_write_text(diff_path, diff_text)
    production_after = production_snapshot_sha256(context.project_root)
    if production_after != production_before:
        diff_path.unlink(missing_ok=True)
        raise AtomicReviewError(
            "production/test state changed while freezing the reviewer diff"
        )
    diff_ref = project_relative(context, diff_path)
    diff_sha256 = _text_sha256(diff_text)

    try:
        authority = authority_projection(data)
    except ValueError as error:
        raise AtomicReviewError(str(error)) from error
    packet = {
        "schema_version": 2,
        "review_protocol": 2,
        "project_root": str(context.project_root.resolve()),
        "change_id": data.get("id") or change.name,
        "task_id": task_id,
        "round": round_number,
        "reviewer": {
            "agent": str(requested.get("role_id") or requested.get("agent") or ""),
            "model": str(requested.get("model_selector") or requested.get("model") or ""),
            "tier": str(requested.get("model_grade") or requested.get("tier") or ""),
        },
        "method": "provider-managed-readonly",
        "runtime": role_packet["runtime"],
        "requested_profile": requested,
        "output_ref": project_relative(context, output),
        "elevated_authorization_ref": elevated_authorization_ref,
        "input_snapshot": input_snapshot,
        "decision_authority": authority,
        "production_diff": {
            "ref": diff_ref,
            "sha256": diff_sha256,
            "production_sha256": production_before,
        },
        "inputs": {
            name.removesuffix(".md").replace("-", "_"): project_relative(
                context, change / name
            )
            for name in ("proposal.md", "design.md", "tasks.md", "verification.md")
        },
    }
    packet["inputs"]["production_diff"] = diff_ref
    request_path = change / "review-request.yaml"
    packet_ref = project_relative(context, request_path)
    packet["instructions"] = _review_message(context, change, packet_ref)
    return packet, task_id


def _validate_frozen_production_input(
    context: ProjectContext,
    packet: dict,
) -> None:
    production = packet.get("production_diff") or {}
    ref = str(production.get("ref") or "").strip()
    expected_diff = str(production.get("sha256") or "").strip()
    expected_production = str(production.get("production_sha256") or "").strip()
    if not ref or not expected_diff or not expected_production:
        raise AtomicReviewError("review request has incomplete frozen production diff metadata")
    path = (context.project_root / ref).resolve()
    try:
        path.relative_to(context.project_root.resolve())
    except ValueError as error:
        raise AtomicReviewError("frozen production diff escapes the project") from error
    if not path.is_file():
        raise AtomicReviewError("frozen production diff is missing")
    actual_diff = _text_sha256(path.read_text(encoding="utf-8"))
    if actual_diff != expected_diff:
        raise AtomicReviewError("frozen production diff changed during reviewer execution")
    if production_snapshot_sha256(context.project_root) != expected_production:
        raise AtomicReviewError("production/test state changed during reviewer execution")


def run_atomic_review(
    context: ProjectContext,
    change_value: str | Path,
    *,
    role: str = "maintainer_reviewer",
    elevated_authorization_ref: str | None = None,
    executor_factory: Callable[[str], Callable] | None = None,
    role_runner: Callable[[ProjectContext, dict, str], RoleRunResult] | None = None,
) -> dict:
    if role not in {"maintainer_reviewer", "deep_reviewer"}:
        raise AtomicReviewError(
            "atomic review role must be maintainer_reviewer or deep_reviewer"
        )
    change_ref = resolve_change_ref(context, change_value)
    change = change_ref.root
    data = _load(change_ref.yaml_path)
    _preflight(change, data)
    packet, task_id = _build_request(
        context,
        change,
        data,
        role=role,
        elevated_authorization_ref=elevated_authorization_ref,
    )
    request_path = change / "review-request.yaml"
    atomic_write_yaml(request_path, packet)

    task_ref = resolve_task_ref(context, task_id)
    attempt = uuid.uuid4().hex[:12]
    staging = (
        task_ref.root
        / "review-staging"
        / f"{change.name}-round-{packet['round']}-{attempt}"
    )
    output_path = staging / "reviewer-output.md"
    attestation_path = staging / "attestation.yaml"
    evidence_path = staging / "runtime-evidence.yaml"
    execution_request_sha256 = _canonical_sha256(packet)
    try:
        if role_runner is None:
            run = run_readonly_packet(
                context,
                packet,
                message=packet["instructions"],
                executor_factory=executor_factory,
            )
        else:
            run = role_runner(context, packet, packet["instructions"])
        _validate_frozen_production_input(context, packet)
        verdict = parse_review_verdict(run.output)
        atomic_write_text(output_path, run.output)
        atomic_write_yaml(attestation_path, run.attestation)
        atomic_write_yaml(evidence_path, run.evidence)

        current_packet = _load(request_path)
        if _canonical_sha256(current_packet) != execution_request_sha256:
            raise AtomicReviewError(
                "review request changed between freeze and Provider execution"
            )
        execution_method = str(
            (run.attestation.get("execution") or {}).get("method") or ""
        )
        current_packet["runtime_execution"] = {
            "provider": run.provider,
            "execution_method": execution_method,
            "session_ref": run.session_ref,
            "attestation_ref": project_relative(context, attestation_path),
            "evidence_ref": project_relative(context, evidence_path),
            "execution_request_sha256": execution_request_sha256,
        }
        atomic_write_yaml(request_path, current_packet)
        recorded, idempotent = record_review(
            context,
            change,
            output_path,
            architecture=str(verdict["architecture"]),
            scope=str(verdict["scope"]),
            numerical_evidence=str(verdict["numerical_evidence"]),
            evidence_ref=run.session_ref,
            remediation_route=verdict["remediation_route"],
        )
    except (
        ProviderRoleRunnerError,
        ReviewVerdictError,
        ReviewTransactionError,
        AtomicReviewError,
        ValueError,
        OSError,
    ) as error:
        request_path.unlink(missing_ok=True)
        raise AtomicReviewError(str(error)) from error

    return {
        "change": data.get("id") or change.name,
        "round": packet["round"],
        "provider": run.provider,
        "role": run.role_id,
        "status": verdict["overall"],
        "architecture": verdict["architecture"],
        "scope": verdict["scope"],
        "numerical_evidence": verdict["numerical_evidence"],
        "remediation_route": verdict["remediation_route"],
        "output_ref": project_relative(context, recorded),
        "attestation_ref": project_relative(context, attestation_path),
        "runtime_evidence_ref": project_relative(context, evidence_path),
        "idempotent": idempotent,
    }
