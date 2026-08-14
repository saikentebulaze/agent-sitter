from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from core.task_runtime import orchestrator_provider
from delegation_transaction import DelegationTransactionError, request_delegation
from project_context import ProjectContext, resolve_project_context
from providers.claude.delegation_runtime import (
    ClaudeDelegationRuntimeError,
    record_isolated_result as record_claude_isolated_result,
    run_isolated as run_claude_isolated,
)
from providers.codex.delegation_runtime import (
    DelegationRuntimeError,
    _record as record_codex_runtime,
    run_isolated as run_codex_isolated,
)
from work_graph import load_yaml, project_relative, resolve_task_root


class DelegateOnceError(RuntimeError):
    pass


# Provider children may render the need-context contract either as a dedicated
# Markdown marker (``NEED_CONTEXT`` / ``**NEED_CONTEXT**``) or as a structured
# status field such as ``status: NEED_CONTEXT`` / ``"status": "NEED_CONTEXT"``.
# Keep both recognizers line-anchored and value-exact so prose that merely
# discusses the protocol does not become a false need-context result.
_NEED_CONTEXT = re.compile(
    r"(?mi)^\s*(?:#{1,6}\s*)?(?:\*\*|__|\*|_)?NEED_CONTEXT(?=(?:\*\*|__|\*|_)?(?:\s|$|[:\-]))"
)
_NEED_CONTEXT_STATUS = re.compile(
    r"""(?mix)
    ^\s*
    (?:[-*+]\s*)?
    \{?\s*
    (?:\*\*|__|\*|_)?
    ["'`]?
    status
    ["'`]?
    (?:\*\*|__|\*|_)?
    \s*[:=]\s*
    (?:\*\*|__|\*|_)?
    ["'`]?
    NEED_CONTEXT
    ["'`]?
    (?:\*\*|__|\*|_)?
    \s*
    [,;]?
    \s*
    \}?
    \s*$
    """
)


def reports_need_context(text: str) -> bool:
    return bool(_NEED_CONTEXT.search(text) or _NEED_CONTEXT_STATUS.search(text))


def infer_outcome(output: Path) -> str:
    text = output.read_text(encoding="utf-8")
    return "need-context" if reports_need_context(text) else "completed"


def _delegation_id(request_path: Path) -> str:
    value = request_path.parent.name
    if not value.startswith("dlg-"):
        raise DelegateOnceError(
            f"delegation request is not inside a dlg-* directory: {request_path}"
        )
    return value


def _task_provider(context: ProjectContext, task_value: str) -> str:
    task_root = resolve_task_root(context, task_value)
    return orchestrator_provider(load_yaml(task_root / "task.yaml"))


