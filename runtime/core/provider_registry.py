"""Registry for fully implemented Agent runtime providers."""

from __future__ import annotations

from core.provider_contract import RuntimeProvider


_PROVIDERS: dict[str, RuntimeProvider] = {}
_DEFAULTS_LOADED = False


def register_provider(provider: RuntimeProvider) -> None:
    provider_id = provider.provider_id
    if not provider_id:
        raise ValueError("runtime provider has no provider_id")
    if provider_id in _PROVIDERS:
        raise ValueError(f"Provider already registered: {provider_id}")
    _PROVIDERS[provider_id] = provider


def _load_defaults() -> None:
    global _DEFAULTS_LOADED
    if _DEFAULTS_LOADED:
        return
    from providers.claude.provider import ClaudeProvider
    from providers.codex.provider import CodexProvider

    register_provider(CodexProvider())
    register_provider(ClaudeProvider())
    _DEFAULTS_LOADED = True


def get_provider(provider_id: str) -> RuntimeProvider:
    _load_defaults()
    try:
        return _PROVIDERS[provider_id]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROVIDERS)) or "<none>"
        raise ValueError(
            f"Unsupported runtime provider: {provider_id}. "
            f"Supported providers: {supported}"
        ) from exc


def registered_providers() -> tuple[str, ...]:
    _load_defaults()
    return tuple(sorted(_PROVIDERS))
