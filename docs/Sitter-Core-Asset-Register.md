# Sitter Core Asset Register

This register classifies Sitter concepts by the value they protect rather than by their current Python module or YAML location.

The purpose is to distinguish the essence of Sitter from mechanisms that can be simplified, replaced, derived, or retired.

## 1. Classification

| Class | Meaning | Default treatment |
| --- | --- | --- |
| `CORE INFORMATION` | Engineering information that cannot be safely reconstructed after it is lost | Preserve durably |
| `CORE GUARANTEE` | A behavior or assurance property Sitter must continue to provide | Never weaken silently |
| `CORE MECHANISM` | A current mechanism that materially implements a core guarantee | Refactor only with equivalent replacement |
| `REPLACEABLE MECHANISM` | A useful implementation that is not itself part of the long-term contract | May merge, replace, or simplify |
| `DERIVED STATE` | State that can be safely reconstructed from canonical facts | Prefer derivation over persistence |
| `COMPATIBILITY / CEREMONY` | Historical compatibility, redundant orchestration, or Agent-facing maintenance burden | Prefer retirement or hiding from the normal path |

The governing simplification rule is:

> **Preserve Information. Preserve Guarantees. Compress Ceremony.**

---

## 2. Work State

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| Task identity and objective | CORE INFORMATION | Very high | Stable container for long-running work |
| Current focus | CORE INFORMATION | Very high | Allows a new session to recover the active work item |
| Task work-item relations | CORE INFORMATION | Very high | Preserves the relationship between Investigations and Changes |
| Investigation | CORE INFORMATION | Very high | Stabilizes what is known before deciding what to change |
| Production Change | CORE INFORMATION | Very high | Stabilizes intended production behavior change and assurance |
| Pivot / revision relations | CORE INFORMATION | Very high | Preserves why work moved between Investigation and Change |
| Risk history | CORE INFORMATION | High | Records uncertainty history and supports adaptive execution |
| Task timeline | CORE INFORMATION | High | Useful for continuity and audit, but may be represented differently |
| Exact current lifecycle state | CORE INFORMATION | High | Current state matters; the particular number of lifecycle states does not |

### Interpretation

The `Task / Investigation / Production Change` separation is a core conceptual asset:

- Task is the stable engineering-work container;
- Investigation stabilizes questions, claims, evidence, experiments, decisions, and unknowns;
- Production Change stabilizes production intent, implementation, assurance, review, and closure.

The current exact lifecycle choreography is not sacred. Intermediate states may be merged if the same facts and guarantees remain reconstructable.

---

## 3. Engineering Evidence

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| Claim | CORE INFORMATION | Very high | Makes engineering conclusions explicit and reviewable |
| Supporting / contradicting evidence | CORE INFORMATION | Very high | Separates fact from Agent plausibility |
| Experiment records | CORE INFORMATION | Very high | Preserves discriminating investigation evidence |
| Remaining unknowns | CORE INFORMATION | Very high | Prevents unresolved uncertainty from disappearing between sessions |
| Accepted engineering decisions | CORE INFORMATION | Very high | Preserves the conclusion and its basis |
| Change Budget | CORE INFORMATION / GUARANTEE | Very high | Bounds authorized production/test scope |
| Readiness criteria | CORE INFORMATION / GUARANTEE | Very high | Defines what must be proven before Candidate review |
| Readiness results | CORE INFORMATION | Very high | Records the actual pre-acceptance evidence |
| Numerical representative / benchmark / analytical evidence requirement | CORE GUARANTEE | Very high | Prevents unit-only numerical acceptance |
| Test finalization evidence | CORE INFORMATION / GUARANTEE | High | Prevents development-only test debris and unclassified test changes |
| Final Verification evidence | CORE INFORMATION | Very high | Proves final behavior after user acceptance |
| Independent Review output | CORE INFORMATION | Very high | Preserves an independent assessment rather than parent reinterpretation |
| Review snapshot / request / attestation lineage | CORE INFORMATION / GUARANTEE | Very high | Makes review reproducible, stale-detectable, and runtime-proven |

### Replaceable parts

Markdown projections such as `verification.md`, archive summaries, dashboards, and status summaries are views when their structured evidence already exists. They may be rendered lazily or regenerated.

---

## 4. Human Authority

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| User decision | CORE INFORMATION | Very high | Final authority for material engineering forks |
| Decision evidence | CORE INFORMATION | Very high | Makes authority durable and auditable |
| Options considered | CORE INFORMATION | High | Preserves context for later reconsideration |
| Agent recommendation | Historical information | High | Useful context, but not authority |
| Human decision digest / projection | CORE MECHANISM | Very high | Binds downstream state to the authoritative decision |
| Downstream stale detection after authority change | CORE GUARANTEE | Very high | Prevents reviewed or remembered state from silently contradicting the user |

The distinction `Agent recommendation != user decision` is non-negotiable.