def _validate_claude_excludes(
    context: ProjectContext,
    task_value: str,
    exclude: list[str],
) -> None:
    """Reject exclusions that would hide Claude's frozen delegation request.

    Claude managed children must be able to read the request generated under
    ``<task>/delegations``. The scope hook gives explicit exclusions precedence,
    so excluding that directory (or one of its ancestors such as ``.agent-work``)
    would mechanically deny the child's own request. Reject the call before a
    delegation request is created instead of producing a doomed attempt.
    """

    project_root = context.project_root.resolve()
    task_root = resolve_task_root(context, task_value).resolve()
    protected = (task_root / "delegations").resolve(strict=False)

    for value in exclude:
        text = str(value or "").strip()
        if not text:
            continue
        raw = Path(text).expanduser()
        candidate = raw if raw.is_absolute() else project_root / raw
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(project_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if protected == resolved or protected.is_relative_to(resolved):
            raise DelegateOnceError(
                "Claude delegation --exclude covers the frozen request location "
                f"{project_relative(context, protected)}; narrow the exclusion so the child can read its request"
            )


def _run_codex(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    outcome: str,
) -> tuple[Path, str, bool, Path, Path]:
    output, attestation_path, evidence_path, attestation = run_codex_isolated(
        context,
        task_value,
        delegation_id,
    )
    resolved = infer_outcome(output) if outcome == "auto" else outcome
    result, recorded_outcome, idempotent = record_codex_runtime(
        context,
        task_value,
        delegation_id,
        artifact=output,
        attestation_path=attestation_path,
        attestation=attestation,
        outcome=resolved,
    )
    return result, recorded_outcome, idempotent, attestation_path, evidence_path


def _run_claude(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    outcome: str,
) -> tuple[Path, str, bool, Path, Path]:
    output, attestation_path, evidence_path = run_claude_isolated(
        context,
        task_value,
        delegation_id,
    )
    resolved = infer_outcome(output) if outcome == "auto" else outcome
    result, recorded_outcome, idempotent = record_claude_isolated_result(
        context,
        task_value,
        delegation_id,
        outcome=resolved,
    )
    return result, recorded_outcome, idempotent, attestation_path, evidence_path


def delegate_once(
    context: ProjectContext,
    task_value: str,
    *,
    role: str,
    target_type: str,
    target_ref: str,
    purpose: str,
    question: str,
    decision_supported: str,
    include: list[str],
    exclude: list[str],
    start_refs: list[str],
    confirmed_facts: list[str],
    outcome: str = "auto",
) -> dict:
    """Request, execute, attest, and record one managed read-only delegation.

    Task-level delegation authorization remains a separate explicit decision.
    This facade only removes the mechanical request -> provider-run -> record
    ceremony after authorization has already been granted.
    """

    if outcome not in {"auto", "completed", "need-context"}:
        raise DelegateOnceError("outcome must be auto, completed, or need-context")

    provider = _task_provider(context, task_value)
    if provider == "claude":
        _validate_claude_excludes(context, task_value, exclude)

    request_path = request_delegation(
        context,
        task_value,
        role=role,
        target_type=target_type,
        target_ref=target_ref,
        purpose=purpose,
        question=question,
        decision_supported=decision_supported,
        include=include,
        exclude=exclude,
        start_refs=start_refs,
        confirmed_facts=confirmed_facts,
    )
    delegation_id = _delegation_id(request_path)

    if provider == "codex":
        result, resolved, idempotent, attestation, evidence = _run_codex(
            context,
            task_value,
            delegation_id,
            outcome=outcome,
        )
    elif provider == "claude":
        result, resolved, idempotent, attestation, evidence = _run_claude(
            context,
            task_value,
            delegation_id,
            outcome=outcome,
        )
    else:
        raise DelegateOnceError(f"managed delegation is unsupported for provider: {provider}")

    return {
        "provider": provider,
        "delegation": delegation_id,
        "outcome": resolved,
        "idempotent": idempotent,
        "request_ref": project_relative(context, request_path),
        "result_ref": project_relative(context, result),
        "attestation_ref": project_relative(context, attestation),
        "evidence_ref": project_relative(context, evidence),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Request, run, attest, and record one managed Sitter read-only Agent"
    )
    parser.add_argument("task")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--role",
        choices=(
            "source_locator",
            "context_scout",
            "test_scout",
            "framework_scout",
            "maintainer_reviewer",
            "deep_reviewer",
        ),
        required=True,
    )
    parser.add_argument(
        "--target-type",
        choices=("task", "investigation", "change"),
        required=True,
    )
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--decision-supported", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--start-ref", action="append", default=[])
    parser.add_argument("--confirmed-fact", action="append", default=[])
    parser.add_argument(
        "--outcome",
        choices=("auto", "completed", "need-context"),
        default="auto",
    )
    args = parser.parse_args()

    try:
        context = resolve_project_context(args.project)
        result = delegate_once(
            context,
            args.task,
            role=args.role,
            target_type=args.target_type,
            target_ref=args.target_ref,
            purpose=args.purpose,
            question=args.question,
            decision_supported=args.decision_supported,
            include=args.include,
            exclude=args.exclude,
            start_refs=args.start_ref,
            confirmed_facts=args.confirmed_fact,
            outcome=args.outcome,
        )
    except (
        ValueError,
        DelegateOnceError,
        DelegationTransactionError,
        DelegationRuntimeError,
        ClaudeDelegationRuntimeError,
    ) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
