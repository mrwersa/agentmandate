# Review evidence for policy revisions

A new policy revision is not evidence that the issuer amended the mandate.
Likewise, matching numeric limits do not establish that two policies permit
the same requests. This attachment lets a reviewer state those claims
separately, tied to exact inputs and a named comparison scope.

It extends [continuity reconciliation](authority-continuity.md) for AgentCore
configuration and limit revisions. It does not interpret policy languages or
change the existing continuity result. With an attachment, a separate result
contains the unchanged baseline plus scoped review assessments. Global safe
continuation remains unresolved and the command exits 1.

## Try it

The [synthetic walkthrough](../examples/revision-review/README.md) runs three
controls from a checkout. It shows scoped equivalent and tightening claims,
plus an approved retaining-state amendment. The baseline still reports the
two observed resets and keeps manifest reachability separate from them.

## What a review must establish

- The exact manifest, provider profile, and predecessor binding being reviewed.
- The predecessor and successor policy bytes and their association with the
  captured revision. The binding's policy digest must match the predecessor.
- The domain in which the policies are equivalent or the successor is more
  restrictive. A finite test domain is not a proof about every future request.
- Whether the issuer left the mandate unchanged or approved a change that
  explicitly retains consumed and in-flight state. An approved decision must
  precede or coincide with the captured transition.

Reviewers supply separate evidence records for comparison and issuer treatment.
Acceptance of one does not accept the other. Hashes establish which bytes are
being discussed; the library does not authenticate the reviewer, issuer,
provider run, or association between opaque policy bytes and live revisions.

Only retaining-state amendments are supported. Forgiving consumption, resetting
a budget, issuing a new mandate, or increasing its authority requires another
contract. A configuration update alone supplies none of these decisions.

The single supported treatment is deliberate. Supporting another legitimate
treatment, such as closing the mandate on revision, requires a new artifact
version and an explicit result-compatibility decision with before/after fixtures.
It must not be added as another enum value under `revision_review_version: 1`.

## Artifact contract

`revision_review_version: 1` is strict: unknown fields and versions are refused.
The root contains `id`, `manifest_sha256`, `provider_sha256`, `binding_sha256`,
`controls`, and `sources`. The manifest digest covers supplied bytes; provider
and binding digests cover their canonical JSON, including review metadata.
Sources use the existing continuity source records and locator restrictions.

Every control review has:

| Field | Meaning |
|---|---|
| `id` | Exact provider control ID; duplicate IDs are malformed |
| `transition_at` | Whole-second UTC time of the captured transition |
| `policies` | `before` and `after` source IDs for the exact policy bytes |
| `association` | Nonempty attestation connecting these policies and the pinned binding to this captured control |
| `comparison` | `relation`, nonempty `scope`, supporting `sources`, and independent `evidence` |
| `amendment` | `status`, `issuer`, `decision_at`, `state_treatment`, supporting `sources`, and independent `evidence` |

Comparison relations are `equivalent`, `tightens`, `incomparable`, or `unknown`.
`equivalent` also requires equal observed limits. `tightens` requires a
non-increasing limit. These arithmetic checks can reject an inconsistent
claim; they cannot prove the claimed policy relation.

Amendment status is `none`, `approved`, or `unknown`. `none` and `approved`
require a named issuer and `state_treatment: retain_consumed_and_in_flight`.
`approved` requires a whole-second UTC `decision_at` no later than the
transition; `none` uses null. `unknown` requires null issuer and decision time,
and `state_treatment: unknown`. Issuer names are evidence aliases, not credentials.
The transition must not be in the future and must fall within the predecessor
binding's half-open validity interval. A current binding cannot retroactively
cover a transition that preceded its issue time.

Each evidence record uses the established confidence, review, reviewer, and
inclusive UTC expiry-date contract. Sources must be nonempty and declared.
The complete source set is supplied separately from provider and binding
sources. One tampered source makes the whole attachment untrusted; an expired
comparison or amendment affects only that claim in its control.

Control reviews may cover a subset of provider controls. Omitted controls stay
unresolved. Unknown control IDs withhold all assessments. Supported controls
must report a changed revision, configuration or limit transition, and one or
two limit entries. This format does not reinterpret principal profiles,
Anthropic cap changes, or arbitrary multi-revision sequences.

## Result and limits

`agentmandate.revision-review/v1` contains `baseline`, the complete unchanged
`agentmandate.continuity/v1` result, plus the canonical review, its digest,
`review_inputs_eligible`, per-control `assessments`, and review findings.
The baseline's manifest Authority and findings remain intact.
`review_inputs_eligible` covers the attachment's sources, input digests, and
baseline trust. Each assessment's `control_joined` additionally checks its
revision, policy, binding, and timing. Neither flag accepts a claim whose own
review is ineligible.

Eligible comparisons report `established_within_reviewed_scope`, together with
the actual scope and relation. `incomparable` reports `not_comparable`;
`unknown` remains unresolved. Issuer treatment reports
`not_required_within_reviewed_scope` or `approved_retaining_state` only when its
own evidence is eligible and its timing and treatment are supported.

All assessments retain `safe_continuation: unresolved`. Neither a scoped
comparison nor a retaining-state amendment repairs a reset, proves reservation
of in-flight work, supplies successor binding verification, or proves global
policy equivalence. The attachment never takes the legacy `approved` shortcut
to a satisfied continuation verdict.

Malformed artifacts, wrong artifact combinations, missing/extra source locators,
and unreadable files exit 2 with empty stdout. Source mismatches, expired or
unreviewed claims, input joins, timing contradictions, and unsupported control
semantics produce complete unresolved assessments and exit 1.

Historical captures remain unreviewed or accepted only within their existing
scope. No historical review or binding is created by this feature. The design
and remaining evidence requirements are tracked in
[#222](https://github.com/mrwersa/agentmandate/issues/222).

## Compatibility

The separate [scalar handover verifier](scalar-handover.md) can check two
reviewed bindings, retained state, and complete next-request inclusion for a
closed integer model at cutover. It does not upgrade this attachment's scoped
comparisons or resolve its global continuation verdict.

The example round-trips through the strict reader. Fixed
[eligible](../tests/fixtures/revision-review-result-v1-eligible.json) and
[expired](../tests/fixtures/revision-review-result-v1-expired.json) CLI results
pin the new envelope; tests also compare its nested baseline with the original
analyzer's result. These are initial v1 baselines, not migrations or completion
of the repository-wide compatibility audit. Commands without review input
retain their existing formats and exit behavior. Python records remain private.
