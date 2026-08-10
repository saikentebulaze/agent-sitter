from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TOOLS = HARNESS_ROOT / "runtime"
ARTIFACTS = (
    "proposal.md", "design.md", "tasks.md", "verification.md",
    "knowledge-sync.md", "archive-summary.md",
)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run_harness(project: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / "harness.py"), "--project", str(project), *map(str, args)],
        cwd=HARNESS_ROOT, text=True, encoding="utf-8", capture_output=True,
    )


def create_project(root: Path) -> tuple[Path, Path]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    change = project / "changes" / "active" / "demo"
    change.mkdir(parents=True)
    data = {
        "schema_version": 4,
        "id": "demo", "task_id": "demo-task", "title": "Demo change",
        "status": "implementing", "execution_state": "active",
        "hold": {"reason": None, "investigation_ref": None, "held_at": None},
        "relations": {
            "derived_from": {"investigations": [], "claims": [], "decisions": [], "evidence": []},
            "produced": {"investigations": [], "evidence": []},
            "supersedes": [], "superseded_by": None,
        },
        "resume_history": [], "revision_history": [],
        "risk": {"semantic": "high", "repository_change": "high"},
        "approval": {"status": "approved"},
        "human_in_loop": {
            "mode": "guided", "mode_evidence": None,
            "decision_assessment": {"status": "resolved", "reasons": ["result semantics required a decision"]},
            "decisions": [{
                "id": "DEC-001", "question": "Which result semantics?",
                "options": ["section-force", "reaction"],
                "recommendation": "section-force matches scope", "user_decision": "section-force",
                "evidence": "user approved",
            }],
            "interruption_budget": {"batch_questions": True, "max_design_checkpoints": 1},
        },
        "critical_surfaces": [],
        "change_budget": {"explicit_non_goals": [], "adjacent_issues": []},
        "methodology": {
            "planning_level": "full", "superpowers_skills": ["writing-plans"],
            "tdd_mode": "targeted", "temporary_tests": [], "test_cleanup_complete": True,
            "retained_test_rationale": ["protects review transaction behavior"],
        },
        "completion": {"implementation_complete": False, "ready_for_user_review": False},
        "user_review": {"status": "pending", "evidence": None},
        "review": {
            "status": "pending", "architecture": "pending", "scope": "pending",
            "numerical_evidence": "pending", "execution": {},
        },
        "review_history": [],
        "remediation": {"route": None, "within_approved_scope": False},
        "verification": {"status": "pass", "latest_results": []},
        "knowledge_sync": {"status": "pending", "entries": []},
        "archive": {"experiment_cleanup_complete": True, "temporary_production_files": [], "blockers": []},
    }
    write_yaml(change / "change.yaml", data)
    for name in ARTIFACTS:
        (change / name).write_text(f"{name} contains enough stable content for validation.", encoding="utf-8")
    return project, change


def reviewer_artifact(project: Path, text: str = "# Review\n\nNo blocking findings.\n") -> Path:
    artifact = project / ".agent-work" / "demo" / "reviewer-output.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(text, encoding="utf-8")
    return artifact


class ReviewRecordingTests(unittest.TestCase):
    def record(self, project: Path, artifact: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return run_harness(
            project, "record-review", "demo", "--artifact", artifact,
            "--architecture", "pass", "--scope", "pass",
            "--numerical-evidence", "warn", "--evidence-ref", "native-thread-review-1", *extra,
        )

    def test_record_review_updates_history_and_advances_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory)); artifact = reviewer_artifact(project)
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            first_packet = yaml.safe_load((change / "review-request.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                first_packet["assurance_snapshot"],
                {"semantic": "high", "repository_change": "high"},
            )
            recorded = self.record(project, artifact)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            self.assertEqual(data["review"]["status"], "warn")
            self.assertEqual(len(data["review_history"]), 1)
            self.assertTrue((change / "reviews" / "round-1.request.yaml").is_file())
            archived = yaml.safe_load(
                (change / "reviews" / "round-1.request.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(archived["assurance_snapshot"], first_packet["assurance_snapshot"])
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            packet = yaml.safe_load((change / "review-request.yaml").read_text(encoding="utf-8"))
            self.assertEqual(packet["round"], 2)

    def test_pending_request_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory))
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            original = (change / "review-request.yaml").read_text(encoding="utf-8")
            second = run_harness(project, "review", "demo")
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((change / "review-request.yaml").read_text(encoding="utf-8"), original)

    def test_stale_snapshot_is_rejected_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory)); artifact = reviewer_artifact(project)
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            (change / "design.md").write_text("design changed after review started", encoding="utf-8")
            result = self.record(project, artifact)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((change / "review-request.yaml").is_file())
            self.assertFalse((change / "reviews" / "round-1.md").exists())

    def test_assurance_change_after_review_request_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory)); artifact = reviewer_artifact(project)
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            data["risk"] = {"semantic": "critical", "repository_change": "high"}
            write_yaml(change / "change.yaml", data)
            result = self.record(project, artifact)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("production assurance changed", result.stderr)
            self.assertTrue((change / "review-request.yaml").is_file())
            self.assertFalse((change / "reviews" / "round-1.md").exists())

    def test_block_requires_remediation_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _ = create_project(Path(directory)); artifact = reviewer_artifact(project)
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            result = run_harness(
                project, "record-review", "demo", "--artifact", artifact,
                "--architecture", "block", "--scope", "pass", "--numerical-evidence", "pass",
                "--evidence-ref", "native-thread-review-1",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("remediation-route", result.stderr)

    def test_repeating_identical_record_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _ = create_project(Path(directory)); artifact = reviewer_artifact(project)
            self.assertEqual(run_harness(project, "review", "demo").returncode, 0)
            first = self.record(project, artifact); second = self.record(project, artifact)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already recorded", second.stdout.lower())


if __name__ == "__main__":
    unittest.main()
