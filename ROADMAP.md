# Roadmap

AgentMandate's centre stays narrow: derive what an agent may do from its tool
graph, then show how that authority changes between releases. Integrations are
useful when they feed that analysis. They are not a reason to become another
runtime proxy or general agent-security scanner.

This is direction, not a release promise.

## Now: trustworthy authority analysis

Version 0.2 makes the existing gate dependable:

- fail-closed replay when control evidence is missing
- tool-contract and run-limit comparison across releases
- one search depth on both sides of a diff
- safe ingestion of untrusted MCP catalogues
- explicit handling of incomparable currencies and different agents

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
