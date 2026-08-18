from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from provider_role_runner import build_role_packet  # noqa: E402


def write_task(project: Path, task_id: str, provider: str) -> None:
    root = project / ".agent-work" / task_id
    root.mkdir(parents=True)
    (root / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 4,
                "id": task_id,
                "status": "active",
                "execution": {"orchestrator_provider": provider},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class ProviderRoleRunnerTests(unittest.TestCase):
    def make_context(self, directory: str) -> tuple[Path, ProjectContext]:
        project = Path(directory) / "project"
        project.mkdir()
        return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_codex_packet_freezes_real_maintainer_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = self.make_context(directory)
            write_task(project, "task-codex", "codex")
            packet, _ = build_role_packet(context, "task-codex", role="maintainer_reviewer")
            requested = packet["requested_profile"]
            self.assertEqual(packet["runtime"]["provider"], "codex")
            self.assertEqual(requested["agent"], "maintainer_reviewer")
            self.assertEqual(requested["sandbox_mode"], "read-only")
            self.assertTrue(requested["model"])
            self.assertTrue(requested["tier"])

    def test_claude_packet_freezes_provider_specific_projection_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = self.make_context(directory)
            write_task(project, "task-claude", "claude")
            packet, _ = build_role_packet(context, "task-claude", role="maintainer_reviewer")
            requested = packet["requested_profile"]
            self.assertEqual(packet["runtime"]["provider"], "claude")
            self.assertEqual(requested["role_id"], "maintainer_reviewer")
            self.assertEqual(requested["write_isolation"], "tool-restricted")
            for key in (
                "profile_source_sha256",
                "model_config_sha256",
                "agent_projection_sha256",
                "settings_projection_sha256",
                "hook_projection_sha256",
            ):
                self.assertEqual(len(requested[key]), 64)


if __name__ == "__main__":
    unittest.main()
