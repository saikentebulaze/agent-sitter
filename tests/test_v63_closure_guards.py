from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TESTS = ROOT / "tests"
for path in (RUNTIME, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _learning_impl import command_observe  # noqa: E402
from change_lifecycle import record_user_review  # noqa: E402
from complete_after_approval import complete_after_approval  # noqa: E402
from governed_work import create_investigation  # noqa: E402
from test_v62_atomic_review import load_yaml  # noqa: E402
from test_v63_normal_path import prepare_task_candidate, verification_batch  # noqa: E402


class V63ClosureGuardTests(unittest.TestCase):
    def test_ordinary_learning_observation_is_preserved_without_extra_human_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, task, _ = prepare_task_candidate(Path(directory))
            command_observe(
                context,
                task / "task.yaml",
                key="v63 ordinary fixture observation",
                title="V6.3 ordinary fixture observation",
                kind="fact",
                scope="project",
                category="v63-normal-path",
                evidence=["fixture:ordinary-learning"],
                workaround=None,
                candidate_target="project-knowledge",
                verified_success=False,
                verified_failure=False,
                immediate=False,
            )
            observed = load_yaml(task / "task.yaml")["learning"]["observations"]
            self.assertEqual(len(observed), 1)
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            result = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch(),
            )
            self.assertEqual(result["status"], "done")
            task_data = load_yaml(task / "task.yaml")
            self.assertEqual(task_data["learning"]["observations"], observed)
            self.assertEqual(task_data["learning"]["closeout"]["observations_added"], 1)
            self.assertFalse(task_data["learning"]["user_attention"]["required"])
            inbox = load_yaml(project / ".agent-work/_learning/inbox.yaml")
            entry = next(item for item in inbox["entries"] if item["id"] == observed[0])
            self.assertEqual(entry["status"], "watching")

    def test_open_task_work_blocks_accidental_task_completion_after_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, task, _ = prepare_task_candidate(Path(directory))
            investigation_id = create_investigation(
                context,
                "task-v63",
                title="Follow-up investigation",
                question="Does follow-up work remain?",
                signature="v63-follow-up",
            )
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            result = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch(),
            )
            self.assertEqual(result["governance_closure"], "task-work-remains")
            self.assertTrue(result["engineering_complete"])
            self.assertTrue((project / "changes/archive/chg-v63").is_dir())
            task_data = load_yaml(task / "task.yaml")
            self.assertEqual(task_data["status"], "active")
            self.assertEqual(
                task_data["current_focus"],
                {"type": "investigation", "ref": investigation_id},
            )


if __name__ == "__main__":
    unittest.main()
