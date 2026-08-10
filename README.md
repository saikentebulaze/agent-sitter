# Sitter

**A babysitter for coding agents.**

> Because autonomous coding agents still need adult supervision.

Sitter is a governance harness for coding agents working in complex repositories. It keeps low-risk work lightweight and adds investigation, read-only scouting, evidence, review, test hygiene, and human decision gates only as risk increases.

## Core Goals

Sitter exists to improve the effectiveness of coding Agents without replacing the engineer who is responsible for the system.

Its long-term design is centered on two core goals.

### 1. Context Capability

Improve the Agent's ability to obtain the **right, sufficiently complete, and current context** before making engineering conclusions or modifying a repository.

This includes:

- within-task context expansion through focused independent Agents such as Locator, Context Scout, Test Scout, and Framework Scout;
- cross-session continuity through compact Task state, durable project knowledge, useful unfinished threads, and other high-value historical context.

Sitter prefers:

- progressive disclosure over eager loading;
- bounded independent exploration over indiscriminate repository scanning;
- distilled project state over conversation transcripts;
- current repository state over historical memory when they disagree;
- version-aware historical context whose freshness can be checked.

The objective is not maximum context volume. The objective is maximizing the probability that important context is present while irrelevant or stale context stays out.

### 2. Human Decision Authority

Agents investigate, collect evidence, run experiments, compare alternatives, explain trade-offs, and recommend options.

For material engineering forks where evidence does not determine one objectively correct answer, the engineer retains final authority.

Examples include:

- algorithm or numerical semantics;
- state ownership and lifecycle;
- sign, unit, coordinate, or result interpretation;
- compatibility and fallback behavior;
- responsibility boundaries;
- precision versus performance;
- architecture choices with multiple valid alternatives.

Explicit user decisions become authoritative project state. Subsequent Design, Change, Implementation, Verification, Review, and durable Knowledge must remain consistent unless the decision is explicitly reconsidered.

Human Decision Authority does not mean constant interruption. Routine deterministic LOW-risk work remains fast and autonomous.

These goals are design invariants. New mechanisms, Agents, Hooks, memory features, and governance rules should primarily justify themselves by improving one of these two goals without materially degrading LOW Fast Path behavior.

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

## V6 Development

V6 begins with behavior benchmarks before implementation. See [`docs/V6-Behavior-Benchmark.md`](docs/V6-Behavior-Benchmark.md).

