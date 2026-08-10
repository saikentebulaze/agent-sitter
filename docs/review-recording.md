# Independent review recording

`review` only freezes the review inputs and creates `review-request.yaml`. The native reviewer remains read-only and returns its findings to the parent Agent; it must not edit project files.

The parent Agent saves the exact reviewer output as a temporary project artifact, then records the result through the Harness:

```powershell
python runtime\harness.py --project <root> review <change-id>

python runtime\harness.py --project <root> record-review <change-id> `
  --artifact .agent-work/<task-id>/reviewer-output.md `
  --architecture pass `
  --scope pass `
  --numerical-evidence warn `
  --evidence-ref native-thread:<thread-id>
```

A BLOCK result also requires one remediation route:

```powershell
--remediation-route implementation
# or
--remediation-route awaiting-production-design
```

`record-review` performs the metadata work that previously had to be edited by hand:

- verifies that the request round is the next round;
- rejects an outstanding request being overwritten;
- verifies the frozen design, task, repository diff and verification hashes;
- copies the exact reviewer output to `reviews/round-N.md`;
- derives the overall result from architecture, scope and numerical-evidence severity;
- records reviewer identity, model, tier, native execution evidence and snapshot;
- appends `review_history` and archives the consumed request as `reviews/round-N.request.yaml`;
- validates the resulting Change state and rolls back partial writes on failure.

Repeating the same `record-review` command with the same artifact, decisions and evidence is idempotent. A conflicting repeat is rejected rather than overwriting review history.
