# Verifying from OpenTelemetry traces

`mandate verify` is what keeps a manifest honest. A declaration nobody checks
drifts from the implementation the moment somebody ships a connector change.

Until now it needed a bespoke JSON Lines file. Teams have traces.

```console
$ mandate verify mandate.yaml --otel trace.json \
    --map scope=app.case.id \
    --map value=app.refund.amount \
    --map currency=app.currency \
    --map approved=app.approved \
    --map principal=app.principal
```

```text
read 5 span(s), 3 tool call(s), 3 observation(s)

replayed 3 observed call(s)
VIOLATION  ceiling_exceeded   issue_refund           line 3
           cumulative 750 against scope 'case-4471' exceeds the declared ceiling 500
```

## What the conventions give you, and what they do not

OpenTelemetry's GenAI semantic conventions describe what a tool call **was**:

| Attribute | Meaning | Read automatically |
|---|---|---|
| `gen_ai.operation.name` | `execute_tool` marks the span | yes |
| `gen_ai.tool.name` | which tool ran | yes |
| `startTimeUnixNano` | call order | yes |

They do not describe what a mandate needs in order to check a **control**:

| Field | Why a mandate needs it | Source |
|---|---|---|
| `scope` | ceilings accumulate per resource | your application |
| `value` | how much was spent | your application |
| `currency` | amounts in two currencies cannot be summed | your application |
| `principal` | whose authority the call spent | your application |
| `approved` | whether a gate actually held | your application |

Those are application facts. An exporter either recorded them or it did not, so
each needs an explicit `--map`. **Nothing is guessed.**

## Missing evidence fails closed, on purpose

Run it without mappings and you get this:

```text
read 5 span(s), 3 tool call(s), 3 observation(s)
  no attribute mapped for: scope, value, currency, principal, approved.
  verify will fail closed on any control that needs them.

VIOLATION  missing_principal  open_case    line 1
VIOLATION  missing_approval   issue_refund line 2
VIOLATION  missing_scope      issue_refund line 2
```

That is the correct outcome rather than an inconvenience. The trace genuinely
does not establish that the approval held, so reporting a pass would be a
claim the evidence never supported.

## The counts are part of the result

The summary prints before the verdict for a reason. Three observations
recovered from four hundred spans is usually a mapping mistake, and a clean
report over almost no evidence should not read as success.

## Inspecting the conversion

```console
$ mandate verify mandate.yaml --otel trace.json --map … --emit observed.jsonl
```

`--emit` writes the plain replay format, so you can read what the trace
actually supported and re-run `--traces observed.jsonl` to get identical
results. An absent field stays absent rather than becoming `null`.

## Ordering

Spans are sorted by start time, because cumulative ceilings accumulate in the
order calls happened rather than the order a collector wrote them. Ties keep
document order.

## Scope

This reads OTLP JSON, the format the OTLP/HTTP exporter and `otel-cli` produce
and every collector accepts. AgentMandate consumes traces. It does not become
an observability backend, store them, or query one.

The convention attribute names are pinned in one place in `agentmandate/otel.py`,
because most `gen_ai.*` attributes still carry Development stability badges and
can change without a major version bump.
