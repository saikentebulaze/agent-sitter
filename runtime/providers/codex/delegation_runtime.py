from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from codex_managed_runtime import (
    CodexManagedRuntimeError,
    execute_managed_read_only,
)
from codex_runtime_attestation import (
    CodexRuntimeAttestationError,
    collect_native_attestation,
    validate_runtime_attestation,
)
from core.task_runtime import orchestrator_provider
from delegation_transaction import (
    DelegationTransactionError,
    record_delegation_result,
)
from managed_delegation_transaction import (
    ManagedDelegationTransactionError,
    record_managed_delegation_result,
)
from project_context import ProjectContext, resolve_project_context
from work_graph import (
    load_yaml,
    project_relative,
    resolve_task_root,
    valid_id,
)


class DelegationRuntimeError(RuntimeError):
    pass


def _entry(task: dict, delegation_id: str) -> dict:
    for item in ((task.get("delegation") or {}).get("planned") or []):
        if item.get("id") == delegation_id:
            return item
    raise DelegationRuntimeError(
        f"delegation not found: {delegation_id}"
    )


def _load(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, dict, dict, Path, dict]:
    task_root = resolve_task_root(context, task_value)
    task = load_yaml(task_root / "task.yaml")
    if orchestrator_provider(task) != "codex":
        raise DelegationRuntimeError(
            "Codex runtime cannot execute a non-Codex Task"
        )
    delegation_id = valid_id(delegation_id, "delegation_id")
    entry = _entry(task, delegation_id)
    request_ref = str(
        (entry.get("context") or {}).get("request_ref") or ""
    )
    if not request_ref:
        raise DelegationRuntimeError(
            "delegation has no request_ref"
        )
    request_path = (context.project_root / request_ref).resolve()
    try:
        request_path.relative_to(task_root.resolve())
    except ValueError as error:
        raise DelegationRuntimeError(
            "delegation request is outside the task directory"
        ) from error
    packet = load_yaml(request_path)
    return task_root, task, entry, request_path, packet


