from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from agent_profiles import load_agent_profile  # noqa: E402
from core.provider_contract import RuntimeContract  # noqa: E402
from core.provider_registry import get_provider, registered_providers  # noqa: E402
from project_context import ProjectContext  # noqa: E402


class ProviderArchitectureTests(unittest.TestCase):
    def context(self) -> ProjectContext:
        return ProjectContext(ROOT, ROOT, ROOT / "adapters" / "default")

    def test_codex_and_claude_are_registered_v5b_providers(self) -> None:
        self.assertEqual(registered_providers(), ("claude", "codex"))
        self.assertEqual(get_provider("codex").provider_id, "codex")
        self.assertEqual(get_provider("claude").provider_id, "claude")

    def test_unknown_provider_is_rejected_explicitly(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Supported providers: claude, codex",
        ):
            get_provider("opencode")

    def test_legacy_profile_entrypoint_routes_through_codex_provider(self) -> None:
        context = self.context()
        provider_profile = get_provider("codex").load_role_profile(
            context,
            "source_locator",
        )
        legacy_profile = load_agent_profile(context, "source_locator")
        self.assertEqual(provider_profile.provider, "codex")
        self.assertEqual(provider_profile.runtime_role, legacy_profile.name)
        self.assertEqual(provider_profile.model, legacy_profile.model)
        self.assertEqual(provider_profile.tier, legacy_profile.tier)
        self.assertEqual(
            provider_profile.reasoning_effort,
            legacy_profile.reasoning_effort,
        )
        self.assertEqual(legacy_profile.sandbox_mode, "read-only")

    def test_codex_runtime_contract_is_unchanged(self) -> None:
        provider = get_provider("codex")
        profile = provider.load_role_profile(self.context(), "context_scout")
        contract = provider.runtime_contract_for_role(profile)
        self.assertEqual(
            contract,
            RuntimeContract(
                context_isolation="fresh",
                write_isolation="os-readonly",
                persistent_context="unknown",
                attestation_strength="runtime-observed",
            ),
        )

    def test_claude_runtime_contract_preserves_real_tool_level_difference(self) -> None:
        provider = get_provider("claude")
        profile = provider.load_role_profile(self.context(), "context_scout")
        self.assertEqual(profile.model, "haiku")
        self.assertEqual(profile.tier, "low")
        self.assertEqual(
            provider.runtime_contract_for_role(profile),
            RuntimeContract(
                context_isolation="fresh",
                write_isolation="tool-restricted",
                persistent_context="disabled",
                attestation_strength="runtime-observed",
            ),
        )

    def test_runtime_contract_rejects_unknown_vocabulary(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid write_isolation"):
            RuntimeContract(
                context_isolation="fresh",
                write_isolation="read-only-ish",
                persistent_context="unknown",
                attestation_strength="runtime-observed",
            )


if __name__ == "__main__":
    unittest.main()
