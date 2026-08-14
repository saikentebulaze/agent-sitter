"""Provider-era facade for the preserved Harness closure implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import _harness_impl as _impl
from _harness_impl import *  # noqa: F401,F403
from decision_authority import authority_projection, human_decision_digest
from knowledge_gate import validate_project_knowledge_for_change
from project_context import ProjectContext
from review_transaction import record_review as _record_review


_base_command_review_packet = _impl.command_review_packet
_base_command_render_knowledge = _impl.command_render_knowledge
_base_command_promote_knowledge = _impl.command_promote_knowledge


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


def command_validate(
    context: ProjectContext,
    change: Path,
    strict_symbols: bool,
) -> None:
    _impl.run_change_validator(context, change)

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


_impl.command_validate = command_validate
_impl.command_review_packet = command_review_packet
_impl.record_review = record_review
_impl.command_render_knowledge = command_render_knowledge
_impl.command_promote_knowledge = command_promote_knowledge


if __name__ == "__main__":
    _impl.main()
