from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "scripts" / "acceptance"


def load_module(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ACCEPTANCE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V6BehaviorBenchmarkTests(unittest.TestCase):
    def test_context_fixture_has_required_useful_decoy_and_scores_runs(self) -> None:
        module = load_module("context-coverage-fixture.py", "v6_context_fixture")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            manifest = module.create_fixture(root)
            self.assertTrue(manifest.is_file())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(data["classification"]["required"])
            self.assertTrue(data["classification"]["useful"])
            self.assertTrue(data["classification"]["decoy"])
            score = module.score_result({
                "selected_files": data["classification"]["required"],
                "independent_exploration_completed": True,
                "conclusion_before_independent_exploration": False,
            })
            self.assertEqual(score["required_context_recall"], 1.0)
            self.assertTrue(score["meets_v6_target"])

    def test_memory_evolution_oracle_covers_all_three_freshness_states(self) -> None:
        module = load_module("memory-evolution-fixture.py", "v6_memory_fixture")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "memory"
            module.create_fixture(repo)
            result = module.exercise_fixture(repo)
            self.assertTrue(result["oracle_matches"])
            observed = {item["observed"] for item in result["cases"]}
            self.assertEqual(observed, {"fresh", "suspect", "unknown"})

    def test_current_human_authority_baseline_is_observable_without_failing_ci(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ACCEPTANCE / "human-authority-fixture.py")],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["H2-material-decision-gate"]["current_validator_blocks"])
        self.assertIn("current_validator_allows_drift", data["H1-human-override"])

    def test_g1_probe_records_current_investigation_boundary_behavior(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ACCEPTANCE / "high-risk-governance-v6-fixture.py")],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["record-evidence"]["current_pass"])
        self.assertTrue(data["record-open-claim"]["current_pass"])
        self.assertTrue(data["experiment"]["current_pass"])
        for key in ("accepted-decision", "conclude-investigation", "pivot-to-change"):
            self.assertIn("current_pass", data[key])

    def test_unified_baseline_is_machine_readable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ACCEPTANCE / "v6-behavior-baseline.py")],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(
            data["baseline_source"],
            "main@f179c2ece4f5e428bfcd33d375c67f87a289e6cb",
        )
        self.assertFalse(data["G1-exploration-gate"]["g1_v6_pass"])
        self.assertTrue(
            data["G1-exploration-gate"]["accepted-decision"]["current_pass"]
        )
        self.assertFalse(data["task-status-dashboard"]["current_read_only"])
        self.assertTrue(data["task-status-dashboard"]["status_artifact_changed"])
        self.assertFalse(data["C7-open-thread"]["implemented"])
        for key in (
            "C1-context-coverage",
            "C2-independent-exploration",
            "H1-human-override",
            "H2-material-decision-gate",
            "G1-exploration-gate",
            "task-status-dashboard",
            "P1-long-term-cost",
            "P2-fast-path-cost",
            "R1-codex-runtime-smoke",
        ):
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
