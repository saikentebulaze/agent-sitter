from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import install


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    install.install(project, dry_run=False, provider_ids=("codex",), trust_project=True)
    created = subprocess.run(
        [
            sys.executable,
            str(RUNTIME / "create_task.py"),
            "smoke-task",
            "--title",
            "Runtime smoke task",
            "--entry",
            "investigation",
            "--signature",
            "runtime-smoke",
            "--project",
            str(project),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if created.returncode:
        raise AssertionError(created.stderr)
    return project


def invoke(project: Path, evidence: str | None) -> subprocess.CompletedProcess[str]:
    hook = project / ".harness" / "sitter" / "runtime" / "session_start_hook.py"
    env = os.environ.copy()
    if evidence is not None:
        env["SITTER_SESSION_START_EVIDENCE_DIR"] = evidence
    else:
        env.pop("SITTER_SESSION_START_EVIDENCE_DIR", None)
    return subprocess.run(
        [sys.executable, str(hook)],
        cwd=project,
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(project),
                "session_id": "fixture-session",
            }
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
    )


class V6SessionStartEvidenceTests(unittest.TestCase):
    def test_normal_session_start_does_not_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            result = invoke(project, None)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((project / ".agent-work" / "_runtime-smoke").exists())

    def test_opt_in_smoke_evidence_proves_hook_and_bounded_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            relative = ".agent-work/_runtime-smoke/session-start"
            result = invoke(project, relative)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence_dir = project / relative
            events = list(evidence_dir.glob("session-start-*.json"))
            self.assertEqual(len(events), 1)
            evidence = json.loads(events[0].read_text(encoding="utf-8"))
            self.assertEqual(evidence["hook_event_name"], "SessionStart")
            self.assertEqual(evidence["source"], "startup")
            self.assertEqual(evidence["active_task_ids"], ["smoke-task"])
            self.assertFalse(evidence["history_scanned"])
            self.assertFalse(evidence["durable_memory_loaded"])
            self.assertIn("smoke-task", evidence["additional_context"])

    def test_smoke_evidence_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root)
            outside = root / "outside"
            result = invoke(project, str(outside))
            self.assertEqual(result.returncode, 0)
            self.assertIn("must remain inside the project root", result.stderr)
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
