"""Backward-compatible CLI and import path for Codex profile validation."""

from providers.codex.profile_validation import (
    EXPECTED,
    main,
    validate_agent_profiles,
)

__all__ = ["EXPECTED", "main", "validate_agent_profiles"]


if __name__ == "__main__":
    main()