---

## 5. Context Infrastructure

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| Independent Scout capability | CORE MECHANISM | Very high | Reduces parent early-convergence and missing-context failures |
| `inheritance=none` or equivalent independent context contract | CORE GUARANTEE | Very high | Prevents parent hypothesis contamination where independence matters |
| Frozen role-specific Context Capsule | CORE MECHANISM | Very high | Keeps child context bounded and auditable |
| `NEED_CONTEXT` bounded supplement | REPLACEABLE / CORE mechanism | High | Allows narrow expansion without abandoning independence |
| Active Task Index | CORE MECHANISM | Very high | Enables bounded cross-session discovery without history scanning |
| SessionStart continuity injection | CORE MECHANISM | Very high | Makes active governed work recoverable in a fresh host session |
| Task / Investigation durable files | CORE INFORMATION | Very high | Long-task memory independent of conversation context |
| Learning observations | CORE INFORMATION | Very high | Preserves reusable experience before curation |
| Learning candidate | CORE INFORMATION | High | Stages possible reusable knowledge without prematurely promoting it |
| Durable Project Knowledge | CORE INFORMATION | Very high | Carries useful context across Tasks |
| Open Thread / Watchpoint semantics | CORE INFORMATION | High | Preserves unfinished or conditional historical context |
| Memory key and supersession | CORE INFORMATION / GUARANTEE | Very high | Prevents silent merging of conflicting history |
| Code-bound memory source commit / validity surface | CORE INFORMATION | Very high | Enables version-aware historical context |
| Memory freshness classification | CORE GUARANTEE | Very high | Keeps stale memory from becoming current truth |
| Memory Scout | REPLACEABLE MECHANISM | Medium-high | Useful low-cost presentation/filtering mechanism, but not the memory itself |

### Core distinction

Memory is not one database or one file. Its core value is:

- current Task work survives session loss;
- active work is rediscovered cheaply;
- durable historical context is retrieved progressively;
- stale or conflicting history is treated conservatively.

Any implementation preserving those guarantees may replace current file formats or helper scripts.

---

## 6. Runtime Proof

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| Task orchestrator Provider binding | CORE INFORMATION | Very high | Defines the runtime authority for one Task |
| Provider-neutral Runtime Contract | CORE GUARANTEE | Very high | Keeps Governance Core independent of vendor-specific mechanics |
| Provider-specific role/model mapping | REPLACEABLE MECHANISM | High | Needed, but model names and selectors may evolve |
| Actual model/profile runtime proof | CORE GUARANTEE | Very high | Prevents configured intent from being mistaken for actual execution |
| Read-only / permission enforcement | CORE GUARANTEE | Very high | Keeps governed child roles within their authority |
| Immutable request / attempt | CORE GUARANTEE | Very high | Prevents after-the-fact mutation of what a child reviewed |
| Runtime attestation | CORE INFORMATION / GUARANTEE | Very high | Proves actual execution type, environment, and binding |
| Stale detection | CORE GUARANTEE | Very high | Prevents output from obsolete inputs from entering current truth |
| Execution type truthfulness | CORE INFORMATION / GUARANTEE | Very high | Native, managed, fallback, or Provider-specific modes must not be mislabeled |

Provider-neutral Core must not flatten real Codex and Claude runtime differences merely to make APIs look uniform.

---

## 7. Candidate Assurance

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| Candidate Readiness boundary | CORE GUARANTEE | Very high | Prevents premature user review |
| Assurance-class-dependent evidence requirement | CORE GUARANTEE | Very high | Keeps proof proportional to the type of engineering change |
| Independent Candidate Reviewer | CORE MECHANISM | Very high | Detects parent blind spots in Architecture, Scope, and Numerical Evidence |
| Reviewer independence and runtime proof | CORE GUARANTEE | Very high | Prevents parent self-review or fabricated review metadata |
| Candidate Human Stop | CORE GUARANTEE | Very high | Preserves explicit acceptance before final closure where required |
| Post-approval Final Verification | CORE GUARANTEE | Very high | Separates readiness from final assurance |
| Test hygiene / scope preflight before Reviewer | CORE GUARANTEE | High | Avoids spending review budget on an already-invalid Candidate |

The exact command sequence and number of lifecycle states are replaceable. The assurance properties are not.

---

## 8. Adaptive Cost Assets

| Asset | Class | Protection | Why it matters |
| --- | --- | --- | --- |
| `current` work risk | CORE INFORMATION / MECHANISM | High | Controls present execution intensity |
| `peak` work risk | CORE INFORMATION | High | Preserves historical uncertainty |
| Production Change assurance floor | CORE GUARANTEE | Very high | Prevents execution downshift from lowering final proof |
| Provider-neutral capability grade | REPLACEABLE / CORE mechanism | High | Enables cheap-vs-strong role assignment without Core model names |
| Role-specific model/reasoning configuration | REPLACEABLE MECHANISM | High | Implements Minimum Sufficient Capability |
| Deterministic-before-model routing | CORE IMPLEMENTATION PRINCIPLE | High | Avoids paying model cost for mechanical facts |
| Evidence-triggered escalation | CORE IMPLEMENTATION PRINCIPLE | High | Prevents over-provisioning model strength and context |
| Stop-when-sufficient behavior | CORE IMPLEMENTATION PRINCIPLE | High | Prevents open-ended extra governance after requirements are met |

