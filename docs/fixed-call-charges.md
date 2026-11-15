# Charge more than one budget for a tool call

Use `fixed_charges` when a completed call consumes a known constant quantity
alongside its variable amount. An export can consume records from its amount
argument, one request and two compute units. Each named pool is accounted for
independently; no conversion or exchange rate is inferred.

```yaml
version: 3
agent: batch-export
limits:
  depth: 4
  quantities:
    exported_records: {amount: "5", unit: record}
    requests: {amount: "2", unit: request}
    compute: {amount: "5", unit: compute_unit}
tools:
  - name: open_batch
    effect: read
    produces: batch
    unbounded: true
  - name: export_records
    effect: irreversible
    requires_approval: true
    requires: [batch]
    scope_key: batch
    value_arg: records
    quantity: exported_records
    ceiling: {amount: "4", unit: record}
    fixed_charges:
      requests: {amount: "1", unit: request}
      compute: {amount: "2", unit: compute_unit}
```

The ceiling limits the cumulative **variable argument amount** against one
batch. It does not make later calls free. After exporting four records, another
call can export zero while still consuming one request and two compute units.
A tool with only fixed costs needs no amount argument or per-binding ceiling.

## Run the example

```bash
mandate reach examples/fixed-call-charges/manifest.json --json
mandate verify examples/fixed-call-charges/manifest.json --traces examples/fixed-call-charges/trace.jsonl --json
```

Both commands exit 1. Within four calls, reachability finds a maximum of eight
records, three requests and six compute units, and a breach for each pool.
These maxima need not occur on one path. Eight records require two batch-opening
and two export calls; three requests require three exports after one opening.

The trace contains three completed exports against one batch, with variable
amounts four, zero and zero. Replay accounts for four records, three requests
and six compute units. The request and compute budgets fail even though the
variable ceiling and record budget hold.

## Declare exact, fixed costs

Each entry is a positive `Quantity` with an exact amount and a unit. Zero budgets
and zero variable amounts are supported; fixed entries themselves must be
positive. Use quoted decimal strings. Units are case-sensitive and must agree
for every contribution to one pool. Names distinguish pools even when their
units match.

A fixed charge may use the variable pool's name. Both contributions then count
toward that pool's mandate budget, but the per-binding ceiling still limits only
the variable argument. Other tools can also consume the same pool. A pool without
a budget is tracked without inventing a limit.

Fixed charges do not depend on input values, which binding was selected, review
approval or the effect class. A reviewed condition narrowing a tool to `read`
does not remove its costs. A reviewed producer refusing a call before execution
does not create a charge.

The declarations are reviewed model assumptions, not measured resource usage.
This slice does not infer token-per-record rates, discounts, refunds, concurrent
gauges, time windows or multiple variable amount arguments.

## Replay and required paths

One trace record represents one completed call. Fixed costs come from the
manifest, so do not add separate cost records or supply them as the variable
`value`. Trace value, quantity, unit and scope still describe the variable
argument only. Fixed-only calls omit those fields. Duplicate completion records
would count as duplicate calls; collection and event identity remain the caller's
responsibility.

An errored charged call does not establish whether consumption committed.
Replay reports `errored_effect` and cannot claim conformance; it does not assume
a refund or zero cost. Use authoritative completion/meter records when failures
or retries can incur charges. This model does not establish their ordering or
authenticate the trace.

Required workflows derive fixed costs in exactly the same way. A path can fail
its request budget with a `workflow.quantity-exceeded` result even when every
variable amount fits. Existing workflow annotations retain their own schema;
they must pin the new manifest bytes rather than reusing a stale digest.

## Compare and repair

`diff` compares declared fixed charges even for an unreachable tool. An added
or increased cost is widening. Reducing a positive cost in the same pool and
unit is narrowing. Removing accounting from a retained tool, reassigning its
pool or changing its unit requires review and is conservatively widening;
deleting the entire tool is a capability reduction. Reachable maxima and
witnesses remain separate from those declared changes.

Repairs keep fixed rates unchanged. Removing a tool removes its capability and
costs together, subject to structural and required-path checks. Adding approval
or reducing a variable ceiling cannot erase charges on retained calls.
Discovery can therefore finish with no feasible ceiling in its declared domain
when a fixed-cost budget remains exceeded. That is not a proof that no other
policy repair exists.

## Artifact boundaries

Manifest version 3 is the only current reader. Fixed-charge declarations require
explicit `version: 3`; old builds reject that version instead of silently
discarding the new field. Unknown fields and duplicate JSON/YAML keys are errors.
Existing declarations without fixed charges default to the current version,
but explicit versions 1 and 2 are refused. There is no compatibility path.

IR keeps its generic graph version 2. The manifest adapter advances to 4 and
the defaults adapter to 3, with a `fixed_charges` fact for every tool, unit checks
and breach provenance. Older closed manifest profiles cannot stand in for this
projection. Scenario witnesses use `agentmandate.scenarios/v3` and retain a
structured cost map for every charged step.

Stateless Cedar and Rego exports cannot maintain cumulative consumption. A
`tool.fixed_charges` loss refuses default export; explicit partial export still
exits 1. Scalar accounting and handover readers refuse fixed costs outside their
measurement domains. No capture acceptance, binding or review is extended to
these charges.

Current synthetic fixtures were rebuilt for this model. Original captures,
signed historical materials and acceptance records remain unchanged. After
updating a current declaration, rerun its checks and review new pins; do not edit
archived evidence to make it pass the current reader.

Both released and proposed inputs must use the current model in `diff`, `review`
and the Action. Prepare reviewed v3 annotations for the selected baseline commit
as well as the proposal; changing only the proposal cannot make a v2 baseline
readable. Regenerate their IR and workflow pins from the exact new bytes. This
is a new model annotation, not a renewal or conversion of historical acceptance.
