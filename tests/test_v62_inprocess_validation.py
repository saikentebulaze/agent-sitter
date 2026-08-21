from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from change_validation import ChangeValidationError, validate_change_in_process  # noqa: E402


class InProcessValidationTests(unittest.TestCase):
    def test_review_transaction_does_not_spawn_python_validator(self) -> None:
        text = (RUNTIME / "review_transaction.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run", text)
        self.assertIn("validate_change_in_process", text)

    def test_validator_failure_does_not_exit_parent_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_change = Path(directory) / "missing-change"
            with self.assertRaises(ChangeValidationError):
                validate_change_in_process(missing_change)


if __name__ == "__main__":
    unittest.main()
