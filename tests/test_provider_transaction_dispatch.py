from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import _delegation_transaction_impl as implementation  # noqa: E402
import delegation_transaction as transaction  # noqa: E402
from core.provider_contract import RuntimeContract, RuntimeEvidence  # noqa: E402


class ProviderTransactionDispatchTests(unittest.TestCase):
    def test_transaction_implementation_uses_provider_validator(self) -> None:
        self.assertIs(
            implementation._validate_attestation,
            transaction._validate_attestation,
        )

    def test_facade_dispatches_and_returns_normalized_runtime_evidence(self) -> None:
        expected = RuntimeEvidence(
            provider="codex",
            role_id="source_locator",
            contract=RuntimeContract(
                context_isolation="fresh",
                write_isolation="os-readonly",
                persistent_context="unknown",
                attestation_strength="runtime-observed",
            ),
            raw_evidence_ref="native-thread:child",
        )
        with mock.patch.object(
            transaction,
            "validate_provider_attestation",
            return_value=expected,
        ) as validator:
            actual = transaction._validate_attestation(
                {"runtime": {"provider": "codex"}},
                {"schema_version": 2},
            )
        self.assertEqual(actual, expected)
        validator.assert_called_once()

    def test_unknown_provider_is_rejected_through_formal_transaction_boundary(self) -> None:
        with self.assertRaisesRegex(
            transaction.DelegationTransactionError,
            "Supported providers: claude, codex",
        ):
            transaction._validate_attestation(
                {"runtime": {"provider": "opencode"}},
                {},
            )

    def test_legacy_codex_schema_error_text_is_preserved(self) -> None:
        with self.assertRaisesRegex(
            transaction.DelegationTransactionError,
            "schema_version must be 2",
        ):
            transaction._validate_attestation(
                {
                    "runtime": {"provider": "codex"},
                    "requested_profile": {},
                },
                {"schema_version": 1},
            )


if __name__ == "__main__":
    unittest.main()
