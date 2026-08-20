---
name: change-governor
description: Govern Sitter work after the lightweight router determines that a formal Task, Investigation, Production Change, escalation, or independent review is needed. Do not use for ordinary LOW fast-path work.
---

# Sitter

This is the formal governance layer. Conversation and clearly LOW work stay in the lightweight router. Governed work keeps the existing Task / Investigation / Production Change graph; do not create a second lite workflow.

## Runtime

```powershell
$ProjectRoot = (Get-Location).Path
$Runtime = Join-Path $ProjectRoot ".harness\sitter\runtime"
```

Use the packaged runtime only.

## Dynamic work risk

- `task.work_risk.current`: current execution intensity; may rise or fall.
- `task.work_risk.peak`: historical maximum; never automatically falls.
- `change.risk`: Production Change assurance floor; final verification/review follows this.

```text
LOW      -> Fast Path; normally no formal Task
MEDIUM   -> existing Task/Change graph with brief governance
HIGH     -> full governance + required independent exploration
CRITICAL -> full governance + escalation-sensitive controls
```

Risk increases are cheap; decreases require resolved unknowns and bounded remaining work. Change -> Investigation raises newly discovered production uncertainty to at least HIGH. Investigation -> Change propagates converged current risk. Lowering current risk never lowers Change assurance. Use `reassess-risk` only when facts change; read `references/risk-classification.md` / `risk-lifecycle.md` only for non-obvious transitions.

## Task / Investigation / Change

Create a Task only after leaving LOW Fast Path. Use Investigation when root cause, responsibility, business/numerical semantics, or expected behavior is not stable. Accepted Decisions remain evidence-backed. Investigation -> Change requires an accepted supported Decision; unexpected behavior during implementation/verification uses Change -> Investigation instead of silently enlarging scope.

Common commands: `record-evidence`, `record-claim`, `record-decision`, `pivot-to-change`, `investigate-change`, `conclude-investigation`. Repeated equivalent pivots require new discrimination and may escalate. An open Investigation or escalation blocks risk de-escalation.

## Delegation

LOW work does not use subagents for ceremony. MEDIUM exploration is optional when one or two local reads resolve scope/ownership. HIGH/CRITICAL retains its independent exploration obligation even if cleanup risk later falls.

### Exploration offload economics

Use the expensive parent for synthesis, decisions, edits and verification—not broad retrieval. After at most one or two obvious anchor reads, delegate early when ownership remains unknown, the chain crosses modules/lifecycle stages, or the next parent step would be broad Grep/Read. For HIGH/CRITICAL, satisfy required independent exploration **early** once the question and bounded starting scope are stable.

Choose the cheapest matching role: `source_locator` for exact symbols/callers/tests, `context_scout` for cross-module state/data flow, `test_scout` for test evidence, `framework_scout` only for real framework/ownership semantics. **Default to one Scout, not fan-out**; add another only for `NEED_CONTEXT`, an independent second search line, or evidence conflict. After a Scout completes, do not repeat its broad search in the parent.

Task-level authorization remains explicit. When policy allows, the parent may authorize a same-tier or cheaper read-only Scout with `--decision optional|required`; stronger-than-parent models still need elevated authorization. Use `delegate_once.py` for request -> Provider runtime -> attestation -> record. A result meant to satisfy a governed Scout/Review gate must be launched through Sitter from the beginning; casually spawned native output is advisory only.

Read `references/subagent-model-policy.md` / `reasoning-budget-policy.md` only when delegation/model budgeting is active.

## Human decisions

HIGH/CRITICAL work must identify genuine forks before silently choosing algorithm/product semantics, state ownership, path behavior, coordinates/sign/units, compatibility/fallback policy, responsibility boundaries, acceptance behavior, or accuracy/performance tradeoffs. Batch genuine decisions; do not interrupt for routine implementation details already implied by accepted design. Resolved user decisions are authoritative state.

## Candidate Readiness and closure

