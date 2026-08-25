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
from complete_after_approval import CompleteAfterApprovalError, complete_after_approval  # noqa: E402
from governed_work import create_investigation  # noqa: E402
from test_v62_atomic_review import load_yaml, write_yaml  # noqa: E402
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
            self.assertEqual(task_data["learning"]["closeout"]["status"], "pending")

    def test_repeating_completed_closure_is_idempotent_done(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, task, _ = prepare_task_candidate(Path(directory))
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            first = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch(),
            )
            self.assertEqual(first["status"], "done")
            self.assertFalse(first["idempotent"])
            second = complete_after_approval(context, "chg-v63")
            self.assertEqual(second["status"], "done")
            self.assertTrue(second["idempotent"])
            self.assertEqual(load_yaml(task / "task.yaml")["status"], "completed")

    def test_governance_only_retry_rejects_redundant_verification_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, _, change = prepare_task_candidate(Path(directory))
            data = load_yaml(change / "change.yaml")
            data["knowledge_sync"]["entries"] = [{"id": "K01"}]
            write_yaml(change / "change.yaml", data)
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            first = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch(),
            )
            self.assertEqual(first["governance_closure"], "knowledge-review")
            before = (change / "change.yaml").read_bytes()
            with self.assertRaisesRegex(
                CompleteAfterApprovalError,
                "resume governance-only closure without --verification-batch",
            ):
                complete_after_approval(
                    context,
                    "chg-v63",
                    verification_batch=verification_batch(),
                )
            self.assertEqual((change / "change.yaml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
