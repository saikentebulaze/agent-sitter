"""Task-level runtime ownership with backward-compatible Codex defaults."""

from __future__ import annotations

from core.provider_registry import get_provider
from core.runtime_selection import DEFAULT_RUNTIME_PROVIDER


def orchestrator_provider(task: dict) -> str:
    execution = task.get("execution")
    if execution is None:
        provider_id = DEFAULT_RUNTIME_PROVIDER
    else:
        if not isinstance(execution, dict):
            raise ValueError("task execution must be a mapping")
        value = execution.get("orchestrator_provider", DEFAULT_RUNTIME_PROVIDER)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "task execution.orchestrator_provider must be a non-empty string"
            )
        provider_id = value.strip()
    # Resolve now so an explicitly unsupported provider cannot enter governed
    # state. Missing legacy metadata still resolves to the Codex default.
    get_provider(provider_id)
    return provider_id


def require_orchestrator_provider(task: dict, expected: str) -> None:
    actual = orchestrator_provider(task)
    if actual != expected:
        raise ValueError(
            f"task orchestrator provider is immutable: expected {expected}, found {actual}"
        )
