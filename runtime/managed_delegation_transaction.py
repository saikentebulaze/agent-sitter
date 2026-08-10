from __future__ import annotations

import copy
from pathlib import Path

import yaml

from codex_managed_runtime import validate_managed_attestation
from delegation_context import verify_snapshot
from delegation_validation import validate_delegation_state
from project_context import ProjectContext
from review_transaction import atomic_write_text
from work_graph import (
    WorkGraphError,
    load_yaml,
    now_iso,
    project_relative,
    resolve_task_root,
    valid_id,
)


class ManagedDelegationTransactionError(WorkGraphError):
    pass


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content.decode("utf-8"))


def _transaction(
    writes: dict[Path, str],
    *,
    validator,
) -> None:
    before = _snapshot(list(writes))
    try:
        for path, content in writes.items():
            atomic_write_text(path, content)
        validator()
    except BaseException:
        _restore(before)
        raise


def _entry_by_id(task: dict, delegation_id: str) -> dict:
    delegation = task.get("delegation") or {}
    for item in delegation.get("planned") or []:
        if item.get("id") == delegation_id:
            return item
    raise ManagedDelegationTransactionError(
        f"delegation not found: {delegation_id}"
    )


def _safe_project_file(
    context: ProjectContext,
    value: Path,
    label: str,
) -> Path:
    path = value.resolve() if value.is_absolute() else (context.project_root / value).resolve()
    try:
        path.relative_to(context.project_root.resolve())
    except ValueError as error:
        raise ManagedDelegationTransactionError(
            f"{label} is outside project"
        ) from error
    if not path.is_file():
        raise ManagedDelegationTransactionError(
            f"{label} does not exist: {path}"
        )
    return path


def record_managed_delegation_result(
    context: ProjectContext,
    task_value: str | Path,
    delegation_id: str,
    *,
    artifact: Path,
    outcome: str,
    evidence_ref: str,
    attestation: Path,
) -> tuple[Path, str, bool]:
    if outcome not in {"completed", "need-context", "failed"}:
        raise ManagedDelegationTransactionError(
            "delegation outcome must be completed, need-context, or failed"
        )
    if not evidence_ref.strip():
        raise ManagedDelegationTransactionError(
            "delegation evidence_ref is required"
        )

    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    task = load_yaml(task_path)
    delegation_id = valid_id(delegation_id, "delegation_id")
    planned = _entry_by_id(task, delegation_id)
    context_data = planned.get("context") or {}
    request_ref = str(context_data.get("request_ref") or "")
    request_path = (context.project_root / request_ref).resolve()
    try:
        request_path.relative_to(task_root.resolve())
    except ValueError as error:
        raise ManagedDelegationTransactionError(
            "delegation request is outside the task directory"
        ) from error
    packet = load_yaml(request_path)
    attempt = int((packet.get("delegation") or {}).get("attempt") or 0)
    if attempt <= 0:
        raise ManagedDelegationTransactionError(
            "delegation request has an invalid attempt"
        )
    directory = request_path.parent
    result_path = directory / f"attempt-{attempt:02d}.result.md"
    record_path = directory / f"attempt-{attempt:02d}.record.yaml"
    expected_attestation = (
        directory / f"attempt-{attempt:02d}.runtime-attestation.yaml"
    )
    expected_evidence = directory / f"attempt-{attempt:02d}.runtime-evidence.json"

    artifact_path = _safe_project_file(context, artifact, "managed output")
    artifact_text = artifact_path.read_text(encoding="utf-8")
    if not artifact_text.strip():
        raise ManagedDelegationTransactionError("managed output is empty")
    attestation_path = _safe_project_file(
        context,
        attestation,
        "managed attestation",
    )
    if attestation_path != expected_attestation.resolve():
        raise ManagedDelegationTransactionError(
            "managed attestation must be the runtime-generated attempt artifact"
        )
    if not expected_evidence.is_file():
        raise ManagedDelegationTransactionError(
            "managed runtime evidence is missing"
        )
    attestation_data = load_yaml(attestation_path)
    validate_managed_attestation(context, packet, attestation_data)

    changed = verify_snapshot(context, packet)
    effective_outcome = "stale" if changed else outcome
    stable_record = {
        "schema_version": 1,
        "delegation_id": delegation_id,
        "attempt": attempt,
        "outcome": effective_outcome,
        "requested_outcome": outcome,
        "evidence_ref": evidence_ref,
        "request_ref": project_relative(context, request_path),
        "output_ref": project_relative(context, result_path),
        "attestation": attestation_data,
        "runtime_evidence_ref": project_relative(context, expected_evidence),
        "stale_inputs": changed,
    }

    if record_path.exists():
        existing = load_yaml(record_path)
        existing_stable = dict(existing)
        existing_stable.pop("recorded_at", None)
        if (
            existing_stable == stable_record
            and result_path.is_file()
            and result_path.read_text(encoding="utf-8") == artifact_text
        ):
            return result_path, effective_outcome, True
        raise ManagedDelegationTransactionError(
            f"conflicting delegation result already exists: {record_path}"
        )
    if result_path.exists():
        raise ManagedDelegationTransactionError(
            f"delegation output exists without matching record: {result_path}"
        )

    task_after = copy.deepcopy(task)
    planned_after = _entry_by_id(task_after, delegation_id)
    planned_after["status"] = effective_outcome
    profile = packet.get("requested_profile") or {}
    completed_entry = {
        "id": delegation_id,
        "agent": profile.get("agent"),
        "model": profile.get("model"),
        "tier": profile.get("tier"),
        "reasoning_effort": profile.get("reasoning_effort"),
        "execution": "app-server-isolated-agent",
        "context": {
            "inheritance": "none",
            "projection": planned_after["context"]["projection"],
            "attempt": attempt,
            "request_ref": project_relative(context, request_path),
        },
        "output_ref": project_relative(context, result_path),
        "record_ref": project_relative(context, record_path),
        "evidence_ref": evidence_ref,
    }
    delegation_after = task_after.setdefault("delegation", {})
    delegation_after.setdefault("completed", [])
    delegation_after.setdefault("failed", [])
    if effective_outcome == "completed":
        delegation_after["completed"].append(completed_entry)
    elif effective_outcome in {"failed", "stale"}:
        delegation_after["failed"].append(
            {
                "id": delegation_id,
                "agent": profile.get("agent"),
                "reason": (
                    "stale-context: " + ", ".join(changed)
                    if effective_outcome == "stale"
                    else "managed-agent-reported-failure"
                ),
                "output_ref": project_relative(context, result_path),
                "evidence_ref": evidence_ref,
            }
        )
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-result-recorded",
            "at": now_iso(),
            "ref": delegation_id,
            "attempt": attempt,
            "execution": "app-server-isolated-agent",
            "outcome": effective_outcome,
        }
    )
    record = {**stable_record, "recorded_at": now_iso()}
    writes = {
        result_path: artifact_text,
        record_path: yaml.safe_dump(
            record,
            allow_unicode=True,
            sort_keys=False,
        ),
        task_path: yaml.safe_dump(
            task_after,
            allow_unicode=True,
            sort_keys=False,
        ),
    }
    _transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context,
            task_root,
            load_yaml(task_path),
        ),
    )
    return result_path, effective_outcome, False
