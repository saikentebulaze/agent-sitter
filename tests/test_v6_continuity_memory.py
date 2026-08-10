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

from active_task_index import session_start_payload  # noqa: E402
from memory_context import memory_conflicts, memory_freshness, recall_memory  # noqa: E402
from project_context import ProjectContext  # noqa: E402


def git(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=check,
    )


def create_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "v6@example.invalid")
    git(project, "config", "user.name", "V6 Fixture")
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def run_tool(project: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(project: Path, message: str) -> str:
    git(project, "add", "-A")
    git(project, "commit", "-m", message)
    return git(project, "rev-parse", "HEAD").stdout.strip()


def write_knowledge(project: Path, entries: list[dict]) -> None:
    index = project / "knowledge" / "index.yaml"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        yaml.safe_dump({"version": 1, "entries": entries}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for entry in entries:
        path = project / str(entry["path"])
        if not path.exists():
            write(path, f"# {entry['title']}\n\nDurable semantic summary for {entry['id']}.\n")


def base_entry(entry_id: str, title: str, entry_type: str, path: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "type": entry_type,
        "evidence_status": "verified",
        "architecture_status": "current",
        "path": path,
        "domains": [],
        "keywords": [],
        "related": [],
    }


class V6ContinuityTests(unittest.TestCase):
    def test_single_active_task_produces_resume_hint_without_history_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            result = run_tool(
                project,
                "create_task.py",
                "continuity-task",
                "--title",
                "Continuity task",
                "--entry",
                "investigation",
                "--signature",
                "continuity-task",
                "--project",
                str(project),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = session_start_payload(context)
            self.assertEqual(payload["resume_hint"], "continuity-task")
            self.assertEqual(payload["active_task_count"], 1)
            self.assertFalse(payload["history_scanned"])
            self.assertFalse(payload["durable_memory_loaded"])
            self.assertEqual(
                payload["files_read"],
                [".agent-work/_context/active-tasks.yaml"],
            )

    def test_p1_session_start_is_independent_of_archived_task_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            for task_id in ("active-one", "active-two"):
                result = run_tool(
                    project,
                    "create_task.py",
                    task_id,
                    "--title",
                    task_id,
                    "--entry",
                    "investigation",
                    "--signature",
                    task_id,
                    "--project",
                    str(project),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            baseline = session_start_payload(context)

            for count in (100, 1000):
                for index in range(count):
                    history = project / ".agent-work" / "_archive" / f"task-{count}-{index:04d}"
                    history.mkdir(parents=True, exist_ok=True)
                    (history / "task.yaml").write_text(
                        "schema_version: 4\nstatus: completed\n",
                        encoding="utf-8",
                    )
                observed = session_start_payload(context)
                self.assertEqual(observed, baseline)
                self.assertEqual(observed["active_task_count"], 2)
                self.assertFalse(observed["history_scanned"])


class V6MemoryTests(unittest.TestCase):
    def prepare_memory_repo(self, root: Path) -> tuple[Path, ProjectContext, str, str]:
        project, context = create_project(root)
        write(project / "src" / "state" / "session.py", "VALUE = 0\n")
        write(project / "docs" / "notes.md", "root\n")
        root_commit = commit(project, "root")
        write(project / "src" / "state" / "session.py", "VALUE = 1\n")
        source_commit = commit(project, "memory source")
        return project, context, root_commit, source_commit

    def code_memory(self, source_commit: str) -> dict:
        entry = base_entry("K01", "Committed state ownership", "fact", "knowledge/k01.md")
        entry.update(
            {
                "domains": ["state"],
                "keywords": ["committed", "ownership"],
                "memory_key": "state-ownership",
                "source_commit": source_commit,
                "validity_surface": ["src/state"],
            }
        )
        return entry

    def test_c6_fresh_suspect_unknown_and_working_tree_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, root_commit, source_commit = self.prepare_memory_repo(Path(directory))
            entry = self.code_memory(source_commit)
            self.assertEqual(memory_freshness(context, entry)["status"], "fresh")

            write(project / "docs" / "notes.md", "unrelated\n")
            commit(project, "unrelated")
            self.assertEqual(memory_freshness(context, entry)["status"], "fresh")

            write(project / "src" / "state" / "session.py", "VALUE = 2\n")
            self.assertEqual(memory_freshness(context, entry)["status"], "suspect")
            git(project, "reset", "--hard")

            write(project / "src" / "state" / "session.py", "VALUE = 3\n")
            commit(project, "related")
            self.assertEqual(memory_freshness(context, entry)["status"], "suspect")

            git(project, "checkout", "-B", "divergent", root_commit)
            write(project / "src" / "other.py", "VALUE = 1\n")
            commit(project, "divergent")
            self.assertEqual(memory_freshness(context, entry)["status"], "unknown")
            self.assertFalse(memory_freshness(context, entry)["usable_as_current_fact"])

    def test_c4_recall_loads_only_small_relevant_set_and_suppresses_untriggered_threads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, _, source_commit = self.prepare_memory_repo(Path(directory))
            stable = self.code_memory(source_commit)
            thread = base_entry("O01", "Finish parser migration", "open-thread", "knowledge/o01.md")
            thread.update(
                {
                    "keywords": ["parser", "migration"],
                    "memory_key": "parser-migration",
                    "trigger_terms": ["parser", "migration"],
                    "trigger_condition": "A new task touches parser migration.",
                }
            )
            watch = base_entry("W01", "Compiler compatibility watch", "watchpoint", "knowledge/w01.md")
            watch.update(
                {
                    "keywords": ["compiler", "compatibility"],
                    "memory_key": "compiler-watch",
                    "trigger_terms": ["compiler", "toolchain"],
                    "trigger_condition": "Compiler/toolchain version changes.",
                }
            )
            noise = []
            for index in range(20):
                entry = base_entry(
                    f"N{index:02d}",
                    f"Unrelated knowledge {index}",
                    "fact",
                    f"knowledge/noise-{index}.md",
                )
                entry["keywords"] = [f"noise-{index}"]
                noise.append(entry)
            write_knowledge(project, [stable, thread, watch, *noise])

            parser = recall_memory(context, "continue parser migration", limit=3)
            selected = {item["id"] for item in parser["selected"]}
            self.assertIn("O01", selected)
            self.assertLessEqual(parser["selected_count"], 3)
            self.assertEqual(parser["history_tasks_scanned"], 0)

            low = recall_memory(context, "rename local variable", limit=3)
            low_ids = {item["id"] for item in low["selected"]}
            self.assertNotIn("O01", low_ids)
            self.assertNotIn("W01", low_ids)

    def test_h5_conflict_is_historical_lead_until_explicit_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context, _, source_commit = self.prepare_memory_repo(Path(directory))
            first = self.code_memory(source_commit)
            second = self.code_memory(source_commit)
            second["id"] = "K02"
            second["title"] = "Alternative state ownership"
            second["path"] = "knowledge/k02.md"
            write_knowledge(project, [first, second])
            conflicts = memory_conflicts([first, second])
            self.assertEqual(conflicts[0]["memory_key"], "state-ownership")
            recalled = recall_memory(context, "state ownership", limit=3)
            self.assertTrue(all(item["conflict"] for item in recalled["selected"]))
            self.assertTrue(
                all(item["usage"] == "historical-lead" for item in recalled["selected"])
            )

            second["supersedes"] = ["K01"]
            write_knowledge(project, [first, second])
            self.assertEqual(memory_conflicts([first, second]), [])
            recalled = recall_memory(context, "state ownership", limit=3)
            self.assertEqual([item["id"] for item in recalled["selected"]], ["K02"])


class V6LearningCurationTests(unittest.TestCase):
    def test_h4_multiple_durable_candidates_require_individual_user_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _ = create_project(Path(directory))
            write(project / "src" / "core.py", "VALUE = 1\n")
            commit(project, "fixture")
            created = run_tool(
                project,
                "create_task.py",
                "memory-closeout",
                "--title",
                "Memory closeout",
                "--entry",
                "investigation",
                "--signature",
                "memory-closeout",
                "--project",
                str(project),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            task = project / ".agent-work" / "memory-closeout" / "task.yaml"
            intake = run_tool(
                project,
                "learning.py",
                "--project",
                str(project),
                "intake",
                str(task.relative_to(project)),
            )
            self.assertEqual(intake.returncode, 0, intake.stderr)

            candidates = [
                (
                    "stable state ownership",
                    "Stable state ownership",
                    "project-knowledge",
                    ["src/core.py"],
                    [],
                ),
                (
                    "parser followup",
                    "Parser follow-up",
                    "open-thread",
                    [],
                    ["parser"],
                ),
                (
                    "compiler warning",
                    "Compiler compatibility warning",
                    "watchpoint",
                    [],
                    ["compiler"],
                ),
            ]
            for key, title, target, surfaces, triggers in candidates:
                args = [
                    "--project", str(project),
                    "propose-durable", str(task.relative_to(project)),
                    "--key", key,
                    "--title", title,
                    "--target", target,
                    "--summary", f"summary for {title}",
                    "--memory-key", key.replace(" ", "-"),
                    "--evidence", "fixture-evidence",
                ]
                for surface in surfaces:
                    args.extend(["--validity-surface", surface])
                for trigger in triggers:
                    args.extend(["--trigger-term", trigger])
                result = run_tool(project, "learning.py", *args)
                self.assertEqual(result.returncode, 0, result.stderr)

            closeout = run_tool(
                project,
                "learning.py",
                "--project",
                str(project),
                "closeout",
                str(task.relative_to(project)),
            )
            self.assertEqual(closeout.returncode, 0, closeout.stderr)
            task_data = yaml.safe_load(task.read_text(encoding="utf-8"))
            ids = task_data["learning"]["closeout"]["candidates_ready_for_review"]
            self.assertEqual(len(ids), 3)

            bulk = run_tool(
                project,
                "learning.py",
                "--project",
                str(project),
                "attention",
                str(task.relative_to(project)),
                "--decision",
                "approved",
                "--evidence",
                "one click must not approve all",
            )
            self.assertNotEqual(bulk.returncode, 0)
            self.assertIn("--candidate", bulk.stderr)

            decisions = ["approved", "dismissed", "approved"]
            for candidate_id, decision in zip(ids, decisions):
                result = run_tool(
                    project,
                    "learning.py",
                    "--project",
                    str(project),
                    "attention",
                    str(task.relative_to(project)),
                    "--candidate",
                    candidate_id,
                    "--decision",
                    decision,
                    "--evidence",
                    f"user chose {decision} for {candidate_id}",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            task_data = yaml.safe_load(task.read_text(encoding="utf-8"))
            attention = task_data["learning"]["user_attention"]
            self.assertEqual(attention["decision"], "resolved")
            self.assertEqual(set(attention["candidate_decisions"]), set(ids))


if __name__ == "__main__":
    unittest.main()
