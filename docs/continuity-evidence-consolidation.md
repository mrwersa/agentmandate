# Continuity evidence consolidation

Status: first profile projection implemented, 9 October 2026. Evidence
acceptance and the remaining capture families are still open.

The [acceptance packet](continuation-evidence-acceptance.md) assigns the human
evidence decision to maintainer **mrwersa**, pins its review materials, and
separates that decision from deployment-owner acceptance of a mandate binding.
The evidence decision and expiry remain pending.

The September AgentCore continuation matrix now has its own canonical
[`agentcore-continuation-v1.json`](../tests/fixtures/agentcore-continuation-v1.json).
It uses the existing private AgentCore profile format, with six controls and
ten trials per control. `v1` names the artifact schema, not a replacement of
the historical capture. No runtime contract or package release is needed.

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

The artifact remains `unreviewed`. Its `binding` is the campaign protocol's
logical Gateway placeholder, not a verified mandate/principal binding.
`same_mandate` stays unknown and mediation stays unestablished. Merely naming
the same manifest in a study protocol does not establish an enforced join.

Structural validation succeeds. Reconciliation through the existing CLI
produces all six observations and complete manifest Authority, exits 1, and
leaves the state, admission, and safe-continuation verdicts unresolved. Even a
synthetic acceptance in tests cannot fill the missing binding: it can expose
the tightening of the numeric limit, but cannot establish mandate continuity.
The unchanged historical signed binding must not be attached to this campaign
as if it covered the new deployment.

Code review of the projection does not constitute accountable acceptance of
the provider evidence. Acceptance still needs a named reviewer, expiry,
source review, and the joins required by the consumer. A fixture refresh must
not silently change that status.

## Remaining work

| Capture family | Current disposition | Required next evidence or modeling decision |
|---|---|---|
| AgentCore revision matrix | Separate canonical profile; unreviewed | Establish the campaign's mandate/principal/boundary join before claiming a mandate reset; separately review comparability and amendment treatment |
| AgentCore configuration diagnostic | Source evidence and independent replay tests | Preserve the configuration comparison without treating it as a same-mandate state transition |
| AgentCore principal change | Captured control | Represent principal identity and boundary selection explicitly; do not relabel a principal change as a fresh session |
| AgentCore completed retransmission | Captured control | Preserve completed execution and repeated accumulation; do not generalise to ambiguous timeouts, pending reservations, or idempotency |
| Managed Agents continuation | Three captured cells | Resolve the absent local mandate/principal binding record; distinguish an applied cap reduction from a refused update and an unchanged live agent version |
| AgentCore deployment change | Authoring refusal | A dataplane comparison with fixed policy and history selection is still unavailable |

These are consolidation gates, not permission to run another live campaign.
The historical migrations, captured source bytes, and frozen protocols remain
unchanged. The overall roadmap item is not complete after this first profile.
