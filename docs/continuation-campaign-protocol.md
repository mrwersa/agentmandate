# Continuation campaign protocol

Status: **preregistered and executed on 11 September 2026.** This document
remains the frozen design and contains no results. Results are in the
[AgentCore revision matrix](evidence/agentcore-refund-policy/README.md#continuation-revision-matrix)
and the [Managed Agents contrast](evidence/anthropic-managed-budget/README.md#continuation-contrast).
An unanticipated byte-identical result led to a separately preregistered
[diagnostic amendment](evidence/agentcore-refund-policy/continuation-diagnostic-protocol.json).
The machine-readable protocols are
[`agentcore-refund-policy/continuation-protocol.json`](evidence/agentcore-refund-policy/continuation-protocol.json)
and
[`anthropic-managed-budget/continuation-protocol.json`](evidence/anthropic-managed-budget/continuation-protocol.json).
Where this document and a JSON protocol disagree, the JSON protocol governs.

## Question and roadmap position

The campaign asks one question on two agent platforms: when a live cumulative
limit's configuration changes, does predecessor consumption still constrain
what the successor admits?

It executes the roadmap's open revision cell (tightened revisions that could
restore capacity) and the evidence plan's provider comparison. It re-captures
the existing AgentCore revision matrix in one window so every cell shares one
service version, clock discipline, and evidence version. Region or deployment
change and idempotent retry remain separate roadmap cells and are out of scope.

The principal-change control is already captured in
[`principal-continuity-*`](evidence/agentcore-refund-policy/README.md#principal-change-continuity-control)
and is not repeated. Every cell uses the same reviewed mandate,
`examples/continuity-refund/manifest.json`, SHA-256
`f8aa99a6d889db19002c193801cd84bce36e10219d343804eb717f61b5236326`.

## AgentCore cells

One short-lived AWS IAM-authenticated Gateway in `us-east-1`, one inert Lambda
tool that returns the requested amount, and one policy engine attached in
`ENFORCE`. A single operator IAM identity signs every call. Each call is
GBP 600.

**Base state.** Before every trial the policy is the permit plus forbid form
`a` at threshold 1,000 with description text `D0`. If the engine is not in that
state, a reset update is applied and polled to `ACTIVE`; reset events are
recorded and never scored. The trial's predecessor session is created only
after the base revision is `ACTIVE`.

| Arm | Update after one admitted 600 | Prediction |
|---|---|---|
| Byte-identical statement | resubmit the exact active statement | no revision; same session refuses the second 600 |
| Bound-variable renaming | form `a` to form `b` | new revision; predecessor stale; fresh successor Allow then Deny |
| Whitespace only | insert one blank line after `when temporal {` | as renaming |
| Description only | description `D0` to `D1`, no definition | as renaming |
| Identical description | resubmit `D0`, no definition | unknown |
| Tightening 1,000 to 700 | form `a` to form `a-700` | as renaming |

The tightening arm discriminates carry from reset. If predecessor consumption
carried, the successor's first 600 would be refused because 600 plus 600
reaches 700. If the successor starts from an empty history, the 600 is
admitted because 600 is below 700. The successor's second 600 is refused in
both cases and confirms that the successor enforces the rule.

**Validation.** Before any trial, two candidates are submitted with
`FAIL_ON_ANY_FINDINGS`, in order: the permit plus forbid pair, then a single
permit whose temporal condition requires the total to stay below the threshold.
The first candidate whose base, renamed, whitespace, and tightened variants all
validate becomes the matrix form, and the whole matrix runs in that mode.
If neither validates, the pair runs under `IGNORE_ALL_FINDINGS` and every
refusal is preserved. No third candidate is tried.

Trials: 10 per arm, 60 in total, in one order shuffled with seed `20260912`.
Pre-flight and post-flight controls run in fresh sessions: a single 500 must
be allowed, a single 1,000 refused, and two 600s in one session Allow then Deny.

## Managed Agents cells

Anthropic Managed Agents has no transition that invalidates a live session.
Sessions stay pinned to their agent version, and the documented cap update
keeps consumed cost. These cells are a contrast, not a replication. One cloud
environment with no network hosts, an agent with no tools, model
`claude-haiku-4-5-20251001`, and the frozen work unit from the earlier pilot.

| Cell | Procedure | Classification | Prediction |
|---|---|---|---|
| Lowered cap carries spend | cap 10 cents; work until reported cost reaches 3; lower the cap to reported plus 2; work until `budget_reached` | added spend at most 3 cents is carry; at least 5 cents is reset; otherwise indeterminate | carry |
| Cap at or below spend | cap 10 cents; work until reported cost reaches 3; set the cap to reported minus 1 | 400 with the documented message and an unchanged retrieved cap | refused |
| Agent update leaves the live session | fresh agent per trial; cap 6 cents; work until reported cost reaches 2; update the agent description; work until `budget_reached` | session still on the original version and final reported cost at most 7 is retained; at least 8 is reset | pinned and retained |

A three-session pilot is excluded from results. It must show at least two work
units per reported cent, so that the one-request overshoot cannot cross a
classification margin. If it does not, the Managed Agents cells stop before
confirmation.

Trials: 10 per cell, 30 in total, shuffled with seed `20260913`.

## Cells deliberately excluded

- **Idle expiry.** The documented policy-session idle timeout is 24 hours, and
  the maximum temporal window is 24 hours. Any request after idle expiry is
  also outside every window, so the result cannot separate expiry from window
  forgetting.
- **Widening revision.** Widening is left to issuer amendment by the property
  under test, so it adds no discriminating evidence.
- **Managed Agents identical agent update.** It involves no consumed state.
- **Managed Agents new-version or new-deployment successor.** A budget attaches
  only at session creation and a deployment copies its cap per run. The zero
  start is fixed by the API, so it is cited as a documented interface property
  rather than measured.

## Threats and how the protocol meets them

| Threat | Mitigation |
|---|---|
| The provider changed between capture windows | the whole AgentCore matrix re-runs in one window; earlier captures remain a historical comparison |
| A cosmetic tightening | 1,000 to 700 with a probe that separates carry from reset |
| A no-op write hides a change | alternating description texts and an identical-description control |
| Update not yet effective | poll to `ACTIVE` with the expected revision and statement digest; Managed Agents updates wait for the update echo before more work |
| Window expiry | UTC and monotonic timestamps on every call, update, and poll; every scored sequence must finish inside one hour |
| Host clock adjustment | causal ordering uses the monotonic clock; UTC endpoints are retained as observed |
| Rounding and in-flight overshoot | single-thread sessions, confirmed idle before each transition, whole-cent classification margins |
| Interference | one dedicated stack and engine; no other agent may use the AWS account during capture; no other sessions on the campaign agent or environment |
| Selective reporting | frozen predictions, seeds, counts, and stop rules; nonconforming trials are retained and never replaced |
| Changing documentation | the session, budget, session-operations, and agent-setup pages are fetched and hashed at capture time |
| Evidence integrity | raw captures stay in temporary storage; committed events are sanitised projections checked by one verifier that derives every count |

## Eligibility and stop rules

- Zero application and SDK retries for scored calls.
- A trial with an unexpected HTTP status, an unrecognised error code, a poll
  timeout (120 polls at one-second intervals), or a missing idle confirmation
  is nonconforming. It is retained and reported, never replaced.
- The campaign stops if a pre-flight control fails, if more than two trials in
  one arm or cell are nonconforming, if cleanup fails, or if spend would exceed
  USD 10 on AWS or USD 5 on Anthropic.
- Deployment corrections made before the first scored trial are recorded in a
  corrections file and never enter results.

## Outcome wording, fixed in advance

| Outcome | What the evidence and paper will say |
|---|---|
| Description only 10 of 10 | description-only updates created a revision in 10 of 10 trials |
| Description only k of 10, k below 10 | report the distribution; the single-trial claim is replaced by k of 10 |
| Identical description creates a revision | deduplication covers statement bytes but not metadata writes |
| Identical description creates no revision | deduplication also covers unchanged metadata |
| Tightening admits the successor's first 600 | a non-widening revision restored capacity the predecessor state refused |
| Tightening refuses the successor's first 600 | consumption carried across that revision; the tightening claim is withdrawn and the difference from earlier windows is reported |
| Renaming or whitespace no longer invalidates | behaviour changed after the earlier windows; both windows are reported with dates |
| A validating form reproduces the matrix | the ignore-findings limitation is removed |
| No candidate validates | native validation rejected every tested cumulative form |
| Managed Agents cells match predictions | an agent platform carries consumed state across a lowered cap, refuses a cap at or below spend, and keeps a live session on its version and spend |
| Any Managed Agents cell contradicts its documentation | reported as observed, with the documentation hash, and disclosed to Anthropic |

## Resources, sanitisation, and cleanup

AWS resources are created by the AgentCore CLI in a dedicated project. The
generated Gateway role receives `GetWorkloadAccessToken` only for the default
workload directory and the Gateway's own workload identity. Credentials never
reach disk. Raw events with account, resource, request, and session identifiers
stay in temporary storage and are deleted after projection to stable aliases.

Cleanup removes the stack, Gateway, target, engine, policies, Lambda, roles,
and log groups, and records operation-level not-found results. Managed Agents
cleanup deletes every session with a typed not-found proof, archives agents,
and deletes the environment.

## Consolidation

Accepted results supersede the earlier transition confirmation as one new
AgentCore evidence version and extend the Managed Agents evidence as one new
version. One verifier derives every count. Superseded records remain as
historical migration inputs. Nothing in the SSR 2026 review artifact changes
before its review ends.
