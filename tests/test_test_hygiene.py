from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from finalize_tests import TestHygieneError, finalize_tests  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402


def create_project(root: Path) -> tuple[Path, ProjectContext, Path]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Harness Test"],
        check=True,
    )
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "fixture"], check=True, capture_output=True, text=True)

    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
    initialize_provider_task(
        context,
        task_id="hygiene-task",
        title="Hygiene",
        entry="change",
        change_id="hygiene-change",
    )
    return project, context, project / "changes" / "active" / "hygiene-change"


def load_change(change: Path) -> dict:
    return yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))


def save_change(change: Path, data: dict) -> None:
    (change / "change.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class TestHygieneTests(unittest.TestCase):
    def test_no_test_changes_finalizes_with_empty_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = create_project(Path(directory))
            evidence = finalize_tests(context, change, retained={}, preexisting={})
            self.assertEqual(evidence, change / "test-finalization.yaml")
            payload = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["decisions"], [])
            data = load_change(change)
            self.assertTrue(data["methodology"]["test_cleanup_complete"])
            self.assertEqual(
                data["methodology"]["test_cleanup_evidence"],
                "changes/active/hygiene-change/test-finalization.yaml",
            )

    def test_existing_temporary_test_blocks_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, change = create_project(Path(directory))
            test = project / "tests" / "test_debug_probe.py"
            test.parent.mkdir(parents=True)
            test.write_text("def test_probe(): assert True\n", encoding="utf-8")
            data = load_change(change)
            data["methodology"]["temporary_tests"] = ["tests/test_debug_probe.py"]
            save_change(change, data)

            with self.assertRaisesRegex(TestHygieneError, "temporary test remains"):
                finalize_tests(context, change, retained={}, preexisting={})
            self.assertFalse((change / "test-finalization.yaml").exists())
            self.assertFalse(load_change(change)["methodology"]["test_cleanup_complete"])

    def test_removed_temporary_test_is_recorded_as_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = create_project(Path(directory))
            data = load_change(change)
            data["methodology"]["temporary_tests"] = ["tests/test_debug_probe.py"]
            save_change(change, data)

            evidence = finalize_tests(context, change, retained={}, preexisting={})
            payload = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["decisions"],
                [{
                    "path": "tests/test_debug_probe.py",
                    "classification": "development-only-removed",
                    "reason": "temporary test no longer exists after development",
                }],
            )

    def test_rerun_preserves_prior_test_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = create_project(Path(directory))
            data = load_change(change)
            data["methodology"]["temporary_tests"] = ["tests/test_debug_probe.py"]
            save_change(change, data)

            evidence = finalize_tests(context, change, retained={}, preexisting={})
            first = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(len(first["decisions"]), 1)

            evidence = finalize_tests(context, change, retained={}, preexisting={})
            second = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(second["decisions"], first["decisions"])

    def test_new_regression_test_requires_retention_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, change = create_project(Path(directory))
            test = project / "tests" / "test_regression.py"
            test.parent.mkdir(parents=True)
            test.write_text("def test_regression(): assert True\n", encoding="utf-8")

            with self.assertRaisesRegex(TestHygieneError, "changed test is unclassified"):
                finalize_tests(context, change, retained={}, preexisting={})

            evidence = finalize_tests(
                context,
                change,
                retained={"tests/test_regression.py": "protects the reproduced production defect"},
                preexisting={},
            )
            payload = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["decisions"][0]["classification"], "permanent-regression")
            data = load_change(change)
            self.assertEqual(
                data["methodology"]["retained_test_rationale"],
                [{
                    "path": "tests/test_regression.py",
                    "reason": "protects the reproduced production defect",
                }],
            )

    def test_preexisting_dirty_test_can_be_excluded_from_change_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, change = create_project(Path(directory))
            test = project / "tests" / "test_user_work.py"
            test.parent.mkdir(parents=True)
            test.write_text("def test_user_work(): assert True\n", encoding="utf-8")
            evidence = finalize_tests(
                context,
                change,
                retained={},
                preexisting={
                    "tests/test_user_work.py": "user change existed before this governed Change"
                },
            )
            payload = yaml.safe_load(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["decisions"][0]["classification"], "pre-existing-not-owned")

    def test_protocol_one_cannot_fake_cleanup_with_boolean_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _, change = create_project(Path(directory))
            data = load_change(change)
            data["status"] = "syncing"
            data["methodology"]["test_cleanup_complete"] = True
            data["methodology"]["test_cleanup_evidence"] = None
            save_change(change, data)
            result = subprocess.run(
                [sys.executable, str(RUNTIME / "validate_change.py"), str(change)],
                cwd=project,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("test_cleanup_evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
