from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-fast-path-ab.py"
SPEC = importlib.util.spec_from_file_location("v6_fast_path_ab", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FAST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FAST)


class V6FastPathABProtocolTests(unittest.TestCase):
    def test_prepare_has_identical_heavy_history_fixture_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fast-ab"
            prepared = FAST.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            self.assertEqual(prepared["status"], "PREPARED_NOT_RUN")
            control = json.loads((root / "control.json").read_text(encoding="utf-8"))
            self.assertEqual(
                control["baseline"]["fixture_sha256"],
                control["candidate"]["fixture_sha256"],
            )
            self.assertEqual(
                control["baseline"]["prompt_sha256"],
                control["candidate"]["prompt_sha256"],
            )
            for side in ("baseline", "candidate"):
                project = Path(control[side]["project"])
                active = (project / ".agent-work" / "_context" / "active-tasks.yaml").read_text(
                    encoding="utf-8"
                )
                archive = (project / ".agent-work" / "_archive" / "archive-index.yaml").read_text(
                    encoding="utf-8"
                )
                knowledge = (project / "knowledge" / "index.yaml").read_text(encoding="utf-8")
                self.assertIn("unrelated-active-one", active)
                self.assertIn("archived-task-0999", archive)
                self.assertIn("FAST-HIST-099", knowledge)

    def test_prepare_alone_cannot_pass_and_creates_no_governed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fast-ab"
            FAST.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            control = json.loads((root / "control.json").read_text(encoding="utf-8"))
            for side in ("baseline", "candidate"):
                project = Path(control[side]["project"])
                result = project / FAST.RESULT_REF
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "parent_model_label": "same-model-control",
                            "test_passed": False,
                            "changed_source": "src/fast_path.py",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            score = FAST.score(root)
            self.assertEqual(score["status"], "FAIL")
            self.assertTrue(score["controls_valid"])
            self.assertEqual(score["baseline"]["task_dirs"], [])
            self.assertEqual(score["candidate"]["task_dirs"], [])
            self.assertFalse(score["candidate"]["checks"]["source_is_minimal_rename"])

    def test_exact_minimal_edit_can_pass_without_governance_overhead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fast-ab"
            FAST.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            control = json.loads((root / "control.json").read_text(encoding="utf-8"))
            receipt = {
                "schema_version": 1,
                "parent_model_label": "same-model-control",
                "test_passed": True,
                "changed_source": FAST.MUTABLE_TARGET,
            }
            for side in ("baseline", "candidate"):
                project = Path(control[side]["project"])
                (project / FAST.MUTABLE_TARGET).write_text(
                    FAST.EXPECTED_SOURCE,
                    encoding="utf-8",
                )
                result = project / FAST.RESULT_REF
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

            score = FAST.score(root)
            diagnostic = json.dumps(score, ensure_ascii=False, indent=2)
            self.assertTrue(score["controls_valid"], diagnostic)
            self.assertTrue(score["baseline"]["absolute_pass"], diagnostic)
            self.assertTrue(score["candidate"]["absolute_pass"], diagnostic)
            self.assertTrue(score["no_overhead_regression"], diagnostic)
            self.assertEqual(score["status"], "PASS", diagnostic)
            self.assertEqual(score["candidate"]["governance_artifact_count"], 0, diagnostic)
            self.assertEqual(score["candidate"]["tracked_diff"], [FAST.MUTABLE_TARGET], diagnostic)
            self.assertEqual(
                score["fast_path_overhead_delta"]["governance_artifacts"], 0, diagnostic
            )


if __name__ == "__main__":
    unittest.main()
