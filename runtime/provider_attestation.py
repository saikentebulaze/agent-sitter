"""Provider-dispatched runtime attestation validation."""

from __future__ import annotations

from core.provider_contract import RuntimeEvidence
from core.provider_registry import get_provider
from core.runtime_selection import provider_id_from_packet


def validate_provider_attestation(
    packet: dict,
    attestation: dict,
) -> RuntimeEvidence:
    provider_id = provider_id_from_packet(packet)
    provider = get_provider(provider_id)
    return provider.validate_attestation(packet, attestation)
