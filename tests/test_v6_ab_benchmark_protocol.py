from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-ab-benchmark.py"
SPEC = importlib.util.spec_from_file_location("v6_ab_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class V6ABBenchmarkProtocolTests(unittest.TestCase):
    def test_root_cause_owner_is_distinct_from_required_ownership_chain(self) -> None:
        manifest = BENCH.FIXTURE.manifest()
        self.assertEqual(
            manifest["expected_root_cause"],
            ["src/planner/dispatch.py"],
        )
        self.assertIn(
            "src/state/session.py",
            manifest["classification"]["required"],
        )

    def test_prepare_uses_identical_fixture_and_prompt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            prepared = BENCH.prepare(
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
            self.assertEqual(control["model_label"], "same-model-control")
            baseline_prompt = Path(control["baseline"]["prompt"]).read_bytes()
            candidate_prompt = Path(control["candidate"]["prompt"]).read_bytes()
            self.assertEqual(baseline_prompt, candidate_prompt)

    def test_score_cannot_pass_from_self_report_without_attested_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            BENCH.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            control = json.loads((root / "control.json").read_text(encoding="utf-8"))
            payload = {
                "schema_version": 1,
                "parent_model_label": "same-model-control",
                "selected_files": list(BENCH.FIXTURE.CLASSIFICATION["required"]),
                "root_cause_files": list(BENCH.FIXTURE.manifest()["expected_root_cause"]),
                "conclusion_before_independent_exploration": False,
                "independent_exploration_completed": True,
                "governed_task_id": None,
                "summary": "self-reported perfect answer without real Scout evidence",
            }
            for side in ("baseline", "candidate"):
                result = Path(control[side]["result"])
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            score = BENCH.score(root)
            self.assertEqual(score["status"], "FAIL")
            self.assertTrue(score["controls_valid"])
            self.assertFalse(score["baseline"]["independent_exploration_completed"])
            self.assertFalse(score["candidate"]["independent_exploration_completed"])
            self.assertEqual(score["candidate"]["actual_exploration"]["attested"], [])

    def test_control_tampering_is_detected_before_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            BENCH.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            control = json.loads((root / "control.json").read_text(encoding="utf-8"))
            for side in ("baseline", "candidate"):
                result = Path(control[side]["result"])
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "parent_model_label": "same-model-control",
                            "selected_files": [],
                            "root_cause_files": [],
                            "conclusion_before_independent_exploration": False,
                            "independent_exploration_completed": False,
                            "governed_task_id": None,
                            "summary": "fixture",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            candidate_prompt = Path(control["candidate"]["prompt"])
            candidate_prompt.write_text("tampered prompt\n", encoding="utf-8")
            score = BENCH.score(root)
            self.assertEqual(score["status"], "FAIL")
            self.assertFalse(score["controls_valid"])


if __name__ == "__main__":
    unittest.main()
