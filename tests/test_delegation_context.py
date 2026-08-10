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
    subprocess.run(
        ["git", "init", str(project)],
        check=True,
        text=True,
        capture_output=True,
    )
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        "package: sitter\nformat_version: 1\n",
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "src" / "contact.cpp").write_text(
        "// contact anchor\n", encoding="utf-8"
    )
    (project / "src" / "mpc.cpp").write_text(
        "// mpc anchor\n", encoding="utf-8"
    )
    return project


def run_script(project: Path, script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def work(project: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return run_script(project, "work.py", "--project", project, *args)


def create_change_task(project: Path) -> tuple[Path, Path]:
    result = run_script(
        project,
        "create_task.py",
        "delegation-smoke",
        "--title",
        "Delegation smoke",
        "--entry",
        "change",
        "--change-id",
        "delegation-change",
        "--project",
        project,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    task_root = project / ".agent-work" / "delegation-smoke"
    change_root = project / "changes" / "active" / "delegation-change"
    return task_root, change_root


def authorize(project: Path) -> None:
    result = work(
        project,
        "authorize-delegation",
        "delegation-smoke",
        "--decision",
        "required",
        "--scope",
        "readonly-exploration",
        "--scope",
        "readonly-review",
        "--evidence",
        "user-authorized-local-smoke",
        "--parent-model",
        "gpt-5.6-terra",
        "--parent-tier",
        "terra",
    )
    if result.returncode:
        raise AssertionError(result.stderr)


def request_context_scout(project: Path) -> subprocess.CompletedProcess[str]:
    return work(
        project,
        "request-delegation",
        "delegation-smoke",
        "--role",
        "context_scout",
        "--target-type",
        "change",
        "--target-ref",
        "delegation-change",
        "--purpose",
        "trace bounded ownership",
        "--question",
        "Does Contact duplicate MPC responsibilities?",
        "--decision-supported",
        "Decide whether the responsibility boundary needs revision.",
        "--include",
        "AnalysisContact",
        "--include",
        "AnalysisMpcConstraint",
        "--exclude",
        "friction-redesign",
        "--start-ref",
        "src/contact.cpp",
        "--start-ref",
        "src/mpc.cpp",
    )


def write_attestation(project: Path, name: str, *, inheritance: str = "none") -> Path:
    path = project / name
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "execution": {
                    "method": "native-subagent",
                    "collector": "codex-rollout-app-server-v1",
                    "codex_version": "codex-cli test",
                    "task_name": "sitter-test-dlg-001",
                    "spawn_call_id": "call-delegation-smoke",
                    "session_ref": "native-thread:delegation-smoke",
                },
                "observed": {
                    "agent": "context_scout",
                    "model": "gpt-5.6-luna",
                    "tier": "luna",
                    "reasoning_effort": "medium",
                    "context_inheritance": inheritance,
                    "sandbox_mode": "read-only",
                    "child_thread_id": "delegation-smoke",
                    "parent_thread_id": "delegation-parent",
                },
                "evidence": {
                    "source": "verified-combined",
                    "parent_rollout": "test-parent-rollout.jsonl",
                    "spawn_line": 1,
                    "activity_line": 2,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


class DelegationContextTests(unittest.TestCase):
    def test_request_uses_independent_role_projection_and_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root, _ = create_change_task(project)
            authorize(project)

            first = request_context_scout(project)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_packet = project / first.stdout.strip()
            packet = yaml.safe_load(first_packet.read_text(encoding="utf-8"))
            self.assertEqual(packet["delegation"]["id"], "dlg-001")
            self.assertEqual(packet["context_policy"]["inheritance"], "none")
            self.assertEqual(packet["projection"]["id"], "context-scout-v1")
            self.assertEqual(packet["bias_control"]["parent_hypotheses"], "withheld")
            refs = {
                item["ref"] for item in packet["projection"]["authority_refs"]
            }
            self.assertIn(
                "changes/active/delegation-change/design.md",
                refs,
            )

            second = request_context_scout(project)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_packet = yaml.safe_load(
                (project / second.stdout.strip()).read_text(encoding="utf-8")
            )
            self.assertEqual(second_packet["delegation"]["id"], "dlg-002")

            task = yaml.safe_load(
                (task_root / "task.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [entry["id"] for entry in task["delegation"]["planned"]],
                ["dlg-001", "dlg-002"],
            )

    def test_completed_result_requires_matching_runtime_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root, _ = create_change_task(project)
            authorize(project)
            requested = request_context_scout(project)
            self.assertEqual(requested.returncode, 0, requested.stderr)

            artifact = project / "child-output.md"
            artifact.write_text(
                "# Findings\n\nNo duplicated ownership was confirmed.\n",
                encoding="utf-8",
            )
            bad = write_attestation(project, "bad-attestation.yaml", inheritance="all")
            rejected = work(
                project,
                "record-delegation-result",
                "delegation-smoke",
                "dlg-001",
                "--artifact",
                artifact,
                "--outcome",
                "completed",
                "--evidence-ref",
                "native-thread:delegation-smoke",
                "--attestation",
                bad,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("context_inheritance", rejected.stderr)

            good = write_attestation(project, "good-attestation.yaml")
            recorded = work(
                project,
                "record-delegation-result",
                "delegation-smoke",
                "dlg-001",
                "--artifact",
                artifact,
                "--outcome",
                "completed",
                "--evidence-ref",
                "native-thread:delegation-smoke",
                "--attestation",
                good,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)

            task = yaml.safe_load(
                (task_root / "task.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(task["delegation"]["planned"][0]["status"], "completed")
            self.assertEqual(
                task["delegation"]["completed"][0]["context"]["inheritance"],
                "none",
            )

    def test_need_context_creates_immutable_second_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root, _ = create_change_task(project)
            authorize(project)
            requested = request_context_scout(project)
            self.assertEqual(requested.returncode, 0, requested.stderr)
            first_packet = project / requested.stdout.strip()
            first_text = first_packet.read_text(encoding="utf-8")

            artifact = project / "need-context.md"
            artifact.write_text(
                "status: NEED_CONTEXT\n\nNeed the nonlinear activation owner.\n",
                encoding="utf-8",
            )
            attestation = write_attestation(project, "attestation.yaml")
            recorded = work(
                project,
                "record-delegation-result",
                "delegation-smoke",
                "dlg-001",
                "--artifact",
                artifact,
                "--outcome",
                "need-context",
                "--evidence-ref",
                "native-thread:delegation-smoke",
                "--attestation",
                attestation,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)

            supplement_file = project / "src" / "activation.cpp"
            supplement_file.write_text("// activation owner\n", encoding="utf-8")
            supplemented = work(
                project,
                "supplement-delegation-context",
                "delegation-smoke",
                "dlg-001",
                "--ref",
                "src/activation.cpp",
                "--reason",
                "contains the missing activation lifecycle",
            )
            self.assertEqual(supplemented.returncode, 0, supplemented.stderr)
            second_packet = project / supplemented.stdout.strip()
            packet = yaml.safe_load(second_packet.read_text(encoding="utf-8"))
            self.assertEqual(packet["delegation"]["attempt"], 2)
            self.assertEqual(first_packet.read_text(encoding="utf-8"), first_text)
            self.assertTrue(
                (
                    task_root
                    / "delegations"
                    / "dlg-001"
                    / "attempt-01.result.md"
                ).is_file()
            )

    def test_changed_frozen_change_input_records_stale_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task_root, change_root = create_change_task(project)
            authorize(project)
            requested = request_context_scout(project)
            self.assertEqual(requested.returncode, 0, requested.stderr)

            (change_root / "design.md").write_text(
                "# Design\n\nChanged after delegation request.\n",
                encoding="utf-8",
            )
            artifact = project / "stale-output.md"
            artifact.write_text("# Findings\n\nBased on stale design.\n", encoding="utf-8")
            attestation = write_attestation(project, "attestation.yaml")
            recorded = work(
                project,
                "record-delegation-result",
                "delegation-smoke",
                "dlg-001",
                "--artifact",
                artifact,
                "--outcome",
                "completed",
                "--evidence-ref",
                "native-thread:delegation-smoke",
                "--attestation",
                attestation,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            self.assertIn("stale", recorded.stdout)

            task = yaml.safe_load(
                (task_root / "task.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(task["delegation"]["planned"][0]["status"], "stale")
            self.assertEqual(task["delegation"]["completed"], [])
            self.assertIn("stale-context", task["delegation"]["failed"][0]["reason"])

    def test_locator_projection_does_not_receive_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            create_change_task(project)
            authorize(project)
            result = work(
                project,
                "request-delegation",
                "delegation-smoke",
                "--role",
                "source_locator",
                "--target-type",
                "change",
                "--target-ref",
                "delegation-change",
                "--purpose",
                "locate exact ownership symbols",
                "--question",
                "Where are Contact and MPC created?",
                "--decision-supported",
                "Choose the next files for bounded inspection.",
                "--include",
                "AnalysisContact",
                "--start-ref",
                "src/contact.cpp",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = yaml.safe_load(
                (project / result.stdout.strip()).read_text(encoding="utf-8")
            )
            refs = {
                item["ref"] for item in packet["projection"]["authority_refs"]
            }
            self.assertNotIn(
                "changes/active/delegation-change/design.md",
                refs,
            )


if __name__ == "__main__":
    unittest.main()
