from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-human-authority-live.py"
SPEC = importlib.util.spec_from_file_location("v6_human_authority_live", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


class V6HumanAuthorityLiveProtocolTests(unittest.TestCase):
    def test_prepare_hides_which_option_is_authoritative_from_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "live"
            prepared = LIVE.prepare(root, False)
            self.assertEqual(prepared["status"], "PREPARED_NOT_RUN")
            prompt = Path(prepared["prompt"]).read_text(encoding="utf-8")
            self.assertNotIn(LIVE.CHOICE_B, prompt)
            self.assertNotIn(LIVE.RECOMMENDATION_A, prompt)

            project = Path(prepared["project"])
            task = LIVE._load_yaml(project / ".agent-work" / LIVE.TASK_ID / "task.yaml")
            change = LIVE._load_yaml(
                project / "changes" / "active" / LIVE.CHANGE_ID / "change.yaml"
            )
            self.assertEqual(
                LIVE._single_decision(task)["recommendation"], LIVE.RECOMMENDATION_A
            )
            self.assertEqual(LIVE._single_decision(task)["user_decision"], LIVE.CHOICE_B)
            self.assertEqual(
                LIVE._single_decision(change)["recommendation"], LIVE.RECOMMENDATION_A
            )
            self.assertEqual(LIVE._single_decision(change)["user_decision"], LIVE.CHOICE_B)

    def test_prepare_alone_cannot_pass_live_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "live"
            LIVE.prepare(root, False)
            result = LIVE.verify(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(result["checks"]["task_authority_preserved"])
            self.assertTrue(result["checks"]["change_authority_preserved"])
            self.assertFalse(result["checks"]["implementation_follows_user"])
            self.assertFalse(result["checks"]["memory_candidate_follows_user"])


if __name__ == "__main__":
    unittest.main()
