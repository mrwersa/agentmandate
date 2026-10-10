# Verify retained state at a scalar handover

Run these commands from the repository root after installing AgentMandate.
Every review and binding here is explicitly synthetic. This example models a
handover; it does not attest a provider run or accept historical evidence.

The mandate has a GBP 1,000 cumulative limit. At cutover, GBP 600 is completed
and one GBP 100 operation is reserved. The successor tightens the limit to
GBP 900, retains both balances, and becomes the exclusive admission path while
the predecessor is fenced. Available capacity falls from GBP 300 to GBP 200.

```bash
mandate continuity validate examples/scalar-handover/handover.json
mandate continuity handover examples/continuity-refund/manifest.json \
  examples/scalar-handover/handover.json \
  --source examples/scalar-handover/before-policy.json=examples/scalar-handover/before-policy.json \
  --source examples/scalar-handover/after-policy.json=examples/scalar-handover/after-policy.json \
  --source examples/scalar-handover/review.json=examples/scalar-handover/review.json \
  --as-of 2026-10-10T00:00:00Z --json
```

Both commands exit 0. The proof reports
`satisfied_for_declared_scalar_handover`, remaining capacities `300` and `200`,
and `established_for_scalar_model` admission inclusion. It checks every
nonnegative integer next-request amount analytically. Exit 0 also requires a
clean, untruncated manifest Authority result, which remains in the output.

Repeat the handover command with these artifact paths to exercise failures:

| Artifact or change | Expected result |
|---|---|
| `examples/scalar-handover/handover-reset.json` | Exit 1: completed spend drops to zero; amount `301` is admitted only by the successor |
| `examples/scalar-handover/handover-lost-reservation.json` | Exit 1: the reservation disappears; tightening hides the capacity increase, but state retention still fails |
| Original artifact with `--as-of 2026-11-09T00:00:00Z` | Exit 1: expired reviews make the proof unresolved and numeric results null |

The two negative variants deliberately violate the intended retention contract.
Their shared synthetic review source describes that contract, not real
execution or proof that the variants satisfy it. Missing or extra source
locators, malformed artifacts, and unreadable files exit 2 with empty stdout.
Changing a captured source without updating its review produces unresolved
evidence, not a proof from the altered bytes.

Read the [contract](../../docs/scalar-handover.md) before authoring a record.
Reviewers must establish the mapping from policy bytes to enforcement, state
snapshots, pending operation identities, and fencing. The verifier checks their
declared model and exact sources; it cannot independently establish those live
facts. This cutover result does not cover future settlement, retries, crash
recovery, or global provider safe continuation.
