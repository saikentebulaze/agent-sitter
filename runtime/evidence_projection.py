from __future__ import annotations

from pathlib import Path

import yaml

from production_snapshot import production_snapshot_sha256
from project_context import ProjectContext
from reference_resolver import resolve_change_ref
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import now_iso


VERIFICATION_RESULTS = {"pass", "partial", "fail"}


class EvidenceProjectionError(ValueError):
    pass


def _load(path: Path) -> dict:
    if not path.is_file():
        raise EvidenceProjectionError(f"missing file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise EvidenceProjectionError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(data, dict):
        raise EvidenceProjectionError(f"expected YAML mapping: {path}")
    return data


def _cell(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|") or "—"


def _verification_status(results: list[dict]) -> str:
    if not results:
        return "pending"
    values = {str(item.get("result") or "") for item in results}
    if "fail" in values:
        return "fail"
    if "partial" in values:
        return "partial"
    return "pass"


def record_verification(
    context: ProjectContext,
    change_value: str | Path,
    *,
    result_id: str,
    kind: str,
    result: str,
    command_or_entry: str,
    evidence: str,
    observed: str | None = None,
    proves: str | None = None,
    does_not_prove: str | None = None,
) -> dict:
    if not result_id.strip() or not kind.strip():
        raise EvidenceProjectionError("verification id and kind are required")
    if result not in VERIFICATION_RESULTS:
        raise EvidenceProjectionError("verification result must be pass, partial, or fail")
    if not command_or_entry.strip() or not evidence.strip():
        raise EvidenceProjectionError("verification command/entry and evidence are required")

    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise EvidenceProjectionError(
            "structured record-verification is only available for activated V6.2 Changes"
        )
    if str(data.get("status") or "") not in {
        "verifying", "syncing", "ready-to-archive", "archived"
    }:
        raise EvidenceProjectionError(
            "final verification evidence may only be recorded after Candidate acceptance"
        )
    user_review = data.get("user_review") or {}
    if user_review.get("status") not in {"approved", "not-required"}:
        raise EvidenceProjectionError(
            "user acceptance is required before final verification evidence"
        )

    snapshot = production_snapshot_sha256(context.project_root)
    entry = {
        "id": result_id.strip(),
        "kind": kind.strip(),
        "command_or_entry": command_or_entry.strip(),
        "result": result,
        "checked_at": now_iso(),
        "evidence": evidence.strip(),
        "observed": observed.strip() if isinstance(observed, str) and observed.strip() else None,
        "proves": proves.strip() if isinstance(proves, str) and proves.strip() else None,
        "does_not_prove": (
            does_not_prove.strip()
            if isinstance(does_not_prove, str) and does_not_prove.strip()
            else None
        ),
        "production_snapshot_sha256": snapshot,
    }
    verification = data.setdefault("verification", {})
    previous = [
        item
        for item in verification.get("latest_results") or []
        if str(item.get("id") or "") != result_id.strip()
    ]
    results = [*previous, entry]
    verification["latest_results"] = results
    verification["status"] = _verification_status(results)
    atomic_write_yaml(ref.yaml_path, data)
    render_evidence(context, ref.root)
    return entry


def _readiness_table(data: dict) -> list[str]:
    readiness = data.get("readiness") or {}
    criteria = {
        str(item.get("id") or ""): item
        for item in readiness.get("criteria") or []
        if isinstance(item, dict)
    }
    results = {
        str(item.get("criterion_id") or ""): item
        for item in readiness.get("latest_results") or []
        if isinstance(item, dict)
    }
    lines = [
        "| Criterion | Kind | Result | Observed | Evidence |",
        "|---|---|---|---|---|",
    ]
    for criterion_id, criterion in criteria.items():
        result = results.get(criterion_id) or {}
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(criterion_id),
                    _cell(criterion.get("kind")),
                    _cell(result.get("result") or "pending"),
                    _cell(result.get("observed")),
                    _cell(result.get("evidence")),
                )
            )
            + " |"
        )
    if len(lines) == 2:
        lines.append("| — | — | pending | — | — |")
    return lines


