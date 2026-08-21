from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TESTS = ROOT / "tests"
for path in (RUNTIME, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _learning_impl import command_propose_durable  # noqa: E402
from change_lifecycle import record_user_review  # noqa: E402
from complete_after_approval import (  # noqa: E402
    CompleteAfterApprovalError,
    complete_after_approval,
)
from prepare_candidate import prepare_candidate  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from readiness import (  # noqa: E402
    ReadinessError,
    freeze_readiness_contract,
    record_readiness_batch,
)
from test_v62_atomic_review import fake_role_runner, load_yaml, write_yaml  # noqa: E402
from test_v62_rc2_closure import PASS_VERDICT, make_project, write_manifest_lock  # noqa: E402
from test_v62_prepare_candidate import setup_fixture  # noqa: E402


def readiness_batch() -> list[dict]:
    return [
        {
            "criterion_id": "focused-regression",
            "result": "pass",
            "command_or_entry": "fixture focused regression",
            "evidence": "fixture:focused-pass",
            "observed": "focused behavior passed",
        }
    ]


def verification_batch(result: str = "pass") -> list[dict]:
    return [
        {
            "id": "full-regression",
            "kind": "regression",
            "result": result,
            "command_or_entry": "fixture final regression",
            "evidence": f"fixture:final-{result}",
            "observed": f"final verification {result}",
        }
    ]


def prepare_task_candidate(root: Path):
    project, context = make_project(root)
    write_manifest_lock(project)
    task = initialize_provider_task(
        context,
        task_id="task-v63",
        title="V6.3 normal path",
        entry="change",
        provider_id="codex",
        change_id="chg-v63",
    )
    change = project / "changes/active/chg-v63"
    freeze_readiness_contract(context, "chg-v63")
    data = load_yaml(change / "change.yaml")
    data["status"] = "implementing"
    write_yaml(change / "change.yaml", data)
    result = prepare_candidate(
        context,
        "chg-v63",
        readiness_batch=readiness_batch(),
        role_runner=fake_role_runner(PASS_VERDICT),
    )
    if result["status"] != "candidate-review":
        raise AssertionError(result)
    return project, context, task, change


class V63BatchEvidenceTests(unittest.TestCase):
    def test_invalid_readiness_batch_has_zero_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            before = (change / "change.yaml").read_bytes()
            with self.assertRaisesRegex(ReadinessError, "unknown readiness criterion"):
                record_readiness_batch(
                    context,
                    "chg",
                    [
                        {
                            "criterion_id": "focused",
                            "result": "pass",
                            "command_or_entry": "valid first item",
                            "evidence": "fixture:first",
                        },
                        {
                            "criterion_id": "missing",
                            "result": "pass",
                            "command_or_entry": "invalid second item",
                            "evidence": "fixture:second",
                        },
                    ],
                )
            self.assertEqual((change / "change.yaml").read_bytes(), before)

    def test_prepare_candidate_accepts_batch_and_stops_for_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, change = prepare_task_candidate(Path(directory))
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "candidate-review")
            self.assertEqual(data["user_review"]["status"], "pending")
            self.assertEqual(data["review"]["status"], "pass")
            self.assertEqual(data["readiness"]["status"], "pass")


