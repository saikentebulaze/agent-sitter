from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from codex_managed_runtime import (  # noqa: E402
    CodexManagedRuntimeError,
    execute_managed_read_only,
)
from delegation_validation import validate_delegation_state  # noqa: E402
from managed_delegation_transaction import (  # noqa: E402
    record_managed_delegation_result,
)
from provider_attestation import validate_provider_attestation  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from work_graph import load_yaml  # noqa: E402


THREAD_ID = "019f-managed-thread"
TURN_ID = "019f-managed-turn"


class FakeManagedClient:
    def __init__(
        self,
        *,
        project: Path,
        sandbox: str = "readOnly",
        parent_thread_id: str | None = None,
    ) -> None:
        self.project = project
        self.sandbox = sandbox
        self.parent_thread_id = parent_thread_id
        self.raw_messages: list[dict] = []
        self.stderr = ""

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
        return None

    def request(
        self,
        method: str,
        params: dict,
        *,
        timeout: float | None = None,
    ) -> dict:
        self.raw_messages.append({"method": method, "params": params})
        thread = {
            "id": THREAD_ID,
            "parentThreadId": self.parent_thread_id,
            "forkedFromId": None,
            "cwd": str(self.project),
        }
        if method == "thread/start":
            return {
                "id": 1,
                "result": {
                    "thread": thread,
                    "model": "gpt-5.6-luna",
                    "reasoningEffort": "low",
                    "cwd": str(self.project),
                    "sandbox": {"type": self.sandbox, "networkAccess": False},
                    "activePermissionProfile": None,
                    "runtimeWorkspaceRoots": [str(self.project)],
                    "instructionSources": [str(self.project / "AGENTS.md")],
                },
            }
        if method == "turn/start":
            return {
                "id": 2,
                "result": {
                    "turn": {
                        "id": TURN_ID,
                        "status": "inProgress",
                        "items": [],
                    }
                },
            }
        if method == "thread/resume":
            return {
                "id": 3,
                "result": {
                    "thread": thread,
                    "model": "gpt-5.6-luna",
                    "reasoningEffort": "low",
                    "cwd": str(self.project),
                    "sandbox": {"type": self.sandbox, "networkAccess": False},
                    "activePermissionProfile": None,
                    "runtimeWorkspaceRoots": [str(self.project)],
                    "instructionSources": [str(self.project / "AGENTS.md")],
                },
            }
        if method == "thread/read":
            return {
                "id": 4,
                "result": {"thread": {**thread, "turns": []}},
            }
        raise AssertionError(method)

    def wait_for_notification(
        self,
        method: str,
        *,
        predicate=None,  # type: ignore[no-untyped-def]
        timeout: float | None = None,
        on_notification=None,  # type: ignore[no-untyped-def]
    ) -> dict:
        self.raw_messages.append({"wait": method})
        params = {
            "threadId": THREAD_ID,
            "turn": {
                "id": TURN_ID,
                "status": "completed",
                "items": [
                    {
                        "id": "item-1",
                        "type": "agentMessage",
                        "text": "# Findings\n\nManaged read-only result.",
                    }
                ],
            },
        }
        if predicate is not None and not predicate(params):
            raise AssertionError("predicate rejected test notification")
        return {"jsonrpc": "2.0", "method": method, "params": params}


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", str(project)],
        check=True,
        text=True,
        capture_output=True,
    )
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        "package: sitter\nformat_version: 1\n",
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "src" / "anchor.cpp").write_text("// anchor\n", encoding="utf-8")
    return project


