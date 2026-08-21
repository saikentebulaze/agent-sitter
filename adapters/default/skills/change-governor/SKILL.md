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

Candidate-ready Changes use the existing lifecycle:

```text
proposed -> designed -> approved -> implementing
-> candidate-review -> verifying -> syncing -> ready-to-archive -> archived
```

The lifecycle and evidence remain authoritative, but V6.3 normal-path orchestration compresses the Agent-visible ceremony. Do **not** manually poll status or stitch together low-level `record/finalize/render/advance` commands when the high-level transaction can determine the next step.

Define `readiness.assurance_class` and criteria with Design/Tasks, then freeze them before implementation evidence:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot freeze-readiness <change-id>
```

Do not weaken criteria after seeing implementation results. `standard` may use focused deterministic evidence; `behavioral` needs integration/representative external behavior; `numerical` needs representative-case, benchmark, or analytical-check. Unit tests alone cannot make a numerical Change Candidate Ready.

After implementation and the required focused/representative checks have actually run, write their structured Readiness results as one YAML/JSON batch and use the normal Candidate transaction:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot prepare-candidate <change-id> `
  --readiness-batch <readiness-results.yaml>
```

The batch must contain the real criterion IDs, results, commands/entries, evidence, and optional observations. `prepare-candidate` validates the entire batch before mutation, binds one coherent Production Snapshot, finalizes readiness and test hygiene, checks the Change Budget before Reviewer cost, runs the Provider-bound FULL independent Reviewer with runtime attestation, rechecks production state after the external Reviewer, records the proof, and advances only on PASS/WARN.

A review BLOCK with remediation `implementation` is repaired inside already approved semantics without user interruption. `awaiting-production-design` means new scope/semantics are required and must reach the human checkpoint. Deep review remains exceptional escalation. Read `references/testing-policy.md`, `review-policy.md`, and `human-in-loop-policy.md` only in these phases.

When `prepare-candidate` succeeds it stops at `candidate-review`. Summarize readiness evidence, representative external/numerical results and known limitations, ask the user to approve or request changes, then **STOP**. Do not run final/full regression, Knowledge, Learning closeout, archive, or another reviewer while acceptance is pending.

Record the decision only through Harness:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot user-review <change-id> `
  --decision approved|changes-requested|not-required --evidence "..."
```

`not-required` requires explicit user evidence; the Agent may not choose it for convenience. `changes-requested` returns to implementation and stales Readiness. `approved` permits Final Verification. Broad PASS evidence added after approval need not invalidate the earlier review when production/design/authority/readiness inputs remain unchanged; production or semantic changes do.

After approval, actually run the required Final Verification, write the structured results as one YAML/JSON batch, and use the closure transaction:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot complete-after-approval <change-id> `
  --verification-batch <final-verification.yaml>
```

`complete-after-approval` validates the full batch before lifecycle mutation, records Final Verification, stops immediately on verification failure, and otherwise continues through closure using authoritative domain transactions. Zero durable Knowledge is explicitly and audibly deferred; real Knowledge candidates are preserved and stop for the existing authority path. Cleanup is checked but never silently deleted. Zero/ordinary Learning is assessed automatically; mature durable Learning candidates stop for individual human curation. The owning Task is completed only when no other active Investigation or non-archived Change remains.

The transaction is resumable. If it returns `governance-closure-pending`, resolve the named real blocker and rerun `complete-after-approval <change-id>` **without** a verification batch; do not redo already-valid engineering verification merely because Knowledge, cleanup, Learning, or other Task work remains.

The V6.2 low-level commands (`record-readiness`, `finalize-readiness`, `review --run`, `record-verification`, `defer-knowledge`, `finalize-archive-cleanup`, `render`, `advance`, `archive`) remain compatibility/recovery APIs. Use them only for historical data, diagnosis, or a transaction that cannot safely continue; they are not the normal successful path.

## Learning and completion

Do not pull LOW Fast Path work into the Work Graph merely for Learning. Governed Tasks retain Learning/completion obligations. Durable candidates still require user review before promotion. Ordinary observations remain recorded even when they require no human stop. Before completion ensure Investigations are concluded, Changes archived/abandoned, required delegations/escalations resolved, temporary artifacts gone, and required Learning closeout satisfied.

Status commands such as `work.py task-status <task-id>`, `work.py validate <task-id>`, `harness.py status <change-id>`, and `harness.py validate-change <change-id>` remain available for diagnosis/recovery. Do not poll them between normal-path transactions merely to rediscover a next step the coordinator already owns. `harness.py status` must only recommend commands the runtime actually exposes.

## Progressive disclosure

Do not preload references. Load only what the current action needs: risk; Investigation; implementation scope; delegation/model budget; readiness/testing/review/human decisions; Knowledge/Learning/archive. Do not reload references or rerun status/intake merely to reconfirm unchanged facts.
