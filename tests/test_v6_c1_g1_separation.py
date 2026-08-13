from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-ab-benchmark.py"
SPEC = importlib.util.spec_from_file_location("v6_ab_c1_g1_separation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class V6C1G1SeparationTests(unittest.TestCase):
    @staticmethod
    def _project(root: Path, risk: str) -> Path:
        project = root / risk
        task_root = project / ".agent-work" / "c1-task"
        investigations = task_root / "investigations"
        investigations.mkdir(parents=True)
        task = {
            "id": "c1-task",
            "work_risk": {
                "current": {"semantic": risk, "repository_change": "medium"},
                "peak": {"semantic": risk, "repository_change": "medium"},
                "history": [],
            },
            "delegation": {"planned": [], "completed": [], "failed": []},
        }
        (task_root / "task.yaml").write_text(
            yaml.safe_dump(task, sort_keys=False),
            encoding="utf-8",
        )
        (investigations / "inv-001.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "inv-001",
                    "task_id": "c1-task",
                    "status": "concluded",
                    "execution_state": "active",
                    "decisions": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        result = {
            "schema_version": 1,
            "parent_model_label": "same-model",
            "selected_files": list(BENCH.FIXTURE.CLASSIFICATION["required"]),
            "root_cause_files": list(BENCH.FIXTURE.manifest()["expected_root_cause"]),
            "conclusion_before_independent_exploration": False,
            "independent_exploration_completed": False,
            "governed_task_id": "c1-task",
            "summary": "Planner owns the defect after reading the required chain.",
        }
        output = project / BENCH.RESULT_REF
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return project

    def test_c1_absolute_target_does_not_require_scout_by_itself(self) -> None:
        score = BENCH.FIXTURE.score_result(
            {
                "selected_files": list(BENCH.FIXTURE.CLASSIFICATION["required"]),
                "independent_exploration_completed": False,
                "conclusion_before_independent_exploration": False,
            }
        )
        self.assertEqual(score["required_context_recall"], 1.0)
        self.assertFalse(score["independent_exploration_completed"])
        self.assertTrue(score["meets_v6_target"])

    def test_medium_c1_final_truth_without_scout_is_not_a_g1_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory), "medium")
            score = BENCH._score_side(project, "same-model")
            self.assertTrue(score["meets_v6_target"])
            self.assertFalse(score["premature_convergence"])
            self.assertFalse(score["independent_exploration_completed"])
            actual = score["actual_exploration"]
            self.assertEqual(actual["exploration_required_task_ids"], [])
            self.assertFalse(actual["governed_final_truth_without_exploration"])
            self.assertFalse(actual["task_risks"]["c1-task"]["g1_exploration_required"])

    def test_high_c1_final_truth_without_scout_remains_premature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory), "high")
            score = BENCH._score_side(project, "same-model")
            self.assertFalse(score["meets_v6_target"])
            self.assertTrue(score["premature_convergence"])
            self.assertFalse(score["independent_exploration_completed"])
            actual = score["actual_exploration"]
            self.assertEqual(actual["exploration_required_task_ids"], ["c1-task"])
            self.assertTrue(actual["governed_final_truth_without_exploration"])
            self.assertTrue(actual["task_risks"]["c1-task"]["g1_exploration_required"])

    def test_invalid_v6_risk_fails_closed_for_g1_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory), "medium")
            task_path = project / ".agent-work" / "c1-task" / "task.yaml"
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            task["work_risk"]["current"]["semantic"] = "mystery"
            task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
            score = BENCH._score_side(project, "same-model")
            self.assertTrue(score["premature_convergence"])
            actual = score["actual_exploration"]
            self.assertEqual(actual["exploration_required_task_ids"], ["c1-task"])
            self.assertEqual(actual["task_risks"]["c1-task"]["current"], "invalid")


if __name__ == "__main__":
    unittest.main()
