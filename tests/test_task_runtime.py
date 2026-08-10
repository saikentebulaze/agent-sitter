from __future__ import annotations

from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.task_runtime import (  # noqa: E402
    orchestrator_provider,
    require_orchestrator_provider,
)


class TaskRuntimeTests(unittest.TestCase):
    def test_new_task_template_declares_codex_orchestrator(self) -> None:
        template = yaml.safe_load(
            (
                ROOT
                / "adapters"
                / "default"
                / "skills"
                / "change-governor"
                / "assets"
                / "task.yaml.template"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(orchestrator_provider(template), "codex")
        self.assertEqual(
            template["execution"]["orchestrator_provider"],
            "codex",
        )

    def test_legacy_task_without_execution_defaults_to_codex(self) -> None:
        self.assertEqual(orchestrator_provider({"schema_version": 4}), "codex")

    def test_explicit_claude_provider_is_supported(self) -> None:
        self.assertEqual(
            orchestrator_provider(
                {"execution": {"orchestrator_provider": "claude"}}
            ),
            "claude",
        )

    def test_unknown_explicit_provider_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Supported providers: claude, codex",
        ):
            orchestrator_provider(
                {"execution": {"orchestrator_provider": "opencode"}}
            )

    def test_task_provider_is_not_silently_reinterpreted(self) -> None:
        task = {"execution": {"orchestrator_provider": "codex"}}
        require_orchestrator_provider(task, "codex")
        with self.assertRaisesRegex(ValueError, "immutable"):
            require_orchestrator_provider(task, "claude")

    def test_claude_task_cannot_be_required_as_codex(self) -> None:
        task = {"execution": {"orchestrator_provider": "claude"}}
        require_orchestrator_provider(task, "claude")
        with self.assertRaisesRegex(ValueError, "immutable"):
            require_orchestrator_provider(task, "codex")


if __name__ == "__main__":
    unittest.main()
