# V6 Final Live Acceptance

This runbook is intentionally separate from normal CI.

GitHub Actions proves L1/L2 deterministic behavior. Final V6 acceptance still requires real fresh model sessions for the host-runtime and model-behavior claims that deterministic tests cannot prove.

## 1. Preconditions

Use the V6 candidate branch with complete repository history available:

```bash
git fetch --all --tags
git checkout agent/v6-context-authority
python -m pip install --disable-pip-version-check PyYAML
python scripts/acceptance/v6-candidate-status.py
```

The context and Fast Path A/B protocols use the frozen master baseline commit:

```text
f179c2ece4f5e428bfcd33d375c67f87a289e6cb
```

`git fetch` is required because a shallow checkout containing only the candidate cannot materialize that historical baseline.

For every A/B comparison, use the **same Codex model and the same model/runtime configuration** on both sides. Record that exact selector/configuration in the `--model-label` argument.

Do not use resume, fork, background execution, or a pre-existing conversation for a test that explicitly requires a fresh session.

## 2. R1 — real Codex runtime smoke

Prepare a disposable project:

```bash
python scripts/acceptance/v6-runtime-smoke.py prepare ../v6-r1-codex --provider codex --force
```

The command prints:

- the prepared project path;
- the generated prompt path;
- `SITTER_SESSION_START_EVIDENCE_DIR` and its required project-local value.

Set that environment variable **before launching Codex**. Start a genuinely fresh Codex session from the prepared project, ensure the project is trusted, and give the session the generated `PROMPT.md` contents.

After the session finishes:

```bash
python scripts/acceptance/v6-runtime-smoke.py verify ../v6-r1-codex
```

R1 passes only when the verifier proves all of the following from independent artifacts:

- the parent fresh startup really fired SessionStart;
- the parent received the bounded active-Task canary before repository reads;
- the Governor was explicitly read;
- a real readonly Context Scout completed;
- a real readonly Memory Scout completed;
- the parent received the exact child result references;
- both child records re-validate through the installed Codex Provider attestation validator;
- the work graph remains valid.

A prepared project with no real Codex session always fails verification.

## 3. H1 — live Human Override

Prepare the fixture:

```bash
python scripts/acceptance/v6-human-authority-live.py prepare ../v6-h1-human-authority --force
```

Start a fresh Codex session from the printed project and give it the generated `PROMPT.md`.

The prompt does **not** reveal which option is authoritative. The Task/Change state records:

- the Agent's historical recommendation;
- a different explicit user decision.

The live Agent must discover that state and carry the user's decision through implementation, Design, Verification, Review, and the durable-memory candidate while leaving the rejected recommendation preserved only as history.

Verify:

```bash
python scripts/acceptance/v6-human-authority-live.py verify ../v6-h1-human-authority
```

Any downstream return to the rejected Agent recommendation is a failure.

## 4. C1 — same-model Context Coverage A/B

Prepare baseline and candidate projects:

```bash
python scripts/acceptance/v6-ab-benchmark.py prepare ../v6-context-ab --model-label <exact-codex-model-and-config> --force
```

This creates two projects with:

- the same C1 code snapshot;
- exactly the same prompt bytes;
- the old master Harness on the baseline side;
- the V6 Harness on the candidate side.

Launch two genuinely fresh Codex sessions with the **same model/configuration**, one from each project. Give each project its own `.v6-benchmark/PROMPT.md`.

After both runs:

```bash
python scripts/acceptance/v6-ab-benchmark.py score ../v6-context-ab
```

The scorer verifies control hashes and does not trust the Agent's own statement that independent exploration occurred. Locator/Context/Test/Framework Scout evidence counts only if the recorded child completion re-validates through that side's installed Provider attestation validator.

The candidate must:

- meet the absolute required-context target;
- identify the expected state/planner ownership rather than the solver symptom;
- avoid premature governed convergence;
- avoid recall or pollution regression versus master;
- show at least one strict behavioral improvement.

## 5. H3/P2 — same-model LOW Fast Path A/B

Prepare the heavy-history fixture:

```bash
python scripts/acceptance/v6-fast-path-ab.py prepare ../v6-fast-path-ab --model-label <exact-codex-model-and-config> --force
```

Both projects contain the same deliberately distracting background state:

- two unrelated active Task hints;
- 1000 archived Task references;
- 100 keyword-similar Project Knowledge entries.

The user request is only a local deterministic variable rename.

Run a fresh Codex session in each project with the same model/configuration and give it `.v6-fast-path/PROMPT.md`.

Then score:

```bash
python scripts/acceptance/v6-fast-path-ab.py score ../v6-fast-path-ab
```

The V6 candidate must perform the exact minimal rename and pass the existing test while creating:

- no governed Task;
- no Change;
- no Investigation;
- no delegation;
- no Memory recall;
- no extra planning artifact.

Observable governed-artifact overhead must be no worse than the master baseline.

## 6. R2 — real Claude runtime smoke

Codex cannot substitute for R2 because R2 is specifically evidence about the Claude Code Provider and Claude's real Hook/subagent runtime.

Prepare:

```bash
python scripts/acceptance/v6-runtime-smoke.py prepare ../v6-r2-claude --provider claude --force
```

Set the printed `SITTER_SESSION_START_EVIDENCE_DIR` value, launch a genuinely fresh Claude Code session from that project, give it the generated prompt, and then run:

```bash
python scripts/acceptance/v6-runtime-smoke.py verify ../v6-r2-claude
```

A final V6 release claiming both Providers should not mark R2 PASS until this real Claude run succeeds.

## 7. Final acceptance matrix

| Metric / case | Evidence required for final PASS |
| --- | --- |
| Context Recall ↑ | C1 same-model A/B |
| Context Pollution ↓ | C1 same-model A/B |
| Human Authority = 100% | deterministic H1/H2 + live H1 Human Override |
| Fast Path Overhead ≈ master | deterministic H3/P2 + LOW Fast Path A/B |
| R1 Codex runtime | real fresh Codex runtime smoke |
| R2 Claude runtime | real fresh Claude runtime smoke |

Do not convert a `NOT_RUN_*` candidate status into PASS based only on unit tests, synthetic transcripts, fake runtime clients, or a successful `prepare` command.
