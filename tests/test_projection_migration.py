from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import projection as legacy  # noqa: E402
from core import managed_projection as core_projection  # noqa: E402
from providers.codex import projection as codex_projection  # noqa: E402


class ProjectionMigrationTests(unittest.TestCase):
    def test_generic_projection_helpers_are_core_implementations(self) -> None:
        self.assertIs(legacy.is_managed, core_projection.is_managed)
        self.assertIs(
            legacy.assert_writable_projection,
            core_projection.assert_writable_projection,
        )
        self.assertIs(legacy.file_sha256, core_projection.file_sha256)

    def test_codex_renderers_are_provider_implementations(self) -> None:
        self.assertIs(legacy.entrypoint_text, codex_projection.entrypoint_text)
        self.assertIs(legacy.toml_text, codex_projection.toml_text)
        self.assertIs(
            legacy.skill_wrapper_text,
            codex_projection.skill_wrapper_text,
        )


if __name__ == "__main__":
    unittest.main()
