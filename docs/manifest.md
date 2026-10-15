# Manifest reference

A mandate manifest declares what an agent is permitted to do. The core analysis
commands read it; artifact validators and source scanning have separate inputs.

YAML is the documented format because a manifest is a hand-authored file that
lives beside CI configuration. JSON is accepted too, with no dependency beyond
the standard library. YAML flow mappings such as
`{agent: a, tools: [{name: t, effect: read}]}` use the optional YAML reader,
even though they begin with `{`. A `{`-leading mapping whose first key is
double-quoted selects JSON: a JSON syntax error is rejected rather than retried
as YAML. Use an unquoted first key for a YAML flow mapping. This keeps malformed
JSON numbers and YAML tags from silently changing a JSON declaration.

```bash
pip install "agentmandate[yaml]"   # YAML support
pip install agentmandate           # JSON only, no dependencies
```

## Top level

| Key | Required | Meaning |
|---|---|---|
| `version` | no | Schema version. Defaults to `2`. A build rejects a version it does not understand rather than guessing |
| `agent` | yes | The agent this mandate describes |
| `identity` | no | The workload identity the agent runs as, such as a SPIFFE ID. Recorded, not verified |
| `limits` | no | Bounds that apply to a whole run |
| `roles` | no | Role assignments, used by the separation-of-duties check |
| `tools` | yes | The tools the agent may call. At least one |

## `limits`

```yaml
limits:
  quantities: {value: { amount: 500, unit: GBP }}
  depth: 8
```

| Key | Meaning |
|---|---|
| `quantities` | Named cumulative budgets, each with an exact `amount` and explicit `unit`; quantities stay separate |
| `depth` | How many calls deep the search goes. Defaults to 8 |
| `effects` | Optional non-negative integer call limits by effect class (`read`, `write`, `irreversible`). An omitted class has no count limit |

For example, `effects: {irreversible: 3}` asks `reach` to find a sequence with
more than three irreversible calls. A zero limit allows no calls of that class
within the declared policy; it does not disable the tool in the deployment.

Depth is a real bound, not a formality. No breach at depth 8 is not proof that
none exists at depth 20, and the report says when the search truncated. Raising
it costs time exponentially, so raise it deliberately.

## `tools`

```yaml
tools:
  - name: issue_refund
    effect: irreversible
    principal: caller
    requires: [case]
    value_arg: amount
    scope_key: case
    quantity: value
    ceiling: { amount: 500, unit: GBP }
    requires_approval: true
```

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Tool name, unique within the manifest |
| `effect` | yes | `read`, `write`, or `irreversible` |
| `principal` | no | `caller` or `service`. Defaults to `caller`. A `service` principal on anything that writes is the confused-deputy shape |
| `requires` | no | Scopes the agent must already hold to call this. A bare string is accepted |
| `produces` | no | A scope this call mints a binding to |
| `unbounded` | no | Whether this tool can be called repeatedly to mint fresh bindings. Defaults to `false` |
| `quantity` | with a ceiling | Named accounting pool consumed by this tool |
| `value_arg` | no | Which argument supplies the consumed amount |
| `scope_key` | no | What the ceiling is measured against. Required whenever a ceiling is declared |
| `ceiling` | no | The most this tool may cumulatively spend against one binding of `scope_key` |
| `requires_approval` | no | Whether a human or independent authority must approve. Defaults to `false` |

`value_arg` and `ceiling` must be declared together. A ceiling with no value
argument bounds nothing, and a value argument with no ceiling is unbounded
spending, so the manifest rejects either on its own.

Use quoted amount strings when decimal precision matters, such as
`amount: "1.0000000000000000000000000001"`. The JSON reader preserves decimal digits; optional YAML readers may resolve or round
unquoted scalars before validation. The search preserves parsed
decimal values using exact arithmetic; its
[maximum-headroom argument](headroom-abstraction.md) explains why it fills
ceilings instead of trying every possible amount.

A quantity name identifies a shared accounting pool. Tools using the same name
must declare the same unit as each other and its optional mandate budget.
Inconsistent declarations remain loadable for lint, but reachability consumers
refuse them with exit 2. Different quantity names stay independent, including
GBP and USD pools in the same manifest. Units are case-sensitive; no conversion
or exchange rate is inferred. See [named quantity budgets](quantity-budgets.md).