class V63CompleteAfterApprovalTests(unittest.TestCase):
    def test_no_approval_cannot_record_final_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, _, change = prepare_task_candidate(Path(directory))
            with self.assertRaisesRegex(
                CompleteAfterApprovalError,
                "user acceptance",
            ):
                complete_after_approval(
                    context,
                    "chg-v63",
                    verification_batch=verification_batch(),
                )
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "candidate-review")
            self.assertEqual((data.get("verification") or {}).get("latest_results") or [], [])

    def test_invalid_verification_batch_does_not_advance_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, _, change = prepare_task_candidate(Path(directory))
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            before = (change / "change.yaml").read_bytes()
            with self.assertRaisesRegex(
                CompleteAfterApprovalError,
                "verification result must be",
            ):
                complete_after_approval(
                    context,
                    "chg-v63",
                    verification_batch=[
                        {
                            "id": "invalid",
                            "kind": "regression",
                            "result": "unknown",
                            "command_or_entry": "fixture",
                            "evidence": "fixture:invalid",
                        }
                    ],
                )
            self.assertEqual((change / "change.yaml").read_bytes(), before)

    def test_verification_failure_stops_before_governance_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, _, change = prepare_task_candidate(Path(directory))
            record_user_review(
                context,
                "chg-v63",
                decision="approved",
                evidence="fixture acceptance",
            )
            result = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch("fail"),
            )
            self.assertEqual(result["status"], "verification-failed")
            self.assertFalse(result["engineering_complete"])
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "verifying")
            self.assertEqual(data["verification"]["status"], "fail")
            self.assertEqual(data["knowledge_sync"]["status"], "pending")

    def test_zero_knowledge_and_no_learning_complete_without_manual_ceremony(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, task, _ = prepare_task_candidate(Path(directory))
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
            self.assertTrue(result["engineering_complete"])
            self.assertTrue(result["task_completed"])
            archived = project / "changes/archive/chg-v63"
            self.assertTrue(archived.is_dir())
            change_data = load_yaml(archived / "change.yaml")
            self.assertEqual(change_data["knowledge_sync"]["status"], "deferred")
            task_data = load_yaml(task / "task.yaml")
            self.assertEqual(task_data["status"], "completed")
            self.assertEqual(task_data["learning"]["closeout"]["status"], "assessed")
            self.assertFalse(task_data["learning"]["user_attention"]["required"])

    def test_real_knowledge_candidate_stops_without_discard(self) -> None:
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
            result = complete_after_approval(
                context,
                "chg-v63",
                verification_batch=verification_batch(),
            )
            self.assertEqual(result["governance_closure"], "knowledge-review")
            self.assertTrue(result["engineering_complete"])
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "syncing")
            self.assertEqual(data["verification"]["status"], "pass")
            self.assertEqual(data["knowledge_sync"]["status"], "pending")
            self.assertEqual(data["knowledge_sync"]["entries"], [{"id": "K01"}])

    def test_cleanup_residue_stops_after_engineering_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, task, change = prepare_task_candidate(Path(directory))
            experiment = task / "experiments/probe.txt"
            experiment.parent.mkdir(parents=True, exist_ok=True)
            experiment.write_text("temporary probe\n", encoding="utf-8")
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
            self.assertEqual(result["governance_closure"], "cleanup")
            self.assertTrue(result["engineering_complete"])
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["verification"]["status"], "pass")
            self.assertEqual(data["knowledge_sync"]["status"], "deferred")
            self.assertFalse(data["archive"]["experiment_cleanup_complete"])

    def test_mature_learning_candidate_stops_after_archive_for_user_curation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, task, _ = prepare_task_candidate(Path(directory))
            command_propose_durable(
                context,
                task / "task.yaml",
                key="v63 durable fixture",
                title="V6.3 durable fixture",
                target="project-knowledge",
                summary="Stable reusable V6.3 fixture learning.",
                memory_key="v63-durable-fixture",
                evidence=["fixture:learning"],
                validity_surface=["src/solver.cpp"],
                trigger_terms=[],
                trigger_condition=None,
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
            self.assertEqual(result["governance_closure"], "learning-curation")
            self.assertTrue(result["engineering_complete"])
            self.assertTrue((project / "changes/archive/chg-v63").is_dir())
            task_data = load_yaml(task / "task.yaml")
            self.assertEqual(task_data["status"], "active")
            self.assertTrue(task_data["learning"]["user_attention"]["required"])
            self.assertEqual(task_data["learning"]["user_attention"]["decision"], "pending")


if __name__ == "__main__":
    unittest.main()
