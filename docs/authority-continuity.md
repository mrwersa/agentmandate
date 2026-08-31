# Authority Continuity Contract

Status: **experimental; gates 1–3 complete, public exposure pending**. This is the
contract for
[#156](https://github.com/mrwersa/agentmandate/issues/156). It defines the
smallest common analysis contract selected by the reviewed
[AgentCore](evidence/agentcore-refund-policy/README.md) and
[Anthropic](evidence/anthropic-managed-budget/README.md) evidence. It does not
change manifest version 1, Authority IR, reachability, or any public CLI.

## Question and invariant

The first consumer answers one narrow question:

> Did the state bounding one reviewed mandate remain attached to that mandate
> across a named session, handoff, or configuration transition?

A provider may correctly decide every request while the answer is no. Authority
continuity therefore remains separate from policy correctness and from compound
reachability. It never removes a reachable tool or converts an observed denial
into mandate authority.

Three outcome axes are required rather than one overloaded verdict:

- **State continuity:** `preserved`, `reset`, or `unresolved` describes whether
  already-consumed authority carried across the transition.
- **Authority change:** `stable`, `widens`, `tightens`, or `unresolved`
  compares the reviewed limit before and after the transition.
- **Admission:** `within_bound`, `overshot`, or `unresolved` compares completed
  usage with the bound while keeping work in flight distinct.

This separation is load-bearing. A live cap increase may preserve consumed
cost while widening remaining authority. A semantically equivalent policy
revision may leave request decisions stable while resetting accumulated state.
Concurrent children may keep one boundary while completed usage overshoots it.

The governing invariant is:

> Between approval and completion, consumed authority does not decrease and
> remaining authority does not increase except through a separately reviewed
> approval.

The contract records evidence for this invariant; it does not implement a
distributed counter or transaction protocol.

## Two trust layers, not one transport format

The common model is an analysis projection. It is not a universal capture
envelope. Gate 2 must define separate strict provider profiles because the two
services expose different facts:

- **AgentCore policy-session profile:** caller-supplied session alias, managed
  policy revision, temporal decisions, stale-session diagnostic, policy state,
  mapping, optional signed binding verification, and cleanup evidence.
- **Anthropic managed-budget profile:** managed session, scalar list-cost cap,
  session cost, parent/child topology, agent version, event order, refusal
  reason, and cleanup evidence. It has no Cedar schema, policy revision, or
  native mandate binding.

Neither profile may gain fields borrowed from the other. Unknown provider facts
remain unknown. The projection admits only meanings proved by the profile's
closed validator and digest-pinned sources.

Gate 2a implements these transports privately in
`agentmandate._continuity`. The canonical migrations are pinned to the exact
committed AgentCore and Anthropic bytes. Migration remains `unreviewed`: byte
identity cannot manufacture an accountable reviewer or expiry, and changed
bytes cannot inherit the canonical record merely by reproducing a summary.
Each record names its adapter and version, uses a strict reader, verifies
caller-supplied bytes without resolving paths, and preserves ordered provider
outcomes. The AgentCore record has no cost accumulator, and the Anthropic
record has no policy-revision or platform-verified mandate binding. No common continuity
outcome is computed by the transport reader itself.

## Reviewed binding

The candidate `continuity_binding_version: 1` record stays separate from the
mandate and from provider observations. The minimum body is:

```json
{
  "continuity_binding_version": 1,
  "id": "bindings/dispute-refund",
  "adapter": {
    "name": "agentmandate.continuity-binding",
    "version": 1
  },
  "mandate": {
    "sha256": "<lowercase-sha256>",
    "principal": "caller"
  },
  "enforcement": {
    "provider": "aws-agentcore",
    "boundary_kind": "policy_session",
    "binding": "refund-gateway",
    "policy_sha256": "<lowercase-sha256>"
  },
  "validity": {
    "issued_at": "2026-08-29T00:00:00Z",
    "expires_at": "2026-08-30T00:00:00Z"
  },
  "derivation": {
    "algorithm": "sha256_uuid_v1",
    "boundary_alias": "reviewed-policy-session"
  },
  "signature": {
    "algorithm": "ed25519"
  },
  "mediation": {
    "kind": "exclusive_adapter"
  },
  "sources": [
    {
      "id": "source:1",
      "kind": "verification-key",
      "locator": "evidence/binding-public-key.pem",
      "content_sha256": "<lowercase-sha256>"
    },
    {
      "id": "source:2",
      "kind": "binding-evaluation",
      "locator": "evidence/binding-result.json",
      "content_sha256": "<lowercase-sha256>"
    },
    {
      "id": "source:3",
      "kind": "signed-binding",
      "locator": "evidence/binding.json",
      "content_sha256": "<lowercase-sha256>"
    }
  ],
  "evidence": {
    "confidence": "exact",
    "review": "accepted",
    "reviewer": "security-platform",
    "expires": "2027-08-29"
  }
}
```

This is the implemented v1 shape with placeholder values; the canonical gate-2
fixture is normative. The signed canonical body, signature bytes, public key
and native verifier output remain adapter sources. The zero-dependency core
does not implement Ed25519. It accepts no `verified: true` boolean detached from
digest-bound verifier evidence.

`mediation.kind` is closed initially to `platform_verified`,
`exclusive_adapter`, and `unestablished`. An exclusive adapter can make session
continuity follow from complete mediation, but it does not prove complete
mediation. It therefore remains a conditional result with the assumption named.
Only `platform_verified` evidence can establish the join inside the enforcement
point's own trust boundary.

Validity is half-open: `issued_at <= as_of < expires_at`. The consumer requires
a caller-supplied, canonical UTC `as_of`; it never reads the wall clock.

## Alignment checks

The consumer evaluates four checks independently:

1. **Continuity:** every observed authority-bearing action for one mandate uses
   the same eligible boundary until a recorded transition occurs.
2. **Derivation integrity:** the boundary is derived from the reviewed binding,
   not accepted as an unrelated caller-selected alias.
3. **Isolation:** distinct mandates and principals do not collapse into one
   accumulated history.
4. **Complete mediation:** every authority-bearing path reaches both the binding
   verifier and the named enforcement point.

Each check carries `observed`, `configured`, `documented`, or `unestablished`
support. Those states are not interchangeable. Documentation cannot become a
live observation, and a configured exclusive adapter cannot become
platform-verified mediation. They classify what a source establishes and remain
orthogonal to evidence confidence and review state. A combined result is clean
only when the checks required by its claim have eligible evidence. Otherwise
the full authority result remains present beside a named unresolved finding.

## Transition identity and state

A transition joins one mandate to before and after observations. Its identity
includes provider profile, logical enforcement binding, principal, boundary
kind, configuration revision, reviewed limit dimension and unit, and canonical
event locators. Raw session IDs, account IDs, ARNs, URLs, trace IDs, credentials,
and tokens are never identity fields in committed fixtures.

The initial transition vocabulary is closed:

- `fresh_session`
- `configuration_revision`
- `limit_revision`
- `delegation_handoff`
- `concurrent_dispatch`

Before and after state records preserve the provider's available values rather
than pretending every provider exposes a ledger:

- boundary and configuration aliases;
- reviewed maximum, dimension, unit and scope;
- consumed value and observation point, when exposed;
- reservation or in-flight count, when exposed;
- decision outcomes and ordered event locations;
- completeness for inventory, event order and request domain; and
- settlement, migration or reapproval evidence, if any.

`unknown` is not zero. Missing consumed state, missing reservation state, or an
incomplete event order cannot prove preservation, reset, or strict admission.

## Analysis semantics

The analysis is reconciliation only. It strictly re-reads every provider record
and binding, verifies caller-supplied source bytes, projects and validates each
closed IR profile, and then evaluates the three axes.

### State continuity

`preserved` requires comparable units and an observed successor consumed value
at least as large as the predecessor value, or provider-native evidence that the
same accumulator survived. `reset` requires a positive predecessor value, a
successor value below it or independently restored capacity, the same reviewed
mandate, and no eligible settlement, migration or reapproval. Everything else
is `unresolved`.

Starting a fresh session is not by itself proof of reset. The binding must show
that both sessions belong to the same mandate and that the successor gained
usable capacity. Conversely, a stale-session rejection is not the unsafe event;
the relevant transition is the permitted successor action after recovery.

### Authority change

Comparable reviewed limits in the same dimension and unit produce `stable`,
`widens`, or `tightens`. These names match effective diff, but this axis
compares reviewed limits rather than exact per-request decisions. A changed
provider cap without a reviewed approval may demonstrate state preservation but
cannot silently become an approved widening. Different units, incomplete
mappings, or representative request sets remain `unresolved`.

The reviewed maximum comes from mandate bytes matching `mandate.sha256`, or
from a separately reviewed successor approval that the transition cites. A
provider configuration value alone is observed enforcement state, not proof of
what the mandate approved.

### Admission

`within_bound` requires a complete observation domain whose completed usage does
not exceed the reviewed maximum. `overshot` requires comparable exact values at
the provider's reported unit and granularity, and completed usage above that
maximum. It describes the observed admission model, not a vulnerability verdict.
Both outcomes are scoped to the captured sequence and completeness boundary;
neither is a universal service-rate estimate.

Completed-event telemetry never proves reservation. If work was concurrently in
flight and no reservation state is exposed, the result states that limitation.
AgentMandate does not claim that a provider promised transactional cancellation.

## Evidence-selected controls

The gate-3 matrix must preserve all reviewed outcomes:

| Transition | Required result |
|---|---|
| AgentCore, one session | state preserved; second request denied inside the cumulative bound |
| AgentCore, two fresh sessions under one mandate | state reset after both gain usable capacity |
| AgentCore, byte-identical policy submission | no new transition; accumulated state preserved |
| AgentCore, equivalent new revision | old boundary stale, successor permitted, state reset |
| AgentCore, signed binding across client processes | continuity preserved conditional on exclusive-adapter mediation |
| AgentCore, binding across policy revision | derivation remains auditable; consumed state resets |
| Anthropic, two fresh sessions under one mandate | independent capacity; state reset across the mandate boundary |
| Anthropic, live cap increase | consumed state preserved; authority-change claim remains separately reviewed |
| Anthropic, parent and children | one accumulated total across the handoff |
| Anthropic, concurrent children | boundary preserved and completed usage overshot; no reset claim |

Provider differences are results, not schema defects. AgentCore has a
configuration revision and Anthropic does not expose the analogous operation.
Anthropic reports session cost and AgentCore exposes temporal decisions rather
than a portable accumulated-state value. No cell is synthesized to make the
matrix rectangular.

Gate 3 now implements this reconciliation privately. Every provider record and
optional binding is serialized, strictly re-read, source-verified, projected,
and closed-profile validated again at consumption. The result keeps ordinary
manifest reachability unchanged beside per-transition alignments, the three
outcome axes, typed before/after limits, completed values, assumptions, and
named findings. The provider profiles keep the comparable units closed:
AgentCore's captured `process_refund.amount` integer is not interchangeable with
Anthropic's reported session-cost minor unit. The Anthropic transport preserves
both predecessor and successor costs for fresh-session and cap-revision
transitions; a successor cost alone cannot prove reset or preservation.
Canonical migrations deliberately
remain `unreviewed`; they therefore produce unresolved results until an
accountable acceptance state is supplied. Tests exercise the accepted path
with synthetic review state without rewriting the evidence fixtures.

The common consumer also preserves a limitation exposed by the migration. The
early AgentCore fresh-session and alpha-equivalent-revision captures establish
provider behavior, but their `same_mandate` value is unknown. They cannot prove
a mandate reset. The later signed binding plus policy-revision control does
establish one mandate and yields `reset`, `widens`, and `overshot` as independent
outcomes. Anthropic's digest-bound study identity supports its transition
comparisons, while derivation and complete mediation remain conditional or
unestablished because the managed service did not verify that local binding.

## Authority IR boundary

Gate 2b uses standalone profiles. Candidate source entities are mandate binding,
principal, enforcement boundary, boundary state, configuration revision, limit,
transition, request and decision. Candidate relations are:

| Relation | Endpoints | Meaning |
|---|---|---|
| `binds_mandate` | binding -> mandate | reviewed binding body and mandate digest |
| `binds_boundary` | binding -> enforcement boundary | derivation and mediation evidence |
| `state_of` | boundary state -> enforcement boundary | observed provider boundary |
| `governed_by` | boundary state -> configuration revision | observed provider state |
| `before_state` | transition -> boundary state | complete before-state evidence |
| `after_state` | transition -> boundary state | complete after-state evidence |
| `observes_decision` | transition -> decision | request and native outcome sources |

Names and endpoints remain proposals until the relation-registry review. Facts
carry limit values, units, consumed/reserved/in-flight observations,
completeness, evidence state and provider-specific source locators.

Gate 2b registers `binds_mandate`, `binds_boundary`, `state_of`,
`before_state`, `after_state`, and `observes_decision`. The binding and both
provider records project through separate closed standalone profiles. Each
profile embeds its strict transport record, checks independent content and
semantic digests, regenerates every entity, fact, and edge after reading, and
remains rejected by manifest `reach --ir`. `governed_by` is deliberately not
registered: the sanitized captures prove whether a revision changed but do not
retain a stable revision identity that could honestly serve as its endpoint.

Generic IR validation proves structure only. Closed provider validators prove
their own profile semantics. The common continuity consumer revalidates every
profile at the consumption boundary. `_analyse_ir` continues to reject all
continuity profiles as manifest authority.

Derived transition outcomes must cite both before and after facts, the binding,
the reviewed limit, relevant decisions, completeness and trust evidence. A
digest alone is insufficient because an attacker can recompute it after
tampering; profile regeneration and semantic checks remain required.

## Failure and presentation contract

Malformed structure is a typed usage error. Missing, expired, contested,
heuristic, digest-mismatched, source-mismatched, provider-incompatible or
mediation-incomplete evidence is a finding with complete output. It never
deletes a tool, narrows reachability, becomes a managed Deny, or manufactures a
clean transition.

Any future public presentation must keep these fields separate:

- manifest authority result;
- alignment checks and their evidence strength;
- state-continuity, authority-change and admission outcomes;
- provider profile and transition identity;
- caller-supplied evaluation time;
- findings and explicit assumptions; and
- source and semantic digests sufficient for offline replay.

Human and JSON output complete before a finding exit. Usage or malformed input
fails before stdout. SARIF, Mermaid, OTel and Authority IR composition remain
unsupported until each can carry transition uncertainty without implying a
stronger result.

## Delivery gates

1. **Gate 1 — contract:** challenge the three-axis outcome model, provider
   separation, alignment checks, transition identity, evidence strength and
   conservative failure semantics.
2. **Gate 2a — provider readers and migrations (complete):** strict private
   AgentCore, Anthropic and signed-binding readers reproduce canonical
   migrations of the committed captures. They verify caller-supplied bytes,
   pin the reviewed source digests and preserve provider-specific unknowns. No
   common analysis is present.
3. **Gate 2b — IR projection (complete):** the minimum evidence-backed source
   relations are registered; separate closed profiles validate content and
   semantic digests by regeneration; manifest `reach --ir` refuses them.
4. **Gate 3 — private reconciliation (complete):** the provider-neutral
   consumer reproduces every evidence-supported control, preserves unknown
   mandate joins as unresolved, separates reset, widening, and overshoot,
   reports all four alignment checks independently, and retains byte-identical
   manifest authority on trust failure. No public Python records.
5. **Gate 4 — public exposure review:** challenge containment, output stability,
   no-partial-output behavior, evaluation-time determinism and composition with
   existing policy, condition, delegation and OTel surfaces before choosing a
   CLI or schema.

This initiative remains experimental and does not block 1.0. The generalized
search problem across arbitrary durable agents, memories and sessions remains
in the advanced roadmap phase.

## Explicit non-goals

- a runtime proxy, session allocator, credential broker or token issuer;
- a distributed budget counter, reservation service or transaction scheduler;
- a general policy evaluator or semantic-equivalence checker;
- interpreting cost, money, effects, calls and produced bindings as one unit;
- inferring strict enforcement from completed-event telemetry;
- declaring complete mediation from a signature or deployment diagram alone;
- changing manifest v1 or narrowing existing reachability;
- provider credentials, raw session identifiers or account metadata in public
  fixtures; and
- public-paper or anonymity-sensitive cross-links before review permits them.