### Scopes are types, not instances

Write `case`, never `case-4471`. The analysis reasons about "a case", so a
manifest that names real identifiers is both wrong and a data-handling problem.

Every required scope needs a producer in the manifest. If none exists, `lint`
reports `scope.missing-producer` as an error and exits 1. The requiring tool
cannot be reached from the model's empty initial bindings, so a clean `reach`
result does not assess it. Confirm the scope requirement and declare a genuine
producer, or remove an unsupported requirement. Producer existence alone does
not prove reachability: cyclic prerequisites can still prevent a call.

### Repeated scope production

A per-scope ceiling continues to bound each binding. If the agent can produce
fresh cases repeatedly, a £500-per-case ceiling permits spending against each
case separately; it does not itself bound the aggregate across cases.

```yaml
  - name: search_cases
    effect: read
    produces: case
    unbounded: true     # repeated calls can produce fresh case bindings
```

`reach` can find a sequence that exceeds a separately declared `limits.quantities`
while respecting every per-case ceiling. Exploration remains bounded by
`limits.depth`. Without a budget for a named quantity, repetition alone is not
a `quantity_budget` breach of the manifest.

## `roles`

```yaml
roles:
  proposer: [issue_refund]
  approver: [approve_refund]
```

Used by the separation-of-duties check. Declaring both a `proposer` and an
`approver` that the same agent identity can call is reported as an error,
because one identity holding both sides is not maker-checker. The approver has
to be a human or an independently authorised service the agent cannot invoke.

Declaring only one side produces no finding. There is nothing to conflict with.

## Effect classes

| Effect | Meaning | Consequence in the analysis |
|---|---|---|
| `read` | Returns data, changes nothing | Can still widen authority by producing scopes |
| `write` | Changes state recoverably | Reported per scope in an authority diff |
| `irreversible` | Cannot be undone by the system | Must declare `requires_approval` or `lint` fails |

Reversibility, not confidence, decides where a gate belongs. A model being sure
is not a reason to skip an approval on something that cannot be undone.

## A complete example

```yaml
version: 2
agent: dispute-resolver
identity: spiffe://bank/agents/dispute-resolver

limits:
  quantities: {value: { amount: 500, unit: GBP }}
  depth: 8

tools:
  - name: open_case
    effect: read
    produces: case

  - name: fetch_case
    effect: read
    requires: [case]

  - name: issue_refund
    effect: irreversible
    principal: caller
    requires: [case]
    value_arg: amount
    scope_key: case
    quantity: value
    ceiling: { amount: 500, unit: GBP }
    requires_approval: true
```

## Observed calls for `verify`

`mandate verify` reads JSON Lines, one recorded call per line. Blank lines and
lines beginning with `#` are skipped.

```jsonl
{"tool": "open_case", "scope": "case-4471", "principal": "caller"}
{"tool": "issue_refund", "scope": "case-4471", "value": "500", "unit": "GBP", "quantity": "value", "approved": true, "principal": "caller"}
```

| Field | Meaning |
|---|---|
| `tool` | The tool called. One the manifest does not declare is a violation |
| `scope` | The resource instance acted on. Required for a tool with a ceiling. Ceilings accumulate per scope |
| `value` | Value spent, read as an exact, finite, non-negative decimal. Required for a tool with a ceiling |
| `quantity` | Named pool; must match the tool declaration |
| `unit` | Declared unit; must match the tool ceiling |
| `approved` | Whether an approval was recorded |
| `principal` | Which identity the call ran as. Required for every declared tool |

Unlike a manifest, these records carry real identifiers, because they come from
real runs. Handle the file as you would the traces it was derived from.

`verify` fails closed when evidence needed by a declared control is absent. A
spending call without its scope, value, quantity or unit is non-conformant. A call
on a tool without a measured quantity must omit value, quantity and unit; any
of these fields makes that record non-conformant. A call
without its principal is also non-conformant. Malformed field types are usage
errors rather than values the verifier guesses or coerces. An empty trace
cannot establish conformance.
