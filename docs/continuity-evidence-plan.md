# Authority-continuity evidence plan

This plan turns the refund example into discriminating provider experiments.
The goal is not to collect more successful requests. It is to change one
lifecycle fact at a time and learn which identity actually owns consumed
authority: mandate, principal, enforcement boundary, policy revision, provider
session, process, or some undocumented combination.

## Core sequence

Use a cumulative GBP 1,000 refund rule and two GBP 600 attempts. Attempt A is
admitted. After exactly one controlled transition, attempt B distinguishes
preserved state (`deny`) from reset state (`allow`). Include below-limit and
over-limit single-request controls so an ordinary policy or transport failure
cannot masquerade as continuity.

The refund domain is intentionally conventional: customer-support automation,
human approval, monetary limits, retries, handoffs, and reconnects are familiar
to reviewers across payments, commerce, insurance, and travel. Amounts should
remain synthetic and no real customer or account data is needed.

## Counterfactual matrix

Run matched pairs in which only the named factor changes:

| Pair | Hold fixed | Change | Distinguishes |
|---|---|---|---|
| Same-session control | mandate, principal, policy revision, boundary | nothing | baseline accumulation and expiry |
| Reconnect | mandate, principal, policy revision, boundary | client/provider session identifier | session identity from mandate identity |
| Process restart | all reviewed identities | client process and connection | local cache from provider state |
| Byte-identical policy write | policy bytes and request | provider revision metadata | content identity from revision identity |
| Semantic no-op revision | matched decisions and limit | policy text/revision | request equivalence from state migration |
| Tighten or widen | mandate join and dimension | reviewed limit | safe translation from restored capacity |
| Principal change | mandate and policy | principal binding | accidental cross-principal state sharing |
| Region or deployment change | mandate, principal, policy | execution boundary | local from replicated state |
| Retry pair | request and transition | idempotency key/retry timing | completed work from duplicate admission |
| Concurrent pair | mandate, principal, boundary | overlap and ordering | completed state from reserved or in-flight work |

Randomize pair order where the provider permits it and run enough repetitions
to expose non-deterministic handoff or propagation behavior. Ten trials per
cell is a useful minimum for reproducibility, not a statistical guarantee.

## Execution status

The AgentCore refund evidence now covers the same-session, reconnect, separate
client-process, byte-identical revision, semantic no-op revision, threshold
revision, principal-change, and synchronized-concurrency cells with repeated
provider trials. The principal-change control held the provider session fixed
and observed Allow–Allow across distinct IAM principals in 10/10 balanced
trials, while same-principal controls were Allow–Deny in 10/10. This locates
the tested history at least at the principal×session boundary.

Region or deployment change and idempotent retry remain unexecuted. The
[continuation campaign](continuation-campaign-protocol.md) closed the tightening
cell on 11 September 2026: after a revision from 1,000 to 700, prescribed
recovery admitted a 600 request that carried predecessor consumption would
refuse in 10 of 10 trials. It also re-ran the revision matrix under native
validation and found byte-identical writes deduplicated only in the earlier
permit and forbid configuration. Managed Agents, by contrast, carried consumed
spend across a lowered live cap in 10 of 10 trials.

## Capture bundle per trial

Retain exact raw bytes plus a small normalized index. The index should include:

- mandate bytes and SHA-256; binding bytes, verification result, principal,
  validity interval, and reviewer;
- provider, region, deployment, enforcement-boundary alias, policy content
  digest, provider revision identifier, and provider session alias;
- ordered request and response bytes, decision outcome and reason, request or
  decision identifier, amount, currency, and idempotency key state;
- wall-clock UTC and monotonic timestamps for send, decision, response,
  transition start, transition completion, and first post-transition request;
- state visible before and after the transition: configured limit, consumed,
  remaining, reserved, in-flight, completed, expired, or explicitly
  unavailable;
- lifecycle API requests and responses for session creation, reconnect,
  deployment, policy update, stale-session recovery, and cleanup;
- SDK/runtime/provider versions, retry configuration, timeout, and observed
  latency; and
- a sanitization map that replaces accounts, ARNs, URLs, credentials, and
  customer identifiers with stable non-secret aliases without changing
  decision messages.

Record absence explicitly. A provider that exposes no consumed or reserved
state supports a weaker claim than one with a state snapshot; the adapter must
not fill that gap from the final allow/deny sequence.

## Results enabled later

This bundle permits several stronger—but still bounded—analyses:

- which lifecycle identifier best predicts preservation or reset;
- whether byte-identical, semantically equivalent, tightening, and widening
  revisions migrate state differently;
- transition propagation latency and the window in which old and new
  boundaries disagree;
- retry duplication and completed-versus-reserved overshoot under concurrency;
- cross-principal, cross-region, or cross-deployment leakage; and
- a provider comparison using the same mandate-level invariant without
  pretending their transport records are interchangeable.

Any published conclusion must name the tested versions, transition, request
domain, repetition count, and missing state fields. A matched request result is
not whole-policy equivalence, and a stable session is still evidence rather
than the mandate.
