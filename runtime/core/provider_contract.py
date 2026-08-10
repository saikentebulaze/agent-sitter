"""Stable boundary between Harness governance and Agent runtimes.

The core describes guarantees that governance needs. A provider translates
those guarantees to its native concepts and proves them with native evidence.
Provider-specific configuration names, hooks, transcripts, and RPC payloads
must not leak into this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.projection_plan import ProjectionPlan


_CONTEXT_ISOLATION = {"fresh", "forked", "resumed", "unknown"}
_WRITE_ISOLATION = {"os-readonly", "tool-restricted", "unrestricted", "unknown"}
_PERSISTENT_CONTEXT = {"disabled", "enabled", "unknown"}
_ATTESTATION_STRENGTH = {
    "runtime-observed",
    "configuration-backed",
    "self-reported",
    "unknown",
}


@dataclass(frozen=True)
class RuntimeContract:
    """Normalized guarantees supplied by one runtime execution."""

    context_isolation: str
    write_isolation: str
    persistent_context: str
    attestation_strength: str

    def __post_init__(self) -> None:
        values = (
            ("context_isolation", self.context_isolation, _CONTEXT_ISOLATION),
            ("write_isolation", self.write_isolation, _WRITE_ISOLATION),
            ("persistent_context", self.persistent_context, _PERSISTENT_CONTEXT),
            ("attestation_strength", self.attestation_strength, _ATTESTATION_STRENGTH),
        )
        for field, value, allowed in values:
            if value not in allowed:
                raise ValueError(f"invalid {field}: {value}")


@dataclass(frozen=True)
class RuntimeRoleProfile:
    """Provider-neutral view of a configured Agent role.

    Fingerprint and resolution fields are opaque to Core. A Provider may freeze
    native source, configuration, projection identities, and an explicit model
    resolution policy so later runtime evidence can prove the exact requested
    role. Existing Providers may leave them empty while retaining historical
    request schemas.
    """

    provider: str
    role_id: str
    runtime_role: str
    model: str
    tier: str
    reasoning_effort: str
    write_isolation: str
    source: Path
    profile_source_ref: str = ""
    profile_source_sha256: str = ""
    model_config_sha256: str = ""
    model_resolution_mode: str = "native"
    expected_resolved_model: str = ""
    proxy_provider: str = ""
    agent_projection_ref: str = ""
    agent_projection_sha256: str = ""
    settings_projection_ref: str = ""
    settings_projection_sha256: str = ""
    hook_projection_ref: str = ""
    hook_projection_sha256: str = ""


@dataclass(frozen=True)
class RuntimeEvidence:
    """Provider-normalized evidence accepted by governance."""

    provider: str
    role_id: str
    contract: RuntimeContract
    raw_evidence_ref: str | None = None


class RuntimeProvider(Protocol):
    """Small extension point implemented by each supported Agent runtime."""

    provider_id: str

    def required_assets(self, context: object) -> tuple[Path, ...]: ...
    def validate_static_configuration(self, context: object) -> None: ...
    def projection_plan(self, context: object) -> ProjectionPlan: ...
    def stale_projection_candidates(self, context: object, plan: ProjectionPlan) -> tuple[Path, ...]: ...
    def load_role_profile(self, context: object, role: str) -> RuntimeRoleProfile: ...
    def runtime_contract_for_role(self, profile: RuntimeRoleProfile) -> RuntimeContract: ...
    def validate_attestation(self, packet: dict, attestation: dict) -> RuntimeEvidence: ...
