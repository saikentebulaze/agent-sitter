from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from delegate_once import DelegateOnceError, delegate_once, infer_outcome  # noqa: E402
from project_context import ProjectContext  # noqa: E402


def context_for(root: Path, provider: str) -> tuple[ProjectContext, Path]:
    project = root / "project"
    task_root = project / ".agent-work" / "demo"
    task_root.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 4,
                "id": "demo",
                "title": "Demo",
                "status": "active",
                "execution": {"orchestrator_provider": provider},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return ProjectContext(ROOT, project, ROOT / "adapters" / "default"), task_root


def fake_runtime_files(task_root: Path, provider: str) -> tuple[Path, Path, Path]:
    directory = task_root / "delegations" / "dlg-001"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "attempt-01.result-candidate.md"
    attestation = directory / "attempt-01.runtime-attestation.yaml"
    evidence = directory / "attempt-01.runtime-evidence.json"
    output.write_text("# Key conclusions\n\nDone.\n", encoding="utf-8")
    attestation.write_text("schema_version: 2\n", encoding="utf-8")
    evidence.write_text("{}\n", encoding="utf-8")
    return output, attestation, evidence


class DelegateOnceTests(unittest.TestCase):
    def test_outcome_inference_only_uses_structured_need_context_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = root / "completed.md"
            completed.write_text(
                "The protocol mentions NEED_CONTEXT but this result is complete.\n",
                encoding="utf-8",
            )
            blocked = root / "blocked.md"
            blocked.write_text(
                "# NEED_CONTEXT\n\nMissing one source file.\n",
                encoding="utf-8",
            )
            bold = root / "bold.md"
            bold.write_text(
                "**NEED_CONTEXT**\n\nMissing one source file.\n",
                encoding="utf-8",
            )
            italic = root / "italic.md"
            italic.write_text(
                "_NEED_CONTEXT_\n\nMissing one source file.\n",
                encoding="utf-8",
            )
            self.assertEqual(infer_outcome(completed), "completed")
            self.assertEqual(infer_outcome(blocked), "need-context")
            self.assertEqual(infer_outcome(bold), "need-context")
            self.assertEqual(infer_outcome(italic), "need-context")

    def test_codex_facade_requests_runs_and_records_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, task_root = context_for(Path(directory), "codex")
            request = task_root / "delegations" / "dlg-001" / "attempt-01.request.yaml"
            request.parent.mkdir(parents=True)
            request.write_text("schema_version: 2\n", encoding="utf-8")
            output, attestation, evidence = fake_runtime_files(task_root, "codex")
            result_path = request.parent / "attempt-01.result.md"
            result_path.write_text("recorded\n", encoding="utf-8")

            with (
                patch("delegate_once.request_delegation", return_value=request) as request_mock,
                patch(
                    "delegate_once.run_codex_isolated",
                    return_value=(output, attestation, evidence, {"execution": {"session_ref": "codex:test"}}),
                ) as run_mock,
                patch(
                    "delegate_once.record_codex_runtime",
                    return_value=(result_path, "completed", False),
                ) as record_mock,
            ):
                result = delegate_once(
                    context,
                    "demo",
                    role="context_scout",
                    target_type="task",
                    target_ref="demo",
                    purpose="find the relevant business chain",
                    question="Where is the state updated?",
                    decision_supported="whether implementation may proceed",
                    include=["src"],
                    exclude=[],
                    start_refs=[],
                    confirmed_facts=[],
                )

            request_mock.assert_called_once()
            run_mock.assert_called_once()
            record_mock.assert_called_once()
            self.assertEqual(result["provider"], "codex")
            self.assertEqual(result["delegation"], "dlg-001")
            self.assertEqual(result["outcome"], "completed")

    def test_claude_facade_uses_claude_managed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, task_root = context_for(Path(directory), "claude")
            request = task_root / "delegations" / "dlg-001" / "attempt-01.request.yaml"
            request.parent.mkdir(parents=True)
            request.write_text("schema_version: 2\n", encoding="utf-8")
            output, attestation, evidence = fake_runtime_files(task_root, "claude")
            output.write_text("**NEED_CONTEXT**\n\nNeed the test result.\n", encoding="utf-8")
            result_path = request.parent / "attempt-01.result.md"
            result_path.write_text("recorded\n", encoding="utf-8")

            with (
                patch("delegate_once.request_delegation", return_value=request),
                patch(
                    "delegate_once.run_claude_isolated",
                    return_value=(output, attestation, evidence),
                ) as run_mock,
                patch(
                    "delegate_once.record_claude_isolated_result",
                    return_value=(result_path, "need-context", False),
                ) as record_mock,
            ):
                result = delegate_once(
                    context,
                    "demo",
                    role="context_scout",
                    target_type="task",
                    target_ref="demo",
                    purpose="find the relevant business chain",
                    question="Where is the state updated?",
                    decision_supported="whether implementation may proceed",
                    include=["src"],
                    exclude=[],
                    start_refs=[],
                    confirmed_facts=[],
                )

            run_mock.assert_called_once()
            self.assertEqual(record_mock.call_args.kwargs["outcome"], "need-context")
            self.assertEqual(result["provider"], "claude")
            self.assertEqual(result["outcome"], "need-context")

    def test_claude_exclude_cannot_hide_frozen_request_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = context_for(Path(directory), "claude")
            with patch("delegate_once.request_delegation") as request_mock:
                with self.assertRaisesRegex(
                    DelegateOnceError,
                    "exclude covers the frozen request location",
                ):
                    delegate_once(
                        context,
                        "demo",
                        role="context_scout",
                        target_type="task",
                        target_ref="demo",
                        purpose="find the relevant business chain",
                        question="Where is the state updated?",
                        decision_supported="whether implementation may proceed",
                        include=["src"],
                        exclude=[".agent-work"],
                        start_refs=[],
                        confirmed_facts=[],
                    )
            request_mock.assert_not_called()

    def test_runtime_failure_does_not_record_false_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, task_root = context_for(Path(directory), "codex")
            request = task_root / "delegations" / "dlg-001" / "attempt-01.request.yaml"
            request.parent.mkdir(parents=True)
            request.write_text("schema_version: 2\n", encoding="utf-8")

            with (
                patch("delegate_once.request_delegation", return_value=request),
                patch("delegate_once.run_codex_isolated", side_effect=RuntimeError("runtime failed")),
                patch("delegate_once.record_codex_runtime") as record_mock,
            ):
                with self.assertRaisesRegex(RuntimeError, "runtime failed"):
                    delegate_once(
                        context,
                        "demo",
                        role="context_scout",
                        target_type="task",
                        target_ref="demo",
                        purpose="find the relevant business chain",
                        question="Where is the state updated?",
                        decision_supported="whether implementation may proceed",
                        include=["src"],
                        exclude=[],
                        start_refs=[],
                        confirmed_facts=[],
                    )
            record_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
