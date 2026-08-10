from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

import yaml

import install as installer


class MultiProviderInstallationTests(unittest.TestCase):
    def project(self, directory: str) -> Path:
        project=Path(directory)/"project"; project.mkdir(); result=subprocess.run(["git","init",str(project)],capture_output=True,text=True); self.assertEqual(result.returncode,0,result.stderr); return project
    def lock(self, project: Path) -> dict:
        return yaml.safe_load((project/".harness"/"sitter"/"manifest-lock.yaml").read_text(encoding="utf-8"))
    def test_default_fresh_install_remains_codex_only(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False); self.assertEqual(self.lock(project)["enabled_providers"],["codex"]); self.assertTrue((project/"AGENTS.md").is_file()); self.assertFalse((project/"CLAUDE.local.md").exists())
    def test_explicit_claude_only_install_does_not_project_codex_or_user_settings(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False,provider_ids=("claude",)); lock=self.lock(project)
            self.assertEqual(lock["enabled_providers"],["claude"]); self.assertTrue((project/"CLAUDE.local.md").is_file()); self.assertFalse((project/"AGENTS.md").exists()); self.assertFalse((project/".claude"/"settings.local.json").exists())
    def test_explicit_dual_provider_install_projects_both(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False,provider_ids=("codex","claude")); lock=self.lock(project)
            self.assertEqual(lock["enabled_providers"],["codex","claude"]); self.assertEqual(set(lock["projection_owners"].values()),{"codex","claude"}); self.assertTrue((project/"AGENTS.md").is_file()); self.assertTrue((project/"CLAUDE.local.md").is_file())
    def test_update_without_provider_arguments_preserves_existing_set(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False,provider_ids=("claude",)); installer.install(project,dry_run=False); self.assertEqual(self.lock(project)["enabled_providers"],["claude"])
    def test_user_local_settings_are_never_overwritten_or_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); settings=project/".claude"/"settings.local.json"; settings.parent.mkdir(); original='{"user_owned": true}\n'; settings.write_text(original,encoding="utf-8")
            installer.install(project,dry_run=False,provider_ids=("claude",)); installer.install(project,dry_run=False,reinstall=True)
            self.assertEqual(settings.read_text(encoding="utf-8"),original); self.assertNotIn(".claude/settings.local.json",self.lock(project)["projections"])
    def test_enable_provider_adds_claude_to_existing_codex_install(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False); installer.install(project,dry_run=False,enable_provider_ids=("claude",)); self.assertEqual(self.lock(project)["enabled_providers"],["codex","claude"])
    def test_existing_provider_cannot_be_removed_implicitly(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); installer.install(project,dry_run=False,provider_ids=("codex","claude"))
            with self.assertRaisesRegex(ValueError,"disabling.*not supported"): installer.install(project,dry_run=False,provider_ids=("claude",))
    def test_claude_only_install_rejects_codex_trust_flag(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d)
            with self.assertRaisesRegex(ValueError,"Codex trust"): installer.install(project,dry_run=False,provider_ids=("claude",),trust_project=True,codex_home=Path(d)/"codex-home")
    def test_local_model_override_is_excluded_but_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            project=self.project(d); local=project/".harness"/"sitter.models.local.yaml"; local.parent.mkdir(); original="schema_version: 1\nproviders: {}\n"; local.write_text(original,encoding="utf-8")
            installer.install(project,dry_run=False); installer.install(project,dry_run=False,reinstall=True); self.assertEqual(local.read_text(encoding="utf-8"),original)
            ignored=subprocess.run(["git","-C",str(project),"check-ignore","-q","--",".harness/sitter.models.local.yaml"],capture_output=True,text=True); self.assertEqual(ignored.returncode,0,ignored.stderr)


if __name__=="__main__": unittest.main()
