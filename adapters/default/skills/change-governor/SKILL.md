---
name: change-governor
description: Govern Sitter work after the lightweight router determines that a formal Task, Investigation, Production Change, escalation, or independent review is needed. Do not use for ordinary LOW fast-path work.
---

# Sitter

Formal governance only. Conversation and clearly LOW work stay in the lightweight router. Governed work uses the existing Task / Investigation / Production Change graph; do not invent a second workflow.

## Runtime

```powershell
$ProjectRoot = (Get-Location).Path
$Runtime = Join-Path $ProjectRoot ".harness\sitter\runtime"
```

Use the packaged runtime only.

## Dynamic work risk

- `task.work_risk.current`: current execution intensity; may rise or fall.
- `task.work_risk.peak`: historical maximum; never automatically falls.
- `change.risk`: Production Change assurance floor; final verification/review follows it.

```text
LOW      -> Fast Path; normally no formal Task
MEDIUM   -> Task/Change graph with brief governance
HIGH     -> full governance + required independent exploration
CRITICAL -> full governance + escalation-sensitive controls
```

Risk increases are cheap; decreases require resolved unknowns and bounded remaining work. Change -> Investigation raises new uncertainty to at least HIGH. Investigation -> Change propagates converged current risk. Lowering current risk never lowers Change assurance. Use `reassess-risk` when facts change; load risk references only for non-obvious transitions.

## Task / Investigation / Change

Create a Task only after leaving LOW Fast Path. Use Investigation when root cause, responsibility, business/numerical semantics, or expected behavior is unstable. Investigation -> Change requires an accepted supported Decision. Unexpected implementation/verification behavior uses Change -> Investigation instead of silently enlarging scope.

Common commands: `record-evidence`, `record-claim`, `record-decision`, `pivot-to-change`, `investigate-change`, `conclude-investigation`. Repeated equivalent pivots require new discrimination and may escalate. Open Investigation/escalation blocks risk de-escalation.

## Delegation

LOW work does not use subagents for ceremony. MEDIUM work may stay in the parent when one or two local reads resolve scope/ownership. HIGH/CRITICAL keeps its independent exploration obligation even if cleanup risk later falls.

### Exploration offload economics

Use the expensive parent for synthesis, decisions, edits and verification—not broad retrieval. After at most one or two obvious anchor reads, delegate early when ownership remains unknown, the chain crosses modules/lifecycle stages, or the next parent step would be broad Grep/Read. For HIGH/CRITICAL, satisfy required independent exploration **early** once the question and bounded starting scope are stable.

Choose the cheapest matching role: `source_locator` for symbols/callers/tests, `context_scout` for cross-module state/data flow, `test_scout` for test evidence, `framework_scout` only for framework/ownership semantics. **Default to one Scout, not fan-out**; add another only for `NEED_CONTEXT`, an independent search line, or evidence conflict. After a Scout completes, do not repeat its broad search in the parent.

Task authorization stays explicit. When policy allows, authorize a same-tier or cheaper read-only Scout with `--decision optional|required`; stronger-than-parent models need elevated authorization. Use `delegate_once.py` for request -> Provider runtime -> attestation -> record. Only Sitter-launched output satisfies governed Scout/Review gates; casual native output is advisory. Load delegation/model-budget references only when active.

## Human decisions

HIGH/CRITICAL work must expose genuine forks before choosing algorithm/product semantics, state ownership, path behavior, coordinates/sign/units, compatibility/fallback policy, responsibility boundaries, acceptance behavior, or accuracy/performance tradeoffs. Batch real decisions; do not interrupt for routine details implied by accepted design. Resolved user decisions are authoritative state.

## Candidate Readiness and closure

Authoritative lifecycle:

```text
proposed -> designed -> approved -> implementing
-> candidate-review -> verifying -> syncing -> ready-to-archive -> archived
```

V6.3 compresses Agent-visible orchestration. Do **not** poll status, hand-edit lifecycle state, or stitch low-level record/finalize/render/advance commands when a high-level transaction owns the sequence.

