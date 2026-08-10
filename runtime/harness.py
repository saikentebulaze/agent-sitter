"""Provider-era facade for the preserved Harness closure implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import _harness_impl as _impl
from _harness_impl import *  # noqa: F401,F403
from knowledge_gate import validate_project_knowledge_for_change
from project_context import ProjectContext
from review_transaction import record_review as _record_review


_base_command_review_packet = _impl.command_review_packet


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


def command_review_packet(
    context: ProjectContext,
    change: Path,
    reviewer_name: str,
    elevated_authorization_ref: str | None,
) -> None:
    """Create the preserved review packet, then freeze production assurance.

    Current Task work risk may have dropped to LOW cleanup by this point. Review
    follows the Change assurance floor, so the packet records that independently
    and record-review rejects later assurance drift.
    """

    _base_command_review_packet(
        context,
        change,
        reviewer_name,
        elevated_authorization_ref,
    )
    packet_path = change / "review-request.yaml"
    packet = _impl.load_yaml(packet_path)
    packet["assurance_snapshot"] = _assurance_snapshot(change)
    _impl.write_yaml(packet_path, packet)


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


if __name__ == "__main__":
    _impl.main()
