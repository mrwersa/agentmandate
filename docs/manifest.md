# Manifest reference

A mandate manifest declares what an agent is permitted to do. Every command in
AgentMandate reads one.

YAML is the documented format because a manifest is a hand-authored file that
lives beside CI configuration. JSON is accepted too, and reading JSON needs no
dependency beyond the standard library.

```bash
pip install "agentmandate[yaml]"   # YAML support
pip install agentmandate           # JSON only, no dependencies
```

## Top level

| Key | Required | Meaning |
|---|---|---|
| `version` | no | Schema version. Defaults to `1`. A build rejects a version it does not understand rather than guessing |
| `agent` | yes | The agent this mandate describes |
| `identity` | no | The workload identity the agent runs as, such as a SPIFFE ID. Recorded, not verified |
| `limits` | no | Bounds that apply to a whole run |
| `roles` | no | Role assignments, used by the separation-of-duties check |
| `tools` | yes | The tools the agent may call. At least one |

## `limits`

```yaml
limits:
  total: { amount: 500, currency: GBP }
  depth: 8
```

| Key | Meaning |
|---|---|
| `total` | The most value one run may spend across every tool. This is what `reach` searches for a way to exceed |
| `depth` | How many calls deep the search goes. Defaults to 8 |

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
    ceiling: { amount: 500, currency: GBP }
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
| `value_arg` | no | Which argument spends value |
| `scope_key` | no | What the ceiling is measured against. Required whenever a ceiling is declared |
| `ceiling` | no | The most this tool may cumulatively spend against one binding of `scope_key` |
| `requires_approval` | no | Whether a human or independent authority must approve. Defaults to `false` |

`value_arg` and `ceiling` must be declared together. A ceiling with no value
argument bounds nothing, and a value argument with no ceiling is unbounded
spending, so the manifest rejects either on its own.

### Scopes are types, not instances

Write `case`, never `case-4471`. The analysis reasons about "a case", so a
manifest that names real identifiers is both wrong and a data-handling problem.

### `unbounded` is the field that matters

A per-scope ceiling is only a bound when the scope itself is bounded. If the
agent can mint cases at will, a £500-per-case ceiling permits £500 multiplied
by however many cases it opens.

```yaml
  - name: search_cases
    effect: read
    produces: case
    unbounded: true     # every ceiling scoped to `case` is now advisory
```

That is the composition `reach` exists to find. Both halves pass an individual
review.

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
version: 1
agent: dispute-resolver
identity: spiffe://bank/agents/dispute-resolver

limits:
  total: { amount: 500, currency: GBP }
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
    ceiling: { amount: 500, currency: GBP }
    requires_approval: true
```

## Observed calls for `verify`

`mandate verify` reads JSON Lines, one recorded call per line. Blank lines and
lines beginning with `#` are skipped.

```jsonl
{"tool": "open_case", "scope": "case-4471", "principal": "caller"}
{"tool": "issue_refund", "scope": "case-4471", "value": "500", "approved": true}
```

| Field | Meaning |
|---|---|
| `tool` | The tool called. One the manifest does not declare is a violation |
| `scope` | The resource instance acted on. Ceilings accumulate per scope |
| `value` | Value spent, read as an exact decimal |
| `approved` | Whether an approval was recorded |
| `principal` | Which identity the call ran as |

Unlike a manifest, these records carry real identifiers, because they come from
real runs. Handle the file as you would the traces it was derived from.
