from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml


class AuditError(ValueError):
    pass


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise AuditError(f"missing file: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"expected YAML mapping: {path}")
    return value


def _inside(project: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(project.resolve())
        return True
    except ValueError:
        return False


def _resolve_change(project: Path, change_id: str) -> Path:
    matches = [
        project / "changes" / parent / change_id
        for parent in ("active", "archive")
        if (project / "changes" / parent / change_id / "change.yaml").is_file()
    ]
    if len(matches) != 1:
        raise AuditError(
            f"expected exactly one active/archive Change named {change_id}; found {len(matches)}"
        )
    return matches[0]


def _ref_exists(project: Path, value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = (project / value).resolve()
    return _inside(project, path) and path.is_file()


def _run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _installed_validation(project: Path, change: Path, task_id: str) -> dict:
    runtime = project / ".harness" / "sitter" / "runtime"
    validate_change = runtime / "validate_change.py"
    work = runtime / "work.py"
    if not validate_change.is_file() or not work.is_file():
        return {
            "change": {"ok": False, "stderr": "installed Sitter validation runtime is missing"},
            "task": {"ok": False, "stderr": "installed Sitter work runtime is missing"},
        }
    return {
        "change": _run([sys.executable, str(validate_change), str(change)], project),
        "task": _run(
            [sys.executable, str(work), "--project", str(project), "validate", task_id],
            project,
        ),
    }


def _common_checks(project: Path, change: Path, data: dict) -> dict:
    review = data.get("review") or {}
    execution = review.get("execution") or {}
    input_snapshot = execution.get("input_snapshot") or {}
    attestation_ref = execution.get("attestation_ref")
    runtime_evidence_ref = execution.get("runtime_evidence_ref") or execution.get("evidence_ref")
    return {
        "candidate_readiness_protocol_1": data.get("candidate_readiness_protocol") == 1,
        "readiness_pass": (data.get("readiness") or {}).get("status") == "pass",
        "review_pass_or_warn": review.get("status") in {"pass", "warn"},
        "review_protocol_2": execution.get("review_protocol") == 2,
        "snapshot_protocol_2": input_snapshot.get("snapshot_protocol") == 2,
        "provider_recorded": bool(str(execution.get("provider") or "").strip()),
        "runtime_method_recorded": bool(str(execution.get("runtime_method") or "").strip()),
        "attestation_artifact_exists": _ref_exists(project, attestation_ref),
        "runtime_evidence_exists": _ref_exists(project, runtime_evidence_ref),
        "review_output_exists": _ref_exists(project, execution.get("output_ref")),
        "no_pending_review_request": not (change / "review-request.yaml").exists(),
    }


def _candidate_checks(data: dict) -> dict:
    verification = data.get("verification") or {}
    return {
        "at_candidate_human_stop": data.get("status") == "candidate-review",
        "user_review_pending": (data.get("user_review") or {}).get("status") == "pending",
        "final_verification_not_started": not bool(verification.get("latest_results") or []),
    }


def _closure_checks(data: dict, task: dict) -> tuple[dict, list[str]]:
    verification = data.get("verification") or {}
    knowledge = data.get("knowledge_sync") or {}
    archive = data.get("archive") or {}
    learning = task.get("learning") or {}
    attention = learning.get("user_attention") or {}
    pending: list[str] = []

    if data.get("status") != "archived":
        pending.append(f"Change status is {data.get('status')!r}, not archived")
    if knowledge.get("status") not in {"promoted", "deferred"}:
        pending.append(f"Knowledge status is {knowledge.get('status')!r}")
    if archive.get("experiment_cleanup_complete") is not True:
        pending.append("archive cleanup is incomplete")
    if (learning.get("closeout") or {}).get("status") != "assessed":
        pending.append("Learning closeout is not assessed")
    if attention.get("required") is True and attention.get("decision") == "pending":
        pending.append("mature Learning candidate still requires individual user curation")
    if task.get("status") != "completed":
        pending.append(
            "owning Task is not completed; this is valid only when another active Investigation/Change or governance stop remains"
        )

    checks = {
        "candidate_acceptance_current": (data.get("user_review") or {}).get("status")
        in {"approved", "not-required"},
        "final_verification_pass_or_partial": verification.get("status") in {"pass", "partial"},
        "final_verification_has_structured_results": bool(verification.get("latest_results") or []),
        "knowledge_resolved": knowledge.get("status") in {"promoted", "deferred"},
        "archive_cleanup_complete": archive.get("experiment_cleanup_complete") is True,
        "change_archived": data.get("status") == "archived",
        "learning_closeout_assessed": (learning.get("closeout") or {}).get("status") == "assessed",
        "learning_attention_resolved_or_not_required": not (
            attention.get("required") is True and attention.get("decision") == "pending"
        ),
        "task_completed": task.get("status") == "completed",
    }
    return checks, pending


def audit(project: Path, change_id: str, phase: str) -> dict:
    project = project.expanduser().resolve()
    change = _resolve_change(project, change_id)
    data = _load_yaml(change / "change.yaml")
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise AuditError("Change has no owning task_id")
    task_path = project / ".agent-work" / task_id / "task.yaml"
    task = _load_yaml(task_path)

    validators = _installed_validation(project, change, task_id)
    checks = _common_checks(project, change, data)
    pending: list[str] = []
    if phase == "candidate":
        checks.update(_candidate_checks(data))
    else:
        closure, pending = _closure_checks(data, task)
        checks.update(closure)

    critical_failures = [name for name, ok in checks.items() if not ok]
    # Task completion and archive state may be intentionally pending after engineering
    # completion; keep those as PENDING only in closure phase when validators and
    # engineering proof still pass.
    soft = {
        "knowledge_resolved",
        "archive_cleanup_complete",
        "change_archived",
        "learning_closeout_assessed",
        "learning_attention_resolved_or_not_required",
        "task_completed",
    }
    hard_failures = [name for name in critical_failures if name not in soft]
    validation_ok = bool(validators["change"].get("ok")) and bool(validators["task"].get("ok"))

    if hard_failures or not validation_ok:
        status = "FAIL"
    elif phase == "closure" and (pending or critical_failures):
        status = "GOVERNANCE_PENDING"
    else:
        status = "PASS"

    review_history = data.get("review_history") or []
    return {
        "schema_version": 1,
        "status": status,
        "phase": phase,
        "project": str(project),
        "change": change_id,
        "change_location": change.relative_to(project).as_posix(),
        "task": task_id,
        "change_status": data.get("status"),
        "task_status": task.get("status"),
        "review_rounds": len(review_history),
        "normal_success_single_reviewer": len(review_history) == 1,
        "installed_validation": validators,
        "checks": checks,
        "hard_failures": hard_failures,
        "governance_pending": pending,
        "manual_metrics_not_inferred": [
            "parent-visible Harness interactions",
            "duplicate Scout count from the real agent transcript",
            "Provider token usage unless trustworthy structured metrics are available",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only V6.3-A real-project acceptance auditor"
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--phase", choices=("candidate", "closure"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.project, args.change, args.phase)
    except (AuditError, OSError, UnicodeError, yaml.YAMLError) as error:
        raise SystemExit(str(error)) from error
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
