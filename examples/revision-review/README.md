# Scoped policy-revision review

This example is synthetic: the observations, policy association, issuer
decision, and reviews do not attest to a live deployment. It reuses the
synthetic refund mandate and predecessor binding from `continuity-refund`.

From the repository root with AgentMandate installed:

```bash
mandate continuity validate examples/revision-review/review.json
mandate continuity reconcile examples/continuity-refund/manifest.json \
  --continuity-provider examples/revision-review/provider.json \
  --continuity-source examples/revision-review/observations.json=examples/revision-review/observations.json \
  --continuity-binding examples/continuity-refund/binding.json \
  --continuity-binding-source examples/continuity-refund/binding-verification.json=examples/continuity-refund/binding-verification.json \
  --continuity-binding-source examples/continuity-refund/policy.json=examples/continuity-refund/policy.json \
  --continuity-review examples/revision-review/review.json \
  --continuity-review-source examples/continuity-refund/policy.json=examples/continuity-refund/policy.json \
  --continuity-review-source examples/revision-review/policy-equivalent.json=examples/revision-review/policy-equivalent.json \
  --continuity-review-source examples/revision-review/policy-tightened.json=examples/revision-review/policy-tightened.json \
  --continuity-review-source examples/revision-review/review-record.json=examples/revision-review/review-record.json \
  --continuity-as-of 2026-10-10T00:00:00Z --json
```

Validation exits 0; reconciliation exits 1. Without `--json`, the same command
prints the review assessments followed by the complete baseline result.

| Control | Scoped comparison | Issuer treatment | Baseline state |
|---|---|---|---|
| `equivalent-reset` | Established within reviewed scope | No amendment required within that scope | Reset |
| `tightening-reset` | Established within reviewed scope | No amendment required within that scope | Reset |
| `retaining-amendment` | Established within reviewed scope | Approved, retaining consumed and in-flight state | Preserved |

Every assessment keeps safe continuation unresolved. A finite comparison scope
does not prove general policy equivalence or verify the successor binding.
Approval retaining consumed state cannot forgive its loss.

The review expires after 8 November 2026 UTC. Evaluating at
`2026-11-09T00:00:00Z` demonstrates unresolved claims without changing the
source bytes. See the [contract](../../docs/revision-review.md) for evidence
requirements and the distinction between input eligibility and claim review.
