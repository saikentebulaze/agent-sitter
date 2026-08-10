from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "agent-boundary-fixture.py"


class AgentBoundaryFixtureTests(unittest.TestCase):
    def create(self, directory: str) -> tuple[Path, dict]:
        fixture = Path(directory) / "fixture"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "create",
                "--root",
                str(fixture),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return fixture, json.loads(completed.stdout)

    def test_create_generates_high_entropy_distinct_canaries_and_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture, value = self.create(directory)
            canaries = value["canaries"]
            self.assertEqual(
                set(canaries),
                {"parent", "bash", "web", "mcp", "memory", "profile", "scope"},
            )
            self.assertEqual(len(set(canaries.values())), len(canaries))
            self.assertTrue(all(len(item) > 40 for item in canaries.values()))
            self.assertTrue((fixture / "positive-control.mcp.json").is_file())
            self.assertTrue((fixture / "forbidden" / "scope-secret.txt").is_file())
            self.assertFalse(Path(value["paths"]["write_marker"]).exists())

    def test_verify_detects_write_memory_and_worktree_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture, value = self.create(directory)
            passed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    "--fixture",
                    str(fixture),
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertEqual(json.loads(passed.stdout)["status"], "passed")

            Path(value["paths"]["write_marker"]).write_text(
                "unexpected write\n",
                encoding="utf-8",
            )
            Path(value["paths"]["memory"]).write_text(
                "unexpected memory mutation\n",
                encoding="utf-8",
            )
            failed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "verify",
                    "--fixture",
                    str(fixture),
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(failed.returncode, 2)
            report = json.loads(failed.stdout)
            self.assertIn("write marker was created", report["failures"])
            self.assertIn("memory canary changed", report["failures"])

    def test_mcp_positive_control_returns_randomized_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture, value = self.create(directory)
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "mcp-server",
                    "--fixture",
                    str(fixture),
                ],
                text=True,
                encoding="utf-8",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                assert process.stdin is not None
                assert process.stdout is not None
                requests = [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "get_secret", "arguments": {}},
                    },
                ]
                for request in requests:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                responses = [json.loads(process.stdout.readline()) for _ in requests]
                self.assertEqual(
                    responses[1]["result"]["tools"][0]["name"],
                    "get_secret",
                )
                self.assertEqual(
                    responses[2]["result"]["content"][0]["text"],
                    value["canaries"]["mcp"],
                )
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