Cheap subagents are one implementation of this principle. They are not themselves a core goal.

---

## 9. Workspace Semantic Surface

Sitter must reason about changed files by engineering role rather than extension.

The minimum useful semantic roles are:

| Surface | Meaning | Production semantics | Assurance relevance |
| --- | --- | --- | --- |
| `production` | Source, configuration, schema, build behavior, durable production-facing tests, or other files that change governed behavior | Yes | Yes |
| `evidence` | Benchmark, reference, comparison, analytical, or other artifacts used to prove a requirement | No direct production behavior | Yes |
| `task-output` | User-requested reports, exports, generated analysis products, or other auxiliary outputs | Usually no | Usually no unless explicitly referenced as evidence |
| `harness` | Task, Change, Investigation, Review, Learning, Knowledge, and installed Harness state | No | Governed by Harness-specific contracts |

Classification is by intent and authority, not by `.xlsx`, `.csv`, `.md`, `.json`, `.png`, or any other extension.

Safe precedence should remain conservative:

1. known Harness-owned path -> `harness`;
2. Change-owned production/test surface -> `production`;
3. explicit readiness/verification/review evidence reference -> `evidence`;
4. explicit exact Task output declaration -> `task-output`;
5. unknown -> `production`.

A tracked production source must not be reclassified as an auxiliary output merely to avoid Candidate staleness.

---

## 10. Known Derived State Candidates

These are not core assets merely because they currently exist in YAML.

| Current state | Classification | Direction |
| --- | --- | --- |
| `completion.implementation_complete` | DERIVED STATE | Derive from canonical readiness/lifecycle facts |
| `completion.ready_for_user_review` | DERIVED STATE | Derive from Candidate lifecycle and gate state |
| `methodology.test_cleanup_complete` | DERIVED STATE candidate | Prefer deriving from authoritative test-finalization evidence |
| aggregate review status | DERIVED STATE candidate | Can be derived from review axes if compatibility allows |
| aggregate verification status | DERIVED STATE candidate | Can be derived from structured final results if compatibility allows |
| `ready-to-archive` | REPLACEABLE lifecycle state | Evaluate whether it is only an Archive transaction precondition |
| generated status Markdown | Projection | Regenerate on demand |
| `verification.md` | Projection | Lazy deterministic rendering |
| `archive-summary.md` | Projection | Lazy deterministic rendering |
| empty `knowledge-sync.md` | Ceremony / Projection | Create only when a Knowledge candidate or review artifact exists |

Derived-state cleanup should be incremental to avoid turning one release into an unnecessary schema migration project.

---

## 11. Compatibility and Ceremony Debt Candidates

These mechanisms are not part of Sitter's essence and should be inventoried for retirement or removal from the normal path:

- Agent-facing low-level lifecycle commands when a deterministic coordinator can own the sequence;
- repeated `status` polling to discover a state Harness just wrote itself;
- repeated Git workspace scans inside one high-level transaction;
- Python subprocess validators that can safely call the same validation logic in-process;
- version-stacked CLI facades such as `harness.py -> _harness_v62_impl.py -> _harness_impl.py`;
- facade/monkeypatch layering such as `work.py -> _work_impl.py` when callers can migrate to the authoritative implementation;
- Learning compatibility wrappers whose only purpose is historical reference parsing;
- old Provider compatibility re-exports after all real callers migrate;
- legacy Scout entrypoints after the Provider-bound governed path fully covers their use case;
- keyword-only Knowledge hints that do not decide truth, promotion, or durable-memory semantics.

Compatibility debt should be removed only after identifying actual external/internal consumers. It should not be preserved forever merely because it once existed.

---

## 12. Simplification Safety Test

Before deleting or merging any state, mechanism, or command, ask:

1. Can a fresh host session still recover the active long-running Task safely?
2. Are Investigation claims, evidence, experiments, decisions, and unknowns still recoverable?
3. Are material user decisions still authoritative downstream?
4. Is historical memory still freshness-checked and conflict-aware?
5. Is required Scout/Reviewer independence preserved?
6. Is Candidate numerical assurance unchanged?
7. Is Candidate Human Stop unchanged where required?
8. Is final verification still distinct from readiness?
9. Is Provider runtime proof still truthful?
10. Did the simplification merely remove Agent-visible ceremony or duplicated state?

If the first nine remain true and the tenth is true, the change is a strong complexity-paydown candidate.
