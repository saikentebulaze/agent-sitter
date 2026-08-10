"""Codex implementation of the V5 runtime provider contract."""

from __future__ import annotations

from pathlib import Path

from core.projection_plan import Projection, ProjectionPlan
from core.provider_contract import (
    RuntimeContract,
    RuntimeEvidence,
    RuntimeRoleProfile,
)
from project_context import ProjectContext
from projection import (
    assert_writable_projection,
    entrypoint_text,
    skill_wrapper_text,
    toml_text,
)
from providers.codex.profiles import load_native_agent_profile
from providers.codex.projection import agent_toml_text, skill_metadata_text


AGENT_FILES = (
    "source-locator.toml",
    "context-scout.toml",
    "framework-scout.toml",
    "test-scout.toml",
    "maintainer-reviewer.toml",
    "deep-reviewer.toml",
)

_PROVIDER_FILES = (
    "app_server.py",
    "attestation.py",
    "delegation_runtime.py",
    "external_fallback.py",
    "managed_runtime.py",
    "profile_validation.py",
    "profiles.py",
    "projection.py",
    "provider.py",
    "trust.py",
)

_COMPATIBILITY_FILES = (
    "agent_profiles.py",
    "check_agent_profiles.py",
    "codex_app_server.py",
    "codex_managed_runtime.py",
    "codex_runtime_attestation.py",
    "codex_trust.py",
    "delegation_runtime.py",
    "launch_scout.py",
    "projection.py",
)


