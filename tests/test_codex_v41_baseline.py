from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import install as installer_module  # noqa: E402
from core.managed_projection import MARKER  # noqa: E402
from providers.codex.projection import (  # noqa: E402
    entrypoint_text,
    skill_metadata_text,
    skill_wrapper_text,
    toml_text,
)


SOURCE_BLOBS = {
    "adapters/default/codex/config.toml": "6bcf94f799157b4ec8670e23d1d97d8d08a22520",
    "adapters/default/codex/agents/context-scout.toml": "24e9b93c99e4b9abeee71e48d36b572ba5bbfd0a",
    "adapters/default/codex/agents/deep-reviewer.toml": "2eef5303c2b68dcfc253306401a10078a1bd91ca",
    "adapters/default/codex/agents/framework-scout.toml": "4b66a03d2c8c3a0aafd696e98ebfc27317fb2e23",
    "adapters/default/codex/agents/source-locator.toml": "08daf527a4e8f4e404dddccc2f333e3e2579408f",
    "adapters/default/codex/agents/maintainer-reviewer.toml": "5fb31c4ce049e55efe4e816459f58f6044b221ac",
    "adapters/default/codex/agents/test-scout.toml": "617749ab79722162e9ac985b3459190d8d673ccc",
}

# V6 may add roles without modifying the frozen V4.1 security/config blobs above.
ADDITIVE_V6_CODEX_ROLES = {"memory_scout.toml"}

SKILLS = (
    "architecture-health-check",
    "change-governor",
    "decision-grill",
    "maintainer-handoff",
)


def git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def repository_text_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").encode("utf-8")


class CodexBehaviorBaselineTests(unittest.TestCase):
    def create_project(self, directory: str) -> Path:
        project = Path(directory) / "project"
        project.mkdir()
        result = subprocess.run(
            ["git", "init", str(project)],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def test_codex_security_and_role_assets_remain_frozen_v41_blobs(self) -> None:
        for relative, expected in SOURCE_BLOBS.items():
            with self.subTest(path=relative):
                self.assertEqual(git_blob_sha(repository_text_bytes(ROOT / relative)), expected)

    def test_fresh_install_preserves_runtime_assets_but_uses_adaptive_router(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(directory)
            installer_module.install(project, dry_run=False)

            self.assertEqual(
                (project / "AGENTS.md").read_text(encoding="utf-8"),
                entrypoint_text(),
            )
            entrypoint = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("lightweight routing policy", entrypoint)
            self.assertIn("Do not load the full Governor", entrypoint)

            adapter = ROOT / "adapters" / "default"
            marker = f"# {MARKER}; do not edit.\n"
            config_source = adapter / "codex" / "config.toml"
            self.assertEqual(
                (project / ".codex" / "config.toml").read_text(encoding="utf-8"),
                toml_text(config_source),
            )
            self.assertTrue(toml_text(config_source).startswith(marker + config_source.read_text(encoding="utf-8")))

            for source in sorted((adapter / "codex" / "agents").glob("*.toml")):
                relative = Path(".codex/agents") / source.name
                with self.subTest(path=str(relative)):
                    self.assertEqual(
                        (project / relative).read_text(encoding="utf-8"),
                        marker + source.read_text(encoding="utf-8"),
                    )

            for name in SKILLS:
                with self.subTest(skill=name):
                    source = adapter / "skills" / name / "SKILL.md"
                    wrapper = project / ".agents" / "skills" / name / "SKILL.md"
                    self.assertEqual(wrapper.read_text(encoding="utf-8"), skill_wrapper_text(source))
                    self.assertNotIn("Before taking any action", wrapper.read_text(encoding="utf-8"))

                    metadata_source = adapter / "skills" / name / "agents" / "openai.yaml"
                    if metadata_source.is_file():
                        metadata = project / ".agents" / "skills" / name / "agents" / "openai.yaml"
                        self.assertEqual(
                            metadata.read_text(encoding="utf-8"),
                            skill_metadata_text(metadata_source),
                        )

            governor_metadata = yaml.safe_load(
                (
                    project / ".agents" / "skills" / "change-governor" / "agents" / "openai.yaml"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(governor_metadata["policy"]["allow_implicit_invocation"])

            expected = {
                "AGENTS.md",
                ".codex/config.toml",
                *{
                    f".codex/agents/{Path(path).name}"
                    for path in SOURCE_BLOBS
                    if "/agents/" in path
                },
                *{f".codex/agents/{name}" for name in ADDITIVE_V6_CODEX_ROLES},
                *{f".agents/skills/{name}/SKILL.md" for name in SKILLS},
                *{
                    f".agents/skills/{name}/agents/openai.yaml"
                    for name in SKILLS
                    if (adapter / "skills" / name / "agents" / "openai.yaml").is_file()
                },
            }
            lock = yaml.safe_load(
                (project / ".harness" / "sitter" / "manifest-lock.yaml").read_text(encoding="utf-8")
            )
            actual = {str(key).replace("\\", "/") for key in lock["projections"]}
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
