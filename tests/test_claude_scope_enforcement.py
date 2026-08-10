from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from providers.claude.delegation_runtime import (  # noqa: E402
    ClaudeDelegationRuntimeError,
    bind_scope_evidence,
    ensure_scope_policy,
    validate_scope_artifacts,
)
from providers.claude.governed_session import native_parent_environment  # noqa: E402


HOOK = (
    ROOT
    / "adapters"
    / "default"
    / "claude"
    / "hooks"
    / "governance-runtime-hook.py"
)


class ClaudeScopeEnforcementTests(unittest.TestCase):
    def fixture(self, directory: str):
        project = Path(directory) / "project"
        project.mkdir()
        allowed = project / "src" / "allowed"
        allowed.mkdir(parents=True)
        allowed_file = allowed / "inside.cpp"
        allowed_file.write_text("// allowed\n", encoding="utf-8")
        allowed_other = allowed / "other.txt"
        allowed_other.write_text("other\n", encoding="utf-8")
        excluded = allowed / "excluded"
        excluded.mkdir()
        excluded_file = excluded / "secret.txt"
        excluded_file.write_text("secret\n", encoding="utf-8")
        outside = project / "outside"
        outside.mkdir()
        outside_file = outside / "secret.txt"
        outside_file.write_text("outside\n", encoding="utf-8")
        request = (
            project
            / ".agent-work"
            / "task"
            / "delegations"
            / "dlg-001"
            / "attempt-01.request.yaml"
        )
        request.parent.mkdir(parents=True)
        request.write_text("schema_version: 2\n", encoding="utf-8")
        packet = {
            "schema_version": 2,
            "delegation": {"id": "dlg-001", "attempt": 1},
            "scope": {
                "include": ["src/allowed", "NonPathSymbol"],
                "exclude": ["src/allowed/excluded"],
            },
            "start_here": [
                {"ref": "src/allowed/inside.cpp"},
            ],
            "projection": {
                "authority_refs": [
                    {"ref": request.relative_to(project).as_posix()},
                ],
            },
            "context_supplements": [],
        }
        context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
        policy_path, digest, policy = ensure_scope_policy(
            context,
            request,
            packet,
        )
        return {
            "project": project,
            "context": context,
            "request": request,
            "packet": packet,
            "policy_path": policy_path,
            "digest": digest,
            "policy": policy,
            "allowed_file": allowed_file,
            "allowed_other": allowed_other,
            "excluded_file": excluded_file,
            "outside_file": outside_file,
        }

    def run_hook(self, fixture: dict, payload: dict):
        evidence = fixture["project"] / "evidence"
        evidence.mkdir(exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "SITTER_CLAUDE_EVIDENCE_DIR": str(evidence),
                "SITTER_CLAUDE_ATTEMPT_NONCE": "scope-attempt",
                "SITTER_CLAUDE_EXECUTION_MODE": "managed",
                "SITTER_CLAUDE_SCOPE_REQUIRED": "1",
                "SITTER_CLAUDE_SCOPE_POLICY": str(
                    fixture["policy_path"]
                ),
                "SITTER_CLAUDE_SCOPE_POLICY_SHA256": fixture["digest"],
            }
        )
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
        )
        files = sorted(evidence.glob("*.json"))
        self.assertEqual(len(files), 1)
        envelope = json.loads(files[0].read_text(encoding="utf-8"))
        files[0].unlink()
        return completed, envelope["event"]

    def payload(self, fixture: dict, tool: str, tool_input: dict) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "tool_use_id": "toolu-scope",
            "cwd": str(fixture["project"]),
            "session_id": "session-scope",
            "agent_id": "agent-scope",
        }

    def test_policy_uses_real_paths_and_ignores_symbolic_include(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            refs = {
                entry["ref"]
                for entry in fixture["policy"]["allowed"]
            }
            self.assertIn("src/allowed", refs)
            self.assertIn("src/allowed/inside.cpp", refs)
            self.assertNotIn("NonPathSymbol", refs)
            self.assertEqual(
                fixture["policy"]["request_sha256"],
                hashlib.sha256(
                    json.dumps(
                        fixture["packet"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            )

    def test_allowed_read_is_recorded_and_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {"file_path": str(fixture["allowed_file"])},
                ),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(event["scope_decision"], "allowed")
            self.assertEqual(
                event["scope_policy_sha256"],
                fixture["digest"],
            )
            self.assertEqual(
                Path(event["scope_resolved_target"]),
                fixture["allowed_file"].resolve(),
            )

    def test_outside_and_excluded_paths_are_denied(self):
        for key, reason in (
            ("outside_file", "target-outside-allowed-scope"),
            ("excluded_file", "target-in-excluded-scope"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory)
                result, event = self.run_hook(
                    fixture,
                    self.payload(
                        fixture,
                        "Read",
                        {"file_path": str(fixture[key])},
                    ),
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("filesystem scope", result.stderr)
                self.assertEqual(event["scope_decision"], "denied")
                self.assertEqual(event["scope_reason"], reason)

    def test_grep_and_glob_require_explicit_scoped_paths(self):
        cases = (
            ("Grep", {"pattern": "token"}, "grep-path-required"),
            ("Glob", {"pattern": "**/*.cpp"}, "glob-path-required"),
            (
                "Glob",
                {
                    "path": str(Path.cwd()),
                    "pattern": "../**/*",
                },
                "glob-pattern-escapes-scope",
            ),
            (
                "Grep",
                {
                    "path": str(Path.cwd()),
                    "pattern": "token",
                    "glob": "../*.txt",
                },
                "grep-pattern-escapes-scope",
            ),
        )
        for tool, tool_input, reason in cases:
            with self.subTest(tool=tool, reason=reason), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory)
                result, event = self.run_hook(
                    fixture,
                    self.payload(fixture, tool, tool_input),
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(event["scope_reason"], reason)

    def test_symlink_escape_is_denied_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            link = fixture["project"] / "src" / "allowed" / "escape.txt"
            try:
                link.symlink_to(fixture["outside_file"])
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {"file_path": str(link)},
                ),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                event["scope_reason"],
                "target-outside-allowed-scope",
            )

    def test_scope_evidence_accepts_blocked_attempts_and_rejects_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            allowed_event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-allowed",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(
                    fixture["allowed_file"].resolve()
                ),
            }
            denied_event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-denied",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "denied",
                "scope_reason": "target-outside-allowed-scope",
                "scope_resolved_target": str(
                    fixture["outside_file"].resolve()
                ),
            }
            attestation = {"observed": {}, "evidence": {}}
            evidence = {"hook_events": [allowed_event, denied_event]}
            bind_scope_evidence(
                fixture["context"],
                fixture["packet"],
                policy_path=fixture["policy_path"],
                policy_sha256=fixture["digest"],
                policy=fixture["policy"],
                attestation=attestation,
                evidence=evidence,
            )
            self.assertEqual(
                attestation["observed"]["scope_allowed_tool_calls"],
                1,
            )
            self.assertEqual(
                attestation["observed"]["scope_denied_tool_calls"],
                1,
            )
            validate_scope_artifacts(
                fixture["context"],
                fixture["packet"],
                attestation,
                evidence,
            )

            evidence["hook_events"].append(
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Read",
                    "tool_use_id": "toolu-denied",
                }
            )
            with self.assertRaisesRegex(
                ClaudeDelegationRuntimeError,
                "reached PostToolUse",
            ):
                validate_scope_artifacts(
                    fixture["context"],
                    fixture["packet"],
                    attestation,
                    evidence,
                )

    def test_scope_event_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-scope",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(
                    fixture["allowed_file"].resolve()
                ),
            }
            attestation = {"observed": {}, "evidence": {}}
            evidence = {"hook_events": [event]}
            bind_scope_evidence(
                fixture["context"],
                fixture["packet"],
                policy_path=fixture["policy_path"],
                policy_sha256=fixture["digest"],
                policy=fixture["policy"],
                attestation=attestation,
                evidence=evidence,
            )
            evidence["hook_events"][0]["scope_reason"] = "tampered"
            with self.assertRaisesRegex(
                ClaudeDelegationRuntimeError,
                "normalized scope events|scope event hash",
            ):
                validate_scope_artifacts(
                    fixture["context"],
                    fixture["packet"],
                    attestation,
                    evidence,
                )

    def test_allowed_directory_subfile_read_is_allowed(self):
        # A file inside an allowed directory but absent from the policy's
        # per-file list must still be readable: directory entries cover all
        # descendants.
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {"file_path": str(fixture["allowed_other"])},
                ),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(event["scope_decision"], "allowed")
            self.assertEqual(
                event["scope_reason"],
                "target-in-allowed-scope",
            )

    def test_read_dotdot_escape_is_denied(self):
        cases = (
            # relative traversal leaving the project root
            (
                "../secret.txt",
                "target-outside-project",
            ),
            # in-project traversal out of the allowed root
            (
                "src/../outside/secret.txt",
                "target-outside-allowed-scope",
            ),
        )
        for file_path, reason in cases:
            with self.subTest(file_path=file_path), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory)
                result, event = self.run_hook(
                    fixture,
                    self.payload(fixture, "Read", {"file_path": file_path}),
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(event["scope_reason"], reason)

    def test_windows_case_variant_path_is_normalized(self):
        # Windows path matching must be case-insensitive: a mixed-case
        # rendering of an allowed path is the same file, not an escape.
        if os.name != "nt":
            self.skipTest("Windows-only case normalization")
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            variant = os.path.normcase(str(fixture["allowed_file"])).swapcase()
            if os.path.normcase(variant) != os.path.normcase(
                str(fixture["allowed_file"])
            ):
                self.skipTest("swapcase did not produce a case variant")
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {"file_path": variant},
                ),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(event["scope_decision"], "allowed")

    def test_windows_junction_escape_is_denied_when_supported(self):
        # A junction inside the allowed directory that resolves outside the
        # project must be denied: resolve() follows reparse points, so the
        # candidate lands outside the project and is rejected there.
        if os.name != "nt":
            self.skipTest("Windows-only junction")
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            junction = (
                fixture["project"] / "src" / "allowed" / "junction-dir"
            )
            outside_dir = fixture["project"].parent / "outside-target"
            outside_dir.mkdir()
            try:
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, OSError):
                self.skipTest("junction creation is unavailable")
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {
                        "file_path": str(
                            junction / "secret.txt"
                        )
                    },
                ),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                event["scope_reason"],
                "target-outside-project",
            )

    def test_tampered_policy_file_is_denied_by_hook(self):
        # The hook verifies the policy file bytes against the frozen digest;
        # a modified policy must be rejected even though the path is valid.
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            with open(fixture["policy_path"], "ab") as stream:
                stream.write(b"\n# tampered\n")
            result, event = self.run_hook(
                fixture,
                self.payload(
                    fixture,
                    "Read",
                    {"file_path": str(fixture["allowed_file"])},
                ),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                event["scope_reason"],
                "scope-policy-hash-mismatch",
            )

    def test_request_hash_mismatch_is_rejected_at_record(self):
        # Changing the frozen request after execution (packet mutation) must
        # fail the record-phase revalidation of request_sha256.
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-scope",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(
                    fixture["allowed_file"].resolve()
                ),
            }
            attestation = {"observed": {}, "evidence": {}}
            evidence = {"hook_events": [event]}
            bind_scope_evidence(
                fixture["context"],
                fixture["packet"],
                policy_path=fixture["policy_path"],
                policy_sha256=fixture["digest"],
                policy=fixture["policy"],
                attestation=attestation,
                evidence=evidence,
            )
            fixture["packet"]["objective"] = {
                "question": "tampered question"
            }
            with self.assertRaises(ClaudeDelegationRuntimeError):
                validate_scope_artifacts(
                    fixture["context"],
                    fixture["packet"],
                    attestation,
                    evidence,
                )

    def test_raw_policy_replacement_is_rejected(self):
        # The raw evidence's embedded policy must equal the on-disk policy;
        # substituting a different policy body breaks revalidation.
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-scope",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(
                    fixture["allowed_file"].resolve()
                ),
            }
            attestation = {"observed": {}, "evidence": {}}
            evidence = {"hook_events": [event]}
            bind_scope_evidence(
                fixture["context"],
                fixture["packet"],
                policy_path=fixture["policy_path"],
                policy_sha256=fixture["digest"],
                policy=fixture["policy"],
                attestation=attestation,
                evidence=evidence,
            )
            evidence["scope_policy"] = {
                "schema_version": 1,
                "provider": "claude",
                "project_root": str(fixture["project"].resolve()),
                "allowed": [],
                "excluded": [],
            }
            with self.assertRaises(ClaudeDelegationRuntimeError):
                validate_scope_artifacts(
                    fixture["context"],
                    fixture["packet"],
                    attestation,
                    evidence,
                )

    def test_deleting_denied_event_breaks_event_hash(self):
        # Removing a denied event from the raw evidence must fail the
        # normalized event hash and counter revalidation; erasing proof of a
        # block is itself an attestation violation.
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            allowed_event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-allowed",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(
                    fixture["allowed_file"].resolve()
                ),
            }
            denied_event = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu-denied",
                "scope_policy_sha256": fixture["digest"],
                "scope_decision": "denied",
                "scope_reason": "target-outside-allowed-scope",
                "scope_resolved_target": str(
                    fixture["outside_file"].resolve()
                ),
            }
            attestation = {"observed": {}, "evidence": {}}
            evidence = {"hook_events": [allowed_event, denied_event]}
            bind_scope_evidence(
                fixture["context"],
                fixture["packet"],
                policy_path=fixture["policy_path"],
                policy_sha256=fixture["digest"],
                policy=fixture["policy"],
                attestation=attestation,
                evidence=evidence,
            )
            evidence["hook_events"] = [allowed_event]
            with self.assertRaises(ClaudeDelegationRuntimeError):
                validate_scope_artifacts(
                    fixture["context"],
                    fixture["packet"],
                    attestation,
                    evidence,
                )

    def test_native_parent_environment_requires_and_exports_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            contract = {
                "evidence_dir": str(fixture["project"] / "events"),
                "attempt_nonce": "native-nonce",
                "scope_policy_path": str(fixture["policy_path"]),
                "scope_policy_sha256": fixture["digest"],
            }
            env = native_parent_environment(contract, {})
            self.assertEqual(env["SITTER_CLAUDE_SCOPE_REQUIRED"], "1")
            self.assertEqual(
                env["SITTER_CLAUDE_SCOPE_POLICY"],
                str(fixture["policy_path"]),
            )
            self.assertEqual(
                env["SITTER_CLAUDE_SCOPE_POLICY_SHA256"],
                fixture["digest"],
            )


if __name__ == "__main__":
    unittest.main()
