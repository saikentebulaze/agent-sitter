"""Claude Code implementation of the V5 runtime provider contract."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.managed_projection import PACKAGE_NAME
from core.projection_plan import Projection, ProjectionPlan
from core.provider_contract import RuntimeContract, RuntimeEvidence, RuntimeRoleProfile
from project_context import ProjectContext
from projection import assert_writable_projection
from providers.claude.profile_validation import EXPECTED_ROLES, validate_agent_profiles
from providers.claude.profiles import load_native_agent_profile
from providers.claude.projection import agent_text, entrypoint_text, governed_settings_text, hook_text, skill_wrapper_text

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GOVERNED_SETTINGS_REF = f".harness/{PACKAGE_NAME}/adapters/default/claude/governed-settings.json"


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


class ClaudeProvider:
    provider_id = "claude"

    def required_assets(self, context: ProjectContext) -> tuple[Path, ...]:
        provider_root = context.package_root / "runtime" / "providers" / "claude"
        assets = [
            provider_root / "__init__.py", provider_root / "profiles.py",
            provider_root / "profile_validation.py", provider_root / "projection.py",
            provider_root / "provider.py", provider_root / "managed_runtime.py",
            provider_root / "native_runtime.py", provider_root / "governed_session.py",
            context.adapter_root / "bootstrap" / "AGENTS.md.template",
            context.adapter_root / "model-profiles.yaml",
            context.adapter_root / "claude" / "governed-settings.json",
            context.adapter_root / "claude" / "hooks" / "governance-runtime-hook.py",
            context.adapter_root / "docs" / "Claude子Agent运行时验收.md",
        ]
        assets.extend(context.adapter_root / "claude" / "agents" / f"{role.replace('_', '-')}.md" for role in EXPECTED_ROLES)
        assets.extend(
            skill_dir / "SKILL.md"
            for skill_dir in sorted((context.adapter_root / "skills").glob("*"))
            if (skill_dir / "SKILL.md").is_file()
        )
        return tuple(assets)

    def validate_static_configuration(self, context: ProjectContext) -> None:
        validate_agent_profiles(context)
        governed = governed_settings_text(context.adapter_root / "claude" / "governed-settings.json")
        for token in (
            '"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"',
            '"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"',
            '"CLAUDE_CODE_FORK_SUBAGENT": "0"',
            '"PreToolUse"', '"PostToolUse"', '"SubagentStart"', '"SubagentStop"',
        ):
            if token not in governed:
                raise ValueError(f"Claude governed settings are missing required safety configuration: {token}")
        for source in sorted((context.adapter_root / "claude" / "agents").glob("*.md")):
            rendered = agent_text(context, source)
            for token in ("PreToolUse:", "PostToolUse:", "PreCompact:", "WorktreeCreate:"):
                if token not in rendered:
                    raise ValueError(f"Claude Agent {source.name} is missing required scoped hook: {token}")
            for forbidden in ("SubagentStart:", "SubagentStop:", "SessionStart:", "SessionEnd:"):
                if forbidden in rendered:
                    raise ValueError(f"Claude Agent {source.name} incorrectly owns parent lifecycle hook: {forbidden}")
        hook = (context.adapter_root / "claude" / "hooks" / "governance-runtime-hook.py").read_text(encoding="utf-8")
        for token in ("SITTER_CLAUDE_EVIDENCE_DIR", "SITTER_CLAUDE_ATTEMPT_NONCE", "SITTER_CLAUDE_EXECUTION_MODE", "PreToolUse", "PreCompact", "WorktreeCreate", "O_EXCL"):
            if token not in hook:
                raise ValueError(f"Claude runtime hook is missing required contract token: {token}")

    def projection_plan(self, context: ProjectContext) -> ProjectionPlan:
        adapter = context.adapter_root
        projections: list[Projection] = [
            Projection(self.provider_id, Path("CLAUDE.local.md"), entrypoint_text()),
            Projection(self.provider_id, Path(".claude/hooks/governance-runtime-hook.py"), hook_text(adapter / "claude" / "hooks" / "governance-runtime-hook.py")),
        ]
        for source in sorted((adapter / "claude" / "agents").glob("*.md")):
            projections.append(Projection(self.provider_id, Path(".claude/agents") / source.name, agent_text(context, source)))
        for skill_dir in sorted((adapter / "skills").glob("*")):
            source = skill_dir / "SKILL.md"
            if source.is_file():
                projections.append(Projection(self.provider_id, Path(".claude/skills") / skill_dir.name / "SKILL.md", skill_wrapper_text(source)))
        return ProjectionPlan(self.provider_id, tuple(projections))

    def frozen_profile_fields(self, context: ProjectContext, role: str) -> dict[str, str]:
        native = load_native_agent_profile(context, role)
        desired = {item.relative_path.as_posix(): item.content for item in self.projection_plan(context).projections}
        agent_ref = f".claude/agents/{native.runtime_name}.md"
        hook_ref = ".claude/hooks/governance-runtime-hook.py"
        governed_source = context.adapter_root / "claude" / "governed-settings.json"
        source_ref = native.source.relative_to(context.package_root).as_posix()
        return {
            "profile_source_ref": source_ref,
            "profile_source_sha256": _text_sha256(native.source.read_text(encoding="utf-8")),
            "model_config_sha256": native.model_config_sha256,
            "agent_projection_ref": agent_ref,
            "agent_projection_sha256": _text_sha256(desired[agent_ref]),
            "settings_projection_ref": _GOVERNED_SETTINGS_REF,
            "settings_projection_sha256": _text_sha256(governed_settings_text(governed_source)),
            "hook_projection_ref": hook_ref,
            "hook_projection_sha256": _text_sha256(desired[hook_ref]),
        }

    def stale_projection_candidates(self, context: ProjectContext, plan: ProjectionPlan) -> tuple[Path, ...]:
        project = context.project_root
        expected_agents = {item.target(project).resolve() for item in plan.projections if item.relative_path.parent == Path(".claude/agents")}
        stale: list[Path] = []
        agent_root = project / ".claude" / "agents"
        if agent_root.is_dir():
            for candidate in agent_root.glob("*.md"):
                if candidate.resolve() not in expected_agents:
                    assert_writable_projection(candidate); stale.append(candidate)
        expected_skills = {item.target(project).parent.resolve() for item in plan.projections if item.relative_path.name == "SKILL.md" and item.relative_path.parent.parent == Path(".claude/skills")}
        skill_root = project / ".claude" / "skills"
        if skill_root.is_dir():
            for candidate in skill_root.glob("*"):
                if not candidate.is_dir() or candidate.resolve() in expected_skills:
                    continue
                wrapper = candidate / "SKILL.md"; assert_writable_projection(wrapper)
                extra = [p for p in candidate.rglob("*") if p.is_file() and p != wrapper]
                if extra:
                    raise ValueError(f"refusing to delete unmanaged stale Claude skill content: {extra[0]}")
                stale.append(candidate)
        return tuple(stale)

    def load_role_profile(self, context: ProjectContext, role: str) -> RuntimeRoleProfile:
        profile = load_native_agent_profile(context, role)
        return RuntimeRoleProfile(
            provider=self.provider_id, role_id=profile.name, runtime_role=profile.runtime_name,
            model=profile.model, tier=profile.model_grade, reasoning_effort=profile.reasoning_effort,
            write_isolation="tool-restricted", source=profile.source,
            model_resolution_mode=profile.model_resolution_mode,
            expected_resolved_model=profile.expected_resolved_model,
            proxy_provider=profile.proxy_provider, **self.frozen_profile_fields(context, role),
        )

    def runtime_contract_for_role(self, profile: RuntimeRoleProfile) -> RuntimeContract:
        if profile.provider != self.provider_id:
            raise ValueError(f"profile provider {profile.provider} does not match {self.provider_id}")
        return RuntimeContract("fresh", "tool-restricted", "disabled", "runtime-observed")

    def validate_attestation(self, packet: dict, attestation: dict) -> RuntimeEvidence:
        if attestation.get("schema_version") != 2:
            raise ValueError("Claude runtime attestation schema_version must be 2")
        execution = attestation.get("execution") or {}; observed = attestation.get("observed") or {}
        expected = packet.get("requested_profile") or {}; evidence = attestation.get("evidence") or {}
        method = execution.get("method")
        collectors = {"claude-managed-agent": "claude-stream-hooks-transcript-v2", "claude-native-subagent": "claude-invocation-hooks-transcript-v2"}
        sources = {"claude-managed-agent": "verified-claude-managed-v2", "claude-native-subagent": "verified-claude-native-v2"}
        if method not in collectors:
            raise ValueError("Claude attestation has an unsupported execution method")
        if execution.get("collector") != collectors[method]:
            raise ValueError("Claude attestation collector does not match execution method")
        if evidence.get("source") != sources[method]:
            raise ValueError("Claude attestation evidence source does not match execution method")
        session_id = str(execution.get("session_id") or "")
        if not session_id or execution.get("session_ref") != f"claude-session:{session_id}":
            raise ValueError("Claude attestation has an invalid session binding")
        checks = {
            "role_id": expected.get("role_id") or expected.get("agent"),
            "runtime_role": expected.get("runtime_role"),
            "model_grade": expected.get("model_grade") or expected.get("tier"),
            "model_selector": expected.get("model_selector") or expected.get("model"),
            "model_resolution_mode": expected.get("model_resolution_mode") or "native",
            "expected_resolved_model": expected.get("expected_resolved_model") or "",
            "proxy_provider": expected.get("proxy_provider") or "",
            "reasoning_effort": expected.get("reasoning_effort"),
        }
        mismatches = [key for key, value in checks.items() if observed.get(key) != value]
        if observed.get("context_inheritance") != "none": mismatches.append("context_inheritance")
        if observed.get("write_isolation") != "tool-restricted": mismatches.append("write_isolation")
        if observed.get("persistent_context") != "disabled": mismatches.append("persistent_context")
        configured = set(observed.get("tools_configured") or observed.get("tools_advertised") or [])
        if configured != {"Read", "Grep", "Glob"}: mismatches.append("tools_configured")
        if set(observed.get("tools_used") or []) - {"Read", "Grep", "Glob"}: mismatches.append("tools_used")
        if observed.get("continuity_events"): mismatches.append("continuity_events")
        frozen_hashes = ("profile_source_sha256", "model_config_sha256", "agent_projection_sha256", "settings_projection_sha256", "hook_projection_sha256")
        runtime_hashes = ("request_sha256", "hook_events_sha256") + (("command_sha256", "stream_sha256") if method == "claude-managed-agent" else ("invocation_sha256", "parent_transcript_sha256", "transcript_sha256"))
        for key in frozen_hashes:
            expected_hash = str(expected.get(key) or ""); actual_hash = str(evidence.get(key) or "")
            if not _HEX_SHA256.fullmatch(expected_hash) or actual_hash != expected_hash: mismatches.append(key)
        for key in runtime_hashes:
            if not _HEX_SHA256.fullmatch(str(evidence.get(key) or "")): mismatches.append(key)
        if mismatches:
            raise ValueError("Claude runtime attestation mismatch: " + ", ".join(dict.fromkeys(mismatches)))
        return RuntimeEvidence(self.provider_id, str(observed.get("role_id") or ""), RuntimeContract("fresh", "tool-restricted", "disabled", "runtime-observed"), str(execution.get("session_ref") or ""))
