from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from review_verdict import ReviewVerdictError, parse_review_verdict  # noqa: E402


class ReviewVerdictTests(unittest.TestCase):
    def test_pass_verdict_is_parsed_from_final_yaml_block(self) -> None:
        result = parse_review_verdict(
            """Architecture and numerical behavior look sound.\n\n```yaml\nsitter_review:\n  architecture: pass\n  scope: warn\n  numerical_evidence: pass\n  remediation_route: null\n```\n"""
        )
        self.assertEqual(result["architecture"], "pass")
        self.assertEqual(result["overall"], "warn")
        self.assertIsNone(result["remediation_route"])

    def test_block_requires_semantic_or_implementation_route(self) -> None:
        with self.assertRaisesRegex(ReviewVerdictError, "requires remediation_route"):
            parse_review_verdict(
                """```yaml\nsitter_review:\n  architecture: block\n  scope: pass\n  numerical_evidence: pass\n```\n"""
            )

    def test_implementation_block_is_machine_readable(self) -> None:
        result = parse_review_verdict(
            """Finding: a known branch was omitted.\n\n```yaml\nsitter_review:\n  architecture: block\n  scope: pass\n  numerical_evidence: warn\n  remediation_route: implementation\n```\n"""
        )
        self.assertEqual(result["overall"], "block")
        self.assertEqual(result["remediation_route"], "implementation")

    def test_prose_without_structured_tail_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReviewVerdictError, "no sitter_review"):
            parse_review_verdict("Architecture: PASS\nScope: PASS\n")


if __name__ == "__main__":
    unittest.main()