def runtime_task_name(
    context: ProjectContext,
    task: dict,
    packet: dict,
) -> str:
    delegation = packet.get("delegation") or {}
    delegation_id = str(delegation.get("id") or "")
    attempt = int(delegation.get("attempt") or 0)
    seed = "|".join(
        (
            str(context.project_root.resolve()).lower(),
            str(task.get("id") or ""),
            delegation_id,
            str(attempt),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    safe_id = re.sub(
        r"[^a-z0-9]+",
        "_",
        delegation_id.lower(),
    ).strip("_")
    return f"sitter_{safe_id}_a{attempt}_{digest}"


def delegation_message(
    context: ProjectContext,
    request_path: Path,
) -> str:
    request_ref = project_relative(context, request_path)
    return (
        f"Read and follow:\n\n{request_ref}\n\n"
        "Use an independent context. Do not rely on parent conversation "
        "history.\n"
        "Do not modify files.\n"
        "Return the required completed output or a structured NEED_CONTEXT "
        "response."
    )


def spawn_contract(
    context: ProjectContext,
    task: dict,
    request_path: Path,
    packet: dict,
) -> dict[str, Any]:
    profile = packet.get("requested_profile") or {}
    task_name = runtime_task_name(context, task, packet)
    request_ref = project_relative(context, request_path)
    return {
        "tool": "spawn_agent",
        "task_name": task_name,
        "agent_type": profile.get("agent"),
        "fork_turns": "none",
        "message": delegation_message(context, request_path),
        "request_ref": request_ref,
    }


def _runtime_packet(
    context: ProjectContext,
    task: dict,
    request_path: Path,
    packet: dict,
) -> dict:
    value = dict(packet)
    value["project_root"] = str(context.project_root.resolve())
    value["runtime"] = {
        "task_name": runtime_task_name(context, task, packet),
        "request_ref": project_relative(context, request_path),
        "fork_turns": "none",
        "agent_type": (
            (packet.get("requested_profile") or {}).get("agent")
        ),
    }
    return value


def _attempt(packet: dict) -> int:
    value = int((packet.get("delegation") or {}).get("attempt") or 0)
    if value <= 0:
        raise DelegationRuntimeError(
            "delegation request has an invalid attempt"
        )
    return value


def _runtime_paths(request_path: Path, packet: dict) -> tuple[Path, Path, Path]:
    attempt = _attempt(packet)
    directory = request_path.parent
    return (
        directory / f"attempt-{attempt:02d}.result-candidate.md",
        directory / f"attempt-{attempt:02d}.runtime-attestation.yaml",
        directory / f"attempt-{attempt:02d}.runtime-evidence.json",
    )


def _write_runtime_artifacts(
    request_path: Path,
    packet: dict,
    attestation: dict,
    evidence: dict,
    *,
    output: str | None = None,
) -> tuple[Path | None, Path, Path]:
    output_path, attestation_path, evidence_path = _runtime_paths(
        request_path,
        packet,
    )
    if output is not None:
        if not output.strip():
            raise DelegationRuntimeError("runtime output is empty")
        output_path.write_text(output.rstrip() + "\n", encoding="utf-8")
    attestation_path.write_text(
        yaml.safe_dump(
            attestation,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return (output_path if output is not None else None), attestation_path, evidence_path


def collect_native(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, Path, dict]:
    _, task, _, request_path, packet = _load(
        context,
        task_value,
        delegation_id,
    )
    runtime_packet = _runtime_packet(
        context,
        task,
        request_path,
        packet,
    )
    attestation, evidence = collect_native_attestation(
        context,
        runtime_packet,
    )
    attempt = _attempt(packet)
    attestation.setdefault("execution", {})["attempt"] = attempt
    evidence["delegation"] = {
        "id": delegation_id,
        "attempt": attempt,
        "request_ref": project_relative(context, request_path),
    }
    _, attestation_path, evidence_path = _write_runtime_artifacts(
        request_path,
        packet,
        attestation,
        evidence,
    )
    validate_runtime_attestation(runtime_packet, attestation)
    return attestation_path, evidence_path, attestation


def run_isolated(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, Path, Path, dict]:
    _, task, _, request_path, packet = _load(
        context,
        task_value,
        delegation_id,
    )
    runtime_packet = _runtime_packet(
        context,
        task,
        request_path,
        packet,
    )
    output, attestation, evidence = execute_managed_read_only(
        context,
        runtime_packet,
        message=delegation_message(context, request_path),
    )
    attempt = _attempt(packet)
    attestation.setdefault("execution", {})["attempt"] = attempt
    evidence["delegation"] = {
        "id": delegation_id,
        "attempt": attempt,
        "request_ref": project_relative(context, request_path),
    }
    output_path, attestation_path, evidence_path = _write_runtime_artifacts(
        request_path,
        packet,
        attestation,
        evidence,
        output=output,
    )
    assert output_path is not None
    return output_path, attestation_path, evidence_path, attestation


def _existing_managed_artifacts(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, Path, dict]:
    _, _, _, request_path, packet = _load(
        context,
        task_value,
        delegation_id,
    )
    output_path, attestation_path, evidence_path = _runtime_paths(
        request_path,
        packet,
    )
    for label, path in (
        ("managed output", output_path),
        ("managed attestation", attestation_path),
        ("managed evidence", evidence_path),
    ):
        if not path.is_file():
            raise DelegationRuntimeError(f"{label} is missing: {path}")
    attestation = load_yaml(attestation_path)
    if (attestation.get("execution") or {}).get("method") != "app-server-isolated-agent":
        raise DelegationRuntimeError(
            "runtime artifacts do not describe app-server-isolated-agent execution"
        )
    return output_path, attestation_path, attestation


def _record(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    artifact: Path,
    attestation_path: Path,
    attestation: dict,
    outcome: str,
) -> tuple[Path, str, bool]:
    execution = attestation.get("execution") or {}
    session_ref = str(execution.get("session_ref") or "")
    if not session_ref:
        raise DelegationRuntimeError("runtime attestation has no session_ref")
    if execution.get("method") == "app-server-isolated-agent":
        return record_managed_delegation_result(
            context,
            task_value,
            delegation_id,
            artifact=artifact,
            outcome=outcome,
            evidence_ref=session_ref,
            attestation=attestation_path,
        )
    return record_delegation_result(
        context,
        task_value,
        delegation_id,
        artifact=artifact,
        outcome=outcome,
        evidence_ref=session_ref,
        attestation=attestation_path,
    )


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Attested Codex runtime operations for Sitter delegation"
        )
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    contract = subparsers.add_parser("spawn-contract")
    contract.add_argument("task")
    contract.add_argument("delegation")

    collect_parser = subparsers.add_parser("collect-attestation")
    collect_parser.add_argument("task")
    collect_parser.add_argument("delegation")

    native_record = subparsers.add_parser("record-result")
    native_record.add_argument("task")
    native_record.add_argument("delegation")
    native_record.add_argument("--artifact", type=Path, required=True)
    native_record.add_argument(
        "--outcome",
        choices=("completed", "need-context", "failed"),
        required=True,
    )

    isolated = subparsers.add_parser("run-isolated")
    isolated.add_argument("task")
    isolated.add_argument("delegation")

    isolated_record = subparsers.add_parser("record-isolated-result")
    isolated_record.add_argument("task")
    isolated_record.add_argument("delegation")
    isolated_record.add_argument(
        "--outcome",
        choices=("completed", "need-context", "failed"),
        required=True,
    )

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        if args.command == "spawn-contract":
            _, task, _, request_path, packet = _load(
                context,
                args.task,
                args.delegation,
            )
            print(
                json.dumps(
                    spawn_contract(
                        context,
                        task,
                        request_path,
                        packet,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        if args.command == "run-isolated":
            output_path, attestation_path, evidence_path, _ = run_isolated(
                context,
                args.task,
                args.delegation,
            )
            print("output: " + project_relative(context, output_path))
            print("attestation: " + project_relative(context, attestation_path))
            print("evidence: " + project_relative(context, evidence_path))
            return

        if args.command == "record-isolated-result":
            output_path, attestation_path, attestation = (
                _existing_managed_artifacts(
                    context,
                    args.task,
                    args.delegation,
                )
            )
            result_path, outcome, idempotent = _record(
                context,
                args.task,
                args.delegation,
                artifact=output_path,
                attestation_path=attestation_path,
                attestation=attestation,
                outcome=args.outcome,
            )
            print("result: " + project_relative(context, result_path))
            print(f"outcome: {outcome}")
            print(f"idempotent: {str(idempotent).lower()}")
            return

        attestation_path, evidence_path, attestation = collect_native(
            context,
            args.task,
            args.delegation,
        )
        print("attestation: " + project_relative(context, attestation_path))
        print("evidence: " + project_relative(context, evidence_path))
        if args.command == "collect-attestation":
            return

        result_path, outcome, idempotent = _record(
            context,
            args.task,
            args.delegation,
            artifact=args.artifact,
            attestation_path=attestation_path,
            attestation=attestation,
            outcome=args.outcome,
        )
        print("result: " + project_relative(context, result_path))
        print(f"outcome: {outcome}")
        print(f"idempotent: {str(idempotent).lower()}")
    except (
        ValueError,
        DelegationRuntimeError,
        CodexRuntimeAttestationError,
        CodexManagedRuntimeError,
        DelegationTransactionError,
        ManagedDelegationTransactionError,
    ) as error:
        fail(str(error))


if __name__ == "__main__":
    main()
