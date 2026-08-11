# V6 Context Capability and Human Decision Authority

V6 develops Sitter around the two long-term design invariants stated in the repository README:

1. **Context Capability**
2. **Human Decision Authority**

LOW Fast Path remains an important constraint, not a third top-level goal.

This document describes the V6 mechanisms that serve those invariants and, equally importantly, the mechanisms V6 deliberately does not introduce.

## 1. Context Capability

### 1.1 Within-task exploration

Engineering Scouts remain ordinary Provider-neutral delegation roles:

- `source_locator`
- `context_scout`
- `test_scout`
- `framework_scout`

Their requests use `inheritance=none`. Parent hypotheses, desired outcome, and proposed patch are withheld from the child request so that an apparently strong parent hypothesis does not silently become the Scout's premise.

V6 does **not** require a fixed number of Scouts for every HIGH task. The governance rule is evidence-oriented: where independent exploration is required, at least one relevant independent exploration must actually complete before a governed Investigation can create final truth.

For HIGH/CRITICAL Investigation work, the parent may still:

- collect evidence;
- record open/supported/refuted claims;
- run discriminating experiments;
- refine hypotheses.

Before required independent exploration completes, it may not:

- accept an engineering decision;
- conclude the Investigation;
- pivot the Investigation into a production Change.

This is the Investigation counterpart of the existing HIGH/CRITICAL Change execution gate; V6 reuses the same delegation evidence rather than creating another governance system.

### 1.2 Read-only action dashboard

`work.py task-status` computes an action dashboard without mutating Task state. It exposes:

- current and peak risk;
- whether delegation is required;
- planned and completed delegation;
- `ACTION REQUIRED` state;
- allowed next actions;
- blocked next actions.

The dashboard never creates a Scout and never changes the work graph.

### 1.3 Bounded cross-session continuity

V6 adds a compact Active Task Index at:

```text
.agent-work/_context/active-tasks.yaml
```

Task creation registers active governed work; Task completion removes it. The index has a hard bounded size.

SessionStart reads **only this index**. It does not glob `.agent-work`, scan archived Tasks, or load Project Knowledge. The startup payload records that archived history was not scanned and durable memory was not loaded.

A unique active Task creates a resume hint. Multiple active Tasks create no automatic selection: the user's continuation request still has to match the subject or Task identity.

The index is a continuity hint, not an implicit router. An unrelated LOW request remains a LOW request even when active governed work exists.

### 1.4 Project Memory is an evolution of Learning and Knowledge

V6 does not introduce a second Memory database or governance layer.

The existing flow remains:

```text
Task experience -> Learning candidate -> human curation -> Project Knowledge
```

V6 extends the durable Knowledge vocabulary with:

- stable reusable Project Knowledge;
- Open Thread;
- Watchpoint.

Task history that has no durable value remains cold history. Most Tasks may close with no durable memory.

Open Threads and Watchpoints require explicit trigger metadata. Keyword resemblance alone is not enough to surface them.

### 1.5 Version-aware code-bound memory

A code-bound durable entry carries both:

- `source_commit`
- a coarse `validity_surface`

Freshness is evaluated lazily with Git only when the entry is recalled.

The vocabulary is intentionally limited:

- `fresh`: the source commit is an ancestor and no invalidating committed or working-tree change was detected on the validity surface;
- `suspect`: a related committed or working-tree change intersects the validity surface;
- `unknown`: ancestry cannot establish that the memory belongs to the current line of development.

`fresh` means only that no invalidating change was detected. It does **not** mean the fact was re-verified.

` suspect` and `unknown` entries are historical leads, never current facts.

### 1.6 Conflict and supersession

Entries sharing a `memory_key` without an explicit supersession relation are a conflict. Conflicting entries are recalled only as historical leads.

V6 never automatically merges conflicting memory and never rewrites the old entry during promotion. A replacement is added only after explicit human curation and an explicit `supersedes` relation. The historical entry remains available for provenance.

### 1.7 Memory Scout

`memory_scout` is a low-cost, read-only delegation role for historical context recovery. Its job is limited to:

- retrieving the already-selected bounded recall packet;
- preserving freshness/conflict labels;
- compressing and presenting historical context;
- identifying missing historical context.

Deterministic code performs ranking and Git freshness before the Agent starts. The Memory Scout does not scan archived Tasks and does not run Git itself.

