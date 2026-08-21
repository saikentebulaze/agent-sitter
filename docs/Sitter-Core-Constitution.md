# Sitter Core Constitution

## 1. Purpose

Sitter exists to improve the effectiveness and reliability of coding Agents working in complex, long-lived repositories without replacing the engineer responsible for the system.

Task, Investigation, Production Change, Scout, Review, Learning, Memory, Readiness, Provider runtimes, and lifecycle commands are mechanisms. They are not goals by themselves.

The long-term top-level goals remain exactly two:

1. **Context Capability**
2. **Human Decision Authority**

`LOW Fast Path` is a design constraint, not a third top-level goal.

A new top-level goal should be introduced only when long-term use demonstrates an independent need that cannot be derived from these two goals.

---

## 2. Context Capability

Context Capability means increasing the probability that an Agent has the **right, sufficiently complete, and current context** before making an engineering conclusion or modifying a repository.

The objective is not to maximize context volume. More context can increase cost and can also introduce stale, irrelevant, or misleading information.

Sitter therefore prefers:

- progressive disclosure over eager loading;
- bounded exploration over indiscriminate repository scanning;
- independent exploration over parent-hypothesis inheritance where independence matters;
- distilled persistent state over conversation transcripts;
- current code and new evidence over historical memory when they disagree;
- version-aware memory over blindly trusted historical knowledge;
- low-cost retrieval and filtering when stronger reasoning is unnecessary.

### 2.1 Spatial context

Within a task, focused readonly roles such as Locator, Context Scout, Test Scout, and Framework Scout exist to reduce early convergence and uncover relevant code, tests, interfaces, ownership, and lifecycle boundaries that the parent may miss.

The invariant is not a fixed Scout count or a fixed role list. The invariant is **bounded independent exploration when the decision requires it**.

### 2.2 Temporal context

Long-running work must survive context-window loss and new sessions.

Sitter therefore preserves durable Task, Investigation, Change, decision, evidence, Learning, Knowledge, and continuity state on disk. Session startup should recover only bounded active-work hints first, then progressively disclose the selected Task and relevant durable memory.

Historical memory is context, not unquestionable truth. Current code and new evidence remain authoritative.

---

## 3. Human Decision Authority

Agents should investigate first. They should locate code, collect evidence, run experiments, compare alternatives, explain trade-offs, and make recommendations.

When evidence does not objectively determine one answer and the remaining choice materially affects engineering semantics, the engineer retains final authority.

Typical material forks include:

- algorithm and numerical semantics;
- state ownership and lifecycle;
- sign, unit, coordinate, and result interpretation;
- compatibility and fallback behavior;
- responsibility boundaries;
- precision versus performance;
- architecture where multiple alternatives remain valid.

A resolved user decision becomes authoritative project state. Downstream Investigation, Design, Change, Implementation, Verification, Review, and Durable Memory must remain consistent with it unless the decision is explicitly reconsidered.

**Human Authority is not Human Interruption.** Routine deterministic and LOW-risk work should remain fast and autonomous.

---

## 4. Derived Engineering Invariants

The two top-level goals imply the following long-term invariants.

### 4.1 Evidence over plausibility

An Agent's confidence or a locally plausible patch is not engineering proof. Material conclusions must be traceable to evidence, experiments, authoritative decisions, review, or verification appropriate to the assurance requirement.

### 4.2 Persistent state over conversation

Critical engineering facts must not depend on one chat transcript still being available. If losing the current conversation would destroy necessary reasoning, evidence, decisions, or task continuity, the required state is not durable enough.

### 4.3 Progressive disclosure

Context should be loaded when the current action needs it. Startup and LOW work must not scan all Task history, all Knowledge, or all policies merely because those assets exist.

### 4.4 Independence where it matters

Scout and Reviewer independence is a quality control against parent self-confirmation. Independent roles must not silently inherit the parent's desired answer, proposed patch, or full conversational hypothesis when the role requires independent judgment.

### 4.5 Current truth over historical memory

Historical Knowledge can accelerate work but cannot overrule current code or new evidence. Code-bound memory must support freshness, staleness, conflict, or equivalent conservative treatment.

### 4.6 Explicit authority

Agent recommendation and user decision are different facts. User decisions must be stored and propagated as authority rather than inferred from the Agent's recommendation.

### 4.7 Adaptive execution cost

Governance cost should follow the uncertainty of the work currently being performed. As the unknown engineering surface becomes bounded, execution intensity may decrease.

Historical peak risk and final Production Change assurance must not automatically decrease with current execution risk.

### 4.8 Truthful runtime proof

