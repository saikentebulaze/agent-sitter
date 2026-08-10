from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.provider_registry import get_provider  # noqa: E402
from core.role_spec import ROLE_SPECS, RoleSpec, role_spec_for  # noqa: E402
from delegation_policy import (  # noqa: E402
    DelegationPolicy,
    POLICIES,
    policy_for_role,
)
from project_context import ProjectContext  # noqa: E402


class RoleSpecCoreTests(unittest.TestCase):
    def context(self) -> ProjectContext:
        return ProjectContext(ROOT, ROOT, ROOT / "adapters" / "default")

    def test_legacy_policy_names_alias_core_role_specs(self) -> None:
        self.assertIs(DelegationPolicy, RoleSpec)
        self.assertIs(POLICIES, ROLE_SPECS)
        for role in ROLE_SPECS:
            with self.subTest(role=role):
                self.assertIs(policy_for_role(role), role_spec_for(role))

    def test_all_core_roles_resolve_in_codex_provider(self) -> None:
        provider = get_provider("codex")
        for role, spec in ROLE_SPECS.items():
            with self.subTest(role=role):
                profile = provider.load_role_profile(self.context(), role)
                self.assertEqual(profile.role_id, spec.role)
                self.assertEqual(profile.provider, "codex")
                self.assertEqual(profile.write_isolation, "os-readonly")

    def test_role_specs_contain_governance_not_runtime_configuration(self) -> None:
        fields = set(RoleSpec.__dataclass_fields__)
        self.assertEqual(
            fields,
            {
                "role",
                "authorization_scope",
                "projection",
                "allowed_targets",
                "authority_files",
                "inline_change_fields",
                "max_context_supplements",
            },
        )
        runtime_specific = {
            "model",
            "reasoning_effort",
            "sandbox_mode",
            "permission_mode",
            "tools",
        }
        self.assertTrue(fields.isdisjoint(runtime_specific))


if __name__ == "__main__":
    unittest.main()
