from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    def test_manifest_declares_existing_runtime_and_default_adapter(self) -> None:
        manifest = ROOT / "manifest.yaml"

        self.assertTrue(manifest.is_file())
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))

        self.assertEqual(data["package"], "sitter")
        self.assertEqual(data["format_version"], 1)
        self.assertTrue((ROOT / data["runtime_path"]).is_dir())
        self.assertTrue((ROOT / data["adapters"]["default"]["path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
