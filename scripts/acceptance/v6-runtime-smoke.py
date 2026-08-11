from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


HARNESS_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "v6-runtime-smoke"
SMOKE_ROOT = Path(".agent-work/_runtime-smoke")
MANIFEST_REF = SMOKE_ROOT / "manifest.json"
PROMPT_REF = SMOKE_ROOT / "PROMPT.md"
OBSERVATION_REF = SMOKE_ROOT / "session-observation.json"
RESULT_REF = SMOKE_ROOT / "agent-result.json"
SESSION_EVIDENCE_REF = SMOKE_ROOT / "session-start"
EXPLORATION_ROLES = {"source_locator", "context_scout", "test_scout", "framework_scout"}


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(command)}\n{message}")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_destination(destination: Path, force: bool) -> Path:
    path = destination.expanduser().resolve()
    if path.exists():
        if not force:
            raise RuntimeError(f"destination already exists: {path}; use --force to replace it")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _install(project: Path, provider: str) -> None:
    _run(
        [
            sys.executable,
            str(HARNESS_ROOT / "install.py"),
            "--project",
            str(project),
            "--provider",
            provider,
        ],
        cwd=HARNESS_ROOT,
    )


def _git(project: Path, *args: str) -> str:
    return _run(["git", *args], cwd=project).stdout.strip()


