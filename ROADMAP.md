# Roadmap

AgentMandate's centre stays narrow: derive what an agent may do from its tool
graph, then show how that authority changes between releases. Integrations are
useful when they feed that analysis. They are not a reason to become another
runtime proxy or general agent-security scanner.

This is direction, not a release promise.

## Current foundation: trustworthy authority analysis

Version 0.3.2 makes the existing gate dependable:

- fail-closed replay when control evidence is missing
- tool-contract and run-limit comparison across releases
- one search depth on both sides of a diff
- safe ingestion of untrusted MCP catalogues
- explicit handling of incomparable currencies and different agents
- reviewed test obligations reconciled against current reachable authority

## Next: easier adoption

1. **Framework inventory adapters.** Import tool catalogues from common agent
   frameworks while preserving a visible `REVIEW` marker for facts their
   schemas cannot supply.
2. **Trace adapters.** Convert OpenTelemetry and selected framework events into
   the strict replay format. AgentMandate should consume traces, not become an
   observability backend.
3. **Developer-native findings.** Add SARIF and a compact graph export so a
   widening path appears beside the pull request that introduced it.
4. **Manifest drift.** Compare the declared tool inventory with a discovered
   inventory and fail when implementation gains a tool the mandate omits.

These features overlap with mature CI and security tooling deliberately. The
new value remains the authority graph and its counterexamples.

## Then: widen the model where evidence demands it

Do not implement every candidate below in parallel. First collect tool graphs
from independent users and identify which abstraction forces them to distort a
real control. Expressiveness increases the search state and the annotation
burden, so a feature needs a concrete graph and counterexample before it earns
that cost.

### Bounded scope cardinality

The current `unbounded` flag distinguishes one binding from an unlimited
source. Real tools often expose a finite collection, such as at most ten cases
or one refund per transaction. A reviewed `max_bindings` bound is the first
candidate extension because it sharpens the existing scope model without
turning the manifest into a full application specification.

Per-customer or relational limits come later. They require resource identity
and relationships, not another integer placed beside the current type count.

### Resource relationships

Scope counts deliberately forget which customer owns a case or whether two
bindings refer to the same object. If real graphs show that this creates false
or missed paths, add a small reviewed relation vocabulary and preserve binding
provenance through tool transitions. Do not jump directly to arbitrary
preconditions and postconditions.

### Non-monetary effect budgets

Some authority limits count irreversible actions rather than currency, such as
accounts closed, credentials rotated, or external messages sent. Generalise
the current cumulative-value mechanism only when those limits share a clear,
reviewable accumulation rule. Confidentiality and data flow remain a separate
model rather than being disguised as a numeric budget.

### Data-flow reachability

Add reviewed source, transform, and sink labels so the analyser can detect a
path such as:

```text
read_customer_record -> summarise -> send_external_message
```

This is distinct from the current value and scope model. It should ship only
with counterexamples that remain understandable to a reviewer.

### Conditional and delegated authority

- represent selected state predicates such as case status and time windows
- model one agent delegating a bounded capability to another
- distinguish authority held by the caller, the agent workload, and a
  delegated downstream identity

The design constraint is the same as today: enough structure to find a real
compound path, without asking teams to formalise the entire application.

## Path to 1.0

AgentMandate reaches 1.0 after:

- the manifest and JSON outputs receive a compatibility audit
- fixtures from every supported schema version are exercised in CI
- at least one independent agent integration tests the model against a real
  tool graph
- search limits and worst-case behaviour are measured and documented
- security and trace-retention guidance receive an external review

The most useful contribution is a real graph the current model cannot describe
without distortion. Open an issue with that graph before proposing another
generic scanner rule.
