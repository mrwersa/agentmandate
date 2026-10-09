# AgentCore continuation evidence acceptance packet

Prepared: 9 October 2026. Status: **pending human decision**.

Accountable maintainer for this decision: **mrwersa**, assigned in the
maintainer conversation on 9 October 2026. That assignment does not accept the
evidence. The deployment owner for a separate mandate-binding decision remains
unassigned.

## Decision requested

Decide whether the committed, sanitised September AgentCore continuation
records and their projection are acceptable evidence for the six scoped
observations below. This decision concerns historical provider observations.
It does not approve a workflow, establish mandate intent, or establish an
enforced mandate/principal/boundary join.

Review base: commit `21fee7014bb31fa585c4eabe14a657dd2521729e`.
The projection was independently code-reviewed in
[PR #209](https://github.com/mrwersa/agentmandate/pull/209). That review and its
passing checks are preparation for this decision, not human evidence acceptance.

The maintainer should record one of **accept**, **reject**, or **defer**, with
reasons. Acceptance needs an explicit expiry. A proposed initial review period
ends **8 November 2026**, thirty days after preparation; that date is a proposal,
not an assigned expiry. Under the current consumer, an accepted evidence
record remains eligible through its expiry date in UTC. Expiry limits reliance
on the review, not the existence of the historical observations.

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

## Claims to review

Every row describes ten trials in the 11 September 2026 capture, using the
selected single-permit form, `FAIL_ON_ANY_FINDINGS`, an enforcing IAM Gateway,
and requests of 600. These are scoped observations, not provider-wide rules.

| Arm | Observation proposed for acceptance |
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

## Human review questions

The accountable maintainer must make these judgments explicitly:

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
are not supplied by this packet. If those records or a capture-operator
attestation are necessary to the maintainer's judgment, the decision stays
deferred until that evidence is available. Code replay cannot answer that
provenance question on the maintainer's behalf.

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
not an acceptance record. Coverage measures exercised statements, not the
truth of the capture or sufficiency of its interpretation.

## What acceptance would change

After an explicit acceptance and expiry, create a separate accepted profile
with the same controls and capture sources, changing only evidence metadata.
Record its byte digest and the dated human decision here. The canonical
archival fixture and its migration remain unreviewed and byte-exact.

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
| Decision | Pending |
| Decision timestamp | Not recorded |
| Accepted scope and reasons | Not recorded |
| Expiry | Not assigned; proposed 2026-11-08 |
| Concerns or exclusions | Not recorded |
| Accepted-profile byte digest | No accepted profile created |
| Mandate-binding acceptance | Separate decision; owner and evidence pending |

Merging this packet records the review assignment and materials. It does not
change the pending decision or authorize an accepted artifact. An acceptance
must identify this packet's exact scope and an expiry; a rejection or deferral
should identify the disputed claim or missing evidence. Partial acceptance
needs a revised packet and separately scoped profile before consumption.
