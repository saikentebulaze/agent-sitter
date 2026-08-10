# Dynamic Risk / Adaptive Governance — Local Codex & Claude Acceptance

Use this template only after the automated GitHub test suite is green on Ubuntu and Windows. Run the scenarios in a disposable or controlled real Sitter worktree after installing/updating this Harness branch.

Record actual commands, Task/Change refs, Agent runtime evidence, and observations. Do not infer success from configuration files alone.

## Environment

- Harness commit:
- Sitter worktree:
- Date:
- Codex CLI/version:
- Claude Code version:
- Installed providers:
- Notes:

---

## A. Projection / installation checks

### A1. Codex adaptive projection

Verify after install/update:

- generated `AGENTS.md` points to the lightweight router;
- `.agents/skills/change-governor/agents/openai.yaml` exists;
- Governor `allow_implicit_invocation` is `false`;
- Codex config and Agent TOMLs retain their expected model/effort/sandbox behavior;
- no unmanaged user Skill files are overwritten/deleted.

Result: PASS / FAIL
Evidence:

### A2. Claude adaptive projection

Verify:

- `CLAUDE.local.md` points to the same lightweight routing semantics;
- `.claude/skills/*` wrappers no longer force the full packaged Skill before unrelated LOW work;
- governed settings, hooks, scoped Agent tools, memory/background isolation, and runtime attestation configuration remain present.

Result: PASS / FAIL
Evidence:

---

## B. LOW Fast Path

Use one small deterministic repository request, for example an explicit comment/naming cleanup plus an existing focused test, or run an already-existing calculation/test case whose result is expected to be normal.

Expected:

- no `.agent-work/<new-task>` is created;
- no Production Change or Investigation is created;
- no Learning intake/closeout is run;
- no Scout is launched merely for ceremony;
- no long plan/design/proposal is written;
- the full Governor / unrelated references are not repeatedly loaded;
- Agent performs locate -> act/run -> focused verification -> concise result.

Codex result: PASS / FAIL
Codex evidence / observed Skill reads:

Claude result: PASS / FAIL
Claude evidence / observed Skill reads:

---

## C. LOW -> HIGH automatic promotion

Start with a request that appears simple, such as running an existing comparison case. Then expose an unexpected result that requires a production Change -> Investigation pivot or otherwise introduces state/lifecycle/path/numerical uncertainty.

Expected once formal governance is created:

```yaml
work_risk:
  current:
    semantic: high   # or critical if justified
  peak:
    semantic: high   # or critical
```

Also verify:

- the risk increase happens because facts changed, not because the initial prompt looked technical;
- associated Production Change assurance is raised appropriately;
- `delegation.decision` becomes required after HIGH/CRITICAL exposure;
- while the Change is paused under Investigation, the Scout completion gate does not prevent investigation work itself;
- independent read-only exploration completes before the Change resumes active implementation/verification.

Codex result: PASS / FAIL
Task / Change / delegation refs:
Runtime attestation evidence:

Claude result: PASS / FAIL
Task / Change / delegation refs:
Runtime attestation evidence:

---

## D. Investigation -> Change assurance propagation

Use an Investigation whose confirmed production semantics reach HIGH or CRITICAL before pivoting to a new Change.

Expected:

- accepted Decision is evidence-backed;
- `pivot-to-change` creates the Change through the existing Work Graph;
- new `Change.risk` is not below the converged Task current risk;
- Task peak remains the historical maximum;
- Provider binding remains unchanged for the Task.

Codex result: PASS / FAIL
Evidence:

Claude result: PASS / FAIL
Evidence:

---

## E. HIGH -> LOW cleanup without assurance loss

After a HIGH/CRITICAL production Change has stable design, implementation, and core verification, reduce current work risk for a clearly bounded tail such as debug-log deletion, test cleanup, naming, comments, or documentation sync.

Expected:

```text
Task current risk -> LOW (or MEDIUM)
Task peak risk    -> remains HIGH/CRITICAL
Change risk       -> remains HIGH/CRITICAL assurance as applicable
```

Also verify:

- cleanup does not repeat completed Scout exploration;
- no new long planning cycle is created solely because the Task was historically HIGH;
- final independent review still runs at the Change assurance level.

