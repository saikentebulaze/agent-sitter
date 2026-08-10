from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from model_profiles import LEGACY_MODEL_GRADES, MODEL_GRADES  # noqa: E402


class ModelProfileVocabularyTests(unittest.TestCase):
    def test_new_grades_are_provider_neutral(self) -> None:
        self.assertEqual(MODEL_GRADES, ("low", "medium", "high"))

    def test_legacy_codex_tiers_are_read_compatibility_only(self) -> None:
        self.assertEqual(
            LEGACY_MODEL_GRADES,
            {"luna": "low", "terra": "medium", "sol": "high"},
        )


if __name__ == "__main__":
    unittest.main()
