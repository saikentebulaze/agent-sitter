# V5-B Claude Code Runtime Provider Design

## Status

Draft design. This document freezes the V5-B implementation boundary before runtime changes.

## Goals

- Add Claude Code as a first-class Runtime Provider.
- Preserve Codex projection, attestation, and compatibility behavior.
- Keep Governance Core Provider-neutral.
- Allow Codex and Claude to coexist in one project.
- Keep one Task bound to one orchestrator provider.
- Do not implement Provider transfer or mixed Provider orchestration.

## Model configuration

Governance Core must not know provider-specific model names.

Use provider-neutral model grades:

- low
- medium
- high

Example:

```yaml
providers:
  codex:
    models:
      low: gpt-5.6-luna
      medium: gpt-5.6-terra
      high: gpt-5.6-sol
  claude:
    models:
      low: haiku
      medium: sonnet
      high: opus
```

Role policy selects a grade; Provider resolves it into the native model selector.

## Provider boundary

Core knows:

- Task provider binding
- role
- model grade
- runtime contract
- normalized evidence

Provider owns:

- native model selector
- project projections
- agent definitions
- runtime execution
- attestation collection

## Testing principle

Passing output is not sufficient evidence.

Tests must detect:

- wrong model actually used
- wrong Agent profile loaded
- inherited parent context
- hidden tool usage
- memory leakage
- nested agents
- resume/fork/background execution
- worktree isolation
- settings ownership conflicts

Every negative capability test requires a positive control proving the capability exists when intentionally enabled.

## Implementation order

1. Freeze contracts and regression gates.
2. Make delegation execution Provider-neutral.
3. Add model configuration and capability resolution.
4. Add multi-provider installation transaction support.
5. Add Claude static Provider.
6. Add Claude managed/native runtime evidence.
7. Run real Claude Code acceptance before merge.
