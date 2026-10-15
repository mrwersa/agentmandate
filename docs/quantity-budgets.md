# Named cumulative quantity budgets

Use quantities to bound how much an agent may consume across a mandate. Money,
exported records, generated tokens, storage written and compute consumed use the
same model. Each quantity has its own name, unit and optional cumulative budget.

```yaml
version: 2
agent: batch-assistant
limits:
  depth: 4
  quantities:
    exported_records: {amount: "1000", unit: record}
    generated_tokens: {amount: "20000", unit: token}
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
    ceiling: {amount: "800", unit: record}
```

The export tool may consume at most 800 records cumulatively against one batch.
Opening a second batch supplies fresh per-batch capacity. Two individually legal
exports can therefore exceed the mandate's 1,000-record budget. The analyzer
reports that path; it does not enforce the budget at runtime.

Run the [complete example](../examples/quantity-budgets/manifest.json):

```bash
mandate reach examples/quantity-budgets/manifest.json --json
```

The example has record and token breaches, each with its own counterexample.
Exit 1 is expected. A maximum for each quantity may come from a different path;
`max_quantities` is not a claim that all maxima are attainable together.

## Choose names and units

A name identifies an accounting pool. Tools declaring the same quantity share
its mandate budget. Different names stay separate even when their units match:
`public_records` and `restricted_records` do not merge just because both use
`record`. All ceilings and the budget for one name must use exactly the same
unit. Units are case-sensitive labels; the analyzer neither converts units nor
infers exchange rates.

Money uses this same structure, for example:

```yaml
limits:
  quantities:
    refund_value: {amount: "500", unit: GBP}
```

A tool consuming this pool declares `quantity: refund_value` and a ceiling with
`unit: GBP`. A different pool may use USD in the same manifest. Their amounts
are never added or compared to each other.

Amounts are finite, non-negative exact decimals. Use quoted decimal strings to
preserve the digits supplied by your application. One tool declares one measured
quantity and one amount argument; several tools may consume the same quantity.
A quantity without a mandate budget is still tracked and reported, but no
cumulative-budget finding is invented for it. Zero is a real budget.

## Follow quantities through the workflow

- `lint` reports inconsistent units within a named quantity. `reach` refuses
  incompatible accounting rather than publishing a partial result.
- `reach` returns separate `max_quantities` and `quantity_budget` findings.
- `diff` compares each declared quantity budget independently of witnesses.
  Raising or removing a budget widens authority; adding or reducing one narrows
  it. Reassigning a tool to another pool or changing a unit requires review.
- `verify` checks recorded `quantity`, `unit`, value and scope, then accumulates
  each pool separately. Missing identity or units cannot establish conformance.
  Calls on tools without a measured quantity must omit value, quantity and unit.
- IR export and analysis preserve quantity assignments, units and budgets.
- Required workflows check each amount against its per-binding ceiling and
  named budget. Remediation and ceiling discovery recheck every pool, keep the
  original budgets fixed and never sum different units to rank a proposal.
- Stateless Cedar/Rego exports disclose that cumulative quantity budgets need
  execution history. Syntax-valid policy does not supply that history.

The search still uses a fixed call-depth bound. A clean result at one depth is
not a proof for longer sequences. Ceiling discovery's step controls proposed
ceilings; it does not make runtime amounts indivisible.

## Boundaries

This is additive consumption in one modeled mandate. It does not model timed
rates, renewal windows, concurrent gauges, negative refunds, recovery of quota,
conversion between pools, argument-dependent production or several simultaneous
quantity charges on one tool call. Declare those semantics only when a future
contract can check them. Effect-class call budgets remain available separately
through `limits.effects`.

This alpha model replaces the money-only manifest: current inputs use manifest
version 2, `Quantity(amount, unit)`, `limits.quantities` and `max_quantities`.
There is no `Money` alias, `limits.total` fallback, currency-field alias in
manifests or replay, or legacy remediation output mode. Historical captures retain their original bytes
and native currency fields; they do not become current manifests or acquire new
acceptance through this change.

Evidence readers retain their own reviewed input domains. In particular, scalar
handover and principal-accounting attachments use scoped integer measurements;
adding a decimal quantity to a manifest does not widen those evidence contracts
or establish continuity for it.