New V6.2 Changes use:

```text
proposed -> designed -> approved -> implementing
-> candidate-review -> verifying -> syncing -> ready-to-archive -> archived
```

Legacy Changes remain read-compatible. For a V6.2 Change, define `readiness.assurance_class` and criteria with Design/Tasks, then freeze them before implementation evidence:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot freeze-readiness <change-id>
```

Do not weaken criteria after seeing implementation results. `standard` may use focused deterministic evidence; `behavioral` needs integration/representative external behavior; `numerical` needs representative-case, benchmark, or analytical-check. Unit tests alone cannot make a numerical Change Candidate Ready.

Record current-snapshot evidence and finalize readiness:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot record-readiness <change-id> `
  --criterion <id> --result pass|fail `
  --command-or-entry "..." --evidence "..." [--observed "..."]
python "$Runtime\harness.py" --project $ProjectRoot finalize-readiness <change-id>
```

Production/test edits stale that evidence; Harness lifecycle/Markdown writes do not. Prefer `harness.py prepare-candidate <change-id>` once required readiness evidence exists: it finalizes tests, mechanically checks changed production/test paths against an explicit Change Budget before spending Reviewer cost, runs the Provider-bound Reviewer, and advances only on PASS/WARN. If using the lower-level path, run `finalize_tests.py` before `harness.py review <change-id> --run`. Deep review remains exceptional escalation.

A review BLOCK with remediation `implementation` is repaired inside already approved semantics without user interruption. `awaiting-production-design` means new scope/semantics are required and must reach the human checkpoint. Read `references/testing-policy.md`, `review-policy.md`, and `human-in-loop-policy.md` only in these phases.

When Readiness, test finalization and independent review are valid, `harness.py advance <change-id>` enters `candidate-review`. If `user_review.status: pending`, summarize readiness evidence, representative external/numerical results and known limitations, ask the user to approve or request changes, then **STOP**. Do not run final/full regression, Knowledge, Learning closeout, archive, or another reviewer while acceptance is pending.

Record the decision only through Harness:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot user-review <change-id> `
  --decision approved|changes-requested|not-required --evidence "..."
```

`not-required` requires explicit user evidence; the Agent may not choose it for convenience. `changes-requested` returns to implementation and stales Readiness. `approved` permits final verification. Broad PASS evidence added after approval need not invalidate the earlier review when production/design/authority/readiness inputs remain unchanged; production or semantic changes do.

After final verification advances the Change to `syncing`, follow `harness.py status`: if no durable Knowledge candidates exist, use `defer-knowledge --reason "..."`; never fake promotion or silently auto-defer. After Knowledge is promoted/deferred, remove any development experiments/temporary production files and run `finalize-archive-cleanup --evidence "..."`; this transaction checks but never deletes artifacts. Then `advance` may reach `ready-to-archive`, and `archive` records `archived` before Task completion. A historical `change revised after investigation` hold is cleared only after the current post-revision Readiness, Review and final Verification have all been re-proved.

## Learning and completion

Do not pull LOW Fast Path work into the Work Graph merely for Learning. Governed Tasks retain Learning/completion obligations. Durable candidates still require user review before promotion. Before completion ensure Investigations are concluded, Changes archived/abandoned, required delegations/escalations resolved, temporary artifacts gone, and required Learning closeout satisfied.

Useful status commands: `work.py task-status <task-id>`, `work.py validate <task-id>`, `harness.py status <change-id>`, `harness.py validate-change <change-id>`. `harness.py status` is authoritative about `ACTION REQUIRED`, `allowed_next`, and `blocked_next`; it must only recommend commands the runtime actually exposes.

## Progressive disclosure

Do not preload references. Load only what the current action needs: risk; Investigation; implementation scope; delegation/model budget; readiness/testing/review/human decisions; Knowledge/Learning/archive. Do not reload references or rerun status/intake merely to reconfirm unchanged facts.
