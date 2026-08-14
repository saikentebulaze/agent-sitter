from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from delegate_once import infer_outcome  # noqa: E402

SCRIPT = ROOT / "scripts" / "acceptance" / "v6-ab-benchmark.py"
SPEC = importlib.util.spec_from_file_location("v6_ab_benchmark_need_context", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class V6C1NeedContextRegressionTests(unittest.TestCase):
    def test_runtime_inference_recognizes_structured_need_context_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = {
                "marker.md": "**NEED_CONTEXT**\n\nMissing source context.\n",
                "yaml.md": "status: NEED_CONTEXT\nrepository_scan: false\n",
                "json.md": '{\n  "status": "NEED_CONTEXT",\n  "repository_scan": false\n}\n',
                "bullet.md": "- status: NEED_CONTEXT\n",
            }
            for name, text in samples.items():
                path = root / name
                path.write_text(text, encoding="utf-8")
                with self.subTest(name=name):
                    self.assertEqual(infer_outcome(path), "need-context")

            prose = root / "prose.md"
            prose.write_text(
                "The protocol mentions status: NEED_CONTEXT, but this result is complete.\n",
                encoding="utf-8",
            )
            self.assertEqual(infer_outcome(prose), "completed")

    def test_c1_scorer_requires_semantically_completed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            delegation_dir = (
                project
                / ".agent-work"
                / "demo"
                / "delegations"
                / "dlg-001"
            )
            delegation_dir.mkdir(parents=True)
            runtime = project / ".harness" / "sitter" / "runtime"
            runtime.mkdir(parents=True)

            request_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.request.yaml"
            record_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.record.yaml"
            output_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.result.md"
            request = project / request_ref
            record = project / record_ref
            output = project / output_ref
            request.write_text("schema_version: 2\n", encoding="utf-8")
            record.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "delegation_id": "dlg-001",
                        "attempt": 1,
                        "outcome": "completed",
                        "requested_outcome": "completed",
                        "request_ref": request_ref,
                        "output_ref": output_ref,
                        "attestation": {"schema_version": 2},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            task = {
                "id": "demo",
                "delegation": {
                    "planned": [
                        {
                            "id": "dlg-001",
                            "agent": "context_scout",
                        }
                    ],
                    "completed": [
                        {
                            "id": "dlg-001",
                            "context": {"request_ref": request_ref},
                            "record_ref": record_ref,
                            "output_ref": output_ref,
                        }
                    ],
                },
            }
            task_path = project / ".agent-work" / "demo" / "task.yaml"
            task_path.write_text(
                yaml.safe_dump(task, sort_keys=False),
                encoding="utf-8",
            )

            attestation_success = subprocess.CompletedProcess(
                args=["validator"],
                returncode=0,
                stdout=json.dumps(
                    {
                        "provider": "codex",
                        "role_id": "context_scout",
                        "context_isolation": "fresh",
                        "write_isolation": "os-readonly",
                        "attestation_strength": "runtime-observed",
                    }
                ),
                stderr="",
            )

            output.write_text(
                "# Key conclusions\n\nThe bounded repository chain was inspected.\n",
                encoding="utf-8",
            )
            with patch.object(BENCH, "_run", return_value=attestation_success) as run_mock:
                positive = BENCH._actual_exploration(project)
            self.assertTrue(positive["completed"])
            self.assertEqual(positive["delegation_ids"], ["dlg-001"])
            self.assertEqual(len(positive["attested"]), 1)
            self.assertEqual(positive["rejected_unattested"], [])
            run_mock.assert_called_once()

            # Live failure shape: the runtime record says completed and carries a
            # valid Provider attestation, but the actual child output explicitly
            # says it needs more context and performed no repository scan.
            output.write_text(
                "status: NEED_CONTEXT\nrepository_scan: false\n"
                "summary: More bounded context is required before exploration.\n",
                encoding="utf-8",
            )
            with patch.object(BENCH, "_run", return_value=attestation_success) as run_mock:
                negative = BENCH._actual_exploration(project)
            self.assertFalse(negative["completed"])
            self.assertEqual(negative["delegation_ids"], [])
            self.assertEqual(negative["attested"], [])
            self.assertEqual(len(negative["rejected_unattested"]), 1)
            rejected = negative["rejected_unattested"][0]
            self.assertEqual(rejected["semantic_status"], "need-context")
            self.assertIn("NEED_CONTEXT", rejected["error"])
            run_mock.assert_not_called()

    def test_c1_scorer_rejects_noncompleted_record_even_if_task_collection_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            delegation_dir = project / ".agent-work" / "demo" / "delegations" / "dlg-001"
            delegation_dir.mkdir(parents=True)
            (project / ".harness" / "sitter" / "runtime").mkdir(parents=True)

            request_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.request.yaml"
            record_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.record.yaml"
            output_ref = ".agent-work/demo/delegations/dlg-001/attempt-01.result.md"
            (project / request_ref).write_text("schema_version: 2\n", encoding="utf-8")
            (project / output_ref).write_text("# Key conclusions\n\nDone.\n", encoding="utf-8")
            (project / record_ref).write_text(
                yaml.safe_dump(
                    {
                        "outcome": "need-context",
                        "requested_outcome": "need-context",
                        "request_ref": request_ref,
                        "output_ref": output_ref,
                        "attestation": {"schema_version": 2},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            completed = {
                "context": {"request_ref": request_ref},
                "record_ref": record_ref,
                "output_ref": output_ref,
            }
            with patch.object(BENCH, "_run") as run_mock:
                valid, evidence = BENCH._validate_completed_attestation(project, completed)
            self.assertFalse(valid)
            self.assertEqual(evidence["recorded_outcome"], "need-context")
            self.assertIn("not completed", evidence["error"])
            run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
