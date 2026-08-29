# Bounded Producer and Quantity Evidence Audit

Status: **cardinality evidence gate not met**. This audit was completed on
29 August 2026. It separates three losses that look similar in a small
manifest—producer arity, binding cardinality, and value relationships—so the
next schema does not solve the wrong problem.

## Gate under review

The roadmap requires two independent real distortions:

1. a producer grants a finite number greater than one of authority-bearing
   bindings, while manifest v1 can express only one binding or an unbounded
   supply; and
2. authority is bounded by a reviewed quantity relationship such as collateral,
   conversion, or net exposure rather than by an integer count.

Each feature must remove a reproduced false path while retaining existing
breach detection. One graph cannot satisfy both gates, and a declared limit is
not evidence unless the pinned implementation enforces it.

## Existing graph audit

| Graph | Candidate | Decision |
|---|---|---|
| Coinbase AgentKit | Compound borrowing is collateral-limited; WETH wrapping is 1:1 with ETH balance; buy then sell exposes gross-versus-net ambiguity | **Quantity half identified.** These are genuine value relationships and explain why `unbounded: true` overstates authority. They do not independently prove finite binding cardinality. |
| AWS PostgreSQL MCP | `create_cluster` yields a job reference and cached database connection | **Producer arity, not cardinality.** Manifest v1 loses one of two different output kinds. It does not show a finite number greater than one of the same authority-bearing scope. |
| GitHub MCP | A workflow write may enable a trigger; triggers can repeat | **Not qualifying.** Workflow production depends on the path argument, while repeated irreversible calls are already represented by effect budgets. Neither establishes a finite produced set. |
| Sentry MCP | A hidden skill catalogue sits behind one dispatch tool | **Inventory/condition issue.** The partial catalogue does not establish a producer or an absence bound. |
| Initiative MCP | List tools return project, status, task, and initiative identifiers | **Bearer selection, not production.** Callers can supply identifiers directly; returning a finite page does not grant new authority. |
| AgentCore refund policy | One mapped tool has two representative request values | **Policy comparison only.** The managed decisions prove exact-request widening, not scope creation or a complete quantity domain. |

The distinction is load-bearing. AWS motivates a future multi-output record,
but treating two output *types* as a bound of two would lose their meanings.
Likewise, a search or pagination limit bounds response size, not authority, when
the consumer accepts caller-supplied IDs. A cardinality claim must change which
compound paths the deployment accepts.

## What AgentKit establishes

The reviewed [AgentKit evidence](evidence/agentkit/README.md#the-four-distortions)
documents three quantity shapes:

- borrowing cannot exceed authority derived from collateral;
- wrapping converts ETH to WETH 1:1 rather than minting unlimited value; and
- buying then selling may measure turnover or net exposure, which are different
  controls even when they use the same currency.

This is enough to retain the quantity half as a roadmap prerequisite. It is not
enough to select a record shape. The current fixture uses invented USD ceilings
and synthetic scope anchors, so implementation still needs a reviewed input
domain and a mechanically reproduced before/after path.

## Acceptance test for cardinality evidence

[Issue #125](https://github.com/mrwersa/agentmandate/issues/125) tracks the
next capture. It counts only if it includes:

1. a public, versioned producer and a reviewed deployment/run boundary;
2. a finite count greater than one, enforced by the pinned implementation;
3. bindings that gate downstream authority rather than ordinary returned data;
4. current analysis reporting a shortest path beyond the real bound, or
   collapsing an accepted multi-binding path to one;
5. an accepted control path at or below the same bound;
6. raw inventory and outcomes, digest-pinned without sensitive identifiers;
7. classified reviewer corrections and an explicit pass/falsification verdict;
   and
8. byte-identical conservative-default results for all existing graphs before
   any schema or analysis promotion.

Pagination, batch-size, result-count, or service-quota fields fail the gate
unless exhaustion alone rejects the reported authority path. A hand-written
quota or finite set may be a synthetic control, but cannot be the load-bearing
evidence.

## Decision

Do not design bounded-producer records yet. Keep the AgentKit quantity evidence
as one half of the prerequisite, track multi-output arity separately, and find
an independent finite-cardinality counterexample through issue #125. This keeps
the roadmap sequence evidence-first: the observed rejection selects the
minimum state transition, support, and completeness rules.
