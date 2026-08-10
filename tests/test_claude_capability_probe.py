from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import install as installer  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from providers.claude.capability_probe import (  # noqa: E402
    load_current_report,
    probe_managed,
    write_report,
)
from providers.claude.managed_runtime import ClaudeManagedRuntimeError  # noqa: E402


class ClaudeCapabilityProbeTests(unittest.TestCase):
    def context(self, directory: str) -> ProjectContext:
        project = Path(directory) / "project"
        project.mkdir()
        result = subprocess.run(
            ["git", "init", str(project)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        installer.install(project, dry_run=False, provider_ids=("claude",))
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def executor(self, context, packet, *, message, **kwargs):
        match = re.search(r"([0-9a-f]{32})", message)
        self.assertIsNotNone(match)
        nonce = match.group(1)
        requested = packet["requested_profile"]
        attestation = {
            "execution": {"session_ref": f"claude-session:{requested['model_grade']}"},
            "observed": {
                "resolved_model": requested["model_selector"],
                "reasoning_effort": requested["reasoning_effort"],
            },
            "evidence": {"request_sha256": requested["profile_source_sha256"]},
        }
        return nonce, attestation, {"grade": requested["model_grade"]}

    def test_probe_reports_each_grade_separately_and_native_manual(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)
            report = probe_managed(
                context,
                executor=self.executor,
                version_provider=lambda _: "claude-code test-1",
            )
            self.assertEqual(set(report["managed"]), {"low", "medium", "high"})
            self.assertTrue(
                all(
                    item["status"] == "supported"
                    for item in report["managed"].values()
                )
            )
            self.assertEqual(report["managed"]["low"]["model_selector"], "haiku")
            self.assertEqual(report["managed"]["medium"]["model_selector"], "sonnet")
            self.assertEqual(report["managed"]["high"]["model_selector"], "opus")
            self.assertEqual(report["native"]["status"], "manual-required")
            self.assertIn("not reused", report["native"]["reason"])

    def test_one_failed_grade_does_not_get_hidden_by_other_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)

            def executor(context, packet, *, message, **kwargs):
                if packet["requested_profile"]["model_grade"] == "medium":
                    raise ClaudeManagedRuntimeError(
                        "configured medium model is unavailable"
                    )
                return self.executor(context, packet, message=message, **kwargs)

            report = probe_managed(
                context,
                executor=executor,
                version_provider=lambda _: "claude-code test-1",
            )
            self.assertEqual(report["managed"]["low"]["status"], "supported")
            self.assertEqual(report["managed"]["medium"]["status"], "unsupported")
            self.assertEqual(report["managed"]["high"]["status"], "supported")
            self.assertIn("unavailable", report["managed"]["medium"]["error"])

    def test_random_canary_must_be_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)

            def wrong_output(*args, **kwargs):
                return "plausible answer without canary", {}, {}

            report = probe_managed(
                context,
                executor=wrong_output,
                version_provider=lambda _: "claude-code test-1",
            )
            self.assertTrue(
                all(
                    item["status"] == "unsupported"
                    for item in report["managed"].values()
                )
            )
            self.assertTrue(
                all(
                    "random canary" in item["error"]
                    for item in report["managed"].values()
                )
            )

    def test_explicit_proxy_freeze_is_carried_into_request_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)
            local = (
                context.project_root
                / ".harness"
                / "sitter.models.local.yaml"
            )
            local.write_text(
                "schema_version: 1\n"
                "providers:\n"
                "  claude:\n"
                "    models:\n"
                "      low:\n"
                "        selector: haiku\n"
                "        resolution_mode: explicit-proxy\n"
                "        expected_resolved_model: deepseek-v4-flash\n"
                "        proxy_provider: deepseek\n"
                "      medium:\n"
                "        selector: sonnet\n"
                "        resolution_mode: explicit-proxy\n"
                "        expected_resolved_model: deepseek-v4-flash[1M]\n"
                "        proxy_provider: deepseek\n"
                "      high:\n"
                "        selector: opus\n"
                "        resolution_mode: explicit-proxy\n"
                "        expected_resolved_model: deepseek-v4-flash[1M]\n"
                "        proxy_provider: deepseek\n",
                encoding="utf-8",
            )
            expected = {
                "low": "deepseek-v4-flash",
                "medium": "deepseek-v4-flash[1M]",
                "high": "deepseek-v4-flash[1M]",
            }
            report = probe_managed(
                context,
                executor=self.executor,
                version_provider=lambda _: "claude-code test-1",
            )
            for grade in ("low", "medium", "high"):
                entry = report["managed"][grade]
                self.assertEqual(entry["status"], "supported")
                self.assertEqual(entry["model_selector"], {
                    "low": "haiku", "medium": "sonnet", "high": "opus",
                }[grade])
                self.assertEqual(
                    entry["model_resolution_mode"], "explicit-proxy"
                )
                self.assertEqual(
                    entry["expected_resolved_model"], expected[grade]
                )
                self.assertEqual(entry["proxy_provider"], "deepseek")

    def test_cache_is_valid_only_for_same_runtime_and_profile_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)
            report = probe_managed(
                context,
                executor=self.executor,
                version_provider=lambda _: "claude-code test-1",
            )
            path = write_report(context, report)
            self.assertTrue(path.is_file())
            current = load_current_report(
                context,
                version_provider=lambda _: "claude-code test-1",
            )
            self.assertIsNotNone(current)
            changed_version = load_current_report(
                context,
                version_provider=lambda _: "claude-code test-2",
            )
            self.assertIsNone(changed_version)

            local = (
                context.project_root
                / ".harness"
                / "sitter.models.local.yaml"
            )
            local.write_text(
                "schema_version: 1\n"
                "providers:\n"
                "  claude:\n"
                "    models:\n"
                "      low:\n"
                "        selector: future-haiku\n",
                encoding="utf-8",
            )
            changed_profile = load_current_report(
                context,
                version_provider=lambda _: "claude-code test-1",
            )
            self.assertIsNone(changed_profile)


if __name__ == "__main__":
    unittest.main()
