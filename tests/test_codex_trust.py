from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "runtime"))

from codex_trust import render_trusted_config  # noqa: E402


class CodexTrustAliasTests(unittest.TestCase):
    def alias_config(
        self,
        trust_root: Path,
        first_level: str | None,
        second_level: str | None,
    ) -> str:
        first = json.dumps(str(trust_root), ensure_ascii=False)
        second = json.dumps(str(trust_root) + "/.", ensure_ascii=False)

        def section(key: str, level: str | None, marker: str) -> str:
            body = f'trust_level = "{level}"\n' if level is not None else f"# {marker}\n"
            return f"[projects.{key}]\n{body}"

        return section(first, first_level, "canonical entry") + "\n" + section(
            second, second_level, "alias entry"
        )

    def test_equivalent_trusted_aliases_are_accepted_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trust_root = Path(directory) / "project"
            config_path = Path(directory) / "config.toml"
            original = self.alias_config(trust_root, "trusted", "trusted")

            updated, changed = render_trusted_config(
                original,
                config_path=config_path,
                trust_root=trust_root,
            )

            self.assertFalse(changed)
            self.assertEqual(updated, original)

    def test_equivalent_alias_without_level_is_reconciled_to_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trust_root = Path(directory) / "project"
            config_path = Path(directory) / "config.toml"
            original = self.alias_config(trust_root, "trusted", None)

            updated, changed = render_trusted_config(
                original,
                config_path=config_path,
                trust_root=trust_root,
            )

            self.assertTrue(changed)
            self.assertIn("# alias entry", updated)
            entries = tomllib.loads(updated)["projects"].values()
            self.assertTrue(all(entry["trust_level"] == "trusted" for entry in entries))

    def test_conflicting_aliases_require_force_before_all_are_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trust_root = Path(directory) / "project"
            config_path = Path(directory) / "config.toml"
            original = self.alias_config(trust_root, "trusted", "untrusted")

            with self.assertRaisesRegex(ValueError, "conflicting Codex trust entries"):
                render_trusted_config(
                    original,
                    config_path=config_path,
                    trust_root=trust_root,
                )

            updated, changed = render_trusted_config(
                original,
                config_path=config_path,
                trust_root=trust_root,
                force=True,
            )
            self.assertTrue(changed)
            entries = tomllib.loads(updated)["projects"].values()
            self.assertTrue(all(entry["trust_level"] == "trusted" for entry in entries))


if __name__ == "__main__":
    unittest.main()
