from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import self_check  # noqa: E402
from core.provider_registry import get_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402


class ProviderSelfCheckTests(unittest.TestCase):
    def context(self) -> ProjectContext:
        return ProjectContext(ROOT, ROOT, ROOT / "adapters" / "default")

    def test_codex_provider_declares_and_validates_its_assets(self) -> None:
        provider = get_provider("codex")
        assets = provider.required_assets(self.context())
        self.assertIn(
            ROOT / "adapters" / "default" / "codex" / "config.toml",
            assets,
        )
        self.assertIn(ROOT / "runtime" / "codex_runtime_attestation.py", assets)
        provider.validate_static_configuration(self.context())

    def test_common_self_check_dispatches_provider_validation(self) -> None:
        class FakeProvider:
            provider_id = "fake"

            def __init__(self) -> None:
                self.called = False

            def required_assets(self, context: ProjectContext) -> tuple[Path, ...]:
                return (context.package_root / "manifest.yaml",)

            def validate_static_configuration(self, context: ProjectContext) -> None:
                self.called = True

        fake = FakeProvider()
        with mock.patch.object(
            self_check,
            "registered_providers",
            return_value=("fake",),
        ), mock.patch.object(
            self_check,
            "get_provider",
            return_value=fake,
        ):
            self_check.run_self_check(self.context())
        self.assertTrue(fake.called)


if __name__ == "__main__":
    unittest.main()
