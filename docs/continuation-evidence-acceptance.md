# AgentCore continuation evidence acceptance packet

Prepared: 9 October 2026. Status: **accepted for the six scoped historical
observations, through 8 November 2026 UTC**.

Accountable maintainer for this decision: **mrwersa**, assigned in the
maintainer conversation on 9 October 2026. The maintainer subsequently supplied
the explicit acceptance recorded below. The deployment owner for a separate
mandate-binding decision remains unassigned.

## Decision scope

The maintainer accepts the committed, sanitised September AgentCore continuation
records and their projection as evidence for the six scoped observations below.
This decision concerns historical provider observations.
It does not approve a workflow, establish mandate intent, or establish an
enforced mandate/principal/boundary join.

Review base: commit `21fee7014bb31fa585c4eabe14a657dd2521729e`.
The projection was independently code-reviewed in
[PR #209](https://github.com/mrwersa/agentmandate/pull/209). That review and its
passing checks supported the decision; the explicit maintainer sign-off below
is the human evidence acceptance.

The maintainer selected **accept**, supplied reasons and conditions, and assigned
an expiry of **8 November 2026**. Under the current consumer, an accepted evidence
record remains eligible through its expiry date in UTC. Expiry limits reliance
on the review, not the existence of the historical observations.

**Renewal checkpoint: 6 November 2026, owner mrwersa.** Decide whether to renew
on the same pinned materials, request a revised packet, or let acceptance lapse.
The existing expiry is unchanged: 8 November inclusive UTC, with ineligibility
from 9 November at 00:00 UTC. Supplying or accepting mandate-binding evidence
does not renew this separate provider-evidence decision.

## Exact materials

The profile schema remains v1. These are file-byte SHA-256 digests, including
their final newline, rather than semantic or result-envelope hashes.

| Material | SHA-256 |
|---|---|
| [Canonical unreviewed profile](../tests/fixtures/agentcore-continuation-v1.json) | `b22f056132e838aadaa7b5191b28f4a5c2fcc1ec8508d332c3d5f1f1df35c254` |
| [Projection implementation](../scripts/migrate_continuity_evidence.py) | `f3e4873abfd55175f63e2fcc7642d1d77ed226271d5d7de6f60274a9dc329714` |
| [Protocol](evidence/agentcore-refund-policy/continuation-protocol.json) | `0f7b530daac148fe745bda47f26228f5a96bd0db93d830661335b8b7add51591` |
| [Sanitised events](evidence/agentcore-refund-policy/continuation-events.json) | `b8f366492f156fa9e1854feea01d458e0e21caf528f85d7d03a38d56bc775ba6` |
| [Deployment and cleanup](evidence/agentcore-refund-policy/continuation-deployment.json) | `d9bca41ce79eaae746f76f5da312b5b488ab6aca6c94eab5b2dd47b619f76c98` |
| [Summary](evidence/agentcore-refund-policy/continuation-summary.json) | `b8884532eba05cf2481e771af9b89e4bc7073a40239eadae05ed06774e7ecc1d` |
| [Study manifest](../examples/continuity-refund/manifest.json) | `f8aa99a6d889db19002c193801cd84bce36e10219d343804eb717f61b5236326` |

The four capture files are the profile's direct sources. The implementation
and study manifest are additional review materials. The manifest digest's
presence in a protocol is not a verified binding to the live caller.

For capture context, inspect the
[revision-matrix account](evidence/agentcore-refund-policy/README.md#continuation-revision-matrix),
the source-linked policy templates, and the separately captured configuration
diagnostic. The diagnostic explains a limitation of interpretation; this
packet does not accept it as another profile or merge its trials into the 60.

## Accepted historical claims

Every row describes ten trials in the 11 September 2026 capture, using the
selected single-permit form, `FAIL_ON_ANY_FINDINGS`, an enforcing IAM Gateway,
and requests of 600. These are scoped observations, not provider-wide rules.

| Arm | Accepted observation |
|---|---|
| Byte-identical statement | A revision was created and the predecessor became stale in ten trials. Recovery was not measured. |
| Bound-variable renaming | A revision was created; predecessor reuse was stale; a fresh successor allowed 600 and then refused another 600 in ten trials. |
| Whitespace only | The same observed revision, stale-predecessor, successor Allow/Deny sequence occurred in ten trials. |
| Description only | The same sequence occurred after a description-only update in ten trials. |
| Identical description | The same sequence occurred after resubmitting the description in ten trials. |
| Tightening 1,000 to 700 | The successor allowed 600 after the predecessor had already consumed 600, then refused another 600, in ten trials. This supports a scoped provider-capacity observation; the mandate-level verdict remains unresolved. |

The [consolidation note](continuity-evidence-consolidation.md) explains the
separate historical fixture where byte-identical submission did not create a
revision. The configuration diagnostic does not isolate policy form from
validation mode. Neither record establishes universal deduplication behaviour.

## Human review basis

The packet presented these questions to the accountable maintainer:

- Are the capture procedure, sanitisation, source provenance, trial inclusion,
  and declared limitations sufficient for the intended historical claims?
- Does the projection preserve the meaning of requests, native responses,
  session aliases, revision changes, and trial ordering, including the missing
  byte-identical recovery observation?
- Are all six claims acceptable at this scope, and is the distinction between
  observed provider capacity and unresolved mandate continuity clear?
- What review expiry is appropriate, and what concerns or exclusions should
  accompany the decision?

Digest equality establishes which bytes were reviewed. It does not authenticate
the original live service execution or independently validate sanitisation.
The deployment record includes hashes of raw captures, but the raw captures
are not supplied by this packet. The maintainer explicitly acknowledged that
the original raw captures have not been independently verified and judged the
available provenance sufficient for these historical observations. This does
not convert replay into independent verification of the original execution.

## Automated review support

At the review base, all 1,662 tests passed with 100% package statement coverage;
all PR checks passed. The targeted checks are reproducible from the repository:

```sh
python scripts/migrate_continuity_evidence.py
python scripts/evidence_lint.py
python -m pytest tests/test_continuation_profile.py tests/test_continuation_evidence.py -q
```

These check the pinned files, canonical projection, native decisions, trial
identities, summary agreement, existing CLI path, and evidence gaps. Tests
with synthetic acceptance show the consumer's remaining limitations; they are
not an acceptance record. Separate regression checks exercise the real accepted
profile, including the expiry boundary and changed source bytes. Coverage
measures exercised statements, not the truth of the capture or sufficiency of
its interpretation.

## Accepted profile and remaining gaps

The separate
[accepted profile](continuity-reviews/agentcore-continuation-2026-10-09.json)
has the same controls and capture sources, changing only evidence metadata to
`review: accepted`, `reviewer: mrwersa`, and `expires: 2026-11-08`.
Its file-byte SHA-256 is
`aa04561c7d2cd0bd0bd9184cefb9868c5be1c470a4f4880eba532c0160eb3ace`.
This later review artifact lives outside the historical capture directory and
its frozen capture index. The canonical archival fixture and its migration
remain unreviewed and byte-exact. Acceptance is pinned to the materials above
at the review base; it must not be regenerated for changed captures or
projections without another human decision.

Within the accepted review period, the current consumer can report the
numeric limit as stable in five arms and tightening in one. The recorded
completed amount is 600 for the byte-identical arm and 1,200 for the other
five. State continuity, admission relative to one mandate, and safe
continuation remain unresolved. Reconciliation still exits 1.

Acceptance must not fill `same_mandate`, upgrade mediation, supply policy
comparability or issuer amendment, or reuse the older deployment's signed
binding. Those require separate evidence and the deployment owner's decision.
No present-day production-deployment claim is included in this packet.

A dated repository sign-off records accountability. The runtime checks review
metadata, expiry, and source digests; it does not authenticate the human behind
the reviewer string or provide a cryptographic signature for this decision.

## Decision record

| Field | Current value |
|---|---|
| Accountable maintainer | mrwersa |
| Decision | ACCEPT |
| Decision date | 2026-10-09, explicit maintainer message |
| Recording timestamp | 2026-10-09T12:53:28Z; repository recording time, not the message timestamp |
| Accepted scope and reasons | Six historical observations at review base `21fee7014bb31fa585c4eabe14a657dd2521729e`; exact reason below |
| Expiry | 2026-11-08, inclusive UTC date |
| Concerns or exclusions | Original raw captures not independently verified; no mandate identity, safe-continuation, or deployment approval |
| Accepted-profile byte digest | `aa04561c7d2cd0bd0bd9184cefb9868c5be1c470a4f4880eba532c0160eb3ace` |
| Mandate-binding acceptance | Separate decision; owner and evidence pending |

Follow-up on 9 October 2026: the maintainer directed that binding approval stay
deferred while the [gaps are audited](continuation-binding-gap-audit.md).
This leaves the accepted observations, conditions, and expiry unchanged.

The maintainer supplied the following reason verbatim:

> I’m satisfied that the evidence is sufficiently documented, scoped, and tested to support the six historical AgentCore observations. The projection has been independently reviewed, and the limitations are clearly stated. While the original raw captures have not been independently verified, I consider the available provenance and reproducible checks sufficient for accepting these as historical observations, not as proof of mandate continuity.

The maintainer supplied the following conditions verbatim:

> Acceptance applies only to the six scoped observations and the pinned evidence at commit `21fee7014bb31fa585c4eabe14a657dd2521729e`. It does not establish mandate identity, safe continuation, or deployment approval. Those remain separate decisions requiring additional evidence.

The source of acceptance is this explicit human decision, not the preparation
of the packet, its earlier merge, an automated check, or an agent's code review.

Authorship confirmation, recorded 9 October 2026: in response to the request
to confirm the two quoted paragraphs, the maintainer explicitly replied:

> Yes—those are my words, and they record my acceptance, subject to the stated scope, conditions, and expiry.

This follow-up confirms authorship of the recorded reason and conditions. It
does not renew or broaden the acceptance: the pinned materials, six-observation
scope, exclusions, and 8 November 2026 inclusive UTC expiry remain unchanged.
The accepted profile remains byte-identical, and mandate-binding approval
remains deferred.
