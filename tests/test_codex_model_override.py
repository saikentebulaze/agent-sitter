from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from providers.codex.provider import CodexProvider  # noqa: E402


class CodexModelOverrideTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_future_selector_changes_profile_and_projection_without_python_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\n"
                "providers:\n"
                "  codex:\n"
                "    models:\n"
                "      low:\n"
                "        selector: future-codex-fast-model\n",
                encoding="utf-8",
            )
            provider = CodexProvider()
            profile = provider.load_role_profile(
                self.context(project),
                "context_scout",
            )
            self.assertEqual(profile.model, "future-codex-fast-model")
            self.assertEqual(profile.tier, "luna")
            projection = next(
                item
                for item in provider.projection_plan(
                    self.context(project)
                ).projections
                if item.relative_path.as_posix()
                == ".codex/agents/context-scout.toml"
            )
            self.assertIn(
                'model = "future-codex-fast-model"',
                projection.content,
            )
            self.assertIn(
                'model_reasoning_effort = "medium"',
                projection.content,
            )
            self.assertNotIn('model = "gpt-5.6-luna"', projection.content)

    def test_role_effort_override_changes_only_native_effort_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\n"
                "roles:\n"
                "  source_locator:\n"
                "    reasoning_effort: medium\n",
                encoding="utf-8",
            )
            provider = CodexProvider()
            projection = next(
                item
                for item in provider.projection_plan(
                    self.context(project)
                ).projections
                if item.relative_path.as_posix()
                == ".codex/agents/source-locator.toml"
            )
            self.assertIn('model = "gpt-5.6-luna"', projection.content)
            self.assertIn(
                'model_reasoning_effort = "medium"',
                projection.content,
            )


if __name__ == "__main__":
    unittest.main()
