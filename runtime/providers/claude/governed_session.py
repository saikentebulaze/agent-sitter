"""Launch a fresh governed Claude parent for one native subagent attempt."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from project_context import ProjectContext
from providers.claude.managed_runtime import executable_identity


class ClaudeGovernedSessionError(RuntimeError):
    pass


_PARENT_DISALLOWED = (
    "Write",
    "Edit",
    "NotebookEdit",
    "Bash",
    "PowerShell",
    "Skill",
    "WebFetch",
    "WebSearch",
    "EnterWorktree",
    "SendMessage",
    "mcp__*",
)


def build_native_parent_command(
    context: ProjectContext,
    contract: dict,
    *,
    command_prefix: tuple[str, ...] | None = None,
    mcp_config: Path,
) -> tuple[str, ...]:
    settings = (
        context.project_root
        / str(contract.get("governed_settings_ref") or "")
    ).resolve()
    if not settings.is_file():
        raise ClaudeGovernedSessionError(
            f"governed Claude settings are missing: {settings}"
        )
    instruction = str(contract.get("parent_instruction") or "").strip()
    if not instruction:
        raise ClaudeGovernedSessionError(
            "native contract has no frozen parent instruction"
        )
    prefix = command_prefix or (executable_identity().path,)
    return (
        *prefix,
        "-p",
        instruction,
        "--session-id",
        str(contract["parent_session_id"]),
        "--settings",
        str(settings),
        "--setting-sources",
        "user,project,local",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Agent,Read,Grep,Glob",
        "--disallowedTools",
        ",".join(_PARENT_DISALLOWED),
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config),
        "--no-chrome",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
    )


def native_parent_environment(
    contract: dict,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environment is None else environment)
    scope_path = str(contract.get("scope_policy_path") or "").strip()
    scope_sha = str(contract.get("scope_policy_sha256") or "").strip()
    if not scope_path or not scope_sha:
        raise ClaudeGovernedSessionError(
            "native contract has no frozen filesystem scope policy"
        )
    env.update(
        {
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_CODE_FORK_SUBAGENT": "0",
            "SITTER_CLAUDE_EVIDENCE_DIR": str(contract["evidence_dir"]),
            "SITTER_CLAUDE_ATTEMPT_NONCE": str(contract["attempt_nonce"]),
            "SITTER_CLAUDE_EXECUTION_MODE": "native",
            "SITTER_CLAUDE_SCOPE_REQUIRED": "1",
            "SITTER_CLAUDE_SCOPE_POLICY": scope_path,
            "SITTER_CLAUDE_SCOPE_POLICY_SHA256": scope_sha,
        }
    )
    return env


def launch_native_parent(
    context: ProjectContext,
    contract: dict,
    *,
    command_prefix: tuple[str, ...] | None = None,
    environment: dict[str, str] | None = None,
) -> int:
    base_environment = dict(os.environ if environment is None else environment)
    identity = executable_identity(
        command_prefix,
        environment=base_environment,
    )
    evidence_dir = Path(str(contract["evidence_dir"])).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="sitter-claude-native-parent-"
    ) as raw:
        mcp = Path(raw) / "empty-mcp.json"
        mcp.write_text(
            '{"mcpServers":{}}\n',
            encoding="utf-8",
            newline="",
        )
        command = build_native_parent_command(
            context,
            contract,
            command_prefix=command_prefix or (identity.path,),
            mcp_config=mcp,
        )
        completed = subprocess.run(
            list(command),
            cwd=context.project_root,
            env=native_parent_environment(contract, base_environment),
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
    (evidence_dir / "parent-launch.stdout.jsonl").write_text(
        completed.stdout,
        encoding="utf-8",
        newline="",
    )
    (evidence_dir / "parent-launch.stderr.txt").write_text(
        completed.stderr,
        encoding="utf-8",
        newline="",
    )
    return int(completed.returncode)
