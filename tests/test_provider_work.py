from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from delegation_transaction import authorize_delegation  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from provider_work import provider_parent_tier, task_provider  # noqa: E402
from work_graph import load_yaml  # noqa: E402


class ProviderWorkTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_provider_grade_is_preserved_for_claude_and_mapped_for_codex(self) -> None:
        self.assertEqual(provider_parent_tier("claude", "low"), "low")
        self.assertEqual(provider_parent_tier("claude", "medium"), "medium")
        self.assertEqual(provider_parent_tier("claude", "high"), "high")
        self.assertEqual(provider_parent_tier("codex", "low"), "luna")
        self.assertEqual(provider_parent_tier("codex", "medium"), "terra")
        self.assertEqual(provider_parent_tier("codex", "high"), "sol")

    def test_task_provider_reads_explicit_and_legacy_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            context = self.context(project)
            initialize_provider_task(
                context,
                task_id="claude-task",
                title="Claude task",
                entry="investigation",
                provider_id="claude",
                signature="claude-task",
            )
            self.assertEqual(task_provider(context, "claude-task"), "claude")

            legacy = project / ".agent-work" / "legacy-task"
            legacy.mkdir(parents=True)
            source = (
                ROOT
                / "adapters"
                / "default"
                / "skills"
                / "change-governor"
                / "assets"
                / "task.yaml.template"
            ).read_text(encoding="utf-8")
            source = source.replace(
                "execution:\n  orchestrator_provider: codex\n\n",
                "",
            ).replace("replace-with-task-id", "legacy-task")
            (legacy / "task.yaml").write_text(source, encoding="utf-8")
            self.assertEqual(task_provider(context, "legacy-task"), "codex")

    def test_claude_authorization_records_provider_grade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            context = self.context(project)
            task_root = initialize_provider_task(
                context,
                task_id="claude-grade",
                title="Claude grade",
                entry="investigation",
                provider_id="claude",
                signature="claude-grade",
            )
            authorize_delegation(
                context,
                "claude-grade",
                decision="required",
                scopes=["readonly-exploration"],
                evidence="authorized",
                parent_model="sonnet",
                parent_tier=provider_parent_tier("claude", "medium"),
            )
            task = load_yaml(task_root / "task.yaml")
            budget = task["delegation"]["model_budget"]
            self.assertEqual(budget["parent_model"], "sonnet")
            self.assertEqual(budget["parent_tier"], "medium")

    def test_codex_authorization_keeps_legacy_tier_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            context = self.context(project)
            task_root = initialize_provider_task(
                context,
                task_id="codex-grade",
                title="Codex grade",
                entry="investigation",
                provider_id="codex",
                signature="codex-grade",
            )
            authorize_delegation(
                context,
                "codex-grade",
                decision="required",
                scopes=["readonly-exploration"],
                evidence="authorized",
                parent_model="gpt-5.6-terra",
                parent_tier=provider_parent_tier("codex", "medium"),
            )
            task = load_yaml(task_root / "task.yaml")
            self.assertEqual(
                task["delegation"]["model_budget"]["parent_tier"],
                "terra",
            )


if __name__ == "__main__":
    unittest.main()
