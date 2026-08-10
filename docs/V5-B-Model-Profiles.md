# V5-B configurable model profiles

This document freezes the first V5-B implementation slice.

- Governance uses `low`, `medium`, and `high` grades.
- Providers map grades to native model selectors.
- The default Codex mapping remains `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`.
- The default Claude mapping is `haiku`, `sonnet`, and `opus`.
- Projects may partially override selectors in `.harness/sitter.models.local.yaml`.
- Unknown future native selectors are accepted as configuration and must be proved by Provider capability tests.
- Claude child profiles reject `inherit`.
- Duplicate selectors across grades require explicit acknowledgement because they collapse stronger-model escalation.