def run_script(project: Path, script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def create_requested_delegation(project: Path) -> tuple[Path, dict]:
    created = run_script(
        project,
        "create_task.py",
        "managed-smoke",
        "--title",
        "Managed delegation smoke",
        "--entry",
        "change",
        "--change-id",
        "managed-change",
        "--project",
        project,
    )
    if created.returncode:
        raise AssertionError(created.stderr)
    authorized = run_script(
        project,
        "work.py",
        "--project",
        project,
        "authorize-delegation",
        "managed-smoke",
        "--decision",
        "required",
        "--scope",
        "readonly-exploration",
        "--evidence",
        "test authorization",
        "--parent-model",
        "gpt-5.6-terra",
        "--parent-tier",
        "terra",
    )
    if authorized.returncode:
        raise AssertionError(authorized.stderr)
    requested = run_script(
        project,
        "work.py",
        "--project",
        project,
        "request-delegation",
        "managed-smoke",
        "--role",
        "source_locator",
        "--target-type",
        "change",
        "--target-ref",
        "managed-change",
        "--purpose",
        "locate managed runtime evidence",
        "--question",
        "Where is the managed runtime implemented?",
        "--decision-supported",
        "Decide whether the managed path is auditable.",
        "--include",
        "managed-runtime",
        "--start-ref",
        "src/anchor.cpp",
    )
    if requested.returncode:
        raise AssertionError(requested.stderr)
    request_path = project / requested.stdout.strip()
    return request_path, load_yaml(request_path)


class ManagedRuntimeTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def runtime_packet(self, project: Path, packet: dict) -> dict:
        value = dict(packet)
        value["project_root"] = str(project.resolve())
        return value

    def test_managed_read_only_thread_returns_verified_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            _, packet = create_requested_delegation(project)
            output, attestation, evidence = execute_managed_read_only(
                self.context(project),
                self.runtime_packet(project, packet),
                message="Read the frozen request.",
                client_factory=lambda: FakeManagedClient(project=project),
                version_provider=lambda: "codex-cli test",
            )
            self.assertIn("Managed read-only result", output)
            self.assertEqual(
                attestation["execution"]["method"],
                "app-server-isolated-agent",
            )
            self.assertEqual(
                attestation["observed"]["sandbox_mode"],
                "read-only",
            )
            self.assertIsNone(attestation["observed"]["parent_thread_id"])
            self.assertEqual(
                evidence["thread_start_params"]["sandbox"],
                "read-only",
            )
            runtime_evidence = validate_provider_attestation(
                self.runtime_packet(project, packet),
                attestation,
            )
            self.assertEqual(runtime_evidence.provider, "codex")
            self.assertEqual(runtime_evidence.role_id, "source_locator")
            attestation["observed"]["context_inheritance"] = "full"
            with self.assertRaisesRegex(
                CodexManagedRuntimeError,
                "context_inheritance",
            ):
                validate_provider_attestation(
                    self.runtime_packet(project, packet),
                    attestation,
                )

    def test_managed_workspace_write_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            _, packet = create_requested_delegation(project)
            with self.assertRaisesRegex(
                CodexManagedRuntimeError,
                "sandbox",
            ):
                execute_managed_read_only(
                    self.context(project),
                    self.runtime_packet(project, packet),
                    message="Read the frozen request.",
                    client_factory=lambda: FakeManagedClient(
                        project=project,
                        sandbox="workspaceWrite",
                    ),
                    version_provider=lambda: "codex-cli test",
                )

    def test_managed_parent_thread_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            _, packet = create_requested_delegation(project)
            with self.assertRaisesRegex(
                CodexManagedRuntimeError,
                "parentThreadId",
            ):
                execute_managed_read_only(
                    self.context(project),
                    self.runtime_packet(project, packet),
                    message="Read the frozen request.",
                    client_factory=lambda: FakeManagedClient(
                        project=project,
                        parent_thread_id="unexpected-parent",
                    ),
                    version_provider=lambda: "codex-cli test",
                )

    def test_managed_runtime_rejects_a_claude_bound_task_before_profile_loading(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            created = run_script(
                project,
                "create_task.py",
                "claude-managed-smoke",
                "--title",
                "Claude managed delegation smoke",
                "--entry",
                "investigation",
                "--provider",
                "claude",
                "--signature",
                "claude-managed-smoke",
                "--project",
                project,
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            rejected = run_script(
                project,
                "delegation_runtime.py",
                "--project",
                project,
                "run-isolated",
                "claude-managed-smoke",
                "dlg-001",
            )

            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "Codex runtime cannot execute a non-Codex Task",
                rejected.stderr,
            )

    def test_managed_result_records_truthful_execution_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            request_path, packet = create_requested_delegation(project)
            context = self.context(project)
            output, attestation, evidence = execute_managed_read_only(
                context,
                self.runtime_packet(project, packet),
                message="Read the frozen request.",
                client_factory=lambda: FakeManagedClient(project=project),
                version_provider=lambda: "codex-cli test",
            )
            directory_path = request_path.parent
            output_path = directory_path / "attempt-01.result-candidate.md"
            attestation_path = directory_path / "attempt-01.runtime-attestation.yaml"
            evidence_path = directory_path / "attempt-01.runtime-evidence.json"
            output_path.write_text(output + "\n", encoding="utf-8")
            attestation_path.write_text(
                yaml.safe_dump(attestation, sort_keys=False),
                encoding="utf-8",
            )
            evidence_path.write_text(
                json.dumps(evidence, indent=2) + "\n",
                encoding="utf-8",
            )
            result_path, outcome, _ = record_managed_delegation_result(
                context,
                "managed-smoke",
                "dlg-001",
                artifact=output_path,
                outcome="completed",
                evidence_ref=f"app-server-thread:{THREAD_ID}",
                attestation=attestation_path,
            )
            self.assertEqual(outcome, "completed")
            self.assertTrue(result_path.is_file())
            task_root = project / ".agent-work" / "managed-smoke"
            task = load_yaml(task_root / "task.yaml")
            self.assertEqual(
                task["delegation"]["completed"][0]["execution"],
                "app-server-isolated-agent",
            )
            validate_delegation_state(context, task_root, task)


if __name__ == "__main__":
    unittest.main()
