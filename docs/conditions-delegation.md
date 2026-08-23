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
- **Unmodellable identity shapes.** Sentry stdio spends a fixed credential
  carrying a user's authority, with no recorded grant proving delegation;
  AWS PostgreSQL spends AWS credentials that meet a database role.
  `principal: caller | service` loses the subject, any grant chain, and the
  intersection — which is why the `identity.service-principal` finding now
  reports its own limit instead of prescribing token exchange.

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
      - predicate: statement_class
        arg: sql
        class: select-only       # dialect-pinned classifier, reviewed
        dialect: postgresql-16
        effect: read             # when classified so, this call is a read
      evidence:
        confidence: exact
        review: accepted
        reviewer: platform-data
    effect: irreversible         # conservative default when no condition holds
```

Intended semantics:

- The predicate vocabulary is closed and typed. `argument_matches` regex
  matching is deliberately excluded: a pattern cannot prove a statement is
  read-only (prefix matches admit multi-statement strings), and arbitrary
  regex would reintroduce the expression language this contract refuses.
  Predicates that need judgement — `statement_class` above — must name a
  pinned, dialect-aware classifier whose failure resolves to the tool's
  default effect, never to the weaker one.
- **Conditions require a condition-context record** to narrow anything.
  `reach` does not enumerate SQL statements, dispatch names, flag values,
  status sets, or time; it cannot evaluate a predicate against an open
  domain. A versioned context artifact — separate from the mandate, in the
  dynamic-inventory pattern — supplies the reviewed admissible domain for
  each conditioned argument or state: its values, producer revision, capture
  digest, selection, completeness, evidence, review, and expiry. Narrowing
  applies only within an eligible context; outside one, every conditioned
  tool stays at its default effect and drift reports the unresolved boundary.
- A condition maps only to a *weaker* declared effect class than the tool's
  default. Widening through conditions is structurally impossible.
- Conditions carry explicit evidence fields (`confidence`, `review`,
  optional reviewer and expiry), as shown above. An unevaluable, unaccepted,
  expired, or context-mismatched condition leaves the tool at its default
  effect, and the counterexample cites which condition was skipped.
- Approval requirements stay attached to the tool, not the condition: a gated
  tool remains gated on every branch.

### Delegations

Delegation vocabulary separates three roles OAuth token exchange already
distinguishes ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693.html#section-1.1)):
the **subject** whose authority is spent, the **actor** that spends it, and
the **grantor** that issued the grant.

```yaml
tools:
  - name: find_projects
    principal:
      kind: delegated_user
      subject: user:ada            # whose authority is spent
      actor: spiffe://bank/agents/dispute-resolver   # what spends it
      grant:
        ref: grants/sentry-2026-11.json   # the reviewed granted surface
        scopes: [project:read, issue:write]
      audience: sentry
      expires: 2026-11-23
    evidence:
      confidence: exact
      review: accepted
      reviewer: security-platform
      expires: 2026-10-01          # review expiry, distinct from grant expiry
```

Intended semantics:

- `principal` gains structured kinds while remaining readable as today's
  two-value form for ordinary manifests. Kinds: `delegated_user` (an actor
  spending a named subject's authority under a grant), `agent_delegate`
  later (one agent acting for another, preserving prior actors separately),
  and `fixed_user_credential` for the Sentry shape — an operator-supplied
  credential carrying a user's authority with *no recorded grant*. A fixed
  credential is not proof of delegation: without evidence establishing grant
  semantics, impersonation and credential sharing look identical, so it is
  modelled honestly as unproven rather than upgraded into a chain.
- The `grant.ref` names the reviewed granted surface — scopes, resources,
  and effects the subject conferred. This is what makes attenuation
  computable: `lint` compares each delegated tool's effective surface against
  its grant and reports any excess as `delegation.widens`. Without a grant
  reference there is nothing to compare, and no widening claim is made.
- Grant expiry and review expiry are independent dates, both evaluated
  against caller-supplied dates — never a clock.
- `reach` cites the hop: a counterexample through a delegated tool names the
  subject, grant, and expiry in its provenance support, so "who allowed
  this" has a mechanical answer.

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
constraint; neither alone describes the boundary. An intersection is not a
delegation chain and does not participate in attenuation.

## Trust rules

Conditions and delegations carry their evidence fields explicitly. Beyond
that:

1. Only `exact` + `accepted` conditions inside an eligible context
   participate in narrowing; anything else leaves the conservative default in
   force.
2. Unknown or malformed delegation records are reader-level rejections,
   following the strict-reader pattern. Records that parse but fail trust —
   contested, expired, missing grant, selector mismatch — keep the tool in
   analysis at full service-principal treatment (existing finding included)
   and add their specific finding. A tool is never omitted from analysis:
   dropping it would manufacture a false-clean result.
3. `fixed_user_credential` tools remain findings
   (`identity.service-principal`, plus `credential.unproven-delegation`)
   until evidence establishes actual grant semantics.
4. Profiles remain separate: the manifest analysis profile extends with a
   schema-version bump and migration fixtures; inventory profiles never gain
   authority-bearing conditions.

## Evidence anchors

| Fixture | Conditional case | Identity case |
|---|---|---|
| AWS PostgreSQL MCP | `run_query` narrows to `read` on classified SELECT-only SQL | `connect_to_database` spends an `intersecting` principal (not a delegation) |
| Sentry MCP | `execute_sentry_tool` narrows on dispatch target for known names inside a reviewed context | tools spend a `fixed_user_credential`; delegation semantics are unproven |
| AgentKit, dispute-resolver | no conditioned tools; must stay byte-identical under conservative defaults | caller/service only; unaffected |

Gate acceptance requires: **all four existing evidence-graph results are
preserved byte-identically under conservative defaults**; a SELECT-only
`run_query` profile inside an eligible context produces no irreversible
gating on that tool; and any counterexample through a credentialed tool cites
its principal record. A genuine delegation-chain fixture — an OAuth token
exchange, MCP delegated authorization, or A2A delegation capture with a
reviewed grant — remains a roadmap prerequisite for the attenuation rules;
neither committed graph proves one.

## Gates

1. **Contract:** this document survives challenge against both fixtures.
2. **Records:** typed condition/delegation records, the condition-context
   artifact, strict reader, canonical fixtures, IR projection behind new
   registered relations.
3. **Analysis:** conditional effects and delegation hops inside `reach` and
   `drift`, with provenance-cited counterexamples; all four graphs unchanged
   under conservative defaults.
4. **Public exposure:** CLI and schema-version bump only after failure
   behaviour and output stability reviews.

## Non-goals

No general expression language, no runtime policy evaluation, no credential
issuance or verification, no automatic inference of conditions from source,
and no widening of authority through either mechanism. Resource relationships
(bounded producers, binding lineage) stay a separate initiative; this contract
only borrows their eventual relation-registry mechanics.
