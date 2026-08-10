# V6 Behavior Baseline Report

## Baseline identity

- Repository: `saikentebulaze/agent-sitter`
- Product baseline: `main@f179c2ece4f5e428bfcd33d375c67f87a289e6cb`
- Benchmark branch: `agent/v6-behavior-benchmark`
- Benchmark implementation commit: `49ba8d3bb34580c272825b661e8f297723655938`
- GitHub Actions run: `31392241431`
- Ubuntu: PASS
- Windows: PASS
- Ubuntu suite: 304 tests, 2 Windows-only skips
- Windows PowerShell parsing: PASS
- Windows Codex static regression: PASS

The benchmark branch intentionally adds measurement fixtures without implementing V6 behavior. The machine-readable baseline therefore reports the behavior of the migrated `main@f179c2e` product state.

## Baseline summary

| Scenario | Baseline | Interpretation |
|---|---|---|
| C1 Context Coverage | MODEL RUN REQUIRED | Deterministic fixture/scorer exists; requires same-model black-box A/B. |
| C2 Independent Exploration | PASS | Delegation already freezes `inheritance=none` and withholds parent hypotheses/outcome. |
| C3 Cross-session Continuity | NOT IMPLEMENTED | No bounded Active Task Index / resume projection. |
| C4 Memory Recall | NOT IMPLEMENTED | No structured durable Memory retrieval / Memory Scout path. |
| C5 Memory Suppression | PASS foundation | LOW router currently keeps simple work outside governed Learning/Memory work. |
| C6 Memory Evolution | NOT IMPLEMENTED | Knowledge schema has no source commit, validity surface, or freshness state. |
| C7 Open Thread | NOT IMPLEMENTED | Durable Open Thread / Watchpoint objects do not exist. |
| H1 Human Override | FAIL | User choice can be recorded, but downstream artifacts may drift back to the Agent recommendation without validator rejection. |
| H2 Material Decision Gate | PASS | Unresolved HIGH/CRITICAL material decisions block advanced work. |
| H3 No HITL Overhead | PASS foundation | LOW Fast Path explicitly avoids Task/Investigation/subagent/long-plan ceremony. |
| H4 Human-curated Memory | FAIL | Learning attention currently applies one decision to all mature candidates. |
| H5 Memory Conflict | NOT IMPLEMENTED | No structured conflict/supersedes semantics for durable memory. |
| G1 Exploration Gate | FAIL | CRITICAL Investigation allows accepted decision, conclude, and pivot before independent exploration. |
| task-status dashboard | FAIL | `task-status` mutates `status.md` and lacks action-oriented blocked/allowed-next output. |
| P1 Long-term Cost | N/A | Continuity subsystem does not exist yet; boundedness must be measured when introduced. |
| P2 Fast Path Cost | PASS foundation | LOW work is routed away from heavy governance. |
| R1 Codex fresh runtime smoke | NOT RUN L3 | Existing runtime tests are contract/synthetic tests, not a real fresh-session smoke. |
| R2 Claude fresh runtime smoke | NOT RUN L3 | Existing runtime tests are contract/synthetic tests, not a real fresh-session smoke. |

## G1 observed behavior

For a CRITICAL Investigation with delegation required and zero completed Scouts:

- `record-evidence`: PASS — desired.
- open/supported claim recording: PASS — desired.
- experiment/evidence collection: PASS — desired.
- `accepted decision`: PASS — V6 requires BLOCK.
- `conclude-investigation`: PASS — V6 requires BLOCK.
- `pivot-to-change`: PASS — V6 requires BLOCK.

This confirms the existing Change implementing/verifying exploration gate must not be replaced. V6 needs the same semantic obligation moved earlier to the Investigation's governed final-truth boundaries.

## H1/H2 observed behavior

The existing HIGH/CRITICAL material-decision gate is useful and should be retained: an unresolved material fork is already rejected.

However, once a user chooses option B, the current structured state does not mechanically bind downstream Design / Implementation / Review / Knowledge to B. A fixture in which the user selected B but downstream artifacts reverted to A still passed the current Change validator. V6 therefore needs an authoritative-decision consistency contract, not another approval layer.

## Memory/Knowledge observation

V6 should evolve existing Learning and Knowledge rather than create a second Memory governance system.

Existing reusable assets include:

- Learning intake / observation / candidate review;
- human-reviewed Project Knowledge;
- Knowledge sync lifecycle;
- bounded delegation Context Capsules.

Missing capabilities are continuity and validity semantics: Active Task resume, compact durable entries, Open Thread / Watchpoint, code-bound source commit and validity surface, fresh/suspect/unknown lazy Git checks, conflict handling, and per-candidate human curation.

## Implementation order selected from baseline

1. **Investigation exploration gate (G1)** — reuse the existing exploration obligation and block only governed final-truth boundaries.
2. **Read-only task-status action dashboard** — expose risk, delegation state, ACTION REQUIRED, allowed next, and blocked next without mutation or Scout creation.
3. **Authoritative human decision consistency (H1)** — bind downstream governed state to explicit user decisions without adding ceremonial checkpoints.
4. **Bounded continuity and durable memory evolution** — extend existing Task/Learning/Knowledge for C3/C4/C6/C7/H4/H5/P1 while preserving C5/P2.
5. **Explicit L3 runtime smoke tooling** — real Codex/Claude fresh sessions, Hooks/subagents/transcripts/attestation; never automatic for ordinary tasks.
6. **L4 same-model A/B** — run `main@f179c2e` and the V6 candidate against the same fixture, snapshot, model, and prompt. Final Codex acceptance remains a separate real-runtime step.

## Benchmark integrity rule

`agent/v6-behavior-benchmark` is the stable measurement branch. V6 feature work should occur on a separate candidate branch so later implementation cannot silently redefine the baseline.
