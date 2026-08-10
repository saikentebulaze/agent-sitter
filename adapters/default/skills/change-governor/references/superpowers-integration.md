# Superpowers Integration

The Sitter Governor owns governance. Superpowers provides optional engineering methods.

## Precedence

The Governor controls:

- investigation vs production-change mode;
- semantic and repository risk;
- user approvals;
- scope, critical surfaces and Change Artifacts;
- subagent authorization and model ceilings;
- completion, review and archive gates.

Superpowers skills may not bypass those decisions. In particular, any Superpowers workflow that would
spawn subagents inherits the Governor's delegation and elevated-model authorization rules.

## Reuse, do not duplicate

Use installed Superpowers skills directly when their method is useful. Do not copy their full procedures
into the Harness and do not create parallel design/plan documents.

- If approved `proposal.md` / `design.md` already exist, brainstorming refines those artifacts rather than creating a second design authority.
- If `tasks.md` already exists, writing-plans may refine it or produce temporary execution notes; it must not create a competing permanent plan.
- The Change Artifacts remain the source of truth.

## Proportional use

### Small / mechanical work

Examples: a local rename, explicit typo, narrow configuration correction, deterministic adapter update.

- no mandatory brainstorming;
- no long implementation plan;
- use a short intent and direct verification;
- TDD is optional when a useful behavior-level regression test would cost more than the change.

### Medium work

Use targeted brainstorming when behavior, ownership or acceptance criteria have more than one plausible interpretation.
Use a brief plan with meaningful slices, not 2-5 minute ceremonial steps.

### High / critical work

Use brainstorming or the Governor's Grill when important semantics remain ambiguous.
Use writing-plans after design approval when implementation crosses modules, state lifecycles or several dependent slices.
Do not use planning as a substitute for reading the real code and tests.

## TDD policy

Use test-driven development when it improves confidence:

- bug fixes with a reproducible behavior;
- solver/state-transition logic;
- public contracts and critical-surface invariants;
- regressions that could recur.

Do not force RED-GREEN ceremony for pure docs, generated projections, trivial metadata or changes whose only useful
verification is integration/runtime evidence.

Investigation may create disposable tests or probes under `.agent-work/<task-id>/experiments/`.
Production implementation should prefer the smallest behavior-level permanent regression test.

## Test lifecycle

Every test added during a task must be classified before completion:

- `permanent-regression`: protects a stable external behavior or invariant;
- `merged`: folded into an existing broader test;
- `development-only`: useful while implementing but not worth permanent maintenance;
- `diagnostic`: one-off experiment or evidence collector.

Before review/archive:

1. remove development-only and diagnostic tests from production test suites;
2. merge overlapping cases when one clearer parameterized/integration test preserves the same evidence;
3. avoid permanent tests for private helpers when the external behavior is already covered;
4. record why each retained new test deserves long-term maintenance;
5. leave no temporary test artifacts unless explicitly blocked and recorded.

The Reviewer must treat unnecessary permanent tests and uncleaned diagnostic tests as scope findings.

## Avoiding workflow conflict

When Superpowers auto-triggers a heavier workflow than the Governor selected, the Governor decision wins.
State the selected proportional mode and continue with the applicable Superpowers skill only.
Do not run both a Governor design/plan flow and a separate Superpowers design/plan flow for the same task.
