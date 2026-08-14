# Sitter

**A babysitter for coding agents.**

> Because autonomous coding agents still need adult supervision.

Sitter is a governance harness for coding agents working in complex repositories. It keeps low-risk work lightweight and adds investigation, read-only scouting, evidence, review, test hygiene, and human decision gates only as risk increases.

Sitter currently supports **OpenAI Codex** and **Claude Code** through a provider-neutral governance core.

## Core Goals

Sitter exists to improve the effectiveness of coding Agents without replacing the engineer who is responsible for the system.

Its long-term design is centered on two core goals.

### 1. Context Capability

Improve the Agent's ability to obtain the **right, sufficiently complete, and current context** before making engineering conclusions or modifying a repository.

This includes:

- **within-task context expansion** through focused, independent Agents such as Locator, Context Scout, Test Scout, and Framework Scout, so the main Agent does not converge too early on the first plausible explanation;
- **cross-session project continuity** through compact Task state, durable project knowledge, useful unfinished threads, and other high-value historical context without loading the entire project history.

More context is not automatically better context. Sitter therefore prefers:

- progressive disclosure over eager loading;
- bounded independent exploration over indiscriminate repository scanning;
- distilled project memory over conversation transcripts;
- current code over historical memory when they disagree;
- version-aware memory whose freshness can be checked against repository evolution;
- low-cost Agents for context retrieval and filtering where appropriate.

The goal is not to maximize the amount of context shown to the main Agent. The goal is to maximize the probability that the **important context is present while irrelevant, stale, and misleading context stays out**.

### 2. Human Decision Authority

Keep the engineer as the authoritative decision-maker for material engineering choices that cannot be resolved objectively from evidence.

Agents should investigate first. They should locate code, collect evidence, run experiments, compare alternatives, explain trade-offs, and make recommendations.

When a decision materially affects areas such as:

- algorithm or numerical semantics;
- state ownership and lifecycle;
- sign, unit, coordinate, or result interpretation;
- compatibility and fallback behavior;
- responsibility boundaries;
- precision versus performance;
- architecture where multiple valid alternatives remain;

the engineer retains the final decision.

Once the user decides, that decision becomes authoritative project state. Downstream Design, Change, Implementation, Verification, Review, and durable Memory must remain consistent with it unless it is explicitly reconsidered.

Human Decision Authority does **not** mean maximizing interruptions. Routine, deterministic, and LOW-risk work should remain fast and autonomous.

These two goals are long-term design invariants. LOW Fast Path is an important constraint, not a third top-level goal. Additional top-level goals should be introduced only when long-term use demonstrates a genuinely independent need.

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

- [`docs/V6-Behavior-Benchmark.md`](docs/V6-Behavior-Benchmark.md) — V6 behavior-first acceptance benchmark.
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
