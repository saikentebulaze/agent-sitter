from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import install as installer  # noqa: E402
from claude_test_support import valid_claude_attestation  # noqa: E402
from delegation_transaction import _canonical_sha256, authorize_delegation, request_delegation  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from providers.claude import delegation_runtime  # noqa: E402
from work_graph import load_yaml  # noqa: E402


class ClaudeDelegationRuntimeTests(unittest.TestCase):
    def prepare(self, directory: str) -> tuple[Path, ProjectContext, Path]:
        project = Path(directory) / "project"; project.mkdir()
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
        installer.install(project, dry_run=False, provider_ids=("claude",))
        context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
        anchor = project / "src" / "anchor.cpp"; anchor.parent.mkdir(); anchor.write_text("// anchor\n", encoding="utf-8")
        task_root = initialize_provider_task(context, task_id="claude-runtime", title="Claude runtime", entry="investigation", provider_id="claude", signature="claude-runtime")
        authorize_delegation(context, "claude-runtime", decision="required", scopes=["readonly-exploration"], evidence="authorized", parent_model="haiku", parent_tier="low")
        request_path = request_delegation(context, "claude-runtime", role="context_scout", target_type="investigation", target_ref="inv-001", purpose="bounded runtime test", question="What owns the anchor?", decision_supported="Decide whether context is sufficient.", include=["src/anchor.cpp"], exclude=[], start_refs=["src/anchor.cpp"], confirmed_facts=["The anchor exists."])
        return task_root, context, request_path

    def runtime_result(self, packet: dict) -> tuple[str, dict, dict]:
        attestation = valid_claude_attestation(packet, request_hash=_canonical_sha256(packet), session_id="runtime-session")
        return "# Key conclusions\n\nManaged runtime result.", attestation, {"schema_version": 2, "attestation": attestation}

    def test_run_writes_exact_attempt_artifacts_and_record_closes_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_root, context, request_path = self.prepare(directory); packet = load_yaml(request_path)
            with mock.patch.object(delegation_runtime, "execute_managed_read_only", return_value=self.runtime_result(packet)) as executor:
                output, attestation, evidence = delegation_runtime.run_isolated(context, "claude-runtime", "dlg-001")
            executor.assert_called_once()
            self.assertEqual([output.name, attestation.name, evidence.name], ["attempt-01.result-candidate.md", "attempt-01.runtime-attestation.yaml", "attempt-01.runtime-evidence.json"])
            self.assertTrue(all(path.is_file() for path in (output, attestation, evidence)))
            result_path, outcome, repeated = delegation_runtime.record_isolated_result(context, "claude-runtime", "dlg-001", outcome="completed")
            self.assertEqual(outcome, "completed"); self.assertFalse(repeated); self.assertTrue(result_path.is_file())
            self.assertEqual(load_yaml(task_root / "task.yaml")["delegation"]["completed"][0]["execution"], "claude-managed-agent")

    def test_second_run_refuses_to_replace_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, request_path = self.prepare(directory); packet = load_yaml(request_path)
            with mock.patch.object(delegation_runtime, "execute_managed_read_only", return_value=self.runtime_result(packet)):
                delegation_runtime.run_isolated(context, "claude-runtime", "dlg-001")
                with self.assertRaisesRegex(delegation_runtime.ClaudeDelegationRuntimeError, "already exists"):
                    delegation_runtime.run_isolated(context, "claude-runtime", "dlg-001")

    def test_non_claude_task_cannot_use_claude_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"; project.mkdir(); context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            initialize_provider_task(context, task_id="codex-runtime", title="Codex runtime", entry="investigation", provider_id="codex", signature="codex-runtime")
            with self.assertRaisesRegex(delegation_runtime.ClaudeDelegationRuntimeError, "non-Claude Task"):
                delegation_runtime.load_attempt(context, "codex-runtime", "dlg-001")


if __name__ == "__main__": unittest.main()
