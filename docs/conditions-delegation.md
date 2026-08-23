# Conditions and delegation contract

Status: **proposed and experimental**. This document is gate 1 of the
Phase-2 initiatives for conditional authority and delegation chains. It
defines the record shapes, trust rules, and evidence gates to test before
either becomes a manifest schema change. It does not alter manifest version 1,
the Authority IR analysis profile, or reachability behaviour. Structural
`mandate ir validate` recognition of the new relations is additive; it proves
graph integrity only and does not accept the records as authority.

Gate 2a's context and grant readers, gate 2b's tool-side readers and IR
projections, and the conditional half of gate 3 are implemented privately.
Structural projection does not make a condition or principal eligible for
analysis. Delegation semantics and every public surface remain gated.

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

Gate 1 narrows this initiative explicitly to **conditional effects**: whether
a call's effect class depends on its arguments or dispatch target. Approval
state, time windows, status, and request-context conditions stay future work —
they need operand sources this contract cannot yet define, and the committed
evidence does not ask for them. Conditions and delegations are declared on
tools in a future manifest version, projected into Authority IR facts and
registered relations exactly as `contains_tool` was. Shapes are illustrative
until fixtures prove them.

### Condition context

Conditions cannot narrow anything until a reviewed record supplies the domain
they classify over. The context is a versioned artifact, separate from the
mandate:

```json
{
  "context_version": 1,
  "id": "contexts/aws-postgres/select-only",
  "target": {
    "source": "src/postgres-server/server.py",
    "binding": "run_query"
  },
  "domain": {
    "predicate": "statement_class",
    "arg": "sql",
    "classifier": "pg-statement-classifier",
    "classifier_version": "1.3.0",
    "dialect": "postgresql-16",
    "classes": ["select-only", "dml", "ddl"]
  },
  "source": {
    "kind": "argument-capture",
    "locator": "inventory/run-query-prod.jsonl",
    "producer_version": "2026.08",
    "content_sha256": "..."
  },
  "completeness": "representative",
  "evidence": {
    "confidence": "exact",
    "review": "accepted",
    "reviewer": "platform-data",
    "expires": "2026-11-23"
  }
}
```

`completeness: representative` means the capture shows what production sends,
not everything that could be sent; narrowing within it is a reviewed judgement
recorded here, and `complete` would claim the domain itself is enumerated.
Classifier identity and version are mandatory operands — two classifier
versions may disagree, so a condition without one is malformed. Digest
verification, strict reading, and expiry follow the dynamic-inventory rules.

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
        effect: read             # when classified so, this call is a read
        evidence:
          confidence: exact
          review: accepted
          reviewer: platform-data
    effect: irreversible         # conservative default when no condition holds
