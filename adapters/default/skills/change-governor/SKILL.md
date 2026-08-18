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
python "$Runtime\create_task.py" <task-id> --title "..." `
  --entry investigation --question "..." --signature <signature> `
  --provider codex|claude --project $ProjectRoot

python "$Runtime\create_task.py" <task-id> --title "..." `
  --entry change --change-id <change-id> `
  --provider codex|claude --project $ProjectRoot
```

Use Investigation when root cause, responsibility, business/numerical semantics, or expected behavior is not stable. Claims and accepted Decisions remain evidence-backed. An Investigation -> Change pivot requires an accepted supported Decision. Unexpected behavior during implementation/verification uses Change -> Investigation rather than silently enlarging scope.

Common commands: `record-evidence`, `record-claim`, `record-decision`, `pivot-to-change`, `investigate-change`, `conclude-investigation`.

Repeated equivalent pivots require new discriminating capability and may escalate to a stronger model or human checkpoint. An open Investigation or active escalation blocks risk de-escalation.

## Delegation

LOW work does not use subagents for ceremony. MEDIUM exploration stays optional when one or two local reads make scope/ownership obvious. Once a Task reaches HIGH/CRITICAL, its independent exploration obligation persists even if cleanup risk later falls. Do not repeat a completed Scout merely because the Task is closing.

### Exploration offload economics

Use the expensive parent for synthesis, decisions, edits, and verification—not broad retrieval. After at most one or two obvious anchor reads, delegate early when ownership is still unknown, the chain crosses modules/lifecycle stages, or the next parent step would be broad Grep/Read. For HIGH/CRITICAL, satisfy required independent exploration early once the question and bounded starting scope are stable.

Choose the cheapest matching role: `source_locator` for exact symbols/callers/tests, `context_scout` for cross-module state/data flow, `test_scout` for test evidence, and `framework_scout` only for real framework/ownership semantics. Default to one Scout; add another only for `NEED_CONTEXT`, an independent second search line, or evidence conflict.

After a Scout completes, do not repeat its broad search in the parent. Read only decisive references needed to validate, synthesize, or modify the system.

Task-level authorization remains explicit in Task state. When the offload trigger is met and no stricter user ceiling applies, the parent may grant same-tier/cheaper read-only exploration itself. Stronger-than-parent models still need elevated authorization.

```powershell
python "$Runtime\work.py" --project $ProjectRoot authorize-delegation <task-id> `
  --decision optional|required --scope readonly-exploration `
  --evidence "bounded retrieval offload for ..." `
  --parent-model <actual-parent-model> --parent-tier luna|terra|sol|unknown

python "$Runtime\delegate_once.py" <task-id> --project $ProjectRoot `
  --role context_scout --target-type investigation --target-ref <inv-id> `
  --purpose "..." --question "..." --decision-supported "..." `
  --include <scope-or-path>
```

The facade dispatches through the Task's Provider, preserves the frozen Context Capsule and provider-specific runtime proof, then records the result. A result intended to satisfy a governed Scout/Review gate must be launched through Sitter from the beginning; a casually spawned native agent may inform reasoning but does not become formal attested evidence after the fact.

Read `references/subagent-model-policy.md` and `references/reasoning-budget-policy.md` only when delegation/model budgeting is active.

## Human decisions

HIGH/CRITICAL work must identify genuine decision forks before silently choosing product behavior, algorithm semantics, state ownership, path behavior, coordinates/sign/units, compatibility/fallback policy, responsibility boundaries, or precision/performance tradeoffs.

Do not interrupt for routine implementation details already implied by an accepted design. Batch genuine forks. Stronger models do not replace user authority over product and engineering semantics.

## Production Change, Candidate Readiness, review

New V6.2 Changes use:

```text
proposed -> designed -> approved -> implementing
-> candidate-review -> verifying -> syncing -> ready-to-archive -> archived
```

Legacy Changes without `candidate_readiness_protocol: 1` remain read-compatible with the old lifecycle.

### Readiness Contract

Before implementation, define `readiness.assurance_class` and criteria with Design/Tasks. Do not invent easier acceptance criteria after seeing implementation results.

- `standard`: focused deterministic evidence may be enough.
- `behavioral`: requires integration or representative external behavior.
- `numerical`: requires representative-case, benchmark, or analytical-check; local unit tests alone cannot make a numerical Change Candidate Ready.

Record each result through the Harness so it is bound to the current production snapshot:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot record-readiness <change-id> `
  --criterion <id> --result pass|fail `
  --command-or-entry "..." --evidence "..." [--observed "..."]

python "$Runtime\harness.py" --project $ProjectRoot finalize-readiness <change-id>
```

Production/test edits after evidence make that evidence stale. Harness-owned lifecycle/Markdown updates do not count as production changes.

### Test finalization and readiness review

After Readiness passes, remove/merge/promote development-only tests before reviewer work:

```powershell
python "$Runtime\finalize_tests.py" <change-id> --project $ProjectRoot `
  [--retain "tests/path=长期回归价值"] `
  [--preexisting "tests/path=任务开始前已有用户修改"]
```

Then run the independent maintainer review. It checks Architecture, Scope and Numerical Evidence, including whether representative evidence truly exercises the target business path. Deep Review remains exceptional escalation.

A reviewer BLOCK with remediation route `implementation` is repaired automatically inside the already approved semantics and does not require user interruption. `awaiting-production-design` means the fix needs a new semantic/scope decision and must go to the human checkpoint.

### Candidate human stop

Once Readiness, test finalization and independent review are valid, advance semantically:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot advance <change-id>
```

When status becomes `candidate-review` and `user_review.status` is `pending`:

1. summarize Candidate Readiness evidence;
2. highlight representative external/numerical results;
3. state remaining known limitations;
4. ask the user to approve or request changes;
5. **STOP**.

Do not start final/full regression, Knowledge, Learning closeout, archive work, extra reviewer work, or any other expensive closure while Candidate acceptance is pending.

Record the user's decision through the Harness:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot user-review <change-id> `
  --decision approved|changes-requested|not-required --evidence "..."
```

`not-required` requires explicit user evidence; the Agent may not choose it for convenience. `changes-requested` returns the Change to implementation and stales Candidate Readiness. `approved` permits the next `advance` into final verification.

Final verification after approval may add broad regression/cross-platform evidence without forcing a second review when production/design/authority/readiness inputs are unchanged. A production or semantic change makes the earlier readiness/review stale and returns to the Candidate cycle.

Read `references/testing-policy.md`, `references/review-policy.md`, and `references/human-in-loop-policy.md` only in those phases.

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

For V6.2 `candidate-review`, `harness.py status` is authoritative about `ACTION REQUIRED`, `allowed_next`, and `blocked_next`; do not continue closure against a pending human stop.

## Progressive disclosure

Do not preload references. Open only what the current governed action requires:

- risk: `risk-classification.md`, `risk-lifecycle.md`
- Investigation: `investigation-contract.md`, `investigation-policy.md`
- implementation scope: `implementation-policy.md`, `change-artifact-policy.md`
- delegation/model budget: `subagent-model-policy.md`, `reasoning-budget-policy.md`
- readiness/testing/review/human decisions: corresponding policy only when active
- knowledge/Learning/archive: only in those phases

Do not reload references or rerun status/intake merely to reconfirm unchanged facts. Load more only when new information changes the action or risk.
