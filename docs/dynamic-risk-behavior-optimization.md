# Dynamic Risk Behavior Optimization

## Purpose

Make governance cost scale with the work being performed while preserving strong proof for material production changes.

## Core model

- `task.work_risk.current` controls current execution intensity and may rise or fall.
- `task.work_risk.peak` records the historical maximum and does not automatically fall.
- `change.risk` remains the Production Change assurance floor for final verification and review.
- Current risk may decrease only after the unknown engineering surface is resolved and remaining work is bounded.
- Final review follows Change assurance, not temporary cleanup risk.

## Execution paths

### Conversation / read-only

No Work Graph merely for explanation, bounded reading, result interpretation, or lookup.

### LOW Fast Path

Bounded deterministic work remains outside the Work Graph:

`locate -> act/run -> focused verification -> concise report`

No Task, Investigation, Change, Learning, long plan, development-only probe, or ceremonial subagent.

### Governed work

MEDIUM+ work uses the existing Task / Investigation / Production Change graph. No second Lite lifecycle is introduced.

HIGH/CRITICAL work retains independent read-only exploration before active production implementation when required by the Task's risk history.

## Dynamic transitions

- Unexpected production uncertainty may promote LOW/MEDIUM work into formal governance.
- Change -> Investigation automatically raises newly discovered production uncertainty to at least HIGH semantic risk and raises the affected Change assurance.
- Investigation -> Change propagates the converged current Task risk into the new Change assurance.
- After design, implementation and core verification stabilize, bounded cleanup may reduce current work risk without reducing peak risk or Change assurance.

## Skill-loading boundary

Real Codex acceptance on 2026-08-08 validated the adaptive risk lifecycle but observed that Codex may re-read the Heavy Governor and selected policy files on later governed turns.

This repository does **not** try to solve that provider/runtime behavior with a session cache, loaded-state marker, continuation state machine, synthetic resume token, or Provider-neutral Skill lifecycle.

Harness is responsible only for avoiding unnecessary reload instructions of its own:

- LOW work must not enter the Heavy Governor.
- Follow-up turns reassess only material new facts.
- Detailed references are loaded only when the current action needs them.
- Intake/status/Skill discovery is not repeated merely to reconfirm unchanged state.
- The Tiny Router may advise against an explicit reload, but it does not claim to control whether the host/model re-reads a selected Skill.

If Codex or another provider still re-reads a short selected Skill after these conditions are met, record it as a provider/runtime limitation rather than adding Harness state to fight it. Future provider improvements may reduce this cost without any Governance Core change.

## Delegation

LOW work does not use subagents for ceremony. HIGH/CRITICAL governed work retains the independent-exploration obligation. After explicit Task-level authorization, `runtime/delegate_once.py` provides the short parent-facing request -> Provider runtime -> attestation -> result path while preserving the existing evidence chain.

## Test Hygiene

Protocol-1 Production Changes use `runtime/finalize_tests.py` before Review. Temporary tests must be removed, merged, or deliberately retained with a durable regression rationale. A manually edited cleanup Boolean is not sufficient evidence.

## Provider boundary

Provider-neutral behavior remains in Governance Core. Codex and Claude keep their real Skill/runtime semantics instead of being forced into one shared session-loading abstraction.

This iteration does not weaken:

- Codex or Claude model/profile contracts;
- sandbox/tool isolation;
- provider-specific managed/native execution;
- attestation and stale detection;
- Claude hook/scope enforcement;
- the existing Task / Investigation / Production Change graph.

Codex may use its native `allow_implicit_invocation` metadata to keep the Heavy Governor out of unrelated LOW work. Claude keeps its normal Skill projection; no special model-invocation workaround is introduced solely to emulate Codex behavior.

## Acceptance model

Automated tests cover risk transitions, adaptive pivots, HIGH exploration gates, delegation facade, Test Finalization, Review assurance, provider projection, install/update, and Provider runtime regression.

Real local acceptance should verify:

- LOW starts without Heavy Governor;
- material uncertainty promotes at the correct time;
- Harness does not explicitly require repeated Governor/policy reads merely because a new user turn arrived;
- risk/phase transitions still load enough governance to remain correct;
- HIGH -> LOW cleanup avoids repeating governance actions such as Scout or planning while Review assurance remains unchanged;
- Codex and Claude retain their real runtime proof.

A provider choosing to re-read a selected Skill is not by itself a Harness failure once Harness has stopped explicitly requesting the reload.

## Non-goals

- Do not replace Provider runtime contracts.
- Do not weaken attestation.
- Do not create a second Work Graph.
- Do not create separate Fast/Lite lifecycle artifacts.
- Do not add a per-turn continuation Skill, Skill cache, loaded marker, or session-level Governor state.
- Do not make Governance Core responsible for future Codex/Claude Skill-loading behavior.
