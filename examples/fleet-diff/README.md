# Compare a fleet release

From the repository root:

```bash
mandate fleet diff --baseline examples/fleet-diff/baseline.json --candidate examples/fleet-diff/candidate.json --baseline-root . --candidate-root . --as-of 2026-10-14 --json
```

Exit 1 is expected: production publication approval is removed, billing staging
is added, and billing production's review is unreviewed. Release staging keeps
its previous authority. `widening.json` isolates the approval-removal change;
comparing it back to `baseline.json` demonstrates a clean narrowing rollback.
All records are synthetic. See the [fleet release guide](../../docs/fleet-diff.md)
for matching, membership uncertainty, scope and exit codes.
