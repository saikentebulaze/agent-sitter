from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import install as installer_module  # noqa: E402
from core.projection_plan import (  # noqa: E402
    Projection,
    ProjectionPlan,
    merge_projection_plans,
)
from core.provider_registry import get_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402


class ProjectionPlanTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def create_project(self, directory: str) -> Path:
        project = Path(directory) / "project"
        project.mkdir()
        completed = subprocess.run(
            ["git", "init", str(project)],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return project

    def test_codex_plan_matches_current_installer_targets_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(directory)
            provider = get_provider("codex")
            plan = provider.projection_plan(self.context(project))
            expected_targets = tuple(installer_module.projection_targets(project))
            self.assertEqual(set(plan.targets(project)), set(expected_targets))

            installer_module.install(project, dry_run=False)
            for projection in plan.projections:
                with self.subTest(path=str(projection.relative_path)):
                    self.assertEqual(
                        projection.target(project).read_text(encoding="utf-8"),
                        projection.content,
                    )

    def test_projection_rejects_absolute_and_parent_paths(self) -> None:
        for value in (Path("/absolute"), Path("../escape")):
            with self.subTest(path=str(value)):
                with self.assertRaisesRegex(ValueError, "must stay relative"):
                    Projection("test", value, "content")

    def test_plan_rejects_duplicate_paths(self) -> None:
        item = Projection("codex", Path("AGENTS.md"), "content")
        with self.assertRaisesRegex(ValueError, "duplicate projection"):
            ProjectionPlan("codex", (item, item))

    def test_cross_provider_ownership_conflict_is_rejected(self) -> None:
        codex = ProjectionPlan(
            "codex",
            (Projection("codex", Path("AGENTS.md"), "codex"),),
        )
        claude = ProjectionPlan(
            "claude",
            (Projection("claude", Path("AGENTS.md"), "claude"),),
        )
        with self.assertRaisesRegex(ValueError, "ownership conflict"):
            merge_projection_plans((codex, claude))

    def test_case_only_cross_provider_conflict_is_rejected_portably(self) -> None:
        codex = ProjectionPlan(
            "codex",
            (Projection("codex", Path("CLAUDE.local.md"), "codex"),),
        )
        claude = ProjectionPlan(
            "claude",
            (Projection("claude", Path("claude.LOCAL.md"), "claude"),),
        )
        with self.assertRaisesRegex(ValueError, "ownership conflict"):
            merge_projection_plans((codex, claude))

    def test_file_directory_ancestor_conflict_is_rejected(self) -> None:
        codex = ProjectionPlan(
            "codex",
            (Projection("codex", Path(".claude"), "not-a-directory"),),
        )
        claude = ProjectionPlan(
            "claude",
            (
                Projection(
                    "claude",
                    Path(".claude/settings.local.json"),
                    "{}",
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "ownership conflict"):
            merge_projection_plans((codex, claude))

    def test_non_overlapping_provider_namespaces_merge_successfully(self) -> None:
        codex = ProjectionPlan(
            "codex",
            (Projection("codex", Path(".codex/config.toml"), "codex"),),
        )
        claude = ProjectionPlan(
            "claude",
            (
                Projection(
                    "claude",
                    Path(".claude/settings.local.json"),
                    "{}",
                ),
            ),
        )
        merged = merge_projection_plans((codex, claude))
        self.assertEqual(
            [item.relative_path.as_posix() for item in merged],
            [".codex/config.toml", ".claude/settings.local.json"],
        )


if __name__ == "__main__":
    unittest.main()