def _final_verification_table(data: dict) -> list[str]:
    results = (data.get("verification") or {}).get("latest_results") or []
    lines = [
        "| ID | Kind | Result | Command / Entry | Observed | Evidence | Proves | Does not prove |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| "
            + " | ".join(
                _cell(item.get(key))
                for key in (
                    "id",
                    "kind",
                    "result",
                    "command_or_entry",
                    "observed",
                    "evidence",
                    "proves",
                    "does_not_prove",
                )
            )
            + " |"
        )
    if len(lines) == 2:
        lines.append("| — | — | pending | — | — | — | — | — |")
    return lines


def _test_finalization(change: Path) -> list[str]:
    path = change / "test-finalization.yaml"
    if not path.is_file():
        return ["- Test finalization: pending"]
    payload = _load(path)
    decisions = payload.get("decisions") or []
    if not decisions:
        return ["- Test finalization: complete; no changed tests required classification."]
    lines = ["| Path | Classification | Reason |", "|---|---|---|"]
    for item in decisions:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_cell(item.get('path'))} | {_cell(item.get('classification'))} | {_cell(item.get('reason'))} |"
        )
    return lines


def render_verification(change: Path, data: dict) -> None:
    readiness = data.get("readiness") or {}
    review = data.get("review") or {}
    execution = review.get("execution") or {}
    user_review = data.get("user_review") or {}
    verification = data.get("verification") or {}
    text = "\n".join(
        [
            "# Verification",
            "",
            "> Generated from structured Sitter evidence. Do not maintain this file as a second source of truth.",
            "",
            "## Candidate Readiness",
            "",
            f"- Assurance class: `{_cell(readiness.get('assurance_class'))}`",
            f"- Status: `{_cell(readiness.get('status'))}`",
            f"- Production snapshot: `{_cell((readiness.get('production_snapshot') or {}).get('sha256'))}`",
            "",
            *_readiness_table(data),
            "",
            "## Test Finalization",
            "",
            *_test_finalization(change),
            "",
            "## Independent Review",
            "",
            f"- Overall: `{_cell(review.get('status'))}`",
            f"- Architecture: `{_cell(review.get('architecture'))}`",
            f"- Scope: `{_cell(review.get('scope'))}`",
            f"- Numerical Evidence: `{_cell(review.get('numerical_evidence'))}`",
            f"- Reviewer output: `{_cell(execution.get('output_ref'))}`",
            f"- Runtime evidence: `{_cell(execution.get('runtime_evidence_ref') or execution.get('evidence_ref'))}`",
            "",
            "## User Acceptance",
            "",
            f"- Status: `{_cell(user_review.get('status'))}`",
            f"- Evidence: {_cell(user_review.get('evidence'))}",
            "",
            "## Final Verification",
            "",
            f"- Overall status: `{_cell(verification.get('status'))}`",
            "",
            *_final_verification_table(data),
            "",
        ]
    )
    atomic_write_text(change / "verification.md", text)


def render_archive_summary(change: Path, data: dict) -> None:
    readiness = data.get("readiness") or {}
    review = data.get("review") or {}
    user_review = data.get("user_review") or {}
    verification = data.get("verification") or {}
    knowledge = data.get("knowledge_sync") or {}
    archive = data.get("archive") or {}
    text = "\n".join(
        [
            "# Archive Summary",
            "",
            "> Generated from authoritative Sitter state.",
            "",
            f"- Change: `{_cell(data.get('id'))}` — {_cell(data.get('title'))}",
            f"- Lifecycle status: `{_cell(data.get('status'))}`",
            f"- Candidate Readiness: `{_cell(readiness.get('status'))}`",
            f"- Independent review: `{_cell(review.get('status'))}`",
            f"- User acceptance: `{_cell(user_review.get('status'))}`",
            f"- Final verification: `{_cell(verification.get('status'))}`",
            f"- Knowledge: `{_cell(knowledge.get('status'))}`",
            f"- Experiment cleanup: `{_cell(archive.get('experiment_cleanup_complete'))}`",
            f"- Archive blockers: {_cell(', '.join(map(str, archive.get('blockers') or [])))}",
            "",
            "See `verification.md`, `reviews/`, and `test-finalization.yaml` for projected and raw evidence.",
            "",
        ]
    )
    atomic_write_text(change / "archive-summary.md", text)


def render_evidence(
    context: ProjectContext,
    change_value: str | Path,
) -> None:
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise EvidenceProjectionError(
            "evidence projection is only available for activated V6.2 Changes"
        )
    render_verification(ref.root, data)
    render_archive_summary(ref.root, data)
