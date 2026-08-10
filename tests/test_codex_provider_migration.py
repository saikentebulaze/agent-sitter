from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import check_agent_profiles as legacy_profile_validation  # noqa: E402
import codex_app_server as legacy_app_server  # noqa: E402
import codex_managed_runtime as legacy_managed_runtime  # noqa: E402
import codex_runtime_attestation as legacy_attestation  # noqa: E402
import codex_trust as legacy_trust  # noqa: E402
import delegation_runtime as legacy_delegation_runtime  # noqa: E402
import launch_scout as legacy_external_fallback  # noqa: E402
from providers.codex import app_server as provider_app_server  # noqa: E402
from providers.codex import attestation as provider_attestation  # noqa: E402
from providers.codex import delegation_runtime as provider_delegation_runtime  # noqa: E402
from providers.codex import external_fallback as provider_external_fallback  # noqa: E402
from providers.codex import managed_runtime as provider_managed_runtime  # noqa: E402
from providers.codex import profile_validation as provider_profile_validation  # noqa: E402
from providers.codex import trust as provider_trust  # noqa: E402


class CodexProviderMigrationTests(unittest.TestCase):
    def test_legacy_trust_api_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(legacy_trust.render_trusted_config, provider_trust.render_trusted_config)
        self.assertIs(legacy_trust.ensure_project_trusted, provider_trust.ensure_project_trusted)
        self.assertIs(legacy_trust.ProjectTrustState, provider_trust.ProjectTrustState)

    def test_legacy_profile_validation_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(
            legacy_profile_validation.validate_agent_profiles,
            provider_profile_validation.validate_agent_profiles,
        )
        self.assertIs(legacy_profile_validation.EXPECTED, provider_profile_validation.EXPECTED)

    def test_legacy_app_server_api_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(legacy_app_server.CodexAppServerClient, provider_app_server.CodexAppServerClient)
        self.assertIs(legacy_app_server.CodexAppServerError, provider_app_server.CodexAppServerError)
        self.assertIs(legacy_app_server.find_codex_executable, provider_app_server.find_codex_executable)

    def test_legacy_attestation_api_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(
            legacy_attestation.collect_native_attestation,
            provider_attestation.collect_native_attestation,
        )
        self.assertIs(
            legacy_attestation.validate_runtime_attestation,
            provider_attestation.validate_runtime_attestation,
        )
        self.assertIs(
            legacy_attestation.CodexRuntimeAttestationError,
            provider_attestation.CodexRuntimeAttestationError,
        )

    def test_legacy_managed_runtime_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(
            legacy_managed_runtime.execute_managed_read_only,
            provider_managed_runtime.execute_managed_read_only,
        )
        self.assertIs(
            legacy_managed_runtime.validate_managed_attestation,
            provider_managed_runtime.validate_managed_attestation,
        )
        self.assertIs(
            legacy_managed_runtime.CodexManagedRuntimeError,
            provider_managed_runtime.CodexManagedRuntimeError,
        )

    def test_legacy_external_fallback_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(
            legacy_external_fallback.build_command,
            provider_external_fallback.build_command,
        )
        self.assertIs(
            legacy_external_fallback.find_role,
            provider_external_fallback.find_role,
        )

    def test_legacy_delegation_runtime_is_backed_by_provider_implementation(self) -> None:
        self.assertIs(
            legacy_delegation_runtime.runtime_task_name,
            provider_delegation_runtime.runtime_task_name,
        )
        self.assertIs(
            legacy_delegation_runtime.spawn_contract,
            provider_delegation_runtime.spawn_contract,
        )
        self.assertIs(
            legacy_delegation_runtime.run_isolated,
            provider_delegation_runtime.run_isolated,
        )


if __name__ == "__main__":
    unittest.main()
