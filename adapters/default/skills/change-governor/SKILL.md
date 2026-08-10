---
name: change-governor
description: Govern Sitter work after the lightweight router determines that a formal Task, Investigation, Production Change, escalation, or independent review is needed. Do not use for ordinary LOW fast-path work.
---

# Sitter

This is the formal governance layer. The lightweight bootstrap router handles conversation and clearly LOW work. Once work is governed, keep the existing Task / Investigation / Production Change graph; do not create a second lite workflow.

## Runtime

```powershell
$ProjectRoot = (Get-Location).Path
$Runtime = Join-Path $ProjectRoot ".harness\sitter\runtime"
```

Use the packaged runtime only.

## Dynamic work risk

Three values have different jobs:

- `task.work_risk.current`: risk of the work being done now; may rise or fall.
- `task.work_risk.peak`: highest execution risk reached; never automatically falls.
- `change.risk`: Production Change assurance floor; final verification/review follows this, not cleanup risk.

```text
LOW      -> Fast Path; normally no formal Task was needed
MEDIUM   -> existing Task/Change graph with brief governance
HIGH     -> full governance + independent exploration before active implementation
CRITICAL -> full governance + escalation-sensitive controls
```

Record a material manual transition only when facts change:

```powershell
python "$Runtime\work.py" --project $ProjectRoot reassess-risk <task-id> `
  --semantic low|medium|high|critical `
  --repository-change low|medium|high|critical `
  --reason "..." [--evidence-ref "..."] `
  [--remaining-work-bounded] [--raise-assurance]
```

Risk increases are cheap; decreases require resolved unknowns and bounded remaining work. `investigate-change` automatically raises newly discovered production uncertainty to at least HIGH and raises the affected Change assurance. `pivot-to-change` propagates the converged Investigation's current risk into the new Change assurance. Lowering current risk never lowers assurance.

Read `references/risk-classification.md` and `references/risk-lifecycle.md` only for non-obvious transitions.

## Task / Investigation / Change

Create a Task only after leaving the LOW Fast Path.

```powershell
# Investigation entry
python "$Runtime\create_task.py" <task-id> --title "..." `
  --entry investigation --question "..." --signature <signature> `
  --provider codex|claude --project $ProjectRoot

# Production Change entry
python "$Runtime\create_task.py" <task-id> --title "..." `
  --entry change --change-id <change-id> `
  --provider codex|claude --project $ProjectRoot
```

Use Investigation when root cause, responsibility, business/numerical semantics, or expected behavior is not stable. Claims and accepted Decisions remain evidence-backed. An Investigation -> Change pivot requires an accepted supported Decision. Unexpected behavior during implementation/verification uses Change -> Investigation rather than silently enlarging scope.

Common commands:

```text
work.py record-evidence
work.py record-claim
work.py record-decision
work.py pivot-to-change
work.py investigate-change
work.py conclude-investigation
```

Repeated equivalent pivots require new discriminating capability and may escalate to a stronger model or human checkpoint. An open Investigation or active escalation blocks risk de-escalation.

## Delegation

LOW work does not use subagents for ceremony. MEDIUM exploration is optional when scope is obvious. Once a Task reaches HIGH/CRITICAL, its independent exploration obligation persists even if later cleanup risk becomes LOW. Do not repeat a completed Scout merely because the Task is closing.

Task-level delegation authorization remains explicit. After authorization is granted, prefer the managed one-command facade instead of manually performing request -> runtime -> attestation -> record:

```powershell
python "$Runtime\delegate_once.py" <task-id> --project $ProjectRoot `
  --role context_scout `
  --target-type investigation --target-ref <inv-id> `
  --purpose "..." --question "..." --decision-supported "..." `
  --include <scope-or-path>
```

The facade dispatches through the Task's Codex or Claude Provider, preserves the frozen Context Capsule and provider-specific runtime proof, then records the result. Structured `NEED_CONTEXT` is recorded as `need-context`; runtime failure never becomes false completion.

Context isolation, attestation, stale detection, model/tier authorization, and result-promotion rules remain mandatory. Child output never mutates authoritative Task/Investigation/Change state automatically. Read `references/subagent-model-policy.md` and `references/reasoning-budget-policy.md` only when delegation/model budgeting is actually active.

## Human decisions

HIGH/CRITICAL work must identify genuine decision forks before silently choosing product behavior, algorithm semantics, state ownership, path behavior, coordinates/sign/units, compatibility/fallback policy, responsibility boundaries, or precision/performance tradeoffs.

Do not interrupt for routine implementation details already implied by an accepted design. Batch genuine forks. Stronger models do not replace user authority over product and engineering semantics.

## Production Change, tests, verification, review

The Change lifecycle remains:

```text
proposed -> designed -> approved -> implementing -> verifying -> syncing -> ready-to-archive -> archived
```

A HIGH/CRITICAL Task cannot actively implement/verify a Change until relevant independent exploration has completed. A paused Change under Investigation is exempt until it resumes.

Development-only tests/probes must be deleted, merged, or deliberately promoted before review. New Changes use the explicit Test Finalization transaction:

```powershell
python "$Runtime\finalize_tests.py" <change-id> --project $ProjectRoot `
  [--retain "tests/path=长期回归价值"] `
  [--preexisting "tests/path=任务开始前已有用户修改"]
```

The transaction writes `test-finalization.yaml`; setting `test_cleanup_complete: true` by hand does not satisfy protocol-1 Changes.

Current work may drop to LOW during cleanup, but final verification and independent review continue to follow `change.risk`. Review request freezes the Change assurance snapshot; changing assurance after review starts invalidates that request. Normal independent review uses the configured Maintainer Reviewer. Deep Review remains exceptional escalation, not an automatic CRITICAL ritual.

Read `references/testing-policy.md` / `references/review-policy.md` only in those phases.

## Learning and completion

Do not pull LOW Fast Path work into the Work Graph merely to run Learning. Governed Tasks retain required Learning/completion obligations. Mature reusable candidates still require user review before promotion to tools, Skills, knowledge, policy, configuration, or Harness changes.

Before completion ensure Investigations are concluded, Changes archived or abandoned, required delegations/escalations resolved, temporary production/test artifacts gone, and required Learning closeout satisfied.

Useful status commands:

```text
work.py task-status <task-id>
work.py validate <task-id>
work.py delegation-status <task-id> [dlg-id]
harness.py status <change-id>
harness.py validate-change <change-id>
```

## Progressive disclosure

Do not preload references. Open only what the current governed action requires:

- risk: `risk-classification.md`, `risk-lifecycle.md`
- Investigation: `investigation-contract.md`, `investigation-policy.md`
- implementation scope: `implementation-policy.md`, `change-artifact-policy.md`
- delegation/model budget: `subagent-model-policy.md`, `reasoning-budget-policy.md`
- testing/review/human decisions: the corresponding policy only when active
- knowledge/Learning/archive: only in those phases

Do not reload references or rerun status/intake merely to reconfirm unchanged facts. Load more only when new information changes the action or risk.
