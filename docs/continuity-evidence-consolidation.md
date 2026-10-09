# Continuity evidence consolidation

Status: first profile projected and its six historical observations accepted
by **mrwersa** on 9 October 2026, expiring 8 November 2026. Mandate-binding
acceptance and the remaining capture families are still open.

The completed-request retransmission capture now also has an **unreviewed**
completed-prefix projection. It preserves repeated execution in the existing
scalar profile; it does not extend the acceptance of the six revision arms.
The principal-change capture has an **unreviewed, repository-only** archival
record and a separate **unreviewed runtime profile**. The new consumer preserves
principal/session observations while leaving mandate continuity unresolved.

The subsequent [clock audit](capture-clock-audit.md) locates six negative UTC
intervals across six inspected AgentCore event files, including four in the
continuation matrix with retained positive monotonic endpoint differences.
It preserves historical bytes and review metadata, distinguishes missing
endpoints from backwards UTC, and sets a timing-retention gate for future capture.

The [acceptance record](continuation-evidence-acceptance.md) contains the human
decision, exact reason and conditions, and pinned review materials. A separate
[accepted profile](continuity-reviews/agentcore-continuation-2026-10-09.json)
records that decision's reviewer and expiry. Deployment-owner acceptance of a
mandate binding remains separate and pending.

The [binding gap audit](continuation-binding-gap-audit.md) records the
maintainer's decision to defer that approval. It distinguishes missing
September evidence from the current consumer's inability to establish
comparability or amendment treatment for changed revisions. The next owner
and evidence requirements are explicit; no new profile claims are inferred.

The September AgentCore continuation matrix now has its own canonical
[`agentcore-continuation-v1.json`](../tests/fixtures/agentcore-continuation-v1.json).
It uses the existing AgentCore profile format (whose Python records remain
private), with six controls and
ten trials per control. `v1` names the artifact schema, not a replacement of
the historical capture. That continuation projection did not require a runtime
contract change or package release; the later principal consumer does.

`project_agentcore_continuation` in
[`scripts/migrate_continuity_evidence.py`](../scripts/migrate_continuity_evidence.py)
pins the protocol, sanitised events, deployment record, and summary by digest.
It derives decisions from native responses, checks their recorded labels,
request amounts, predecessor/successor session aliases and call ordering,
checks revision changes, and reconciles every arm's summary with its trials.
Duplicate or missing trial identities are refused. The existing replay command
checks this fixture alongside the three historical fixtures:

```sh
python scripts/migrate_continuity_evidence.py
```

The fixed source digests are the input boundary. This projection is not a
general importer for other captures; a changed source requires a new review.
The source records remain the place to inspect policy templates, validation
attempts, clocks, and deployment details that the scalar profile does not carry.

## Projected observations

| Arm | Limits | Decisions in each trial | Boundary detail |
|---|---|---|---|
| Byte-identical statement | 1,000 | Allow, stale predecessor | Recovery was not measured |
| Bound-variable renaming | 1,000 | Allow, stale predecessor, recovery Allow, Deny | New revision and successor session |
| Whitespace only | 1,000 | Allow, stale predecessor, recovery Allow, Deny | New revision and successor session |
| Description only | 1,000 | Allow, stale predecessor, recovery Allow, Deny | New revision and successor session |
| Identical description | 1,000 | Allow, stale predecessor, recovery Allow, Deny | New revision and successor session |
| Tightening | 1,000 → 700 | Allow, stale predecessor, recovery Allow, Deny | Recovery admits a second 600 |