```

Intended semantics:

- Gate 1 defines exactly two predicates, each with its operand source in the
  context record: `statement_class` (a pinned classifier classifies a string
  argument into a closed class set) and `dispatch_target` (the reviewed
  hidden-tool catalogue names the operations a dispatch tool may reach, so
  known dispatch targets narrow while unknown ones stay at the default).
  Regex argument matching is deliberately excluded: a pattern cannot prove a
  statement is read-only (prefix matches admit multi-statement strings), and
  arbitrary patterns would reintroduce the expression language this contract
  refuses. Adding predicates later means extending the vocabulary and the
  context schema together.
- **Conditions require an eligible condition-context record** to narrow
  anything. `reach` does not enumerate SQL statements or dispatch names; it
  cannot evaluate a predicate against an open domain. The context supplies
  the reviewed domain; narrowing applies only within it. Outside an eligible
  context, every conditioned tool stays at its default effect and drift
  reports the unresolved boundary.
- A condition maps only to a *weaker* declared effect class than the tool's
  default. Widening through conditions is structurally impossible.
- Conditions carry explicit evidence fields (`confidence` and `review`);
  accepted or contested evidence also requires a paired reviewer and expiry,
  as shown above. An unevaluable, unaccepted,
  expired, or context-mismatched condition leaves the tool at its default
  effect, and the counterexample cites which condition was skipped.
- Approval requirements stay attached to the tool, not the condition: a gated
  tool remains gated on every branch.

### Grants

A delegation is verifiable only against a reviewed grant artifact — the same
separation that keeps inventory captures outside the mandate:

```json
{
  "grant_version": 1,
  "id": "grants/sentry-2026-11.json",
  "grantor": "authorization-server:sentry",
  "subject": "user:ada",
  "actor": "spiffe://bank/agents/dispute-resolver",
  "audience": "sentry",
  "surface": {
    "scopes": ["project:read", "issue:write"],
    "tools": ["find_projects", "update_issue"],
    "effects": ["read", "write"]
  },
  "issued": "2026-08-01",
  "expires": "2026-11-23",
  "evidence": {
    "confidence": "exact",
    "review": "accepted",
    "reviewer": "security-platform",
    "expires": "2026-10-01"
  }
}
```

`surface` is the complete authority the subject conferred: scopes, named
tools, and permitted effect classes. The effect set is the sole source of
truth for irreversible authority; there is no second boolean that can disagree.
Attenuation is the mechanical comparison of each delegated tool's effective
surface (its declared effect, approval state, and required scopes from the
manifest) against this object; any excess is `delegation.widens`. The grant's
own digest and review state travel with it, so `lint` receives referenced
grant bytes explicitly, verifies them, and never resolves a locator itself.

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
      subject: user:ada             # whose authority is spent
      actor: spiffe://bank/agents/dispute-resolver   # what spends it
      grant: grants/sentry-2026-11.json   # reviewed granted surface, verified bytes
      audience: sentry
      expires: 2026-11-23           # grant expiry, mirrors the artifact
    evidence:
      confidence: exact
      review: accepted
      reviewer: security-platform
      expires: 2026-10-01           # review expiry, distinct from grant expiry
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
- The manifest carries only the grant reference; the surface lives in the
  verified grant artifact. Attenuation is the mechanical comparison described
  above, reported as `delegation.widens`. A dangling or unverifiable grant
  reference is a finding, not a widening claim and not silent service
  treatment.
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
4. Evidence accountability follows the dynamic-inventory rule:
   `unreviewed` evidence names neither reviewer nor expiry; `accepted` or
   `contested` evidence requires both. Partial accountability is a reader
   rejection, not a warning.
5. Profiles remain separate: the manifest analysis profile extends with a
   schema-version bump and migration fixtures; inventory profiles never gain
   authority-bearing conditions.

## Evidence anchors

| Fixture | Conditional case | Identity case |
|---|---|---|
| AgentKit MCP (evidence graph) | no conditioned tools; must stay byte-identical under conservative defaults | caller/service only; unaffected |
| GitHub MCP (evidence graph) | no conditioned tools; must stay byte-identical under conservative defaults | caller/service only; unaffected |
| AWS PostgreSQL MCP (evidence graph) | `run_query` narrows to `read` on classified SELECT-only SQL | `connect_to_database` spends an `intersecting` principal (not a delegation) |
| Sentry MCP (evidence graph) | `execute_sentry_tool` narrows on dispatch target for known names inside a reviewed context | tools spend a `fixed_user_credential`; delegation semantics are unproven |
| dispute-resolver (example, not evidence) | no conditioned tools; must stay byte-identical under conservative defaults | unaffected |

All four committed **evidence graphs** must stay byte-identical under
conservative defaults. Gate acceptance additionally requires: a SELECT-only
`run_query` profile inside an eligible context produces no irreversible
gating on that tool; and any counterexample through a credentialed tool cites
its principal record. A genuine delegation-chain fixture — an OAuth token
exchange, MCP delegated authorization, or A2A delegation capture with a
reviewed grant — remains a roadmap prerequisite for the attenuation rules;
no committed graph proves one. The committed condition-context and grant
fixtures are explicitly synthetic samples pending captures with real
provenance: they pin schema behaviour, not upstream facts.

## Gate 2b projection profiles

Two private version-1 JSON artifacts preserve the tool-side declarations
without changing manifest v1. A tool condition records one target
(`source`, `binding`, and reviewed tool name), one closed predicate, argument,
class, weaker effect, context reference, and evidence. A tool principal records
the same target plus exactly one of these closed shapes:

- `fixed_user_credential`: actor and audience, with no invented subject or grant;
- `intersecting`: at least two distinct, jointly bounding principal names;
- `delegated_user`: subject, actor, audience, grant reference, and grant expiry.

Canonical fixtures live in `tests/fixtures/condition-*-v1.json` and
`tests/fixtures/principal-*-v1.json`. The AWS and Sentry records are
evidence-shaped acceptance fixtures; the delegated-user record is synthetic
and proves transport only.

Projection creates digest-bound, provenance-bearing IR facts and the closed
relations `has_condition`, `uses_context`, `narrows_to`, `constrained_by`, and
`under_grant`; structured principals reuse `acts_as`. Every fact cites the
record and its JSON location. The condition and principal profiles reject
unknown predicates, incomplete fact sets, inconsistent evidence state,
non-canonical targets, entity mismatch, and digest drift. They deliberately do
not evaluate conditions, attest grants, or enter the manifest-v1 analysis
profile.

## Gate 3 conditional trust semantics

The private consumer serializes and strictly rereads every condition and
context, reruns the closed condition IR profile, and requires a caller-supplied
evaluation date. It never reads the wall clock. Narrowing occurs only when all
of these statements hold:

- exactly one condition targets the tool and exactly one context matches its ID;
- target source and binding, predicate, and argument agree;
- both artifacts carry exact, accepted, unexpired evidence;
- the context's captured bytes match its reviewed digest;
- the context is `complete` and its entire class set is the condition's one class;
- the selected effect is strictly weaker than the manifest's default effect.

A representative capture, a complete mixed-class context, missing bytes, or
any trust failure leaves the tool at its strongest manifest effect and emits a
specific unresolved finding. This distinction matters: observing one `SELECT`
does not prove that production cannot issue `DROP`. The committed complete
SELECT-only context is explicitly synthetic and proves conservative analysis
semantics, not a real deployment restriction.

An applied decision retains the condition source, relevant condition fact IDs,
and the context completeness, class, evidence, and digest locations. The
existing reachability kernel then analyzes a temporary attenuated mandate; the
kernel itself is not forked.

## Gates

1. **Contract:** this document survives challenge against both fixtures.
2. **Records:** typed condition/delegation records, the condition-context
   artifact, strict reader, canonical fixtures, IR projection behind new
   registered relations. Split for review: gate 2a delivers the context and
   grant artifact readers with canonical synthetic fixtures (done); gate 2b
   delivers tool-side condition and structured-principal records plus their
   IR projection behind registered relations (done).
3. **Analysis:** conditional effects and delegation hops inside `reach` and
   `drift`, with provenance-cited counterexamples; all four graphs unchanged
   under conservative defaults. The private conditional reachability consumer
   is done; drift integration and delegation remain pending, with delegation
   blocked on genuine chain evidence.
4. **Public exposure:** CLI and schema-version bump only after failure
   behaviour and output stability reviews.

## Non-goals

No general expression language, no runtime policy evaluation, no credential
issuance or verification, no automatic inference of conditions from source,
and no widening of authority through either mechanism. Resource relationships
(bounded producers, binding lineage) stay a separate initiative; this contract
only borrows their eventual relation-registry mechanics.