class CodexProvider:
    provider_id = "codex"

    def required_assets(self, context: ProjectContext) -> tuple[Path, ...]:
        package = context.package_root
        adapter = context.adapter_root
        provider_root = package / "runtime" / "providers" / "codex"
        assets = [provider_root / name for name in _PROVIDER_FILES]
        assets.extend(package / "runtime" / name for name in _COMPATIBILITY_FILES)
        assets.extend(
            (
                adapter / "bootstrap" / "AGENTS.md.template",
                adapter / "codex" / "config.toml",
                adapter / "model-profiles.yaml",
                adapter / "docs" / "Codex子Agent运行时验收.md",
            )
        )
        assets.extend(adapter / "codex" / "agents" / name for name in AGENT_FILES)
        for skill_dir in sorted((adapter / "skills").glob("*")):
            skill_source = skill_dir / "SKILL.md"
            if skill_source.is_file():
                assets.append(skill_source)
            metadata = skill_dir / "agents" / "openai.yaml"
            if metadata.is_file():
                assets.append(metadata)
        return tuple(assets)

    def validate_static_configuration(self, context: ProjectContext) -> None:
        config_text = (
            context.adapter_root / "codex" / "config.toml"
        ).read_text(encoding="utf-8")
        if 'approval_policy = "on-request"' not in config_text:
            raise ValueError("Codex config does not use on-request approval")
        if 'sandbox_mode = "workspace-write"' not in config_text:
            raise ValueError("Codex config does not use workspace-write sandbox")
        if "danger-full-access" in config_text:
            raise ValueError("Codex config must not default to danger-full-access")
        from providers.codex.profile_validation import validate_agent_profiles

        validate_agent_profiles(context)
        for name in (
            "source_locator",
            "context_scout",
            "test_scout",
            "framework_scout",
            "maintainer_reviewer",
            "deep_reviewer",
        ):
            load_native_agent_profile(context, name)

    def projection_plan(self, context: ProjectContext) -> ProjectionPlan:
        adapter = context.adapter_root
        projections: list[Projection] = [
            Projection(self.provider_id, Path("AGENTS.md"), entrypoint_text()),
            Projection(
                self.provider_id,
                Path(".codex/config.toml"),
                toml_text(adapter / "codex" / "config.toml"),
            ),
        ]
        for source in sorted((adapter / "codex" / "agents").glob("*.toml")):
            projections.append(
                Projection(
                    self.provider_id,
                    Path(".codex/agents") / source.name,
                    agent_toml_text(context, source),
                )
            )
        for skill_dir in sorted((adapter / "skills").glob("*")):
            source = skill_dir / "SKILL.md"
            if not source.is_file():
                continue
            projected_root = Path(".agents/skills") / skill_dir.name
            projections.append(
                Projection(
                    self.provider_id,
                    projected_root / "SKILL.md",
                    skill_wrapper_text(source),
                )
            )
            metadata = skill_dir / "agents" / "openai.yaml"
            if metadata.is_file():
                projections.append(
                    Projection(
                        self.provider_id,
                        projected_root / "agents" / "openai.yaml",
                        skill_metadata_text(metadata),
                    )
                )
        return ProjectionPlan(self.provider_id, tuple(projections))

    def stale_projection_candidates(
        self,
        context: ProjectContext,
        plan: ProjectionPlan,
    ) -> tuple[Path, ...]:
        project = context.project_root
        expected_agents = {
            item.target(project).resolve()
            for item in plan.projections
            if item.relative_path.parent == Path(".codex/agents")
        }
        stale: list[Path] = []
        agent_root = project / ".codex" / "agents"
        if agent_root.is_dir():
            for candidate in agent_root.glob("*.toml"):
                if candidate.resolve() not in expected_agents:
                    assert_writable_projection(candidate)
                    stale.append(candidate)

        expected_skills = {
            (
                project
                / item.relative_path.parts[0]
                / item.relative_path.parts[1]
                / item.relative_path.parts[2]
            ).resolve()
            for item in plan.projections
            if len(item.relative_path.parts) >= 4
            and item.relative_path.parts[:2] == (".agents", "skills")
                    }
        skill_root = project / ".agents" / "skills"
        if skill_root.is_dir():
            for candidate in skill_root.glob("*"):
                if not candidate.is_dir() or candidate.resolve() in expected_skills:
                    continue
                wrapper = candidate / "SKILL.md"
                metadata = candidate / "agents" / "openai.yaml"
                managed_files = {path for path in (wrapper, metadata) if path.is_file()}
                extra_files = [
                    path
                    for path in candidate.rglob("*")
                    if path.is_file() and path not in managed_files
                ]
                if extra_files:
                    raise ValueError(
                        "refusing to delete unmanaged stale skill content: "
                        f"{extra_files[0]}"
                    )
                for path in managed_files:
                    assert_writable_projection(path)
                stale.append(candidate)
        return tuple(stale)

    def load_role_profile(
        self,
        context: ProjectContext,
        role: str,
    ) -> RuntimeRoleProfile:
        profile = load_native_agent_profile(context, role)
        return RuntimeRoleProfile(
            provider=self.provider_id,
            role_id=profile.name,
            runtime_role=profile.name,
            model=profile.model,
            tier=profile.tier,
            reasoning_effort=profile.reasoning_effort,
            write_isolation=(
                "os-readonly" if profile.sandbox_mode == "read-only" else "unknown"
            ),
            source=profile.source,
        )

    def runtime_contract_for_role(
        self,
        profile: RuntimeRoleProfile,
    ) -> RuntimeContract:
        if profile.provider != self.provider_id:
            raise ValueError(
                f"profile provider {profile.provider} does not match {self.provider_id}"
            )
        return RuntimeContract(
            context_isolation="fresh",
            write_isolation=profile.write_isolation,
            persistent_context="unknown",
            attestation_strength="runtime-observed",
        )

    def validate_attestation(
        self,
        packet: dict,
        attestation: dict,
    ) -> RuntimeEvidence:
        execution = attestation.get("execution") or {}
        observed = attestation.get("observed") or {}
        expected = packet.get("requested_profile") or {}
        evidence = attestation.get("evidence") or {}
        if attestation.get("schema_version") != 2:
            raise ValueError("runtime attestation schema_version must be 2")
        if execution.get("method") != "native-subagent":
            raise ValueError("attestation must prove native-subagent execution")
        if execution.get("collector") != "codex-rollout-app-server-v1":
            raise ValueError(
                "runtime attestation must come from codex-rollout-app-server-v1"
            )
        if evidence.get("source") != "verified-combined":
            raise ValueError(
                "runtime attestation must use verified-combined evidence"
            )
        if not execution.get("spawn_call_id") or not execution.get("session_ref"):
            raise ValueError(
                "runtime attestation is missing the spawn call or child session"
            )

        checks = {
            "agent": expected.get("agent"),
            "model": expected.get("model"),
            "tier": expected.get("tier"),
            "reasoning_effort": expected.get("reasoning_effort"),
            "sandbox_mode": expected.get("sandbox_mode"),
        }
        mismatches = [
            key for key, value in checks.items() if observed.get(key) != value
        ]
        if observed.get("context_inheritance") != "none":
            mismatches.append("context_inheritance")
        if not observed.get("child_thread_id"):
            mismatches.append("child_thread_id")
        if not observed.get("parent_thread_id"):
            mismatches.append("parent_thread_id")
        if mismatches:
            raise ValueError(
                "runtime attestation mismatch: " + ", ".join(mismatches)
            )

        return RuntimeEvidence(
            provider=self.provider_id,
            role_id=str(observed.get("agent") or ""),
            contract=RuntimeContract(
                context_isolation="fresh",
                write_isolation="os-readonly",
                persistent_context="unknown",
                attestation_strength="runtime-observed",
            ),
            raw_evidence_ref=str(execution.get("session_ref") or "") or None,
        )
