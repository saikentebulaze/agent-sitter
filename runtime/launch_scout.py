"""Backward-compatible CLI for the Codex external Scout fallback."""

from providers.codex.external_fallback import (
    build_command,
    find_role,
    load_toml,
    main,
)

__all__ = ["build_command", "find_role", "load_toml", "main"]


if __name__ == "__main__":
    main()