Codex result: PASS / FAIL
Evidence:

Claude result: PASS / FAIL
Evidence:

---

## F. Follow-up requirement triggers incremental reassessment

During an otherwise bounded task, add a follow-up requirement such as:

> this state must also survive into the next step/load case

or another requirement that materially introduces path/state semantics.

Expected:

- Agent reassesses the delta, rather than restarting every governance ritual from zero;
- risk increases when appropriate;
- heavy governance is loaded only after the material change;
- already-known status/references are not reread merely to reconfirm unchanged facts.

Codex result: PASS / FAIL
Evidence:

Claude result: PASS / FAIL
Evidence:

---

## G. One-command managed Scout

For an authorized governed Task, run the managed facade:

```powershell
python ".harness\sitter\runtime\delegate_once.py" <task-id> --project . `
  --role context_scout `
  --target-type investigation --target-ref <inv-id> `
  --purpose "..." --question "..." --decision-supported "..." `
  --include <scope>
```

Expected:

- Task-level authorization is still required first;
- a real frozen request packet is created;
- Task orchestrator Provider decides Codex vs Claude runtime;
- actual read-only/tool-restricted execution occurs;
- actual attestation/evidence files are generated;
- result is recorded through the normal delegation transaction;
- structured `NEED_CONTEXT` becomes `need-context` rather than false completion;
- runtime failure never produces a completed delegation.

Codex result: PASS / FAIL
Delegation / attestation refs:

Claude result: PASS / FAIL
Delegation / attestation refs:

---

## H. Test Hygiene

During governed development, create/register a development-only diagnostic test or probe. Resolve the core issue, then run Test Finalization.

Expected:

- leaving the temporary test in place causes finalization to fail;
- deleting it records `development-only-removed`;
- deliberately retaining a real regression test requires a durable rationale;
- pre-existing dirty user test changes can be marked `pre-existing-not-owned` and are not deleted;
- success writes `test-finalization.yaml`;
- manually setting only `test_cleanup_complete: true` is insufficient for a protocol-1 Change.

Codex result: PASS / FAIL
Evidence:

Claude result: PASS / FAIL
Evidence:

---

## I. Review assurance

After HIGH/CRITICAL work has entered LOW cleanup, create the independent review request.

Expected:

- review packet contains `assurance_snapshot` matching `Change.risk`;
- current Task risk does not reduce reviewer requirement;
- changing Change assurance after review starts makes the request stale;
- normal review remains the configured Maintainer Reviewer unless a separate deep-review escalation is justified.

Codex result: PASS / FAIL
Evidence:

Claude result: PASS / FAIL
Evidence:

---

## J. Regression / runtime proof

Confirm the behavior optimization did not weaken V5 runtime guarantees.

Codex:

- model/tier/effort matches requested profile;
- read-only sandbox for governed child;
- independent context / expected parent-thread relation;
- runtime attestation source/collector remains accepted.

Claude:

- Read/Grep/Glob scoped child behavior;
- tool-restricted write isolation;
- persistent context disabled;
- governed hooks/transcript evidence present;
- forbidden continuity/background/worktree behavior is not silently reintroduced.

Codex result: PASS / FAIL
Claude result: PASS / FAIL
Evidence:

---

# Final verdict

- [ ] LOW work is materially faster/lighter than V4.1/V5-B behavior.
- [ ] LOW tasks do not acquire governance artifacts merely for ceremony.
- [ ] Risk rises automatically/explicitly when engineering facts expand.
- [ ] Current risk can fall after uncertainty closes.
- [ ] Peak risk and production assurance are not lost during cleanup.
- [ ] HIGH work uses independent exploration before active production implementation.
- [ ] Scout execution is easier to invoke without weakening attestation.
- [ ] Temporary tests have an explicit cleanup action and evidence.
- [ ] Final review remains assurance-driven.
- [ ] Codex repeated heavy Skill loading is visibly reduced in ordinary LOW turns.
- [ ] Claude retains its real runtime safety differences.
- [ ] No significant Codex or Claude V5-B runtime regression observed.

Final verdict: PASS / FAIL

Blocking findings:

Follow-up improvements (non-blocking):