All six arms use the selected single-permit configuration and
`FAIL_ON_ANY_FINDINGS`. In this capture, even byte-identical submission creates
a revision and stales the predecessor. The earlier permit/forbid capture
reported no revision and retained refusal. Both remain separate, reproducible
records. The [diagnostic capture](evidence/agentcore-refund-policy/README.md#continuation-revision-matrix)
does not isolate policy form from validation mode, so the projection does not
attribute the difference to either one or infer a provider-wide deduplication rule.

## Trust and interpretation

The canonical archival artifact remains `unreviewed`. Its `binding` is the campaign protocol's
logical Gateway placeholder, not a verified mandate/principal binding.
`same_mandate` stays unknown and mediation stays unestablished. Merely naming
the same manifest in a study protocol does not establish an enforced join.

Structural validation succeeds. Reconciliation through the existing CLI
produces all six observations and complete manifest Authority, exits 1, and
leaves the state, admission, and safe-continuation verdicts unresolved. The
separate accepted profile exposes tightening of the numeric limit while its
review is eligible, but the missing binding still prevents establishing mandate
continuity. Expired review or changed source bytes make its evidence ineligible.
The unchanged historical signed binding must not be attached to this campaign
as if it covered the new deployment.

Code review of the projection does not constitute accountable acceptance of
the provider evidence. The maintainer's explicit acceptance supplies the named
reviewer and expiry for the pinned historical observations; the joins required
for mandate continuity remain absent. A fixture refresh must not transfer that
acceptance to changed evidence.

## Completed-request retransmission projection

[`agentcore-retransmission-v1.json`](../tests/fixtures/agentcore-retransmission-v1.json)
contains two controls, `same-id-completed-prefix` and
`fresh-id-completed-prefix`, with ten trials each. In each trial, two admitted
400-unit requests returned distinct execution markers. The same-ID arm reused
the first request bytes; the fresh-ID arm changed only the JSON-RPC identifier.
Both prefixes therefore retain 800 units of observed completed execution. They
are not deduplicated into 400, multiplied by the ten repetitions, or inflated to
1,100 by counting the denied final 300-unit probe as completed work.

**This is a partial projection of the capture.** The v1 AgentCore profile has
one `request_amount` per control. Encoding the full Allow–Allow–Deny sequence
with amount 400 would invent a denied 400-unit call; the actual denied probe
was 300. The profile consequently contains only the completed Allow–Allow
prefix, with its scope in each control ID. The full mixed-amount trace and the
independent 500-Allow/1,000-Deny controls remain in the pinned source records.
The projection checks all 62 native requests/responses before producing the
two prefix controls. A future full-trace consumer would need an explicitly
reviewed per-call-amount contract; this projection does not supply it.

`project_agentcore_retransmission` in the existing migration script pins the
contract, events, deployment, and summary. It checks request-byte digests,
JSON-RPC request/response joins, native outcomes, processed amounts, distinct
execution markers, same-ID byte equality, fresh-ID differences, the fresh probe
identifier, trial identities, and summary counts. The normal migration replay
also reproduces this fixture. These checks verify consistency of the committed
sanitized records, not the authenticity of the original live execution.

**Clock limitation:** the second call in `same_id`, trial label 6, is located at
`/trials/10/calls/1` in `retry-continuity-events.json`: zero-based trial-array
index 10 (the eleventh pair in shuffled order), call index 1 (the second call).
The trial label is per arm, not the shuffled array index. This call records start
`2026-09-11T19:32:38.917842Z` and finish
`2026-09-11T19:32:38.765727Z`, despite a positive recorded duration of
516.247859 ms. The original bytes remain unchanged. The projection does not
repair the clocks or treat them as independent proof of response ordering;
`intervals_overlap` stays unknown. Completed-response sequencing and the
250 ms delay are claims of the captured procedure and contract. The cause of
the wall-clock inconsistency is not established here.

The sequencing claim concerns program order: the procedure says the driver
received the complete response before sending again. The second execution is
supported separately by its distinct Lambda execution marker in the native
response. Neither argument is computed from wall-clock differences. The clock
anomaly therefore weakens interval evidence without contradicting those two
records. This does not independently authenticate the driver run: the committed
retransmission projector checks the recorded completed-response contract, and
the projection retains that attestation boundary.

The profile has `confidence: exact`, `review: unreviewed`, unknown
`same_mandate`, and unestablished mediation. Its Gateway placeholder identifies
the capture, not a verified mandate/principal binding. The source explicitly
says that the Gateway did not inspect the experiment's mandate. The recorded
fixed session/revision boundary supports `same_boundary`; it does not prove
mandate identity. The MCP version was not captured and is not inferred from a
different campaign.

The existing CLI validates the profile, then reconciliation exits 1. State,
admission, authority change, and safe continuation stay unresolved while its
evidence is unreviewed. A synthetic acceptance used only in tests makes the
stable numeric threshold and within-bound completed total eligible; state,
binding derivation, mediation, and safe continuation remain unresolved. The
800-unit value is derived from observed completed calls, not a provider ledger
snapshot; consumed, remaining, reserved, and in-flight quantities were unavailable.

The denied probe remains corroborating source evidence for repeated temporal
accumulation. The prefix profile alone cannot establish that accumulation or
represent the full refusal trace. No timeout, lost response, pending
reservation, automatic retry, or application idempotency key was tested.
No human acceptance is recorded for these new observations, and the older
signed binding or September revision-matrix acceptance must not be reused.

## Principal and session observations

[`agentcore-principal-observations-v1.json`](../tests/fixtures/agentcore-principal-observations-v1.json)
preserves 20 trial pairs and four independent single-request controls from the
principal-change capture. It is a repository-only archival format, with no
continuity verdict, not another input supported by `mandate continuity`.
Both `validate` and `reconcile` reject it with exit 2; tests pin that boundary.

| Recorded principal sequence | Session within each pair | Pairs | Outcomes | Observed completed amount by principal |
|---|---|---|---|---|
| A → A | Same | 5 | Allow, Deny | A: 600 |
| B → B | Same | 5 | Allow, Deny | B: 600 |
| A → B | Same | 5 | Allow, Allow | A: 600; B: 600 |
| B → A | Same | 5 | Allow, Allow | B: 600; A: 600 |

The 1,200 sum in a changed-principal pair is observed execution **across
principals**, not established consumption under one mandate. The artifact
preserves each principal sequence, the shared session alias, the original event
pointer and call order, native outcome, request amount, recorded clocks, and
per-principal totals. Provider ledger quantities remain unavailable.
`same_mandate` remains unknown and mediation unestablished. The retained STS
distinct-identity statement is a capture claim; the original identity results
and session identifiers were sanitized away.

[`scripts/project_principal_observations.py`](../scripts/project_principal_observations.py)
pins the complete existing ten-file bundle, including its index, policy bytes,
original sanitizer and procedure. It verifies source and policy joins, all 44
native request/response records, balanced directions, the committed shuffled
order, distinct request identities, session aliases, and summary counts. It
reads the original sanitizer as pinned bytes; it does not execute that code or
repeat a provider call. Reproduce the artifact with:

```sh
python scripts/project_principal_observations.py
```

**Timing boundary:** one recorded call has a wall-clock delta of -127.88 ms
and a positive duration of 450.186783 ms. Both remain unchanged. The pinned
original sanitizer required ordered raw monotonic endpoints, but it omitted
those endpoints from the committed events. The new projection can recheck the
UTC delta and preserve the recorded duration; it cannot independently repeat
the original causal-order check. It supplies no inferred interval-overlap value.

**Runtime consumer gate ([#214](https://github.com/mrwersa/agentmandate/issues/214)):**
v1 `AgentCoreControl` has no before/after principal
fields and its closed transition vocabulary has no principal-change member.
`fresh_session` would misname this experiment; `same_boundary` would lose the
changed principal axis, and splitting the pair would lose its relationship.
The v1 binding also identifies a single principal. Therefore no v1 continuity
profile is fabricated from these observations.

The first consumer now uses the separate
[`principal_continuity_version: 1` contract](principal-continuity.md).
[`agentcore-principal-continuity-v1.json`](../tests/fixtures/agentcore-principal-continuity-v1.json)
projects all 20 paired trials, retaining native outcomes, per-call amounts,
principal/session aliases, and references to each original call. The same
repository script reproduces both artifacts. Its verification of native
processed-response payloads supports the completion classification; it does
not infer completion merely from an authorization decision.

The four independent single-request controls remain in the pinned sources and
archival record; the runtime profile contains paired trials only. Raw clock
fields also remain there. Its `attested_program_order` label carries the
original procedure's claim, not a reconstructed monotonic check. Review remains
`unreviewed`, authentication remains an attestation, and reconciliation exits 1.
The new format never imports the archival cross-principal sum.

The optional [reviewed accounting consumer](principal-accounting.md) now checks
separate binding authorization for identity mappings, shared intent, mediation,
execution uniqueness, and the manifest monetary limit. No such binding has been
accepted for this historical profile. It therefore keeps its observation-only
result; no principal change by itself establishes a reset or mandate overshoot.
Issue #214 stays open for the remaining historical evidence boundary. Historical-evidence acceptance and shared-mandate approval remain
separate.

## Remaining work

| Capture family | Current disposition | Required next evidence or modeling decision |
|---|---|---|
| AgentCore revision matrix | Archival profile remains unreviewed; separate accepted historical-evidence profile expires 2026-11-08 | Establish the campaign's mandate/principal/boundary join before claiming a mandate reset; separately review comparability and amendment treatment |
| AgentCore configuration diagnostic | Source evidence and independent replay tests | Preserve the configuration comparison without treating it as a same-mandate state transition |
| AgentCore principal change | Separate unreviewed runtime profile preserves all 20 pairs; archival format remains rejected; observation consumer leaves mandate continuity unresolved | Review cross-principal mandate/accounting authorization; source acceptance and binding remain separate |
| AgentCore completed retransmission | Two unreviewed completed-prefix controls projected; full mixed-amount trace stays in pinned sources | Accountable review must consider the clock limitation and partial projection; full-trace consumption needs per-call amounts, and mandate-binding evidence remains absent |
| Managed Agents continuation | Three captured cells | Resolve the absent local mandate/principal binding record; distinguish an applied cap reduction from a refused update and an unchanged live agent version |
| AgentCore deployment change | Authoring refusal | A dataplane comparison with fixed policy and history selection is still unavailable |

These are consolidation gates, not permission to run another live campaign.
The historical migrations, captured source bytes, and frozen protocols remain
unchanged. The overall roadmap item is not complete after this first profile.
