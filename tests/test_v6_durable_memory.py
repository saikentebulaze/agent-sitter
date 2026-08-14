from __future__ import annotations

import json
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

from decision_authority import human_decision_digest  # noqa: E402
from knowledge_tool import validate_entries  # noqa: E402


def run(project: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "v6@example.invalid")
    git(project, "config", "user.name", "V6 Fixture")
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    source = project / "src" / "state.py"
    source.parent.mkdir(parents=True)
    source.write_text("STATE = 'committed'\n", encoding="utf-8")
    git(project, "add", "-A")
    git(project, "commit", "-m", "fixture")
    return project


def create_memory_task(project: Path, task_id: str = "memory-task") -> Path:
    created = run(
        project,
        "create_task.py",
        task_id,
        "--title",
        "Durable memory task",
        "--entry",
        "investigation",
        "--signature",
        task_id,
        "--project",
        str(project),
    )
    if created.returncode:
        raise AssertionError(created.stderr)
    task = project / ".agent-work" / task_id / "task.yaml"
    intake = run(
        project,
        "learning.py",
        "--project",
        str(project),
        "intake",
        str(task.relative_to(project)),
    )
    if intake.returncode:
        raise AssertionError(intake.stderr)
    return task


def propose_and_approve(
    project: Path,
    task: Path,
    *,
    key: str,
    target: str = "project-knowledge",
    memory_key: str = "state-ownership",
    trigger: str | None = None,
) -> str:
    args = [
        "--project",
        str(project),
        "propose-durable",
        str(task.relative_to(project)),
        "--key",
        key,
        "--title",
        f"Memory {key}",
        "--target",
        target,
        "--summary",
        f"Semantic durable summary for {key}.",
        "--memory-key",
        memory_key,
        "--evidence",
        "fixture-evidence",
    ]
    if target == "project-knowledge":
        args.extend(["--validity-surface", "src/state.py"])
    if trigger:
        args.extend(["--trigger-term", trigger])
    proposed = run(project, "learning.py", *args)
    if proposed.returncode:
        raise AssertionError(proposed.stderr)
    candidate_id = json.loads(proposed.stdout)["id"]

    closeout = run(
        project,
        "learning.py",
        "--project",
        str(project),
        "closeout",
        str(task.relative_to(project)),
    )
    if closeout.returncode:
        raise AssertionError(closeout.stderr)
    approved = run(
        project,
        "learning.py",
        "--project",
        str(project),
        "attention",
        str(task.relative_to(project)),
        "--candidate",
        candidate_id,
        "--decision",
        "approved",
        "--evidence",
        "user approved this durable candidate",
    )
    if approved.returncode:
        raise AssertionError(approved.stderr)
    return candidate_id


