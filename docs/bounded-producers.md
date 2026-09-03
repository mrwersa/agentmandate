# Bounded Producer Contract

Status: **experimental; gates 1 through 3 complete; Gate 4 exposure deferred**.
This is the contract for
[#128](https://github.com/mrwersa/agentmandate/issues/128). It defines the
minimum trust and analysis contract selected by the
[AWS IAM cardinality evidence](evidence/aws-iam-access-keys/README.md). It does
not change manifest version 1, the analyzable Authority IR profile,
reachability, or any public CLI.

The roadmap initiative contains two different losses. This contract addresses
finite **binding cardinality** only. AgentKit's collateral, conversion, and
net-exposure evidence remains a separate **quantity** track; it must not be
encoded as a count.

## Question and invariants

The first consumer answers one narrow question:

> For this reviewed producer, output scope, resource partition, and run
> boundary, how many successful authority-bearing bindings can coexist?

The answer may narrow an existing `unbounded: true` producer. It never adds a
tool, output scope, effect, principal, or binding absent from reviewed mandate
intent. Missing or ineligible evidence retains today's unbounded analysis and
adds an unresolved finding; it never manufactures a smaller clean graph.

Three neighboring concepts remain distinct:

- **Arity** is how many different output kinds one successful call returns.
- **Cardinality** is how many bindings of one output kind may coexist inside a
  reviewed partition.
- **Quantity** is a value relationship such as collateral, conversion, or net
  exposure.

Effect budgets count successful calls with an effect. Inventory pagination,
API rate limits, and response sizes constrain none of these authority sets.

## Producer-boundary artifact

The private `producer_boundary_version: 1` artifact stays separate from the
mandate. Reviewed intent says a tool may produce a scope; observed evidence
says a particular deployment enforces a finite boundary.

```json
{
  "producer_boundary_version": 1,
  "id": "producer-boundaries/iam-user-access-keys",
  "adapter": {
    "name": "agentmandate.producer-boundary",
    "version": 1
  },
  "target": {
    "source": "docs/evidence/aws-iam-access-keys/capture.py",
    "binding": "create_access_key",
    "producer": "awslabs.iam-mcp-server",
    "producer_version": "1.0.11"
  },
  "partition": {
    "argument": "user_name",
    "binding": "reviewed-iam-user"
  },
  "output": {
    "scope": "access_key",
    "capacity": {
      "kind": "concurrent",
      "maximum": 2
    }
  },
  "run_boundary": {
    "inventory": ["create_access_key"],
    "inventory_completeness": "complete",
    "release_tools": [],
    "release_completeness": "complete"
  },
  "controls": {
    "accepted_through": {
      "count": 2,
      "source": "source:outcomes",
      "location": "/outcomes/1"
    },
    "exhausted_at": {
      "attempt": 3,
      "reason": "capacity_exhausted",
      "source": "source:outcomes",
      "location": "/outcomes/2"
    }
  },
  "sources": [
    {
      "id": "source:catalogue",
      "kind": "tool-catalogue",
      "role": "upstream-inventory",
      "locator": "docs/evidence/aws-iam-access-keys/catalogue.json",
      "content_sha256": "6ad70d0ecf3d05e8e9e2b08a52e7d2b8099954b586f52c6bd68bc3d99e5cff3c"
    },
    {
      "id": "source:outcomes",
      "kind": "producer-outcomes",
      "role": "capacity-controls",
      "locator": "docs/evidence/aws-iam-access-keys/capture.json",
      "content_sha256": "199f47e9bc87d39ab129bcd01ab69200326d759e1621cfdc5c5abfa9511fb3c8"
    },
    {
      "id": "source:adapter",
      "kind": "capture-adapter",
      "role": "selected-run-boundary",
      "locator": "docs/evidence/aws-iam-access-keys/capture.py",
      "content_sha256": "ace01427863ddeb8880ed1f42ed8e1a8dd6a6cc1fbaeb7c856967708120d0b88"
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

The example shows the reviewed record shape. Gate 2a's canonical migration
fixture is normative for the committed IAM evidence. The strict reader uses
exact field sets, immutable canonical
collections, lowercase SHA-256 digests, repository-relative POSIX locators,
non-empty stripped identifiers, positive integer maxima, and one typed error
boundary that never echoes rejected values. It hashes caller-supplied bytes
only and reads neither files, networks, credentials, nor clocks.

## Gate 2a implementation

The private `agentmandate._producer` module implements boundary version 1. Its
reader canonicalizes set-like inventory, release-tool, and source collections;
requires one source for each of upstream inventory, capacity controls, and the
selected run boundary; checks control references; and keeps structural validity
separate from evidence acceptance.

The canonical migration consumes exactly three caller-supplied sources: the
29-tool catalogue, sanitized live outcome, and capture adapter. It verifies
their reviewed digests, rechecks the selected tool schema, two authenticated
successful productions, exhaustion-only third rejection, shared principal,
cleanup, sanitization, package revision, and deployment controls, then emits
`tests/fixtures/producer-boundary-iam-v1.json`. Migration evidence remains
`unreviewed`: byte identity cannot manufacture an accountable reviewer or
expiry. No reader path opens a locator or reads a clock.

Gate 2a adds no analysis, public Python export, manifest meaning, or CLI
surface. Those remain behind their separate gates.

## Gate 2b implementation

The private reader projects each boundary into a closed standalone Authority
IR profile. It registers `bounds_producer`, `bounds_output`, and
`partitioned_by` with typed endpoints, emits one boundary plus its tool, scope,
and reviewed partition-binding entities, and preserves capacity, controls,
run-boundary completeness, original sources, and evidence state as explicit
facts. One producer-boundary source pins the record bytes, adapter version,
producer revision, and a semantic digest recomputed over entities, facts, and
edges.

The producer-specific validator first applies generic IR structural checks,
then reconstructs the strict boundary record and verifies the complete entity,
fact, evidence, relation-support, content-digest, and semantic-digest sets.
This makes the projection portable without making it authority: generic
manifest-v1 reachability explicitly rejects the standalone source profile.
Gate 2b adds no private narrowing analysis, manifest meaning, public export, or
CLI surface.

## Gate 3 implementation

The private `analyse_producers` consumer canonicalizes every boundary through
serialization and the strict reader, regenerates and validates its closed IR
profile, verifies the exact caller-supplied source bytes, and joins it to an
explicit caller-selected deployment, producer revision, output, and reviewed
partition. It also requires an existing unbounded mandate producer, complete
selected inventory, complete release classification, no reachable releaser or
competing producer of the output scope, and current exact accepted evidence.

Eligible records supply per-tool capacity to the existing breadth-first
search. Once the producer has minted `maximum` live bindings, its next call is
unavailable before reachability, effect counting, or state transition: the
service rejected that attempted production, so it cannot support a successful
path. Records that are absent, duplicate, competing, expired, incomplete,
unreviewed, mismatched, lifecycle-ambiguous, or source-unverifiable retain the
unmodified manifest analysis and produce provenance-bearing findings.

The IAM maximum-two case removes the modeled third successful creation while
retaining the first two. Test-only maxima one and three exercise both sides of
the transition; they are controls, not evidence claims. The committed
migration remains unreviewed and is therefore refused until a caller supplies
an accountable accepted review. Gate 3 adds no public API, manifest field, CLI
surface, runtime enforcement, reservation, or release semantics.

## Scope of a bound

Every part of the boundary identity is load-bearing:

- `target` joins the source locator, tool binding, producer identity, and
  producer revision. The IAM 1.0.11 claim cannot attach to 1.0.23, whose
  response redacts the credential.
- `partition` says where the service applies the count. Two keys **per IAM
  user** must never become two keys across every user or two keys per caller.
  The binding is a reviewed alias; raw resource IDs and secret-shaped values
  are forbidden.
- `output.scope` must equal the mandate tool's declared `produces` value. A
  declaration cannot introduce or rename authority.
- `capacity.kind` is closed to `concurrent` in v1. `maximum` counts distinct
  simultaneously live bindings, not attempts, historical creations, or
  effect calls.
- `run_boundary` establishes whether the search state is monotone. Complete
  selected inventory and complete release classification must show that no
  reachable transition releases or replenishes the capacity during the run.
- `controls` names the accepted maximum and the next exhaustion observation by
  source ID and JSON Pointer. The maximum fact cannot float free of the raw
  outcomes that selected it.

The IAM service permits creation after a key is deleted. The evidence adapter
exposes no deletion transition, so its selected graph is monotone even though
the service lifecycle is not. A future graph containing `delete_access_key`
cannot reuse this v1 narrowing: it remains unbounded with a named lifecycle
finding until search models release and replacement explicitly.

The full catalogue records upstream inventory; it does not establish the
selected run boundary. The digest-pinned adapter source and its reviewed
one-tool manifest establish that separate fact. An implementation must verify
both roles instead of silently shrinking the upstream catalogue.

Claims for different producer revisions are separate observations and are
never unioned; only the exact selected revision participates. Two eligible
declarations for the same revision, target, and partition that disagree are a
conflict. Duplicate IDs, mismatched selections, or multiple records competing
for one tool block every narrowing on that tool.

## Trust and eligibility

Structural validity makes a boundary transportable, not trustworthy. Every
consumer serializes and strictly re-reads the record, verifies every supplied
source byte, projects and validates its closed IR profile, and then requires:

1. exact target, producer revision, partition, output scope, and selected live
   binding matches;
2. a mandate tool already declaring the same output and `unbounded: true`;
3. complete selected inventory containing the target and complete release
   classification containing no reachable releaser;
4. reproduced accepted outcomes through `maximum` and an exhaustion-only
   rejection at `maximum + 1` for the same partition;
5. exact, accepted evidence with reviewer and expiry; and
6. caller-supplied `as_of` as a `date`, with `as_of <= expires`. A `datetime`
   is rejected and the wall clock is never consulted.

The outcome requirement prevents service documentation or a hand-written
quota from becoming authority evidence. Partial captures may remain visible as
observations but cannot reduce reachability. Expired, contested, heuristic,
digest-mismatched, source-mismatched, selection-mismatched, incomplete, or
lifecycle-ambiguous records produce specific findings and retain the strongest
manifest result.

Malformed structure is a typed usage error. A structurally valid record that
fails trust is an analysis finding with complete output. This preserves the
same validate-versus-authority boundary used by inventory, conditions,
delegations, and managed Cedar evidence.

## Analysis semantics

The private consumer combines a mandate with zero or more eligible producer
boundaries. With no records, `analyse(mandate)` remains byte-identical.

For an eligible boundary with maximum `N`, the search records how many live
bindings that exact boundary has minted. The producer transition is successful
only while the count is below `N`; the next transition is unavailable because
the reviewed service boundary rejects it. Other tools, effects, scopes,
budgets, approvals, and producers retain existing semantics.

This is stricter than merely suppressing a new binding after the call. A
rejected production is not a successful effectful transition, so it cannot be
used to construct a path or breach. The result should therefore remove the IAM
fixture's third `create_access_key` step while preserving its accepted first
and second steps. Synthetic controls at maxima one and three test both sides of
the state transition; only the real maximum two is evidence-bearing.

A cardinality boundary is not a least-privilege recommendation. It reports the
strongest successful compound path under reviewed enforcement evidence. It
does not reserve capacity, prevent races, predict external actors, or guarantee
that a call observed after analysis will succeed.

## Authority IR profile

Gate 2b projects the artifact through a standalone profile, not the analyzable
manifest-v1 profile. Its entities are producer boundary, tool, output scope,
and partition binding. Its source relations are:

| Relation | Endpoints | Cardinality and support |
|---|---|---|
| `bounds_producer` | producer boundary → tool | one/single; target and selected-inventory facts |
| `bounds_output` | producer boundary → scope | one/single; output-scope and capacity facts |
| `partitioned_by` | producer boundary → resource binding | one/single; partition argument and reviewed alias facts |

Capacity kind, maximum, inventory completeness, release completeness, producer
revision, and evidence state remain facts supporting those edges. The profile
has one source adapter/version and a recomputed semantic digest. Generic IR
validation proves structure; the closed producer validator proves these
semantics. `_analyse_ir` continues to reject the standalone profile. Only an
explicit producer consumer may combine it with manifest authority.

The registry now fixes those relation names and endpoints for the private
profile. No derived relation is needed for gate 2b. Gate 3 may add a
provenance-bearing `bounded_by` result edge only if its support names the
manifest production, boundary, partition, verified outcome, and eligibility
facts needed to replay the narrowing.

## Quantity track stays separate

AgentKit identifies three real quantity questions: collateral-limited
borrowing, 1:1 ETH/WETH conversion, and gross-versus-net exposure. None is a
finite binding set. Reusing `maximum` would discard units, valuation time,
conversion direction, price/oracle provenance, and aggregation semantics.

No quantity record is proposed in gate 1. Before that track selects a shape it
still needs a reviewed operational input domain and a reproduced before/after
path for at least one of:

- conservation under a fixed-ratio conversion;
- a ceiling derived from reviewed collateral and valuation evidence; or
- gross versus net aggregation under one named control.

The eventual vocabulary must be closed and typed, use decimal strings, carry
units and provenance, and fail to today's unbounded/value-conservative result
when any operand is missing. It is not an arbitrary formula evaluator,
portfolio system, price oracle, or general accounting language.

## Delivery gates

1. **Gate 1 — contract (complete):** challenge this scope, especially partition identity,
   concurrent versus cumulative semantics, monotone-run eligibility, and the
   separation from quantity.
2. **Gate 2a — reader and migration (complete):** a strict private boundary reader,
   canonical IAM migration fixture, caller-bytes digest verification, exact
   outcome controls, and adversarial record tests. No analysis.
3. **Gate 2b — IR projection (complete):** register the minimum source relations, validate
   a closed standalone profile and semantic digest, and prove manifest
   `reach --ir` refuses it.
4. **Gate 3 — private analysis (complete):** consume only re-read/profile-validated
   boundaries; reproduce maximum two, synthetic one/three controls, conflicts,
   expiry, selection mismatch, incomplete inventory, release ambiguity, and
   conservative fallback. All seven real graphs remain byte-identical with no
   boundary input.
5. **Gate 4 — public exposure review (complete; exposure deferred):** the
   [recorded review](bounded-producer-gate-4-review.md) accepts the private
   semantics but requires an accountable clean fixture, stable finding codes
   and result envelope, explicit composition refusal, and CLI failure tests
   before choosing any public surface.

Quantity records follow their own evidence-driven gates and do not delay the
finite-cardinality reader. Finite cardinality remains private after its public
review deferred exposure; the quantity track has not selected a contract.

## Explicit non-goals

- changing manifest v1 or interpreting `unbounded` as a number;
- inferring a bound from documentation, schemas, pagination, quotas, or tool
  names without reproduced exhaustion;
- producer arity or multi-output records;
- cumulative call budgets, API throttling, or response-size limits;
- release, replacement, revocation, reservation, or concurrent-runtime
  coordination;
- raw resource identifiers, credentials, or secret-shaped partition values;
- a general constraint solver, expression language, or accounting engine; and
- presenting the historical IAM MCP 1.0.11 result as current 1.0.23 behavior.
