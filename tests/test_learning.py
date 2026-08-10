from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TOOLS = HARNESS_ROOT / "runtime"
TASK_TEMPLATE = (
    HARNESS_ROOT / "adapters" / "default" / "skills"
    / "change-governor" / "assets" / "task.yaml.template"
)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", str(project)],
        check=True,
        capture_output=True,
        text=True,
    )
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        "package: sitter\nformat_version: 1\n",
        encoding="utf-8",
    )
    return project


def create_task(project: Path, task_id: str) -> Path:
    data = yaml.safe_load(TASK_TEMPLATE.read_text(encoding="utf-8"))
    data["id"] = task_id
    data["title"] = f"Learning fixture {task_id}"
    data["status"] = "active"
    path = project / ".agent-work" / task_id / "task.yaml"
    write_yaml(path, data)
    return path


def run_learning(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOLS / "learning.py"),
            "--project",
            str(project),
            *args,
        ],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def run_validator(task: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / "validate_task_state.py"), str(task)],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class LearningLifecycleTests(unittest.TestCase):
    def test_v4_task_cannot_be_active_without_automatic_intake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_task(project, "intake-gate")
            blocked = run_validator(task)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("learning intake", blocked.stderr.lower())
            result = run_learning(
                project, "intake", str(task.relative_to(project))
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(run_validator(task).returncode, 0)

    def test_exceptional_reasoning_requires_explicit_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_task(project, "reasoning-gate")
            self.assertEqual(
                run_learning(
                    project, "intake", str(task.relative_to(project))
                ).returncode,
                0,
            )
            request = (
                task.parent
                / "delegations"
                / "dlg-001"
                / "attempt-01.request.yaml"
            )
            write_yaml(
                request,
                {
                    "schema_version": 1,
                    "delegation": {
                        "id": "dlg-001",
                        "attempt": 1,
                        "task_id": "reasoning-gate",
                        "role": "source_locator",
                    },
                    "context_policy": {"inheritance": "none"},
                },
            )
            data = yaml.safe_load(task.read_text(encoding="utf-8"))
            data["delegation"] = {
                "protocol_version": 1,
                "decision": "optional",
                "authorization": {
                    "status": "granted",
                    "scopes": ["readonly-exploration"],
                    "evidence": "user approved",
                },
                "model_budget": {
                    "parent_model": "gpt-5.6-terra",
                    "parent_tier": "terra",
                    "default_ceiling": "parent",
                    "elevated_authorization": {
                        "status": "not-requested",
                        "approved_tiers": [],
                        "evidence": None,
                    },
                    "reasoning_authorization": {
                        "status": "pending",
                        "approved_efforts": [],
                        "evidence": None,
                    },
                },
                "planned": [
                    {
                        "id": "dlg-001",
                        "agent": "source_locator",
                        "model": "gpt-5.6-luna",
                        "tier": "luna",
                        "reasoning_effort": "max",
                        "default_reasoning_effort": "low",
                        "effort_escalation": "pending",
                        "effort_reason": "exhaustive evidence audit",
                        "purpose": "locate evidence",
                        "relation_to_parent": "weaker",
                        "elevation_authorization": "not-required",
                        "target": {"type": "task", "ref": "reasoning-gate"},
                        "context": {
                            "inheritance": "none",
                            "projection": "locator-v1",
                            "attempt": 1,
                            "request_ref": request.relative_to(project).as_posix(),
                        },
                        "status": "requested",
                    }
                ],
                "completed": [],
                "failed": [],
                "user_override": False,
            }
            write_yaml(task, data)
            blocked = run_validator(task)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("reasoning authorization", blocked.stderr.lower())
            data["delegation"]["planned"][0]["effort_escalation"] = "granted"
            data["delegation"]["model_budget"]["reasoning_authorization"] = {
                "status": "granted",
                "approved_efforts": ["max"],
                "evidence": "user approved max",
            }
            write_yaml(task, data)
            self.assertEqual(run_validator(task).returncode, 0)

    def test_repeated_observation_requires_attention_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            first = create_task(project, "encoding-1")
            second = create_task(project, "encoding-2")
            for task in (first, second):
                self.assertEqual(
                    run_learning(
                        project, "intake", str(task.relative_to(project))
                    ).returncode,
                    0,
                )
            common = [
                "observe",
                str(first.relative_to(project)),
                "--key",
                "windows powershell nonascii output",
                "--title",
                "PowerShell Chinese output decoding",
                "--kind",
                "pitfall",
                "--scope",
                "user-environment",
                "--category",
                "encoding",
                "--candidate-target",
                "local-tool",
                "--workaround",
                "use explicit UTF-8",
                "--verified-success",
            ]
            self.assertEqual(run_learning(project, *common).returncode, 0)
            second_args = common.copy()
            second_args[1] = str(second.relative_to(project))
            self.assertEqual(run_learning(project, *second_args).returncode, 0)
            self.assertEqual(run_learning(project, *second_args).returncode, 0)
            self.assertEqual(
                run_learning(
                    project, "closeout", str(second.relative_to(project))
                ).returncode,
                0,
            )
            data = yaml.safe_load(second.read_text(encoding="utf-8"))
            data["status"] = "completed"
            data["current_focus"] = {"type": "none", "ref": None}
            write_yaml(second, data)
            blocked = run_validator(second)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("must be presented", blocked.stderr.lower())
            attention = run_learning(
                project,
                "attention",
                str(second.relative_to(project)),
                "--decision",
                "deferred",
                "--evidence",
                "user reviewed and deferred the candidate",
            )
            self.assertEqual(attention.returncode, 0, attention.stderr)
            self.assertEqual(run_validator(second).returncode, 0)

    def test_empty_closeout_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_task(project, "empty-closeout")
            self.assertEqual(
                run_learning(
                    project, "intake", str(task.relative_to(project))
                ).returncode,
                0,
            )
            self.assertNotEqual(
                run_learning(
                    project, "closeout", str(task.relative_to(project))
                ).returncode,
                0,
            )
            result = run_learning(
                project,
                "closeout",
                str(task.relative_to(project)),
                "--reason",
                "No reusable issue or tool gap occurred.",
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
