from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from providers.codex import attestation as native_module  # noqa: E402
from providers.codex import configured_models  # noqa: E402
from providers.codex import managed_runtime as managed_module  # noqa: E402


class CodexConfiguredRuntimeTests(unittest.TestCase):
    def context(self, directory: str) -> ProjectContext:
        project = Path(directory) / "project"
        project.mkdir()
        local = project / ".harness" / "sitter.models.local.yaml"
        local.parent.mkdir()
        local.write_text(
            "schema_version: 1\n"
            "providers:\n"
            "  codex:\n"
            "    models:\n"
            "      low:\n"
            "        selector: future-codex-fast\n"
            "      medium:\n"
            "        selector: future-codex-balanced\n"
            "      high:\n"
            "        selector: future-codex-deep\n",
            encoding="utf-8",
        )
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_effective_mapping_adds_future_selectors_without_mutating_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)
            original_native = native_module.MODEL_TIERS
            original_managed = managed_module.MODEL_TIERS
            with configured_models.effective_tier_mapping(context) as mapping:
                self.assertEqual(mapping["future-codex-fast"], "luna")
                self.assertEqual(mapping["future-codex-balanced"], "terra")
                self.assertEqual(mapping["future-codex-deep"], "sol")
                self.assertIs(native_module.MODEL_TIERS, mapping)
                self.assertIs(managed_module.MODEL_TIERS, mapping)
            self.assertIs(native_module.MODEL_TIERS, original_native)
            self.assertIs(managed_module.MODEL_TIERS, original_managed)

    def test_managed_wrapper_exposes_mapping_during_real_collector_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)

            def fake_execute(context, packet, **kwargs):
                self.assertEqual(
                    managed_module.MODEL_TIERS["future-codex-fast"],
                    "luna",
                )
                return "output", {"observed": {"tier": "luna"}}, {}

            with mock.patch.object(
                managed_module,
                "execute_managed_read_only",
                side_effect=fake_execute,
            ) as execute:
                result = configured_models.execute_managed_read_only(
                    context,
                    {"requested_profile": {}},
                    message="probe",
                )
            execute.assert_called_once()
            self.assertEqual(result[1]["observed"]["tier"], "luna")

    def test_native_wrapper_exposes_mapping_during_collector_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(directory)

            def fake_collect(context, packet, **kwargs):
                self.assertEqual(
                    native_module.MODEL_TIERS["future-codex-deep"],
                    "sol",
                )
                return {"observed": {"tier": "sol"}}, {}

            with mock.patch.object(
                native_module,
                "collect_native_attestation",
                side_effect=fake_collect,
            ) as collect:
                result = configured_models.collect_native_attestation(
                    context,
                    {"requested_profile": {}},
                )
            collect.assert_called_once()
            self.assertEqual(result[0]["observed"]["tier"], "sol")


if __name__ == "__main__":
    unittest.main()
