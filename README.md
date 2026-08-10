# Sitter

**A babysitter for coding agents.**

> Because autonomous coding agents still need adult supervision.

Sitter is a governance harness for coding agents working in complex repositories. It keeps low-risk work lightweight and adds investigation, read-only scouting, evidence, review, test hygiene, and human decision gates only as risk increases.

Sitter currently supports **OpenAI Codex** and **Claude Code** through a provider-neutral governance core.

## Why Sitter

Coding agents are fast. In mature codebases, the dangerous failure mode is often not invalid syntax but a locally plausible change that silently degrades architecture, skips important context, leaves temporary tests behind, or cannot prove how it was produced.

Sitter adds structure where it matters without turning every small edit into a ceremony.

## What it does

- Adaptive `LOW / MEDIUM / HIGH / CRITICAL` work risk.
- A `Task / Investigation / Change` work graph for governed changes.
- Read-only scout roles for bounded repository exploration.
- Human decision gates for architecture-sensitive work.
- Test finalization and temporary-test cleanup checks.
- Review, evidence, learning, and archive lifecycles.
- Provider-neutral governance with provider-specific runtime enforcement.
- Transactional install/update behavior with rollback on failure.
- Runtime attestation for governed Codex and Claude executions.

## Architecture

```text
Sitter
├─ Governance Core
│  ├─ Task / Investigation / Change
│  ├─ Risk / Evidence / Decision
│  ├─ Delegation / Review / Learning
│  └─ Provider-neutral contracts
└─ Runtime Providers
   ├─ Codex
   └─ Claude Code
```

Codex and Claude can coexist in one repository, but one Task is bound to one orchestrator provider. Sitter does not transfer a Task between providers or mix Codex and Claude orchestration inside the same Task.

## Install

Requirements:

- Python 3.12+
- `PyYAML`
- Git
- Codex and/or Claude Code when using the corresponding provider

Install the Python dependency:

```bash
python -m pip install PyYAML
```

Always pass the exact Git repository or worktree root as `<project-root>`.

### Codex-only

A fresh install defaults to Codex-only:

```bash
python install.py --project <project-root> --dry-run
python install.py --project <project-root> --trust-project
python check.py --project <project-root>
```

### Claude-only

```bash
python install.py --project <project-root> --provider claude --dry-run
python install.py --project <project-root> --provider claude
python check.py --project <project-root>
```

### Codex + Claude

```bash
python install.py --project <project-root> --provider codex --provider claude --trust-project --dry-run
python install.py --project <project-root> --provider codex --provider claude --trust-project
python check.py --project <project-root>
```

Run the installed self-check after installation:

```bash
python <project-root>/.harness/sitter/runtime/self_check.py --project <project-root>
```

See [`docs/local-update-and-sharing.md`](docs/local-update-and-sharing.md) for installation ownership, updates, worktrees, and drift handling.

## What Sitter writes

Depending on enabled providers, Sitter projects generated files such as:

```text
AGENTS.md
.codex/config.toml
.codex/agents/*.toml
.agents/skills/*/SKILL.md
CLAUDE.local.md
.claude/agents/*.md
.claude/skills/*/SKILL.md
.claude/hooks/governance-runtime-hook.py
.harness/sitter/
```

These are managed installation artifacts and are recorded in the installation manifest.

The following are durable project or user state and are **not** replaced as part of a Sitter update:

```text
.agent-work/
changes/
knowledge/
.claude/settings.local.json
.harness/sitter.models.local.yaml
production source code and user-owned files
```

Sitter refuses to silently overwrite an unverified user-owned projection.

## Roles and skills

Read-only / review agent roles:

- `source-locator`
- `context-scout`
- `framework-scout`
- `test-scout`
- `maintainer-reviewer`
- `deep-reviewer`

Governance skills:

- `change-governor`
- `architecture-health-check`
- `decision-grill`
- `maintainer-handoff`

The product is called **Sitter**; internal governance concepts intentionally use neutral engineering names rather than `sitter-*` prefixes.

## Model profiles

Default provider/model profiles live in:

```text
adapters/default/model-profiles.yaml
```

Per-project overrides live in:

```text
.harness/sitter.models.local.yaml
```

Provider-neutral grades are mapped by each provider to native selectors.

## Validation

Run the full test suite:

```bash
python -m unittest discover -s tests -v
```

The CI matrix runs on Ubuntu and Windows. Windows CI also parses the PowerShell acceptance scripts and runs the Codex static regression from outside the Sitter working directory.

## Documentation

Useful design and operating references:

- [`docs/V5-Provider架构重构说明.md`](docs/V5-Provider架构重构说明.md) — provider-neutral architecture.
- [`docs/V5-B-Claude-Code-Provider-Design.md`](docs/V5-B-Claude-Code-Provider-Design.md) — Claude Code provider design.
- [`docs/V5-B-Model-Profiles.md`](docs/V5-B-Model-Profiles.md) — model-profile configuration.
- [`docs/delegation-context.md`](docs/delegation-context.md) — delegation/context contracts.
- [`docs/dynamic-risk-behavior-optimization.md`](docs/dynamic-risk-behavior-optimization.md) — adaptive risk behavior.
- [`docs/v4-work-graph.md`](docs/v4-work-graph.md) — governed work graph.
- [`docs/review-recording.md`](docs/review-recording.md) — review recording.

Reusable acceptance templates remain under `docs/acceptance/`; private development transcripts and dated internal acceptance reports are intentionally not part of the public release.

## Scope

Sitter 1.0 supports Codex and Claude Code. It intentionally does not provide Kimi Code, OpenCode, Pi, cross-provider Task transfer, or mixed-provider orchestration within one Task.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