The Memory Scout may not form a new engineering conclusion. It therefore does **not** satisfy the HIGH/CRITICAL independent engineering exploration gate.

If deterministic recall finds no relevant durable memory, no Memory Scout is launched.

## 2. Human Decision Authority

### 2.1 Material forks

Sitter distinguishes evidence-resolvable engineering questions from material forks with multiple reasonable semantics. Material forks include areas such as:

- algorithm and numerical semantics;
- state ownership/lifecycle;
- sign, unit, coordinate, and result interpretation;
- compatibility and fallback behavior;
- responsibility boundaries;
- precision/performance trade-offs.

Agents investigate and recommend first. When evidence does not objectively produce a unique answer, the user's explicit choice is authoritative.

### 2.2 Authoritative state

The existing `human_in_loop.decisions` structure remains the source of truth. V6 does not introduce a parallel Decision object.

A resolved decision preserves both history and authority:

- options considered;
- Agent recommendation;
- **user decision**;
- durable evidence of that decision.

The recommendation remains historical information. The user decision is the downstream authority.

Investigation-to-Change propagation preserves the resolved human decision state. Review snapshots freeze a projection containing the user decision and evidence, not the Agent recommendation. If the authoritative decision changes after review begins, that review becomes stale.

Durable Knowledge promoted from work with resolved human decisions carries an authority digest. A candidate bound to an obsolete authority digest cannot silently become current Knowledge.

### 2.3 Human-curated closeout

Mature durable candidates are curated individually. When K01, O01, and W01 all exist, one bulk approval is not accepted as three decisions.

The user may independently approve, defer, or dismiss each candidate. Promotion is allowed only for an individually approved candidate.

Conflicting durable memory requires explicit supersession or re-verification. The Agent cannot choose the winner by silently merging the histories.

### 2.4 Human Authority is not Human Interruption

LOW deterministic work remains outside the governed work graph unless another independent reason requires governance. Existing active Tasks, Project Knowledge, or keyword similarity do not turn an unrelated LOW request into a Task, Memory Scout run, or human checkpoint.

## 3. Runtime boundaries

V6 distinguishes three forms of evidence:

1. **L1/L2 deterministic evidence** proves schema, transaction, gate, projection, freshness, curation, and cost behavior.
2. **L3 real runtime evidence** proves a fresh Codex/Claude host session actually loaded the project, executed SessionStart, ran real readonly children, delivered their results to the parent, and produced valid Provider attestation.
3. **L4 model behavior evidence** compares the baseline and candidate using identical controls and validates real exploration evidence.

Synthetic transcript tests and fake clients remain useful L1 tests but do not count as L3 or L4 success.

## 4. SessionStart runtime evidence

Normal SessionStart remains read-only and produces no persistent smoke artifact.

For an explicit L3 acceptance run only, the environment variable:

```text
SITTER_SESSION_START_EVIDENCE_DIR
```

may point to a project-local evidence directory. The shared SessionStart hook then records the exact bounded payload and injected context. Paths outside the project are rejected. This opt-in path exists solely so a real fresh runtime can prove that SessionStart actually fired; it is not enabled during normal work.

## 5. Deliberate non-goals

V6 does not add:

- RAG;
- embeddings;
- a vector database;
- archive scanning at every SessionStart;
- automatic rewriting of historical memory;
- automatic merge of conflicting memory;
- a fixed multi-Scout fan-out for every HIGH task;
- a multi-agent scheduler;
- broad Read/Grep/Bash/Edit hook interception;
- a second router or second governance system;
- implicit Governor invocation.

## 6. Acceptance entrypoints

Deterministic candidate status:

```bash
python scripts/acceptance/v6-candidate-status.py
```

Real Provider runtime smoke preparation/verification:

```bash
python scripts/acceptance/v6-runtime-smoke.py prepare <project> --provider codex
python scripts/acceptance/v6-runtime-smoke.py verify <project>

python scripts/acceptance/v6-runtime-smoke.py prepare <project> --provider claude
python scripts/acceptance/v6-runtime-smoke.py verify <project>
```

Same-model C1 A/B preparation/scoring:

```bash
python scripts/acceptance/v6-ab-benchmark.py prepare <root> --model-label <exact-model-control>
python scripts/acceptance/v6-ab-benchmark.py score <root>
```

`prepare` never executes a model and can never produce a passing L3/L4 result. The actual fresh sessions are intentionally external to normal CI.
