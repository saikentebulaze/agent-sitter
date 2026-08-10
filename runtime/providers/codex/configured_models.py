"""Run Codex collectors with the current project model-grade configuration."""

from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

from project_context import ProjectContext
from providers.codex import attestation as native_module
from providers.codex import managed_runtime as managed_module
from providers.codex.profiles import effective_model_tiers


@contextmanager
def effective_tier_mapping(context: ProjectContext):
    """Temporarily expose configured selectors to existing V5-A collectors.

    V5-A collectors intentionally remain byte-compatible and look up observed
    tiers through their module-level MODEL_TIERS mapping. V5-B injects the
    current project mapping only for one synchronous execution, so future model
    selectors do not require collector rewrites and default behavior is
    unchanged after the call.
    """

    mapping = effective_model_tiers(context)
    with mock.patch.object(native_module, "MODEL_TIERS", mapping), mock.patch.object(
        managed_module,
        "MODEL_TIERS",
        mapping,
    ):
        yield mapping


def execute_managed_read_only(
    context: ProjectContext,
    packet: dict,
    **kwargs,
):
    with effective_tier_mapping(context):
        return managed_module.execute_managed_read_only(
            context,
            packet,
            **kwargs,
        )


def collect_native_attestation(
    context: ProjectContext,
    packet: dict,
    **kwargs,
):
    with effective_tier_mapping(context):
        return native_module.collect_native_attestation(
            context,
            packet,
            **kwargs,
        )


__all__ = [
    "collect_native_attestation",
    "effective_tier_mapping",
    "execute_managed_read_only",
]
