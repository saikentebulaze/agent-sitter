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

    @staticmethod
    def _write_same_result(root: Path, *, selected_files: list[str], self_report_scout: bool = False) -> None:
        control = json.loads((root / "control.json").read_text(encoding="utf-8"))
        payload = {
            "schema_version": 1,
            "parent_model_label": "same-model-control",
            "selected_files": selected_files,
            "root_cause_files": list(BENCH.FIXTURE.manifest()["expected_root_cause"]),
            "conclusion_before_independent_exploration": False,
            "independent_exploration_completed": self_report_scout,
            "governed_task_id": None,
            "summary": "fixture result",
        }
        for side in ("baseline", "candidate"):
            result = Path(control[side]["result"])
            result.parent.mkdir(parents=True, exist_ok=True)
            result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_equal_ceiling_sample_passes_without_strict_improvement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            BENCH.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            self._write_same_result(
                root,
                selected_files=list(BENCH.FIXTURE.CLASSIFICATION["required"]),
            )

            score = BENCH.score(root)
            self.assertEqual(score["status"], "PASS")
            self.assertTrue(score["baseline"]["meets_v6_target"])
            self.assertTrue(score["candidate"]["meets_v6_target"])
            self.assertTrue(score["delta"]["baseline_at_ceiling"])
            self.assertFalse(score["delta"]["strict_improvement"])
            self.assertTrue(score["delta"]["comparison_requirement_met"])
            self.assertEqual(score["delta"]["comparison_mode"], "non-regressive-at-ceiling")

    def test_equal_non_ceiling_sample_still_requires_improvement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            BENCH.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            selected = list(BENCH.FIXTURE.CLASSIFICATION["required"])
            selected.append(BENCH.FIXTURE.CLASSIFICATION["decoy"][0])
            self._write_same_result(root, selected_files=selected)

            score = BENCH.score(root)
            self.assertEqual(score["status"], "FAIL")
            self.assertTrue(score["baseline"]["meets_v6_target"])
            self.assertTrue(score["candidate"]["meets_v6_target"])
            self.assertFalse(score["delta"]["baseline_at_ceiling"])
            self.assertFalse(score["delta"]["strict_improvement"])
            self.assertFalse(score["delta"]["comparison_requirement_met"])
            self.assertEqual(score["delta"]["comparison_mode"], "improvement-required")

    def test_score_ignores_self_report_without_attested_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ab"
            BENCH.prepare(
                root,
                baseline_ref="HEAD",
                candidate_ref="HEAD",
                model_label="same-model-control",
                force=False,
            )
            self._write_same_result(
                root,
                selected_files=list(BENCH.FIXTURE.CLASSIFICATION["required"]),
                self_report_scout=True,
            )

            score = BENCH.score(root)
            self.assertEqual(score["status"], "PASS")
            self.assertTrue(score["controls_valid"])
            self.assertFalse(score["baseline"]["independent_exploration_completed"])
            self.assertFalse(score["candidate"]["independent_exploration_completed"])
            self.assertEqual(score["candidate"]["actual_exploration"]["attested"], [])
            self.assertEqual(score["delta"]["comparison_mode"], "non-regressive-at-ceiling")

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
