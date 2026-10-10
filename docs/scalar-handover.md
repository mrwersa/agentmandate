# Verify a scalar handover

Use this experimental verifier when both sides of a handover use the same
declared integer monetary accounting model. It checks successor binding,
retained completed spend, retained pending reservations, and available capacity.
The [synthetic walkthrough](../examples/scalar-handover/README.md) includes a
useful tightening and a reset that the verifier refuses.

`mandate continuity handover` checks one handover independently of provider
observation profiles. Its proof concerns the declared scalar model at cutover.
It does not infer provider policy equivalence, authenticate a live execution,
or grant deployment approval. The existing continuity and revision-review
commands keep their own results and verdicts.

## Model and proof

Both captured policies must use this closed JSON contract:

```json
{"scalar_policy_version":1,"tool":"process_refund","value_arg":"amount",
 "unit":"GBP","limit":1000,"accounting":"completed_plus_reserved",
 "comparison":"inclusive"}
```

Requests have nonnegative integer amounts. At cutover, a request `q` is
admissible exactly when `completed + sum(pending) + q <= limit`.
The tool, argument, unit, accounting, and comparison must agree on both sides
and with the manifest's sole value-spending tool. The predecessor limit equals
the manifest total; the successor may tighten it. There is no currency
conversion, rolling window, compensation, or amended mandate in this model.
This domain describes cumulative admission only. Approval, resource scope,
per-tool ceilings, and other manifest restrictions retain their separate
Authority analysis; the model proof does not grant a tool permission to run.

The verifier checks all integer request amounts analytically. If the successor
has more available capacity, it supplies the smallest amount admitted only by
the successor. Negative remaining capacity means no request is admissible,
including zero; it is not clamped to zero. Tightening below already consumed
spend therefore leaves an empty future domain without inventing a fresh budget.

Model conformance additionally requires completed spend not to fall, exactly
the same pending operation IDs and amounts, a fenced predecessor, and an
exclusive successor. A reset fails this contract even when a much lower limit
would happen to hide the extra capacity. The proof does not turn an inclusion
calculation into permission to lose state.

## Evidence and binding

The strict marker is `scalar_handover_version: 1`. Required root fields are:

| Field | Meaning |
|---|---|
| `id` | Nonempty handover identifier |
| `manifest_sha256` | Digest of the exact supplied manifest bytes |
| `cutover_at` | Whole-second UTC cutover time, no later than explicit `--as-of` |
| `bindings` | `before` and `after`, each a complete existing continuity binding |
| `policies` | `before` and `after` source IDs for the captured scalar policies |
| `state` | `completed_before`, `completed_after`, `pending_before`, `pending_after` |
| `fence` | `predecessor_fenced` and `successor_exclusive` |
| `attestation` | Nonempty `statement` and nonempty declared `sources` references |
| `sources`, `evidence` | Existing continuity source/review records for the whole handover |

Completed values are nonnegative integers or null for unknown. Pending values
are arrays of `{id, amount}` records with distinct IDs, or null for unknown.
An empty array attests that no operation is pending; it differs from null.
Fence fields are booleans or null. Unknown state or unestablished fencing
withholds conformance. Operation IDs are reviewed execution aliases; a JSON-RPC
request ID alone does not establish operation identity.

All handover and binding sources must be declared in the root, with identical
records, and supplied exactly through `--source LOCATOR=PATH`. Each source is
checked against its digest. Both bindings must join the supplied manifest and
selected tool principal, use platform-verified mediation, and name their own
policy digest. Their IDs and enforcement bindings must distinguish the two
sides. The predecessor must be valid at cutover; the successor must be valid at
both cutover and evaluation. Binding validity is half-open. Review expiry
includes the whole stated UTC date.

The handover and both bindings require exact, accepted, current evidence.
Review must establish that the closed scalar policies actually model the
selected enforcement paths, the snapshots belong to the same mandate run,
pending IDs identify distinct operations and retain their reservations, and
the predecessor can no longer admit work after cutover. It must also establish
that the successor is the exclusive admission path. Digest equality, strings,
and Boolean attestations cannot independently prove these operational facts.
The verifier does not verify binding signatures or a live coordinator.

## Result and gate

`agentmandate.scalar-handover/v1` includes the canonical handover and digest,
explicit evaluation time, full independent manifest Authority, evidence
findings, and `proof`. The proof reports both remaining capacities, a successor
admission witness when one exists, the admission-inclusion assessment, and one
of these conformance verdicts:

- `satisfied_for_declared_scalar_handover` — all required evidence and model
  obligations hold;
- `violated_for_declared_scalar_handover` — eligible, joined evidence shows a
  widening limit, lost completed spend, changed pending reservations, or extra
  successor admission;
- `unresolved` — evidence, binding, policy, timing, state, or fencing is missing
  or ineligible.

Exit 0 means conformance to this declared handover and a clean, untruncated
manifest Authority analysis. Findings exit 1 with complete output. Malformed
handover artifacts, missing or extra source locators, and I/O failures exit 2
with empty stdout. Captured policy-format or digest failures are unresolved
evidence findings. Global provider safe continuation is not a field of this
result and is not established by exit 0.

## Compatibility

The [retained](../tests/fixtures/scalar-handover-result-v1-retained.json),
[reset](../tests/fixtures/scalar-handover-result-v1-reset.json), and
[expired](../tests/fixtures/scalar-handover-result-v1-expired.json) fixtures pin
the initial CLI result bytes, including the embedded handover input. These are
v1 baselines, not migrations. Future changes to this strict input, policy model,
or result meaning require an explicit compatibility decision and affected
before/after fixtures. Existing continuity results retain their own contracts.

This is a cutover snapshot verifier, not a settlement/retry replay engine.
Later settlement, cancellation, new admissions, crash recovery, distributed
atomicity, and other tools need their own evidence. Historical captures and
binding approval retain their existing status. The design is tracked in
[#224](https://github.com/mrwersa/agentmandate/issues/224).