Before production edits, finish Design/Tasks, set an explicit Change Budget, resolve or rule out material Human Decisions, and define `readiness.assurance_class` plus criteria. Then:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot begin-implementation <change-id>
```

`begin-implementation` owns the pre-implementation transitions, freezes the Readiness Contract immediately before implementation, and ends at `implementing`. HIGH/CRITICAL repository changes fail closed until explicit human approval exists; only then may the caller use `--approved-by <identity>`. Never invent approval provenance. `freeze-readiness` remains recovery/compatibility, not the normal V6.3 path.

Never weaken criteria after seeing results. `standard` may use focused deterministic evidence; `behavioral` needs integration/representative external behavior; `numerical` needs representative-case, benchmark, or analytical-check. Unit tests alone cannot make a numerical Change Candidate Ready.

Stage batch files under `changes/active/<change-id>/` so they remain Harness state rather than project-root production artifacts. Structured `change.yaml` values remain authoritative.

After implementation and required engineering checks actually run, write all Readiness results to one YAML/JSON batch and run:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot prepare-candidate <change-id> `
  --readiness-batch <readiness-results.yaml>
```

The batch carries real criterion IDs, results, commands/entries, evidence, and optional observations. `prepare-candidate` validates the whole batch before mutation, binds one Production Snapshot, finalizes readiness/test hygiene, checks Change Budget before Reviewer cost, runs the Provider-bound FULL Reviewer with runtime attestation, rechecks production, records proof, and advances only on PASS/WARN.

A review BLOCK with remediation `implementation` stays inside approved semantics. `awaiting-production-design` means new scope/semantics require the human checkpoint. Deep review is exceptional. `finalize_tests.py` remains a recovery/compatibility entrypoint, not the normal success path.

On success `prepare-candidate` stops at `candidate-review`. Summarize Readiness, representative external/numerical evidence, and limitations; ask the user to approve or request changes; then **STOP**. While acceptance is pending, do not run final/full regression, Knowledge, Learning closeout, archive, or another Reviewer.

Record acceptance only through Harness:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot user-review <change-id> `
  --decision approved|changes-requested|not-required --evidence "..."
```

`not-required` needs explicit user evidence; the Agent may not choose it for convenience. `changes-requested` returns to implementation and stales Readiness. `approved` permits Final Verification.

After approval, actually run required Final Verification, put all results in one batch, then run:

```powershell
python "$Runtime\harness.py" --project $ProjectRoot complete-after-approval <change-id> `
  --verification-batch <final-verification.yaml>
```

`complete-after-approval` validates before lifecycle mutation and stops on engineering failure. On success: zero durable Knowledge is explicitly deferred; real Knowledge candidates stop for authority; cleanup is checked but never silently deleted; zero/ordinary Learning is assessed automatically; mature durable Learning candidates stop for individual curation; the Task completes only when no active Investigation or non-archived Change remains.

If it returns `governance-closure-pending`, resolve only that blocker and rerun `complete-after-approval <change-id>` without a verification batch. Do not redo valid engineering verification merely because Knowledge, cleanup, Learning, or other Task work remains.

Low-level V6.2 commands (`freeze-readiness`, `record-readiness`, `finalize-readiness`, `review --run`, `record-verification`, `defer-knowledge`, `finalize-archive-cleanup`, `render`, `advance`, `archive`) remain recovery/compatibility APIs for history, diagnosis, or unsafe transaction recovery; they are not the normal success path.

## Learning and completion

Do not pull LOW work into the Work Graph merely for Learning. Governed Tasks retain Learning/completion obligations. Ordinary observations do not create a human stop; mature durable candidates still require user curation. Completion requires Investigations concluded, Changes archived/abandoned, delegations/escalations resolved, temporary artifacts gone, and Learning closeout satisfied.

Use `work.py task-status`, `work.py validate`, `harness.py status`, and `harness.py validate-change` for diagnosis/recovery, not routine polling.

## Progressive disclosure

Do not preload references. Load only what the current action needs: risk; Investigation; implementation scope; delegation/model budget; readiness/testing/review/human decisions; Knowledge/Learning/archive. Do not reload references or rerun status/intake merely to reconfirm unchanged facts.
