from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from artifact_consistency import file_sha256, git_diff_sha256
from project_context import ProjectContext


REVIEW_STATUS = {"pass", "warn", "block"}
REMEDIATION_ROUTES = {"implementation", "awaiting-production-design"}
SEVERITY = {"pass": 0, "warn": 1, "block": 2}


class ReviewTransactionError(ValueError):
    pass


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ReviewTransactionError(f"missing file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ReviewTransactionError(f"invalid YAML in {path}:{location}: {error}") from error
    if not isinstance(data, dict):
        raise ReviewTransactionError(f"expected YAML mapping: {path}")
    return data


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_yaml(path: Path, data: dict) -> None:
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ReviewTransactionError(f"generated invalid YAML for {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise ReviewTransactionError(f"generated YAML is not a mapping: {path}")
    atomic_write_text(path, content)


def project_path(context: ProjectContext, value: str | Path, label: str) -> Path:
    raw = Path(value)
    path = raw.resolve() if raw.is_absolute() else (context.project_root / raw).resolve()
    try:
        path.relative_to(context.project_root)
    except ValueError as error:
        raise ReviewTransactionError(f"{label} is outside project: {value}") from error
    return path


def project_relative(context: ProjectContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.project_root).as_posix()
    except ValueError as error:
        raise ReviewTransactionError(f"path is outside project: {path}") from error


def current_snapshot(context: ProjectContext, change: Path) -> dict:
    return {
        "design_sha256": file_sha256(change / "design.md"),
        "tasks_sha256": file_sha256(change / "tasks.md"),
        "diff_sha256": git_diff_sha256(context.project_root),
        "verification_sha256": file_sha256(change / "verification.md"),
    }


def _validate_snapshot(expected: object, actual: dict) -> None:
    if not isinstance(expected, dict):
        raise ReviewTransactionError("review request input_snapshot must be a mapping")
    changed = [key for key, value in actual.items() if expected.get(key) != value]
    if changed:
        raise ReviewTransactionError(
            "review request is stale; changed inputs: " + ", ".join(changed)
        )


def _overall_status(architecture: str, scope: str, numerical_evidence: str) -> str:
    values = (architecture, scope, numerical_evidence)
    invalid = [value for value in values if value not in REVIEW_STATUS]
    if invalid:
        raise ReviewTransactionError(
            f"invalid review status: {invalid[0]}; allowed values: pass, warn, block"
        )
    return max(values, key=lambda value: SEVERITY[value])


def _validate_reviewer(packet: dict) -> dict:
    reviewer = packet.get("reviewer")
    if not isinstance(reviewer, dict):
        raise ReviewTransactionError("review request reviewer must be a mapping")
    for key in ("agent", "model", "tier"):
        value = reviewer.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ReviewTransactionError(f"review request reviewer.{key} is required")
    if packet.get("method") != "native-subagent":
        raise ReviewTransactionError("review request method must be native-subagent")
    if reviewer["agent"] == "deep_reviewer" and not packet.get(
        "elevated_authorization_ref"
    ):
        raise ReviewTransactionError("deep review request lacks elevated authorization evidence")
    return reviewer


def _matches_recorded_review(
    context: ProjectContext,
    data: dict,
    artifact_text: str,
    architecture: str,
    scope: str,
    numerical_evidence: str,
    evidence_ref: str,
) -> Path | None:
    review = data.get("review") or {}
    execution = review.get("execution") or {}
    if any(
        review.get(key) != value
        for key, value in (
            ("architecture", architecture),
            ("scope", scope),
            ("numerical_evidence", numerical_evidence),
        )
    ):
        return None
    if execution.get("evidence_ref") != evidence_ref:
        return None
    output_ref = execution.get("output_ref")
    if not isinstance(output_ref, str) or not output_ref:
        return None
    output = project_path(context, output_ref, "recorded review output")
    if not output.is_file() or output.read_text(encoding="utf-8") != artifact_text:
        return None
    return output


def _run_validator(context: ProjectContext, change: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(context.package_root / "runtime" / "validate_change.py"),
            str(change),
        ],
        cwd=context.project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "change validation failed"
        raise ReviewTransactionError(message)


def _archive_request(change: Path, packet: dict) -> None:
    round_number = packet["round"]
    archived = change / "reviews" / f"round-{round_number}.request.yaml"
    current = change / "review-request.yaml"
    if archived.exists():
        existing = load_yaml(archived)
        if existing != packet:
            raise ReviewTransactionError(f"review request archive conflicts: {archived}")
    else:
        atomic_write_yaml(archived, packet)
    current.unlink(missing_ok=True)


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
) -> tuple[Path, bool]:
    if not evidence_ref.strip():
        raise ReviewTransactionError("--evidence-ref must be a non-empty string")

    overall = _overall_status(architecture, scope, numerical_evidence)
    if overall == "block":
        if remediation_route not in REMEDIATION_ROUTES:
            allowed = ", ".join(sorted(REMEDIATION_ROUTES))
            raise ReviewTransactionError(
                f"BLOCK review requires --remediation-route; allowed values: {allowed}"
            )
    elif remediation_route is not None:
        raise ReviewTransactionError("--remediation-route is only valid for a BLOCK review")

    artifact_path = project_path(context, artifact, "review artifact")
    if not artifact_path.is_file():
        raise ReviewTransactionError(f"review artifact does not exist: {artifact_path}")
    artifact_text = artifact_path.read_text(encoding="utf-8")
    if not artifact_text.strip():
        raise ReviewTransactionError("review artifact is empty")

    change_yaml = change / "change.yaml"
    data = load_yaml(change_yaml)
    packet_path = change / "review-request.yaml"
    if not packet_path.is_file():
        recorded = _matches_recorded_review(
            context,
            data,
            artifact_text,
            architecture,
            scope,
            numerical_evidence,
            evidence_ref,
        )
        if recorded is not None:
            return recorded, True
        raise ReviewTransactionError(
            "no pending review request; run harness review before record-review"
        )

    packet = load_yaml(packet_path)
    history = data.get("review_history") or []
    if not isinstance(history, list):
        raise ReviewTransactionError("review_history must be a list")
    expected_round = len(history) + 1
    round_number = packet.get("round")
    if round_number != expected_round:
        raise ReviewTransactionError(
            f"review request round {round_number} does not match next round {expected_round}"
        )
    change_id = data.get("id") or change.name
    if packet.get("change_id") != change_id:
        raise ReviewTransactionError("review request change_id does not match change.yaml")

    reviewer = _validate_reviewer(packet)
    _validate_snapshot(packet.get("input_snapshot"), current_snapshot(context, change))

    output_ref = packet.get("output_ref")
    if not isinstance(output_ref, str) or not output_ref:
        raise ReviewTransactionError("review request output_ref is required")
    output = project_path(context, output_ref, "review output")
    expected_output = (change / "reviews" / f"round-{round_number}.md").resolve()
    if output != expected_output:
        raise ReviewTransactionError(
            f"review output_ref must be {project_relative(context, expected_output)}"
        )

    already_recorded = _matches_recorded_review(
        context,
        data,
        artifact_text,
        architecture,
        scope,
        numerical_evidence,
        evidence_ref,
    )
    if already_recorded is not None:
        _archive_request(change, packet)
        return already_recorded, True
    if output.exists():
        raise ReviewTransactionError(f"review output already exists: {output}")

    execution = {
        "agent": reviewer["agent"],
        "model": reviewer["model"],
        "tier": reviewer["tier"],
        "method": packet["method"],
        "output_ref": output_ref,
        "evidence_ref": evidence_ref,
        "round": round_number,
        "input_snapshot": packet["input_snapshot"],
    }
    if packet.get("elevated_authorization_ref"):
        execution["elevated_authorization_ref"] = packet["elevated_authorization_ref"]

    review = {
        "status": overall,
        "architecture": architecture,
        "scope": scope,
        "numerical_evidence": numerical_evidence,
        "execution": execution,
    }
    round_data = {"round": round_number, **review}
    if overall == "block":
        round_data["remediation_route"] = remediation_route
        data["remediation"] = {
            "route": remediation_route,
            "within_approved_scope": True,
        }
        data["status"] = (
            "implementing"
            if remediation_route == "implementation"
            else "designed"
        )
    else:
        data["remediation"] = {"route": None, "within_approved_scope": False}

    data["review"] = review
    data["review_history"] = [*history, round_data]

    original_change = change_yaml.read_text(encoding="utf-8")
    output_written = False
    archived_request = change / "reviews" / f"round-{round_number}.request.yaml"
    archived_existed = archived_request.exists()
    try:
        atomic_write_text(output, artifact_text)
        output_written = True
        atomic_write_yaml(change_yaml, data)
        _run_validator(context, change)
        _archive_request(change, packet)
    except Exception:
        atomic_write_text(change_yaml, original_change)
        if output_written:
            output.unlink(missing_ok=True)
        if not archived_existed:
            archived_request.unlink(missing_ok=True)
        if not packet_path.exists():
            atomic_write_yaml(packet_path, packet)
        raise

    return output, False
