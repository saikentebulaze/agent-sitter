from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from model_profiles import (  # noqa: E402
    ModelProfileError,
    load_effective_model_profiles,
    normalize_model_grade,
    resolve_model_selection,
)
from project_context import ProjectContext  # noqa: E402


class ModelProfileTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_default_profiles_preserve_codex_and_define_claude_grades(self) -> None:
        context = self.context(ROOT)
        codex = resolve_model_selection(context, "codex", "context_scout")
        claude = resolve_model_selection(context, "claude", "deep_reviewer")
        self.assertEqual(
            (codex.model_grade, codex.model_selector, codex.reasoning_effort),
            ("low", "gpt-5.6-luna", "medium"),
        )
        self.assertEqual(
            (claude.model_grade, claude.model_selector, claude.reasoning_effort),
            ("high", "opus", "high"),
        )

    def test_partial_local_override_changes_only_selected_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "providers": {
                            "claude": {
                                "models": {
                                    "high": {"selector": "claude-opus-next"}
                                }
                            }
                        },
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            context = self.context(project)
            self.assertEqual(
                resolve_model_selection(
                    context, "claude", "deep_reviewer"
                ).model_selector,
                "claude-opus-next",
            )
            self.assertEqual(
                resolve_model_selection(
                    context, "claude", "context_scout"
                ).model_selector,
                "haiku",
            )

    def test_unknown_native_selector_is_configuration_not_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\nproviders:\n  codex:\n    models:\n      low:\n        selector: future-codex-model\n",
                encoding="utf-8",
            )
            selection = resolve_model_selection(
                self.context(project), "codex", "source_locator"
            )
            self.assertEqual(selection.model_selector, "future-codex-model")

    def test_claude_inherit_is_rejected_for_governed_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\nproviders:\n  claude:\n    models:\n      low:\n        selector: inherit\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ModelProfileError,
                "must not use model: inherit",
            ):
                load_effective_model_profiles(self.context(project))

    def test_duplicate_grade_selectors_are_rejected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\nproviders:\n  claude:\n    models:\n      low:\n        selector: sonnet\n      medium:\n        selector: sonnet\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ModelProfileError, "same selector"):
                load_effective_model_profiles(self.context(project))

    def test_grade_aliasing_can_be_enabled_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\nallow_grade_aliasing: true\nproviders:\n  claude:\n    models:\n      low:\n        selector: sonnet\n      medium:\n        selector: sonnet\n",
                encoding="utf-8",
            )
            config, digest = load_effective_model_profiles(self.context(project))
            self.assertEqual(
                config["providers"]["claude"]["models"]["low"]["selector"],
                "sonnet",
            )
            self.assertEqual(len(digest), 64)

    def test_legacy_tiers_normalize_without_becoming_new_output(self) -> None:
        self.assertEqual(normalize_model_grade("luna"), "low")
        self.assertEqual(normalize_model_grade("terra"), "medium")
        self.assertEqual(normalize_model_grade("sol"), "high")

    def test_unknown_overlay_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            local = project / ".harness" / "sitter.models.local.yaml"
            local.parent.mkdir()
            local.write_text(
                "schema_version: 1\nunexpected: true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ModelProfileError, "unknown top-level field"):
                load_effective_model_profiles(self.context(project))


if __name__ == "__main__":
    unittest.main()