def write_existing_memory(project: Path, entry_id: str, memory_key: str) -> tuple[Path, bytes]:
    content = project / "knowledge" / "memory" / f"{entry_id}.md"
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text(f"# Existing {entry_id}\n\nDo not rewrite this historical memory.\n", encoding="utf-8")
    original = content.read_bytes()
    index = project / "knowledge" / "index.yaml"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "entries": [
                    {
                        "id": entry_id,
                        "title": f"Existing {entry_id}",
                        "type": "fact",
                        "evidence_status": "verified",
                        "architecture_status": "current",
                        "path": content.relative_to(project).as_posix(),
                        "domains": ["state"],
                        "keywords": [memory_key],
                        "related": [],
                        "memory_key": memory_key,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return content, original


class DurableMemoryPromotionTests(unittest.TestCase):
    def test_individually_approved_candidate_promotes_into_existing_knowledge_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_memory_task(project)
            candidate_id = propose_and_approve(project, task, key="stable-state")

            promoted = run(
                project,
                "durable_memory.py",
                "--project",
                str(project),
                "promote",
                candidate_id,
            )
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            result = json.loads(promoted.stdout)
            self.assertEqual(result["knowledge_id"], candidate_id)
            self.assertEqual(result["type"], "fact")
            self.assertTrue(result["source_commit"])

            index = yaml.safe_load((project / "knowledge" / "index.yaml").read_text(encoding="utf-8"))
            entry = index["entries"][0]
            self.assertEqual(entry["id"], candidate_id)
            self.assertEqual(entry["memory_key"], "state-ownership")
            self.assertEqual(entry["validity_surface"], ["src/state.py"])
            self.assertEqual(validate_entries(project, index["entries"]), [])
            self.assertTrue((project / entry["path"]).is_file())

            inbox = yaml.safe_load(
                (project / ".agent-work" / "_learning" / "inbox.yaml").read_text(encoding="utf-8")
            )
            learned = next(item for item in inbox["entries"] if item["id"] == candidate_id)
            self.assertEqual(learned["status"], "promoted")

    def test_conflict_blocks_without_mutation_until_user_explicitly_supersedes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            old_path, old_bytes = write_existing_memory(project, "K-OLD", "state-ownership")
            task = create_memory_task(project)
            candidate_id = propose_and_approve(project, task, key="replacement-state")
            index_path = project / "knowledge" / "index.yaml"
            before_index = index_path.read_bytes()

            blocked = run(
                project,
                "durable_memory.py",
                "--project",
                str(project),
                "promote",
                candidate_id,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("conflict", blocked.stderr.lower())
            self.assertEqual(index_path.read_bytes(), before_index)
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertFalse((project / "knowledge" / "memory" / f"{candidate_id}.md").exists())

            promoted = run(
                project,
                "durable_memory.py",
                "--project",
                str(project),
                "promote",
                candidate_id,
                "--supersede",
                "K-OLD",
            )
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            self.assertEqual(old_path.read_bytes(), old_bytes)
            index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
            self.assertEqual(len(index["entries"]), 2)
            replacement = next(item for item in index["entries"] if item["id"] == candidate_id)
            self.assertEqual(replacement["supersedes"], ["K-OLD"])
            self.assertEqual(validate_entries(project, index["entries"]), [])

    def test_open_thread_and_watchpoint_keep_explicit_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            for task_id, target, trigger in (
                ("thread-task", "open-thread", "parser"),
                ("watch-task", "watchpoint", "compiler"),
            ):
                task = create_memory_task(project, task_id)
                candidate_id = propose_and_approve(
                    project,
                    task,
                    key=f"{target}-{task_id}",
                    target=target,
                    memory_key=f"{target}-{task_id}",
                    trigger=trigger,
                )
                promoted = run(
                    project,
                    "durable_memory.py",
                    "--project",
                    str(project),
                    "promote",
                    candidate_id,
                )
                self.assertEqual(promoted.returncode, 0, promoted.stderr)

            index = yaml.safe_load((project / "knowledge" / "index.yaml").read_text(encoding="utf-8"))
            by_type = {entry["type"]: entry for entry in index["entries"]}
            self.assertEqual(by_type["open-thread"]["trigger_terms"], ["parser"])
            self.assertEqual(by_type["watchpoint"]["trigger_terms"], ["compiler"])
            self.assertEqual(validate_entries(project, index["entries"]), [])

    def test_promoted_memory_records_resolved_human_authority_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_memory_task(project)
            task_data = yaml.safe_load(task.read_text(encoding="utf-8"))
            task_data["human_in_loop"] = {
                "mode": "guided",
                "mode_evidence": None,
                "decision_assessment": {
                    "status": "resolved",
                    "reasons": ["material state ownership fork"],
                },
                "decisions": [
                    {
                        "id": "DEC-STATE",
                        "question": "Which state owner is authoritative?",
                        "options": ["A", "B"],
                        "recommendation": "A",
                        "user_decision": "B",
                        "evidence": "user explicitly chose B",
                    }
                ],
                "interruption_budget": {
                    "batch_questions": True,
                    "max_design_checkpoints": 1,
                },
            }
            task.write_text(
                yaml.safe_dump(task_data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            expected = human_decision_digest(task_data)
            candidate_id = propose_and_approve(project, task, key="authority-memory")
            promoted = run(
                project,
                "durable_memory.py",
                "--project",
                str(project),
                "promote",
                candidate_id,
            )
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            index = yaml.safe_load((project / "knowledge" / "index.yaml").read_text(encoding="utf-8"))
            entry = next(item for item in index["entries"] if item["id"] == candidate_id)
            self.assertEqual(entry["authority_sha256"], expected)

    def test_human_decision_change_makes_durable_candidate_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = create_memory_task(project)
            task_data = yaml.safe_load(task.read_text(encoding="utf-8"))
            task_data["human_in_loop"] = {
                "mode": "guided",
                "mode_evidence": None,
                "decision_assessment": {
                    "status": "resolved",
                    "reasons": ["material state ownership fork"],
                },
                "decisions": [
                    {
                        "id": "DEC-STATE",
                        "question": "Which state owner is authoritative?",
                        "options": ["A", "B"],
                        "recommendation": "A",
                        "user_decision": "B",
                        "evidence": "user explicitly chose B",
                    }
                ],
                "interruption_budget": {
                    "batch_questions": True,
                    "max_design_checkpoints": 1,
                },
            }
            task.write_text(
                yaml.safe_dump(task_data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            candidate_id = propose_and_approve(
                project,
                task,
                key="stale-authority-memory",
            )

            task_data = yaml.safe_load(task.read_text(encoding="utf-8"))
            task_data["human_in_loop"]["decisions"][0]["user_decision"] = "A"
            task_data["human_in_loop"]["decisions"][0]["evidence"] = (
                "user explicitly reconsidered and selected A"
            )
            task.write_text(
                yaml.safe_dump(task_data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            promoted = run(
                project,
                "durable_memory.py",
                "--project",
                str(project),
                "promote",
                candidate_id,
            )
            self.assertNotEqual(promoted.returncode, 0)
            self.assertIn("authoritative human decisions changed", promoted.stderr)
            self.assertFalse((project / "knowledge" / "index.yaml").exists())


if __name__ == "__main__":
    unittest.main()
