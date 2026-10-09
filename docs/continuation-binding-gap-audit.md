# September AgentCore mandate-binding gap audit

Audited 9 October 2026 against repository commit
`6b33e2d6effccb85d8245c228c065eeecaaab274`. **Binding approval is deferred** at
the maintainer's request. No deployment owner is assigned by this audit.

The [accepted historical observations](continuation-evidence-acceptance.md)
remain valid within their existing scope and expiry. The committed September
materials do not establish an enforced mandate/principal/boundary join. This
is a finding about the available repository evidence, not proof that no other
records exist.

## Evidence inventory and gaps

| Required relationship | What the committed materials supply | Gap |
|---|---|---|
| Mandate bytes to observed execution | The [protocol](evidence/agentcore-refund-policy/continuation-protocol.json) names the study manifest and its digest | The [projector](evidence/agentcore-refund-policy/project_continuation.py) copies that digest into events and summary. Agreement between those fields is not an independent observation that the live execution enforced the mandate. |
| Mandate principal to authenticated caller | The manifest names `caller`; the protocol specifies one operator IAM identity; the [driver](evidence/agentcore-refund-policy/capture_continuation_live.py) signs HTTP calls with SigV4 | The committed projection does not supply a reviewed identity mapping from that operator to the mandate's `caller`. IAM request authentication alone is not mandate binding. |
| Mandate to session and policy revision | Events preserve predecessor/successor session aliases and policy revision aliases | Sessions are caller-supplied in the policy-session header. The driver does not send a mandate digest or verify a signed mandate binding in this call path. No campaign-specific signed derivation or verifier result is supplied. |
| Logical Gateway alias to the enforcement deployment | The protocol uses `<reviewed-continuation-gateway>`; deployment records an IAM-authenticated, enforcing MCP Gateway | The placeholder is a logical name. It is not an independently verified derivation of that deployment from the mandate. |
| Manifest tool and approval rules to native requests | The [study manifest](../examples/continuity-refund/manifest.json) has `open_case`, scoped `process_refund`, and required approval. The driver calls `ContinuationTarget___process_refund` with an amount and an inert Lambda returns it | No record establishes enforcement of the manifest's case prerequisite, scope, approval, or irreversible-money semantics in this inert provider control. Matching a refund name and amount does not establish the full tool contract. |
| Mandate limit to native history semantics | [Base](evidence/agentcore-refund-policy/continuation-candidate-permit-a.dogwood) and [tightened](evidence/agentcore-refund-policy/continuation-candidate-permit-a-700.dogwood) templates use strict `total < 1000` and `total < 700` over a one-hour history | A reviewed mapping must address dimension, unit, strict boundary, time window, and accounting scope. The scalar profile does not prove equivalence to the manifest's GBP total limit. |
| Complete mediation and isolation | The protocol states dedicated resources and exclusive account use during capture | This is experimental procedure, not proof that every authority-bearing path enforced a mandate binding. The accepted profile correctly retains `mediation: unestablished`. |
| Policy comparability and issuer amendment | There are pinned templates and observed revisions, including tightening | No accepted comparability or issuer-amendment treatment was supplied. Historical-observation acceptance expressly excludes filling these claims. |

The [summary](evidence/agentcore-refund-policy/continuation-summary.json) also
records the provider state snapshot as unavailable. The
[deployment record](evidence/agentcore-refund-policy/continuation-deployment.json)
reports cleanup complete and all listed resources verified absent. Recreating
resources would be a new deployment and capture, not additional observation of
the September deployment. No live capture is authorized or run by this audit.

## Why the older signed binding cannot fill the gap

The [historical binding fixture](../tests/fixtures/continuity-binding-v1.json)
is a separate, still-unreviewed record. Its signed source remains unchanged.

| Field | Older binding | September continuation profile |
|---|---|---|
| Mandate byte SHA-256 | `401289117ed27255b734e64ef378fd43f65befba62cc55b51ce40a5dfbdd2c85` | `f8aa99a6d889db19002c193801cd84bce36e10219d343804eb717f61b5236326` in the study protocol |
| Logical enforcement binding | `agentcore-refund-gateway` | `<reviewed-continuation-gateway>` |
| Signed validity interval | 2026-08-29T00:00:00Z to 2026-08-30T00:00:00Z, end exclusive | No signed campaign-specific interval supplied; capture occurred 11 September |
| Mediation | `exclusive_adapter` | `unestablished` |

The shared principal label `caller` and provider name do not repair these
mismatches. Changing identifiers, dates, or policy hashes on the older signed
record would not extend what its original signature and verifier evidence
established. Acceptance of September observations does not accept that older
binding.

## Consumer limits that remain after evidence collection

The current implementation in
[`agentmandate/_continuity.py`](../agentmandate/_continuity.py) keeps these
gates distinct:

1. `analyse_continuity` checks binding review eligibility, signed validity,
   provider and logical-binding agreement, and exact mandate bytes/principal
   matching. These metadata checks do not authenticate the human reviewer.
2. `_agentcore_axes` requires a reviewed same-mandate claim and an eligible
   binding to classify a cross-boundary mandate reset. The binding and control
   mediation must agree. The accepted September controls retain
   `same_mandate: null`; supplying a separate binding cannot silently change
   their reviewed content.
3. `_transition_claims` currently establishes comparability and a
   `not_required` amendment only for an unchanged boundary without an observed
   revision. All six September controls have changed revisions and boundaries,
   so those two claims remain unresolved even if a valid binding were supplied.
4. `_safe_continuation` requires resolved comparison/amendment claims and all
   alignment checks established. An exclusive adapter gives conditional
   mediation, not a platform-verified complete-mediation result.

Consequently, a binding owner's signature alone would not make these results
conclusive. Consuming comparability/amendment evidence for changed revisions
would require a separately reviewed extension of the current closed profile
and consumer. This audit does not relax those gates or manufacture that evidence.

## What can unblock the next decision

Binding approval stays deferred. Before preparing an acceptance packet for it:

- Identify a deployment owner who can attest to the relevant execution and
  supply contemporaneous records; maintainer evidence acceptance does not
  assign that role.
- Locate any surviving September identity mapping, signed mandate derivation,
  native verification results, policy/deployment mapping, and mediation evidence.
  Review their provenance and whether they cover the actual trial sessions.
- Review the manifest-to-provider tool and limit mappings explicitly, including
  the approval prerequisite and one-hour strict-boundary semantics.
- Decide whether those records support a historical binding at all. If they do
  not, retain the historical observations with unresolved mandate continuity.
  A future deployment study would need its own owner, procedure, authorization,
  evidence, and review; it cannot retroactively bind the September capture.

Only after the relevant evidence exists should the project decide which
additional profile claims and consumer behavior are justified. No accepted
profile, capture, or historical binding is modified by this audit.

## Independent renewal checkpoint

**6 November 2026 — mrwersa:** decide whether to renew acceptance of the same
pinned historical observations, request a revised packet, or let it lapse.
The current acceptance expires **8 November 2026 inclusive UTC** and becomes
ineligible on **9 November 2026 at 00:00 UTC**. This checkpoint is also visible
in the roadmap and acceptance record. A binding decision does not renew the
provider evidence, and this audit assigns no new expiry.
