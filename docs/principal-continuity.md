# Principal and session observations

Use this experimental profile when a capture changes the authenticated caller,
the provider session, or both. It keeps those boundaries separate: two identities
using the same session do not automatically spend the same mandate.

This is the observation surface of [#214](https://github.com/mrwersa/agentmandate/issues/214).
It validates observations and reports completed amounts **per principal, per
trial**. A separate [reviewed accounting binding](principal-accounting.md) can
authorize a shared total; the commands below supply no such binding.
The existing [continuity profiles](authority-continuity.md) are unchanged.

## Try it

From a repository checkout with AgentMandate installed:

```bash
mandate continuity validate examples/principal-continuity/profile.json
mandate continuity reconcile examples/principal-continuity/manifest.json \
  --continuity-provider examples/principal-continuity/profile.json \
  --continuity-source observations.json=examples/principal-continuity/observations.json \
  --continuity-as-of 2026-10-09T12:00:00Z --json
```

The first command exits 0 for a well-formed profile. The second exits 1 and
reports three synthetic controls: the same principal in the same session,
changed principal in the same session, and the same principal in a fresh
session. These illustrate the format; they are not live provider evidence.
The fixture's named review and expiry are synthetic too.

Read `observations_eligible` before interpreting the amounts. It is true only
when every supplied source matches its digest and the profile is exact,
accepted, and current at the explicit evaluation time. Expiry includes the
whole stated UTC date. Eligibility records a human review of the observations;
it does not authenticate the identities, source execution, or reviewer.

Even with eligible observations, `mandate_identity`, `state`, `admission`, and
`safe_continuation` remain `unresolved` in this unbound result.
A principal change alone cannot establish a reset or
overshoot, and the result never adds amounts across principals or trials.

## Profile contract

The strict JSON marker is `principal_continuity_version: 1`. Unknown fields,
unsupported versions, missing fields, and duplicate identities are malformed.
The Python records remain private. Required fields are:

| Field | Meaning |
|---|---|
| `provider` | Name of the observed provider |
| `boundary` | Capture-local alias for one provider enforcement boundary |
| `measurement` | `tool`, `dimension`, and `unit`; all calls use this one measurement, without conversion or a join to manifest tools |
| `principals` | Distinct `alias` values, each with an `authentication` attestation and nonempty `sources` references |
| `trials` | Independent trials with distinct `id`, `ordering`, and an ordered `calls` array of at least two observations |
| `sources` | Nonempty source records: `id`, `kind`, repository-relative `locator`, lowercase `content_sha256` |
| `evidence` | `confidence`, `review`, `reviewer`, `expires`, using the existing continuity review contract |

A call has `principal`, `session`, `amount`, `completion`, `native_outcome`,
`source`, and `pointer`. The principal must be declared. Session is a nonempty
capture-local alias or null for unknown. Amount is a non-negative integer in
the profile's measurement. Completion is `completed`, `not_completed`, or
`unknown`; a native allow alone is not completion evidence. The original
outcome string remains visible independently of the completion classification.

`source` names a declared source; `pointer` is a non-root JSON Pointer to the
captured call occurrence. A source/pointer pair may occur only once across the
profile. This rejects duplicate references; review must still check that
different references do not disguise one execution. A reused JSON-RPC request
ID is not an execution identity. Pointers and normalized call meanings are
reviewed claims, not an automatically verified provider-specific mapping.

`ordering` is `attested_program_order` or `unknown`. Array order preserves the
recorded sequence, without proving temporal order. This format does not infer
order from UTC timestamps or positive durations, and does not claim to verify
monotonic endpoints. See the [capture clock audit](capture-clock-audit.md).

## Historical capture

The separate
[historical runtime profile](../tests/fixtures/agentcore-principal-continuity-v1.json)
is reproducible with `python scripts/project_principal_observations.py` from
the repository root. It remains unreviewed. It contains the 20 paired trials;
four single-request controls and the original clock fields remain in its
pinned sources and the unchanged archival observations.

The source-specific projector checks native processed-response payloads to
classify completion. Authentication and program order remain capture
attestations. The missing monotonic endpoints and backwards UTC delta are
[disclosed in the consolidation record](continuity-evidence-consolidation.md#principal-and-session-observations).
No new acceptance, binding, or live capture is implied by this projection.

## Compatibility fixtures

This surface adds two contracts to the pre-1.0 compatibility inventory:

| Contract | Committed baseline and check |
|---|---|
| `principal_continuity_version: 1` input | The synthetic example round-trips through the strict reader; the separate historical profile is reproduced from pinned sources by `scripts/project_principal_observations.py` |
| `agentmandate.principal-continuity/v1` output | [Eligible](../tests/fixtures/principal-continuity-result-v1-eligible.json) and [expired](../tests/fixtures/principal-continuity-result-v1-expired.json) synthetic results pin complete CLI JSON output; `tests/test_principal_continuity.py` compares emitted bytes with these fixed files |

Both result fixtures retain unresolved mandate verdicts and full manifest
Authority. The expired fixture changes observation eligibility, not the
observed amounts. The test reads committed expectations rather than generating
them from the current analyzer during the assertion.

These are initial v1 compatibility baselines. There is no earlier principal
result version to migrate; the archival observation format is not such a
predecessor. Future changes need explicit versioning and reviewed before/after
fixtures, rather than silently regenerating the expectations. This covers the
new surface without declaring the repository-wide 1.0 audit complete.

## Result and failure behavior

JSON output uses the separate `agentmandate.principal-continuity/v1` schema.
It includes the explicit evaluation time, canonical profile digest, supplied
manifest digest, measurement, full manifest Authority, and source/review
findings. Trial results preserve call order and report adjacent principal and
session relations independently. Session relation is unknown if either alias
is absent. Relations compare recorded aliases, not authenticated identities.

`observed_completed_by_principal` sums only calls classified `completed`.
`completion_known` is false if any call has unknown completion; the amounts
then represent only the known completed subset. These amounts remain visible
when evidence is ineligible, with eligibility false. No trial-count multiplier,
cross-principal total, provider-limit comparison, or authority narrowing occurs.

Valid reconciliation always exits 1 with complete output because mandate
continuity is unresolved. Source digest mismatches are findings and make the
observations ineligible. Missing or extra source locators, malformed input,
unreadable files, unsupported binding types, and unsupported composition exit 2
with empty stdout. Both JSON and text output preserve the manifest analysis.

The archival `principal_observations_version` format remains repository-only
and is still rejected. This profile does not change the review state of any
historical capture. Supplying a
[principal accounting binding](principal-accounting.md) selects a separate
result schema. It checks identity mappings, shared intent, mediation, limits,
and execution references before accounting, without resolving continuation safety.
