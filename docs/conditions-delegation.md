# Conditions and delegation contract

Status: **proposed and experimental**. This document is gate 1 of the
Phase-2 initiatives for conditional authority and delegation chains. It
defines the record shapes, trust rules, and evidence gates to test before
either becomes a manifest schema change. It does not alter manifest version 1,
the Authority IR analysis profile, or any shipped CLI behaviour.

## Problem boundary

Two committed evidence graphs record authority that manifest v1 cannot
express:

- **Conditional effects.** `run_query` spans reads, writes, and destructive
  DDL depending on its `sql` argument and server flags; `execute_sentry_tool`
  dispatches over hidden tools ranging from reads to DSN creation. Manifest v1
  forces both to their strongest effect, so every SELECT is gated like a DROP.
- **Delegated and intersecting identity.** Sentry stdio spends a fixed
  delegated User Auth Token; AWS PostgreSQL spends AWS credentials that meet a
  database role. `principal: caller | service` loses the token owner, the
  grant chain, and the intersection — which is why the
  `identity.service-principal` finding now reports its own limit instead of
  prescribing token exchange.

Both gaps push reviewers toward either ignoring real distinctions or
inventing per-deployment conventions. This contract gives them one reviewed,
typed vocabulary instead.

## Design centre

A condition or delegation may **narrow** what an analysis reports as
reachable, and may explain a path, but must never widen it. An unevaluable
condition resolves conservatively (strongest declared effect); an absent,
unknown, or contested delegation value is a finding, never permission.

This mirrors the existing rule that absent control evidence fails closed, and
extends it: uncertainty about *when* authority applies resolves to the most
protective reading already in the document.

## Candidate records

Conditions and delegations are declared on tools in a future manifest
version, projected into Authority IR facts and registered relations exactly as
`contains_tool` was. Shapes are illustrative until fixtures prove them.

### Conditions

```yaml
tools:
  - name: run_query
    principal: service
    requires: [database_connection]
    conditions:
      - predicate: argument_matches
        arg: sql
        matches: "^(SELECT|EXPLAIN)\\b"
        effect: read            # when true, this call is a read
    effect: irreversible        # conservative default when no condition holds
```

Intended semantics:

- The predicate vocabulary is closed and typed:
  `argument_matches`, `flag_enabled`, `selection_equals`,
  `time_within`, `status_is`. Each names its operands; free-form expressions
  are rejected by profile validation.
- A condition maps only to a *weaker* declared effect class than the tool's
  default. Widening through conditions is structurally impossible.
- Every condition carries the standard evidence pair (`confidence`, 
  `review`). An unevaluable or unaccepted condition leaves the tool at its
  default effect, and the counterexample cites which condition was skipped.
- Approval requirements stay attached to the tool, not the condition: a gated
  tool remains gated on every branch.

### Delegations

```yaml
tools:
  - name: find_projects
    principal:
      kind: delegated_user
      granted_by: spiffe://bank/agents/dispute-resolver
      audience: sentry
      expires: 2026-11-23
```

Intended semantics:

- `principal` gains structured kinds while remaining readable as today's
  two-value form for ordinary manifests. New kinds: `delegated_user` (a fixed
  credential spending a named user's authority) and later `agent_delegate`
  (one agent acting for another).
- Every delegation records grantor, audience, and expiry. Expiry is evaluated
  against a caller-supplied date, as dynamic inventory does — never a clock.
- Attenuation is checkable: a delegated credential may spend only authorities
  its grantor holds for the same audience. `lint` reports a delegation whose
  effective surface exceeds its grantor's as `delegation.widens`.
- `reach` cites the hop: a counterexample through a delegated tool names the
  grantor and expiry in its provenance support, so "who allowed this" has a
  mechanical answer.

### Intersecting principals

AWS-style intersections (cloud credentials meeting a database role) are
recorded as a second structured kind, `intersecting`, listing the principals
that jointly bound the call:

```yaml
    principal:
      kind: intersecting
      principals: [aws-role:arn:..., pg-role:refund_rw]
```

Analysis treats each listed principal as an independent fail-closed
constraint; neither alone describes the boundary.

## Trust rules

The standard evidence pair governs both records. Additionally:

1. Only `exact` + `accepted` conditions participate in narrowing; anything
   else leaves the conservative default in force.
2. Contested or expired delegations produce findings (`delegation.expired`,
   `delegation.contested`) rather than silent service treatment.
3. Unknown predicate kinds, unknown principal kinds, and malformed operand
   types are reader-level rejections, following the strict-reader pattern.
4. Profiles remain separate: the manifest analysis profile extends with a
   schema-version bump and migration fixtures; inventory profiles never gain
   authority-bearing conditions.

## Evidence anchors

The two graphs that asked for this are the acceptance fixtures:

| Fixture | Conditional case | Delegation case |
|---|---|---|
| AWS PostgreSQL MCP | `run_query` narrows to `read` on SELECT-shaped SQL | `connect_to_database` spends an `intersecting` principal |
| Sentry MCP | `execute_sentry_tool` narrows on dispatch target for known names | every tool spends a `delegated_user` token |

Gate acceptance requires: the shortest AgentKit/Sentry counterexample is
unchanged under conservative defaults; a SELECT-only `run_query` profile
produces no irreversible gating on that tool; and a Sentry breach path cites
its delegation hop.

## Gates

1. **Contract:** this document survives challenge against both fixtures.
2. **Records:** typed condition/delegation records, strict reader, canonical
   fixtures, IR projection behind new registered relations.
3. **Analysis:** conditional effects and delegation hops inside `reach` and
   `drift`, with provenance-cited counterexamples.
4. **Public exposure:** CLI and schema-version bump only after failure
   behaviour and output stability reviews.

## Non-goals

No general expression language, no runtime policy evaluation, no credential
issuance or verification, no automatic inference of conditions from source,
and no widening of authority through either mechanism. Resource relationships
(bounded producers, binding lineage) stay a separate initiative; this contract
only borrows their eventual relation-registry mechanics.
