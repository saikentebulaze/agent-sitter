"""Provider-era facade for the preserved Harness closure implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _harness_impl as _impl
from _harness_impl import *  # noqa: F401,F403
from change_lifecycle import (
    ChangeLifecycleError,
    advance_change,
    build_change_dashboard,
    record_user_review,
)
from decision_authority import authority_projection, human_decision_digest
from knowledge_gate import validate_project_knowledge_for_change
from project_context import ProjectContext, resolve_project_context
from readiness import (
    ReadinessError,
    finalize_readiness,
    freeze_readiness_contract,
    record_readiness,
    validate_readiness_contract,
)
from review_transaction import record_review as _record_review


_base_command_review_packet = _impl.command_review_packet
_base_command_render_knowledge = _impl.command_render_knowledge
_base_command_promote_knowledge = _impl.command_promote_knowledge
_base_command_status = _impl.command_status


def _assurance_snapshot(change: Path) -> dict[str, str]:
    data = _impl.load_yaml(change / "change.yaml")
    risk = data.get("risk") or {}
    semantic = str(risk.get("semantic") or "").strip().lower()
    repository = str(risk.get("repository_change") or "").strip().lower()
    allowed = {"low", "medium", "high", "critical"}
    if semantic not in allowed or repository not in allowed:
        raise _impl.ReviewTransactionError("Change risk is invalid before review")
    return {
        "semantic": semantic,
        "repository_change": repository,
    }


def _current_authority(change: Path) -> dict:
    data = _impl.load_yaml(change / "change.yaml")
    try:
        return authority_projection(data)
    except ValueError as error:
        raise _impl.ReviewTransactionError(str(error)) from error


def command_review_packet(
    context: ProjectContext,
    change: Path,
    reviewer_name: str,
    elevated_authorization_ref: str | None,
) -> None:
    """Create review input that freezes assurance and explicit user decisions."""

    data = _impl.load_yaml(change / "change.yaml")
    if data.get("candidate_readiness_protocol") == 1:
        try:
            validate_readiness_contract(data)
        except ReadinessError as error:
            raise _impl.ReviewTransactionError(str(error)) from error
        readiness = data.get("readiness") or {}
        if readiness.get("status") != "pass":
            raise _impl.ReviewTransactionError(
                "Candidate Readiness must pass before independent readiness review"
            )
        methodology = data.get("methodology") or {}
        if methodology.get("test_cleanup_protocol") == 1 and (
            methodology.get("test_cleanup_complete") is not True
            or not str(methodology.get("test_cleanup_evidence") or "").strip()
        ):
            raise _impl.ReviewTransactionError(
                "test finalization must complete before independent readiness review"
            )

    _base_command_review_packet(
        context,
        change,
        reviewer_name,
        elevated_authorization_ref,
    )
    packet_path = change / "review-request.yaml"
    packet = _impl.load_yaml(packet_path)
    authority = _current_authority(change)
    packet["assurance_snapshot"] = _assurance_snapshot(change)
    packet["decision_authority"] = authority
    packet.setdefault("input_snapshot", {})["human_decisions_sha256"] = authority["sha256"]
    packet["instructions"] = (
        str(packet.get("instructions") or "")
        + " Resolved user decisions in decision_authority are authoritative. "
        "Agent recommendations are advisory only. If Design, implementation diff, "
        "Verification, or proposed durable Knowledge contradicts a user decision, "
        "return BLOCK rather than silently reverting to the recommendation."
    )
    _impl.write_yaml(packet_path, packet)


def _validate_recorded_authority(change: Path) -> None:
    data = _impl.load_yaml(change / "change.yaml")
    authority = _current_authority(change)
    review = data.get("review") or {}
    if str(review.get("status") or "pending") == "pending":
        return
    execution = review.get("execution") or {}
    snapshot = execution.get("input_snapshot") or {}
    expected = str(snapshot.get("human_decisions_sha256") or "")
    if authority["status"] == "authoritative" and not expected:
        raise _impl.ReviewTransactionError(
            "recorded review has no authoritative human decision snapshot"
        )
    if expected and expected != authority["sha256"]:
        raise _impl.ReviewTransactionError(
            "recorded review is stale; authoritative human decisions changed"
        )


def record_review(
    context: ProjectContext,
    change: Path,
    artifact: str | Path,
    *,
    architecture: str,
    scope: str,
    numerical_evidence: str,
    evidence_ref: str,
    remediation_route: str | None = None,
):
    packet_path = change / "review-request.yaml"
    if packet_path.is_file():
        packet = _impl.load_yaml(packet_path)
        expected = packet.get("assurance_snapshot")
        if not isinstance(expected, dict):
            raise _impl.ReviewTransactionError(
                "review request has no production assurance snapshot"
            )
        actual = _assurance_snapshot(change)
        normalized = {
            "semantic": str(expected.get("semantic") or "").strip().lower(),
            "repository_change": str(
                expected.get("repository_change") or ""
            ).strip().lower(),
        }
        if normalized != actual:
            raise _impl.ReviewTransactionError(
                "review request is stale; production assurance changed after review started"
            )

        expected_authority = packet.get("decision_authority")
        current_authority = _current_authority(change)
        if not isinstance(expected_authority, dict):
            raise _impl.ReviewTransactionError(
                "review request has no human decision authority projection"
            )
        if str(expected_authority.get("sha256") or "") != current_authority["sha256"]:
            raise _impl.ReviewTransactionError(
                "review request is stale; authoritative human decisions changed after review started"
            )
    else:
        _validate_recorded_authority(change)

    return _record_review(
        context,
        change,
        artifact,
        architecture=architecture,
        scope=scope,
        numerical_evidence=numerical_evidence,
        evidence_ref=evidence_ref,
        remediation_route=remediation_route,
    )


def command_render_knowledge(context: ProjectContext, change: Path) -> None:
    _base_command_render_knowledge(context, change)
    data = _impl.load_yaml(change / "change.yaml")
    data.setdefault("knowledge_sync", {})["human_decisions_sha256"] = human_decision_digest(data)
    _impl.write_yaml(change / "change.yaml", data)


def command_promote_knowledge(
    context: ProjectContext,
    change: Path,
    reviewed_by: str,
    evidence: str,
) -> None:
    data = _impl.load_yaml(change / "change.yaml")
    sync = data.get("knowledge_sync") or {}
    expected = str(sync.get("human_decisions_sha256") or "")
    authority = _current_authority(change)
    actual = human_decision_digest(data)
    if authority["status"] == "authoritative" and not expected:
        raise _impl.ReviewTransactionError(
            "knowledge candidate has no authoritative human decision snapshot; render it again"
        )
    if expected and expected != actual:
        raise _impl.ReviewTransactionError(
            "knowledge candidate is stale; authoritative human decisions changed"
        )
    _base_command_promote_knowledge(context, change, reviewed_by, evidence)


def _validate_v62_gate(change: Path, data: dict) -> None:
    validate_readiness_contract(data)
    status = str(data.get("status") or "")
    completion = data.get("completion") or {}
    user_review = data.get("user_review") or {}
    if status == "candidate-review":
        if completion.get("implementation_complete") is not True:
            raise ReadinessError("candidate-review requires implementation_complete")
        if completion.get("ready_for_user_review") is not True:
            raise ReadinessError("candidate-review requires ready_for_user_review")
    if user_review.get("status") in {"approved", "changes-requested", "not-required"}:
        if not str(user_review.get("evidence") or "").strip():
            raise ReadinessError("decided user_review requires evidence")
        if not str(user_review.get("reviewed_at") or "").strip():
            raise ReadinessError("decided user_review requires reviewed_at")
    if status in {"verifying", "syncing", "ready-to-archive", "archived"}:
        if user_review.get("status") not in {"approved", "not-required"}:
            raise ReadinessError("user acceptance is required before final verification")


def command_validate(
    context: ProjectContext,
    change: Path,
    strict_symbols: bool,
) -> None:
    data = _impl.load_yaml(change / "change.yaml")
    if data.get("candidate_readiness_protocol") == 1 and data.get("status") == "candidate-review":
        _validate_v62_gate(change, data)
    else:
        _impl.run_change_validator(context, change)
        if data.get("candidate_readiness_protocol") == 1:
            _validate_v62_gate(change, data)

    link_errors = _impl.validate_markdown_links(change, context.project_root)
    if link_errors:
        for error in link_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    validate_project_knowledge_for_change(context, change)

    warnings = _impl.symbol_warnings(change, context.project_root)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if strict_symbols and warnings:
        raise SystemExit(2)
    print("change_consistency: valid")


def command_status(context: ProjectContext, change: Path) -> None:
    data = _impl.load_yaml(change / "change.yaml")
    if data.get("candidate_readiness_protocol") == 1:
        print(json.dumps(build_change_dashboard(context, change), ensure_ascii=False, indent=2))
        return
    _base_command_status(context, change)


def _run_v62_command(argv: list[str]) -> bool:
    commands = {
        "freeze-readiness",
        "record-readiness",
        "finalize-readiness",
        "advance",
        "user-review",
    }
    command = next((value for value in argv if value in commands), None)
    if command is None:
        return False

    parser = argparse.ArgumentParser(description="Sitter V6.2 Candidate Readiness commands")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze-readiness")
    freeze.add_argument("change")

    record = subparsers.add_parser("record-readiness")
    record.add_argument("change")
    record.add_argument("--criterion", required=True)
    record.add_argument("--result", choices=("pass", "fail"), required=True)
    record.add_argument("--command-or-entry", required=True)
    record.add_argument("--evidence", required=True)
    record.add_argument("--observed")

    finalize = subparsers.add_parser("finalize-readiness")
    finalize.add_argument("change")

    advance = subparsers.add_parser("advance")
    advance.add_argument("change")

    user = subparsers.add_parser("user-review")
    user.add_argument("change")
    user.add_argument(
        "--decision",
        choices=("approved", "changes-requested", "not-required"),
        required=True,
    )
    user.add_argument("--evidence", required=True)

    args = parser.parse_args(argv)
    context = resolve_project_context(args.project)
    try:
        if args.command == "freeze-readiness":
            print(f"readiness contract frozen: {freeze_readiness_contract(context, args.change)}")
        elif args.command == "record-readiness":
            record_readiness(
                context,
                args.change,
                criterion_id=args.criterion,
                result=args.result,
                command_or_entry=args.command_or_entry,
                evidence=args.evidence,
                observed=args.observed,
            )
            print(f"recorded readiness: {args.criterion}")
        elif args.command == "finalize-readiness":
            print(json.dumps(finalize_readiness(context, args.change), ensure_ascii=False, indent=2))
        elif args.command == "advance":
            print(f"advanced: {advance_change(context, args.change)}")
        elif args.command == "user-review":
            print(
                f"user review recorded: {record_user_review(context, args.change, decision=args.decision, evidence=args.evidence)}"
            )
    except (ReadinessError, ChangeLifecycleError, ValueError) as error:
        raise SystemExit(str(error)) from error
    return True


_impl.command_validate = command_validate
_impl.command_review_packet = command_review_packet
_impl.record_review = record_review
_impl.command_render_knowledge = command_render_knowledge
_impl.command_promote_knowledge = command_promote_knowledge
_impl.command_status = command_status


if __name__ == "__main__":
    if not _run_v62_command(sys.argv[1:]):
        _impl.main()
