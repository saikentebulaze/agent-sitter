from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCOPES = (
    ROOT / "README.md", ROOT / "manifest.yaml", ROOT / "install.py", ROOT / "check.py",
    ROOT / "runtime", ROOT / "adapters", ROOT / "scripts", ROOT / "tests", ROOT / "docs",
)
OLD_BRAND = "ci" + "oes"


class BrandingNeutralityTests(unittest.TestCase):
    def test_old_commercial_brand_is_absent(self) -> None:
        offenders: list[str] = []
        for scope in SCOPES:
            paths = [scope] if scope.is_file() else list(scope.rglob("*"))
            for path in paths:
                if not path.is_file() or ".git" in path.parts:
                    continue
                relative = path.relative_to(ROOT).as_posix()
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if OLD_BRAND in text.lower() or OLD_BRAND in relative.lower():
                    offenders.append(relative)
        self.assertEqual(offenders, [], "old brand remains in: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