def _prepare_project(project: Path, provider: str) -> dict:
    _git(project, "init")
    _git(project, "config", "user.email", "v6-runtime-smoke@example.invalid")
    _git(project, "config", "user.name", "V6 Runtime Smoke")
    canary = f"sitter-v6-{secrets.token_hex(12)}"
    source = project / "src" / "runtime_smoke.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "def current_state():\n"
        "    return 'committed-runtime-smoke-state'\n",
        encoding="utf-8",
    )
    _git(project, "add", "src/runtime_smoke.py")
    _git(project, "commit", "-m", "Create V6 runtime smoke fixture")
    source_commit = _git(project, "rev-parse", "HEAD")

    _install(project, provider)
    installed_runtime = project / ".harness" / "sitter" / "runtime"

    memory_path = project / "knowledge" / "runtime-smoke.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        "# Runtime smoke continuity\n\n"
        "The runtime smoke fixture uses committed state from `src/runtime_smoke.py`. "
        "This entry exists only to prove bounded, version-aware Memory Scout recall.\n",
        encoding="utf-8",
    )
    knowledge = {
        "version": 1,
        "entries": [
            {
                "id": "RUNTIME-K01",
                "title": "Runtime smoke continuity",
                "type": "fact",
                "evidence_status": "verified",
                "architecture_status": "current",
                "path": "knowledge/runtime-smoke.md",
                "domains": ["runtime-smoke"],
                "keywords": ["runtime", "smoke", "continuity", canary],
                "related": [],
                "memory_key": "runtime-smoke-continuity",
                "source_commit": source_commit,
                "validity_surface": ["src"],
            }
        ],
    }
    (project / "knowledge" / "index.yaml").write_text(
        yaml.safe_dump(knowledge, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    _run(
        [
            sys.executable,
            str(installed_runtime / "create_task.py"),
            TASK_ID,
            "--title",
            f"V6 runtime smoke {canary}",
            "--entry",
            "investigation",
            "--signature",
            "v6-runtime-smoke",
            "--provider",
            provider,
            "--project",
            str(project),
        ],
        cwd=project,
    )
    task_ref = Path(".agent-work") / TASK_ID / "task.yaml"
    _run(
        [
            sys.executable,
            str(installed_runtime / "learning.py"),
            "--project",
            str(project),
            "intake",
            task_ref.as_posix(),
            "--keyword",
            "runtime",
            "--keyword",
            "smoke",
        ],
        cwd=project,
    )
    _run(
        [
            sys.executable,
            str(installed_runtime / "work.py"),
            "--project",
            str(project),
            "authorize-delegation",
            TASK_ID,
            "--decision",
            "required",
            "--scope",
            "readonly-exploration",
            "--evidence",
            "V6 real runtime smoke requires readonly Context Scout and Memory Scout",
            "--parent-model",
            "runtime-smoke-parent",
            "--parent-tier",
            "sol",
        ],
        cwd=project,
    )

    governor_ref = (
        ".agents/skills/change-governor/SKILL.md"
        if provider == "codex"
        else ".claude/skills/change-governor/SKILL.md"
    )
    commands = {
        "context_scout": [
            sys.executable,
            ".harness/sitter/runtime/delegate_once.py",
            TASK_ID,
            "--project",
            ".",
            "--role",
            "context_scout",
            "--target-type",
            "task",
            "--target-ref",
            TASK_ID,
            "--purpose",
            "prove a real fresh readonly Context Scout can inspect a bounded project chain",
            "--question",
            "What current source file defines the runtime smoke committed state, and what value does it return?",
            "--decision-supported",
            "runtime acceptance only; no production engineering conclusion is delegated",
            "--include",
            "src",
            "--start-ref",
            "src/runtime_smoke.py",
        ],
        "memory_scout": [
            sys.executable,
            ".harness/sitter/runtime/memory_scout_once.py",
            TASK_ID,
            "--project",
            ".",
            "--query",
            "runtime smoke continuity",
            "--limit",
            "2",
        ],
        "validate": [
            sys.executable,
            ".harness/sitter/runtime/work.py",
            "--project",
            ".",
            "validate",
            TASK_ID,
        ],
    }
    manifest = {
        "schema_version": 1,
        "provider": provider,
        "task_id": TASK_ID,
        "session_start_canary": canary,
        "source_commit": source_commit,
        "governor_ref": governor_ref,
        "session_start_evidence_env": "SITTER_SESSION_START_EVIDENCE_DIR",
        "session_start_evidence_ref": SESSION_EVIDENCE_REF.as_posix(),
        "session_observation_ref": OBSERVATION_REF.as_posix(),
        "agent_result_ref": RESULT_REF.as_posix(),
        "commands": commands,
    }
    _write_json(project / MANIFEST_REF, manifest)
    (project / PROMPT_REF).write_text(_prompt_text(), encoding="utf-8")
    return manifest


def _prompt_text() -> str:
    return """# V6 real runtime smoke

This is a black-box acceptance run for the already-installed Sitter Harness. Do not implement or modify production code and do not create another Task.

Follow this sequence exactly:

1. **Before reading any repository file, including the smoke manifest**, use only the developer/session context already present at session start. Write `.agent-work/_runtime-smoke/session-observation.json` containing exactly these two fields:
   - `active_task_id`: the single active governed Task ID you received from SessionStart context;
   - `session_start_canary`: the unique canary embedded in that Task's title.
   If that information was not present before repository reads, stop and report failure rather than reconstructing it from files.
2. Read `.agent-work/_runtime-smoke/manifest.json`.
3. Explicitly read the Governor file named by `governor_ref`. Compute the SHA-256 of the exact file you read. This is an explicit Governor invocation for acceptance only; do not let it create extra work.
4. Execute the `context_scout` argv from the manifest exactly once. Capture the parsed JSON printed by the command. The readonly child must actually run and complete; do not substitute your own exploration.
5. Execute the `memory_scout` argv from the manifest exactly once. Capture the parsed JSON printed by the command. The Memory Scout must actually run; do not summarize the memory yourself instead.
6. Execute the `validate` argv from the manifest.
7. Write `.agent-work/_runtime-smoke/agent-result.json` with this shape:

```json
{
  "schema_version": 1,
  "governor_ref": "the manifest governor_ref",
  "governor_sha256": "sha256 of the exact Governor file read",
  "context_scout": {"the": "exact parsed JSON returned by the context_scout command"},
  "memory_scout": {"the": "exact parsed JSON returned by the memory_scout command"},
  "work_graph_valid": true
}
```

Do not put invented attestation data in the result. Runtime attestation and evidence are verified independently from the Task's recorded delegation artifacts.
"""


def prepare(destination: Path, provider: str, force: bool) -> dict:
    if provider not in {"codex", "claude"}:
        raise RuntimeError("provider must be codex or claude")
    project = _safe_destination(destination, force)
    manifest = _prepare_project(project, provider)
    return {
        "status": "PREPARED_NOT_RUN",
        "project": str(project),
        "provider": provider,
        "task_id": manifest["task_id"],
        "prompt": str(project / PROMPT_REF),
        "session_start_evidence_env": manifest["session_start_evidence_env"],
        "session_start_evidence_value": manifest["session_start_evidence_ref"],
        "next": (
            "Set the listed environment variable before launching a genuinely fresh provider session "
            "from this project, then give that session the PROMPT.md contents. For Codex, ensure the "
            "project is trusted before launch. Do not use resume/fork for this smoke."
        ),
    }


def _load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected mapping: {path}")
    return value


def _find_completed_role(task: dict, role: str) -> tuple[dict | None, dict | None]:
    delegation = task.get("delegation") or {}
    planned = next(
        (item for item in delegation.get("planned") or [] if item.get("agent") == role),
        None,
    )
    if planned is None:
        return None, None
    completed = next(
        (item for item in delegation.get("completed") or [] if item.get("id") == planned.get("id")),
        None,
    )
    return planned, completed


def _validate_completed_attestation(project: Path, completed: dict) -> dict:
    runtime = project / ".harness" / "sitter" / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    from provider_attestation import validate_provider_attestation

    request = _load_yaml(project / str((completed.get("context") or {}).get("request_ref")))
    record = _load_yaml(project / str(completed.get("record_ref")))
    attestation = record.get("attestation")
    if not isinstance(attestation, dict):
        raise RuntimeError(f"delegation record has no attestation: {completed.get('record_ref')}")
    evidence = validate_provider_attestation(request, attestation)
    return {
        "provider": evidence.provider,
        "role_id": evidence.role_id,
        "context_isolation": evidence.contract.context_isolation,
        "write_isolation": evidence.contract.write_isolation,
        "attestation_strength": evidence.contract.attestation_strength,
        "request_ref": (completed.get("context") or {}).get("request_ref"),
        "record_ref": completed.get("record_ref"),
        "output_ref": completed.get("output_ref"),
    }


def _session_event_matches(event: dict, task_id: str, canary: str) -> bool:
    return bool(
        str(event.get("source") or "") == "startup"
        and task_id in (event.get("active_task_ids") or [])
        and canary in str(event.get("additional_context") or "")
        and not bool(event.get("history_scanned"))
        and not bool(event.get("durable_memory_loaded"))
    )


def verify(project: Path) -> dict:
    project = project.expanduser().resolve()
    manifest = json.loads((project / MANIFEST_REF).read_text(encoding="utf-8"))
    provider = str(manifest["provider"])
    task_id = str(manifest["task_id"])
    canary = str(manifest["session_start_canary"])
    checks: dict[str, object] = {}

    session_event_paths = sorted((project / SESSION_EVIDENCE_REF).glob("session-start-*.json"))
    parsed_events: list[dict] = []
    for path in session_event_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            parsed_events.append(value)
    host_events = [event for event in parsed_events if _session_event_matches(event, task_id, canary)]
    checks["session_start_evidence_present"] = bool(parsed_events)
    checks["session_start_host_event_count"] = len(host_events)
    checks["session_start_hook_effective"] = bool(host_events)
    session_evidence = host_events[0] if host_events else None

    observation_path = project / OBSERVATION_REF
    checks["parent_received_session_context"] = False
    if observation_path.is_file():
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        checks["parent_received_session_context"] = (
            observation.get("active_task_id") == task_id
            and observation.get("session_start_canary") == canary
        )

    governor = project / str(manifest["governor_ref"])
    result_path = project / RESULT_REF
    receipt = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    checks["agent_receipt_present"] = bool(receipt)
    checks["governor_explicit_receipt_valid"] = (
        governor.is_file()
        and receipt.get("governor_ref") == manifest["governor_ref"]
        and receipt.get("governor_sha256") == _sha256(governor)
    )

    task_path = project / ".agent-work" / task_id / "task.yaml"
    task = _load_yaml(task_path)
    checks["task_provider_stable"] = (
        str((task.get("execution") or {}).get("orchestrator_provider") or "codex") == provider
    )

    runtime_evidence: dict[str, object] = {}
    for role in ("context_scout", "memory_scout"):
        planned, completed = _find_completed_role(task, role)
        role_checks = {
            "planned": planned is not None,
            "completed": completed is not None,
            "inheritance_none": bool(
                planned
                and (planned.get("context") or {}).get("inheritance") == "none"
            ),
        }
        if completed is not None:
            try:
                attested = _validate_completed_attestation(project, completed)
                role_checks["attestation_valid"] = True
                role_checks["attestation"] = attested
            except (OSError, ValueError, RuntimeError) as error:
                role_checks["attestation_valid"] = False
                role_checks["attestation_error"] = str(error)
        else:
            role_checks["attestation_valid"] = False
        returned = receipt.get(role) if isinstance(receipt, dict) else None
        role_checks["parent_received_result"] = bool(
            completed
            and isinstance(returned, dict)
            and returned.get("delegation") == completed.get("id")
            and returned.get("result_ref") == completed.get("output_ref")
            and returned.get("outcome") == "completed"
        )
        runtime_evidence[role] = role_checks
    checks["delegations"] = runtime_evidence

    validate = _run(
        [
            sys.executable,
            str(project / ".harness" / "sitter" / "runtime" / "work.py"),
            "--project",
            str(project),
            "validate",
            task_id,
        ],
        cwd=project,
        check=False,
    )
    checks["work_graph_valid"] = validate.returncode == 0 and bool(receipt.get("work_graph_valid"))

    role_passes = all(
        bool(value.get("planned"))
        and bool(value.get("completed"))
        and bool(value.get("inheritance_none"))
        and bool(value.get("attestation_valid"))
        and bool(value.get("parent_received_result"))
        for value in runtime_evidence.values()
    )
    passed = all(
        bool(checks[key])
        for key in (
            "session_start_evidence_present",
            "session_start_hook_effective",
            "parent_received_session_context",
            "agent_receipt_present",
            "governor_explicit_receipt_valid",
            "task_provider_stable",
            "work_graph_valid",
        )
    ) and role_passes

    return {
        "schema_version": 1,
        "provider": provider,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "session_start_evidence": session_evidence,
        "all_session_start_event_count": len(parsed_events),
        "l3_black_box": True,
        "note": (
            "PASS requires a matching startup SessionStart event produced by the real fresh parent host session plus "
            "real provider-validated child attestations; later child/session hook events cannot replace the parent evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 real Codex/Claude black-box runtime smoke")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_cmd = subparsers.add_parser("prepare")
    prepare_cmd.add_argument("destination", type=Path)
    prepare_cmd.add_argument("--provider", choices=("codex", "claude"), required=True)
    prepare_cmd.add_argument("--force", action="store_true")

    verify_cmd = subparsers.add_parser("verify")
    verify_cmd.add_argument("project", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = prepare(args.destination, args.provider, args.force)
        else:
            value = verify(args.project)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
