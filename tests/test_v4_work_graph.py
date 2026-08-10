from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project


def run(project: Path, script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def work(project: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return run(project, "work.py", "--project", project, *args)


def harness(project: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return run(project, "harness.py", "--project", project, *args)


def create_investigation_task(project: Path, task_id: str = "demo") -> Path:
    result = run(
        project,
        "create_task.py",
        task_id,
        "--title", "Demo investigation",
        "--entry", "investigation",
        "--question", "Why does the result differ?",
        "--signature", "result-difference",
        "--project", project,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return project / ".agent-work" / task_id


def record_actionable_decision(project: Path, task: str, investigation: str, suffix: str) -> None:
    commands = [
        (
            "record-evidence", task, investigation,
            "--id", f"evd-{suffix}",
            "--kind", "experiment",
            "--source-ref", f"experiments/{suffix}",
            "--provenance", "bounded fixture evidence",
            "--reliability", "high",
        ),
        (
            "record-claim", task, investigation,
            "--id", f"clm-{suffix}",
            "--statement", "The bounded explanation is supported",
            "--status", "supported",
            "--confidence", "high",
            "--supporting-evidence", f"evd-{suffix}",
        ),
        (
            "record-decision", task, investigation,
            "--id", f"dec-{suffix}",
            "--statement", "Proceed with the bounded engineering action",
            "--status", "accepted",
            "--claim", f"clm-{suffix}",
            "--evidence", f"evd-{suffix}",
        ),
    ]
    for command in commands:
        result = work(project, *command)
        if result.returncode:
            raise AssertionError(result.stderr)


def create_change_from_investigation(project: Path) -> Path:
    create_investigation_task(project)
    record_actionable_decision(project, "demo", "inv-001", "001")
    result = work(
        project,
        "pivot-to-change", "demo", "inv-001", "demo-change",
        "--title", "Implement the confirmed fix",
        "--rationale", "supported",
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return project / "changes" / "active" / "demo-change"


class WorkGraphLifecycleTests(unittest.TestCase):
    def test_investigation_pivots_to_change_with_evidence_relations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root = create_investigation_task(project)
            record_actionable_decision(project, "demo", "inv-001", "001")

            result = work(
                project,
                "pivot-to-change", "demo", "inv-001", "demo-change",
                "--title", "Implement the confirmed fix",
                "--rationale", "The accepted decision is supported by bounded evidence",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(work(project, "validate", "demo").returncode, 0)

            task = yaml.safe_load((task_root / "task.yaml").read_text(encoding="utf-8"))
            change = yaml.safe_load(
                (project / "changes" / "active" / "demo-change" / "change.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(task["current_focus"], {"type": "change", "ref": "demo-change"})
            self.assertEqual(change["task_id"], "demo")
            self.assertEqual(change["relations"]["derived_from"]["investigations"], ["inv-001"])
            self.assertEqual(change["relations"]["derived_from"]["decisions"], ["dec-001"])

    def test_change_pivots_to_investigation_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            change_root = create_change_from_investigation(project)

            created = work(
                project,
                "investigate-change", "demo-change",
                "--title", "Unexpected verification result",
                "--question", "Why does the result remain different?",
                "--signature", "unexpected-verification-result",
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            change_path = change_root / "change.yaml"
            change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            self.assertEqual(change["execution_state"], "paused")
            self.assertEqual(change["hold"]["investigation_ref"], "inv-002")

            record_actionable_decision(project, "demo", "inv-002", "002")
            resumed = work(
                project,
                "conclude-investigation", "demo", "inv-002",
                "--disposition", "resume-change",
                "--target", "demo-change",
                "--rationale", "The approved scope and design remain valid",
                "--scope-revalidated", "--design-revalidated", "--approval-still-valid",
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            self.assertEqual(change["execution_state"], "active")
            self.assertEqual(len(change["resume_history"]), 1)

    def test_repeated_pivot_uses_frozen_model_review_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            create_change_from_investigation(project)
            self.assertEqual(
                work(
                    project,
                    "investigate-change", "demo-change",
                    "--title", "First unexpected result",
                    "--question", "Why?",
                    "--signature", "unexpected-result",
                ).returncode,
                0,
            )
            record_actionable_decision(project, "demo", "inv-002", "002")
            self.assertEqual(
                work(
                    project,
                    "conclude-investigation", "demo", "inv-002",
                    "--disposition", "resume-change",
                    "--target", "demo-change",
                    "--rationale", "bounded implementation detail",
                    "--scope-revalidated", "--design-revalidated", "--approval-still-valid",
                ).returncode,
                0,
            )
            repeated = work(
                project,
                "investigate-change", "demo-change",
                "--title", "Repeated unexpected result",
                "--question", "Why again?",
                "--signature", "unexpected-result",
                "--discrimination-rationale", "Add a matrix trace and one-element model",
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)

            drift = work(
                project,
                "create-investigation", "demo",
                "--title", "Unrelated work",
                "--question", "Can focus move?",
                "--signature", "unrelated-work",
            )
            self.assertNotEqual(drift.returncode, 0)
            task_path = project / ".agent-work" / "demo" / "task.yaml"
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["current_focus"], {"type": "investigation", "ref": "inv-003"})
            self.assertEqual(task["escalation"]["target_investigation_ref"], "inv-003")

            unauthorized = work(
                project,
                "request-model-review", "demo",
                "--role", "deep_reviewer",
            )
            self.assertNotEqual(unauthorized.returncode, 0)
            requested = work(project, "request-model-review", "demo")
            self.assertEqual(requested.returncode, 0, requested.stderr)

            artifact = project / "model-review-output.md"
            artifact.write_text("# Model review\n\nThe evidence remains inconclusive.\n", encoding="utf-8")
            reviewed = work(
                project,
                "record-model-review", "demo",
                "--artifact", artifact,
                "--outcome", "inconclusive",
                "--evidence-ref", "native-thread:framework-review",
            )
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["escalation"]["level"], "human-checkpoint")
            self.assertFalse((project / ".agent-work" / "demo" / "model-review-request.yaml").exists())
            self.assertTrue(
                (project / ".agent-work" / "demo" / "model-reviews" /
                 "inv-003-round-1.request.yaml").is_file()
            )

    def test_change_id_collision_never_overwrites_existing_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            first = run(
                project, "create_task.py", "first-task",
                "--title", "First", "--entry", "change",
                "--change-id", "shared-change", "--project", project,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            change_path = project / "changes" / "active" / "shared-change" / "change.yaml"
            original = change_path.read_bytes()
            second = run(
                project, "create_task.py", "second-task",
                "--title", "Second", "--entry", "change",
                "--change-id", "shared-change", "--project", project,
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(change_path.read_bytes(), original)
            self.assertFalse((project / ".agent-work" / "second-task").exists())

    def test_concluded_investigation_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            create_change_from_investigation(project)
            result = work(
                project,
                "record-evidence", "demo", "inv-001",
                "--id", "evd-late",
                "--kind", "experiment",
                "--source-ref", "experiments/late",
                "--provenance", "late mutation",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("immutable", result.stderr)

    def test_supported_claim_and_accepted_decision_require_valid_evidence_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root = create_investigation_task(project)
            bad_claim = work(
                project,
                "record-claim", "demo", "inv-001",
                "--id", "clm-bad",
                "--statement", "Unsupported claim",
                "--status", "supported",
                "--confidence", "high",
            )
            self.assertNotEqual(bad_claim.returncode, 0)
            investigation = yaml.safe_load(
                (task_root / "investigations" / "inv-001.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(investigation["claims"], [])

            open_claim = work(
                project,
                "record-claim", "demo", "inv-001",
                "--id", "clm-open",
                "--statement", "Still open",
                "--status", "open",
                "--confidence", "low",
            )
            self.assertEqual(open_claim.returncode, 0, open_claim.stderr)
            bad_decision = work(
                project,
                "record-decision", "demo", "inv-001",
                "--id", "dec-bad",
                "--statement", "Act on open claim",
                "--status", "accepted",
                "--claim", "clm-open",
            )
            self.assertNotEqual(bad_decision.returncode, 0)

    def test_revise_preserves_review_rounds_and_cancels_pending_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            change_root = create_change_from_investigation(project)
            change_path = change_root / "change.yaml"
            change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            change["review_history"] = [{
                "round": 1,
                "status": "warn",
                "architecture": "pass",
                "scope": "pass",
                "numerical_evidence": "warn",
                "execution": {"output_ref": "changes/active/demo-change/reviews/round-1.md"},
            }]
            change["review"] = {
                "status": "warn",
                "architecture": "pass",
                "scope": "pass",
                "numerical_evidence": "warn",
                "execution": {"output_ref": "changes/active/demo-change/reviews/round-1.md"},
            }
            change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8")
            reviews = change_root / "reviews"
            reviews.mkdir(exist_ok=True)
            (reviews / "round-1.md").write_text("# Round 1\n", encoding="utf-8")
            (change_root / "review-request.yaml").write_text(
                yaml.safe_dump({"round": 2, "change_id": "demo-change"}),
                encoding="utf-8",
            )

            self.assertEqual(
                work(
                    project,
                    "investigate-change", "demo-change",
                    "--title", "Design contradiction",
                    "--question", "Must the design change?",
                    "--signature", "design-contradiction",
                ).returncode,
                0,
            )
            record_actionable_decision(project, "demo", "inv-002", "002")
            revised = work(
                project,
                "conclude-investigation", "demo", "inv-002",
                "--disposition", "revise-change",
                "--target", "demo-change",
                "--rationale", "The approved design must be revised",
            )
            self.assertEqual(revised.returncode, 0, revised.stderr)
            change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            self.assertEqual(len(change["review_history"]), 1)
            self.assertFalse((change_root / "review-request.yaml").exists())
            self.assertTrue(
                (reviews / "revision-1-cancelled-review.request.yaml").exists()
            )
            next_review = harness(project, "review", "demo-change")
            self.assertEqual(next_review.returncode, 0, next_review.stderr)
            packet = yaml.safe_load(
                (change_root / "review-request.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(packet["round"], 2)

    def test_complete_task_closes_concluded_investigations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root = create_investigation_task(project)
            concluded = work(
                project,
                "conclude-investigation", "demo", "inv-001",
                "--disposition", "no-change-required",
                "--rationale", "No production change is needed",
            )
            self.assertEqual(concluded.returncode, 0, concluded.stderr)
            task_path = task_root / "task.yaml"
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            task["learning"]["closeout"]["status"] = "assessed"
            task["learning"]["closeout"]["reason"] = "No reusable learning candidate"
            task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

            completed = work(
                project,
                "complete-task", "demo",
                "--rationale", "Investigation concluded without a production change",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            investigation = yaml.safe_load(
                (task_root / "investigations" / "inv-001.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(task["status"], "completed")
            self.assertEqual(investigation["status"], "closed")
            self.assertEqual(work(project, "validate", "demo").returncode, 0)

    def test_legacy_task_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task.yaml"
            task.write_text("schema_version: 3.3\nmode: investigation\nphase: intake\n", encoding="utf-8")
            result = run(Path(directory), "validate_task_state.py", task)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("schema_version must be 4", result.stderr)


if __name__ == "__main__":
    unittest.main()
