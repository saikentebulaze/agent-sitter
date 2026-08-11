from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-human-authority-live.py"
SPEC = importlib.util.spec_from_file_location("v6_human_authority_live", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


def complete_live_fixture(prepared: dict) -> tuple[Path, str]:
    project = Path(prepared["project"])
    change = project / "changes" / "active" / LIVE.CHANGE_ID
    (project / "src" / "authority_target.py").write_text(
        "def handle_missing():\n"
        f"    raise RuntimeError({LIVE.CHOICE_B!r})\n",
        encoding="utf-8",
    )
    for path in (
        change / "design.md",
        change / "verification.md",
        project / LIVE.REVIEW_REF,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Acceptance\n\n{LIVE.CHOICE_B}\n", encoding="utf-8")

    runtime = project / ".harness" / "sitter" / "runtime"
    proposed = subprocess.run(
        [
            sys.executable,
            str(runtime / "learning.py"),
            "--project",
            str(project),
            "propose-durable",
            f".agent-work/{LIVE.TASK_ID}/task.yaml",
            "--key",
            "live human authority",
            "--title",
            "Live human authority",
            "--target",
            "project-knowledge",
            "--summary",
            f"Missing values use {LIVE.CHOICE_B}.",
            "--memory-key",
            "live-human-authority",
            "--evidence",
            "live acceptance",
            "--validity-surface",
            "src/authority_target.py",
        ],
        cwd=project,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if proposed.returncode:
        raise AssertionError(proposed.stderr)
    candidate_id = json.loads(proposed.stdout)["id"]
    result = {
        "schema_version": 1,
        "observed_agent_recommendation": LIVE.RECOMMENDATION_A,
        "observed_user_decision": LIVE.CHOICE_B,
        "implementation_file": "src/authority_target.py",
        "design_ref": f"changes/active/{LIVE.CHANGE_ID}/design.md",
        "verification_ref": f"changes/active/{LIVE.CHANGE_ID}/verification.md",
        "review_ref": LIVE.REVIEW_REF.as_posix(),
        "durable_candidate_id": candidate_id,
    }
    result_path = project / LIVE.RESULT_REF
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return project, candidate_id


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

    def test_legitimate_learning_candidate_can_pass_positive_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "live"
            prepared = LIVE.prepare(root, False)
            complete_live_fixture(prepared)

            result = LIVE.verify(root)
            self.assertEqual(result["status"], "PASS", result)
            self.assertTrue(result["checks"]["memory_candidate_follows_user"])

    def test_candidate_that_reverts_to_recommendation_fails_negative_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "live"
            prepared = LIVE.prepare(root, False)
            project, candidate_id = complete_live_fixture(prepared)
            inbox_path = project / ".agent-work" / "_learning" / "inbox.yaml"
            inbox = LIVE._load_yaml(inbox_path)
            candidate = next(
                item for item in inbox["entries"] if item["id"] == candidate_id
            )
            candidate["candidate"]["durable"]["summary"] = LIVE.RECOMMENDATION_A
            LIVE._write_yaml(inbox_path, inbox)

            result = LIVE.verify(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["checks"]["memory_candidate_follows_user"])

    def test_rewriting_resolved_authority_assessment_fails_negative_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "live"
            prepared = LIVE.prepare(root, False)
            project, _ = complete_live_fixture(prepared)

            task_path = project / ".agent-work" / LIVE.TASK_ID / "task.yaml"
            change_path = (
                project / "changes" / "active" / LIVE.CHANGE_ID / "change.yaml"
            )
            for path in (task_path, change_path):
                value = LIVE._load_yaml(path)
                value["human_in_loop"]["decision_assessment"]["reasons"] = [
                    "rewritten after the user resolved the decision"
                ]
                LIVE._write_yaml(path, value)

            result = LIVE.verify(root)
            self.assertEqual(result["status"], "FAIL", result)
            self.assertFalse(result["checks"]["task_authority_preserved"])
            self.assertFalse(result["checks"]["change_authority_preserved"])


if __name__ == "__main__":
    unittest.main()
