from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from archive_lifecycle import ArchiveLifecycleError, finalize_archive_cleanup  # noqa: E402
from change_lifecycle import advance_change, build_change_dashboard, record_user_review  # noqa: E402
from evidence_projection import record_verification  # noqa: E402
from knowledge_lifecycle import KnowledgeLifecycleError, defer_knowledge  # noqa: E402
from readiness import record_readiness  # noqa: E402
from review_runner import run_atomic_review  # noqa: E402
from test_v62_atomic_review import (  # noqa: E402
    fake_role_runner,
    load_yaml,
    make_project,
    prepare_change,
    write_yaml,
)
from test_v62_prepare_candidate import pass_runner, setup_fixture  # noqa: E402
from prepare_candidate import PrepareCandidateError, prepare_candidate  # noqa: E402


PASS_VERDICT = (
    "  architecture: pass\n"
    "  scope: pass\n"
    "  numerical_evidence: pass\n"
    "  remediation_route: null\n"
)


def write_manifest_lock(project: Path) -> None:
    lock = project / ".harness/sitter/manifest-lock.yaml"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")


class V62RC2ClosureTests(unittest.TestCase):
    def test_zero_candidate_defer_revised_hold_and_archive_close_legally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            write_manifest_lock(project)
            change = prepare_change(project, context)
            run_atomic_review(
                context,
                "chg-one",
                role_runner=fake_role_runner(PASS_VERDICT),
            )
            self.assertEqual(advance_change(context, "chg-one"), "candidate-review")
            record_user_review(
                context,
                "chg-one",
                decision="approved",
                evidence="fixture human acceptance",
            )
            self.assertEqual(advance_change(context, "chg-one"), "verifying")
            record_verification(
                context,
                "chg-one",
                result_id="full-regression",
                kind="regression",
                result="pass",
                command_or_entry="fixture regression",
                evidence="fixture:final-pass",
                observed="final fixture verification passed",
            )
            self.assertEqual(advance_change(context, "chg-one"), "syncing")

            dashboard = build_change_dashboard(context, "chg-one")
            self.assertEqual(dashboard["allowed_next"], ["defer-knowledge"])
            self.assertIn("no durable candidates", dashboard["ACTION REQUIRED"][0])
            self.assertEqual(
                defer_knowledge(
                    context,
                    "chg-one",
                    reason="No durable project knowledge from this fixture",
                ),
                "deferred",
            )

            dashboard = build_change_dashboard(context, "chg-one")
            self.assertEqual(dashboard["allowed_next"], ["finalize-archive-cleanup"])
            self.assertEqual(
                finalize_archive_cleanup(
                    context,
                    "chg-one",
                    evidence="Task experiments inspected; no development artifacts remain",
                ),
                "complete",
            )

            # Reproduce the real revise-change archive hold. A fresh readiness,
            # review, human acceptance and final verification cycle has already
            # covered the current snapshot, so this historical hold must clear.
            data = load_yaml(change / "change.yaml")
            data["archive"]["blockers"] = ["change revised after investigation"]
            write_yaml(change / "change.yaml", data)

            self.assertEqual(advance_change(context, "chg-one"), "ready-to-archive")
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["archive"]["blockers"], [])

            archived = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME / "archive_change.py"),
                    str(change),
                    "--project",
                    str(project),
                ],
                cwd=project,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(archived.returncode, 0, archived.stderr)
            archived_root = project / "changes/archive/chg-one"
            self.assertTrue(archived_root.is_dir())
            self.assertFalse(change.exists())
            self.assertEqual(load_yaml(archived_root / "change.yaml")["status"], "archived")

    def test_defer_requires_zero_candidates_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            data = load_yaml(change / "change.yaml")
            data["status"] = "syncing"
            data["knowledge_sync"]["entries"] = [{"id": "durable-one"}]
            write_yaml(change / "change.yaml", data)
            with self.assertRaisesRegex(KnowledgeLifecycleError, "candidates exist"):
                defer_knowledge(context, "chg-one", reason="not applicable")
            data = load_yaml(change / "change.yaml")
            data["knowledge_sync"]["entries"] = []
            write_yaml(change / "change.yaml", data)
            with self.assertRaisesRegex(KnowledgeLifecycleError, "reason is required"):
                defer_knowledge(context, "chg-one", reason="   ")

    def test_archive_cleanup_refuses_remaining_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            data = load_yaml(change / "change.yaml")
            data["status"] = "syncing"
            write_yaml(change / "change.yaml", data)
            experiment = project / ".agent-work/task-one/experiments/probe.txt"
            experiment.parent.mkdir(parents=True, exist_ok=True)
            experiment.write_text("development probe\n", encoding="utf-8")
            with self.assertRaisesRegex(ArchiveLifecycleError, "development experiments remain"):
                finalize_archive_cleanup(
                    context,
                    "chg-one",
                    evidence="cleanup checked",
                )
            self.assertFalse(load_yaml(change / "change.yaml")["archive"]["experiment_cleanup_complete"])

    def test_prepare_candidate_blocks_out_of_budget_artifact_before_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            output = project / "outputs/result.xlsx"
            output.parent.mkdir()
            output.write_bytes(b"fixture workbook artifact")

            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            data["change_budget"]["allowed_files"] = ["src.cpp"]
            write_yaml(change / "change.yaml", data)
            record_readiness(
                context,
                "chg",
                criterion_id="focused",
                result="pass",
                command_or_entry="focused fixture after generated artifact",
                evidence="fixture:focused-current",
            )

            calls: list[int] = []
            with self.assertRaisesRegex(
                PrepareCandidateError,
                "out-of-budget production/test paths.*outputs/result.xlsx",
            ):
                prepare_candidate(
                    context,
                    "chg",
                    role_runner=pass_runner(calls),
                )
            self.assertEqual(calls, [])
            self.assertFalse((change / "review-request.yaml").exists())


if __name__ == "__main__":
    unittest.main()