Governance Core defines what must be proven. Runtime Providers must truthfully prove what actually happened in their native environment, including relevant model/profile, context isolation, sandbox or permissions, execution type, and runtime evidence.

Provider differences must not be flattened merely to produce a uniform-looking abstraction.

### 4.9 No silent fallback

When Sitter cannot establish a required fact, classify a changed surface, or prove an assurance condition, the default must be conservative. It must not silently lower assurance, waive tolerance, ignore unknown paths, or reinterpret weaker runtime behavior as stronger behavior.

---

## 5. Minimum Sufficient Capability

For any engineering objective with a fixed quality and assurance requirement, Sitter should prefer the least expensive execution path that can reliably satisfy that requirement.

Efficiency is an implementation principle, not a third top-level goal. It must never reduce Context Capability, Human Decision Authority, or required assurance.

The preferred execution ladder is:

1. deterministic computation before model reasoning;
2. cheaper narrow model before stronger model;
3. lower reasoning effort before higher reasoning effort;
4. narrow context before broad context;
5. valid existing evidence before recomputation;
6. sequential execution by default, parallelism only when independent work justifies it;
7. minimum tool and permission surface;
8. escalation triggered by evidence of insufficiency rather than by task labels alone;
9. **once the current requirement is satisfied, stop adding work by default.**

Execution cost includes more than model price:

- model and reasoning tokens;
- parent-context pollution;
- child coordination and repeated reads;
- tool, MCP, CLI, Git, and subprocess overhead;
- latency;
- retries and failed process launches;
- repeated review or verification that does not add assurance.

Cheap subagents are one useful mechanism, not the goal. A larger number of cheap agents can cost more than one stronger agent. Sitter should optimize total cost subject to required quality and assurance.

Core should express provider-neutral capability or reasoning needs. Provider implementations may map those needs to their real model families and native subagent configuration.

---

## 6. Design Constraints

### 6.1 One governed Work Graph

MEDIUM+ governed work uses one Task / Investigation / Production Change model. Sitter must not create a separate Lite/Fast lifecycle merely to reduce ceremony.

### 6.2 LOW remains lightweight

Conversation, bounded read-only work, and deterministic LOW tasks should not create Task, Change, Learning, Scout, long plans, or governance artifacts without an independent reason.

### 6.3 Core semantics, Provider enforcement

Governance Core defines provider-neutral semantics and evidence requirements. Provider-specific model names, session behavior, permission models, hooks, transcript formats, and native execution mechanisms remain in Providers unless multiple Providers have demonstrated a genuinely common semantic abstraction.

### 6.4 Prefer canonical facts over duplicated state

Persistent state should represent facts that cannot be safely and deterministically reconstructed. Derived booleans, aggregate statuses, Markdown projections, and convenience caches should not become additional sources of truth without a strong reason.

### 6.5 Internalize deterministic orchestration

A lifecycle step should not remain Agent-facing merely because a Python command exists. If Harness can deterministically perform a sequence while preserving transaction boundaries and stop conditions, normal-path orchestration should be owned by Harness.

### 6.6 Preserve information, preserve guarantees, compress ceremony

This is the primary complexity-paydown rule:

> **Core information must not be lost. Core guarantees must not be weakened. Implementation ceremony should continuously decrease.**

---

## 7. Non-negotiable Guarantees

A simplification or future release must not silently remove these guarantees:

- long-running governed work can survive a new session through durable state;
- Investigation claims, evidence, experiments, decisions, and unresolved questions remain recoverable;
- material user decisions remain authoritative downstream;
- HIGH/CRITICAL independent exploration remains genuinely independent when required;
- numerical Changes cannot satisfy readiness through local unit tests alone when representative, benchmark, analytical, or equivalent evidence is required;
- Candidate independent review remains independent and runtime-proven;
- Candidate Human Stop remains a real user acceptance boundary when required;
- final verification occurs after acceptance rather than being substituted by pre-acceptance readiness;
- historical memory that may be stale cannot silently become current truth;
- Provider attestation and stale detection remain truthful;
- unrelated LOW work is not dragged into heavy governance merely because governed work or memory exists elsewhere in the repository.

---

## 8. Change Review Rule

Every substantial Sitter design or complexity-paydown proposal should answer:

- Which top-level goal does this serve?
- Which observed failure mode does it address?
- Why are existing mechanisms insufficient?
- How many Agent-facing concepts or mandatory actions does it add?
- How much persistent state does it add?
- Can any new state be derived instead?
- Does it add a lifecycle state or another governance graph?
- Can deterministic logic or a cheaper capability satisfy the same requirement?
- Which core assets and guarantees prove that the change is non-regressive?

If a mechanism cannot explain which core goal or guarantee it serves, it should not be promoted into Governance Core by default.
