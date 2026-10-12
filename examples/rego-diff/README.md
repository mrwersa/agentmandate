# Review a publication-policy release

Run from the repository root:

```bash
mandate rego diff --baseline examples/rego-diff/baseline.json \
  --candidate examples/rego-diff/candidate.json \
  --baseline-root . --candidate-root . --as-of 2026-10-12 --json
```

Exit 1 is expected. Removing publication approval changes one exact request
from Deny to Allow, alongside the independently reported manifest widening and
ungated-publication breach. Both original reconciliation reports remain present.

The baseline index points to the existing deployment-reconciliation example.
The candidate supplies a new manifest, regenerated Rego bundle, revision r2,
OPA-shaped decisions and OTLP-shaped attempts with updated pins. All captures
are synthetic. Native OPA tests verify their decisions against the generated
policies; they do not authenticate a live service execution.

See the [comparison guide](../../docs/rego-diff.md) for matching rules, capture
requirements, exit codes, expiry and limitations. Use the baseline index on
both sides for an unchanged result, or swap the indexes for narrowing.
