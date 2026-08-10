from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from codex_runtime_attestation import (  # noqa: E402
    CodexRuntimeAttestationError,
    collect_native_attestation,
    find_spawn_evidence,
    validate_runtime_attestation,
)
from delegation_runtime import runtime_task_name, spawn_contract  # noqa: E402
from delegation_transaction import (  # noqa: E402
    DelegationTransactionError,
    _validate_attestation,
)
from project_context import ProjectContext  # noqa: E402


TASK_NAME = "sitter_dlg_001_a1_deadbeef1234"
CALL_ID = "call-runtime-proof"
CHILD_ID = "019f-child"
PARENT_ID = "019f-parent"
PROJECT = ROOT.resolve()


def write_rollout(
    codex_home: Path,
    *,
    duplicate: bool = False,
) -> Path:
    path = (
        codex_home
        / "sessions"
        / "2026"
        / "08"
        / "04"
        / "parent.jsonl"
    )
    path.parent.mkdir(parents=True)
    records = [
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "call_id": CALL_ID,
                "arguments": json.dumps(
                    {
                        "task_name": TASK_NAME,
                        "agent_type": "source_locator",
                        "fork_turns": "none",
                        "message": "redacted",
                    }
                ),
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": CALL_ID,
                "agent_thread_id": CHILD_ID,
                "kind": "started",
            },
        },
    ]
    if duplicate:
        records.append(records[0])
    path.write_text(
        "\n".join(json.dumps(row) for row in records) + "\n",
        encoding="utf-8",
    )
    return path


class FakeClient:
    def __init__(
        self,
        codex_home: Path,
        *,
        sandbox: str = "readOnly",
    ) -> None:
        self._codex_home = codex_home
        self._sandbox = sandbox
        self.raw_messages: list[dict] = []
        self.stderr = ""

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
        return None

    @property
    def codex_home(self) -> Path:
        return self._codex_home

    def request(self, method: str, params: dict) -> dict:
        self.raw_messages.append(
            {"method": method, "params": params}
        )
        thread = {
            "id": CHILD_ID,
            "parentThreadId": PARENT_ID,
            "agentRole": "source_locator",
            "agentNickname": "Darwin",
            "cwd": str(PROJECT),
        }
        if method == "thread/read":
            return {"id": 1, "result": {"thread": thread}}
        if method == "thread/resume":
            return {
                "id": 2,
                "result": {
                    "thread": thread,
                    "model": "gpt-5.6-luna",
                    "reasoningEffort": "low",
                    "cwd": str(PROJECT),
                    "sandbox": {
                        "type": self._sandbox,
                        "writableRoots": [],
                    },
                    "activePermissionProfile": None,
                    "runtimeWorkspaceRoots": [str(PROJECT)],
                    "instructionSources": [
                        str(PROJECT / "AGENTS.md")
                    ],
                },
            }
        raise AssertionError(method)


class CodexRuntimeAttestationTests(unittest.TestCase):
    def packet(self) -> dict:
        return {
            "project_root": str(PROJECT),
            "delegation": {
                "id": "dlg-001",
                "attempt": 1,
                "task_id": "task",
            },
            "requested_profile": {
                "agent": "source_locator",
                "model": "gpt-5.6-luna",
                "tier": "luna",
                "reasoning_effort": "low",
                "sandbox_mode": "read-only",
            },
            "runtime": {"task_name": TASK_NAME},
        }

    def test_exact_rollout_call_binds_child_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            parent = write_rollout(codex_home)
            evidence = find_spawn_evidence(
                codex_home,
                task_name=TASK_NAME,
            )
            self.assertEqual(evidence.parent_rollout, parent)
            self.assertEqual(evidence.call_id, CALL_ID)
            self.assertEqual(evidence.child_thread_id, CHILD_ID)
            self.assertEqual(evidence.fork_turns, "none")

    def test_ambiguous_spawn_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            write_rollout(codex_home, duplicate=True)
            with self.assertRaisesRegex(
                CodexRuntimeAttestationError,
                "exactly one",
            ):
                find_spawn_evidence(
                    codex_home,
                    task_name=TASK_NAME,
                )

    def test_observed_read_only_profile_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            write_rollout(codex_home)
            attestation, _ = collect_native_attestation(
                ProjectContext(PROJECT, PROJECT, PROJECT),
                self.packet(),
                client_factory=lambda: FakeClient(
                    codex_home,
                    sandbox="readOnly",
                ),
                version_provider=lambda: "codex-cli test",
            )
            self.assertEqual(
                attestation["observed"]["tier"],
                "luna",
            )
            validate_runtime_attestation(
                self.packet(),
                attestation,
            )

    def test_workspace_write_is_not_treated_as_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            write_rollout(codex_home)
            attestation, _ = collect_native_attestation(
                ProjectContext(PROJECT, PROJECT, PROJECT),
                self.packet(),
                client_factory=lambda: FakeClient(
                    codex_home,
                    sandbox="workspaceWrite",
                ),
                version_provider=lambda: "codex-cli test",
            )
            with self.assertRaisesRegex(
                CodexRuntimeAttestationError,
                "sandbox_mode",
            ):
                validate_runtime_attestation(
                    self.packet(),
                    attestation,
                )

    def test_legacy_manual_attestation_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            DelegationTransactionError,
            "schema_version must be 2",
        ):
            _validate_attestation(
                self.packet(),
                {
                    "schema_version": 1,
                    "execution": {"method": "native-subagent"},
                    "observed": self.packet()["requested_profile"],
                },
            )

    def test_spawn_contract_is_deterministic_and_explicit(self) -> None:
        context = ProjectContext(PROJECT, PROJECT, PROJECT)
        task = {"id": "task"}
        packet = {
            "delegation": {
                "id": "dlg-001",
                "attempt": 1,
            },
            "requested_profile": {
                "agent": "source_locator"
            },
        }
        request = (
            PROJECT
            / ".agent-work"
            / "task"
            / "delegations"
            / "dlg-001"
            / "attempt-01.request.yaml"
        )
        first = runtime_task_name(context, task, packet)
        second = runtime_task_name(context, task, packet)
        self.assertEqual(first, second)
        contract = spawn_contract(
            context,
            task,
            request,
            packet,
        )
        self.assertEqual(contract["task_name"], first)
        self.assertEqual(
            contract["agent_type"],
            "source_locator",
        )
        self.assertEqual(contract["fork_turns"], "none")


if __name__ == "__main__":
    unittest.main()
