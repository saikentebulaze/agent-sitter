# V6 Behavior Benchmark

V6 starts with behavior measurement, not new mechanisms.

The benchmark protects two long-term Harness invariants:

1. Context Capability
2. Human Decision Authority

LOW Fast Path remains a constraint: these capabilities must not make ordinary deterministic work heavy.

## Benchmark Layers

### L1 Mechanical correctness

Unit and transaction tests verify schemas, validators, transactions, freshness classification, projections, and evidence records.

### L2 Deterministic acceptance fixtures

Fixtures verify observable governance behavior without depending on a live model.

Required fixture families:

- `context-coverage-fixture`
- `memory-evolution-fixture`
- `human-authority-fixture`
- `high-risk-governance-fixture`

### L3 Runtime smoke

Real Codex and Claude fresh sessions validate:

- project entry loading;
- explicit Governor availability;
- SessionStart behavior;
- readonly Scout and Memory Scout startup;
- result delivery;
- attestation evidence.

Synthetic transcript tests do not count as real runtime smoke.

### L4 A/B benchmark

Compare current baseline and V6 candidate using:

- same model;
- same repository snapshot;
- same task prompt.

Measure:

- context recall;
- context pollution;
- material decision correctness;
- fast-path overhead.

## Baseline Expectations

The initial baseline is expected to expose known gaps:

- HIGH/CRITICAL exploration currently protects active Change execution but not every Investigation conclusion boundary.
- Existing Learning and Knowledge provide human-reviewed state but do not yet provide version-aware Memory semantics.
- Existing runtime tests prove provider contracts but not full real-session behavior.

These are benchmark observations, not implementation decisions.

## V6 Acceptance Scenarios

| ID | Scenario | Expected property |
| --- | --- | --- |
| C1 | Context coverage | independent exploration improves relevant context recall |
| C2 | Independent exploration | parent hypothesis cannot bias Scout evidence |
| C3 | Cross-session continuity | active work resumes without rebuilding history |
| C4 | Memory recall | only relevant historical state appears |
| C5 | Memory suppression | similar words do not force irrelevant history |
| C6 | Memory evolution | freshness is checked against repository evolution |
| C7 | Open Thread | unfinished future work appears only when relevant |
| H1 | Human override | explicit user choice remains authoritative |
| H2 | Material decision gate | unresolved forks block production progress |
| H3 | No HITL overhead | LOW work remains lightweight |
| H4 | Human-curated memory | promotion requires user judgement |
| H5 | Memory conflict | conflicts are surfaced, not merged silently |
| G1 | Exploration gate | final conclusions require independent evidence where required |
| P1 | Long-term cost | startup cost remains bounded with archive growth |
| P2 | Fast path cost | LOW work avoids memory subsystem overhead |
| R1/R2 | Runtime smoke | Codex and Claude execution evidence is real |

