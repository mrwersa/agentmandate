# Verifying from OpenTelemetry traces

`mandate verify` is what keeps a manifest honest. A declaration nobody checks
drifts from the implementation the moment somebody ships a connector change.

Use `--otel` to read an OTLP JSON export instead of converting it to the
[neutral JSON Lines format](manifest.md#observed-calls-for-verify).

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
| `startTimeUnixNano` | recorded sort order, not independent causal-order proof | yes |

Both attributes are required on a tool-execution span by the convention, and
both are required here. A span carrying only a name is not treated as an
execution unless you pass `--lenient-tool-spans`, because inferring one from
the other is a guess.

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

## Trace grouping and execution identity

Spans are partitioned by `traceId` and each trace is verified independently.
This is an input grouping convention: use it only when a trace covers the
complete run whose limits you want to check. A trace ID does not establish
mandate identity or authorize a fresh budget. If one mandate spans several
traces, prepare a complete authoritative call record for that mandate instead.

Duplicate detection also uses the trace boundary. Repeated
`gen_ai.tool.call.id` values within a trace are treated as instrumentation of
one execution. That convention is unsuitable if a retry reuses the ID but
executes again. Preserve distinct execution identities or use the neutral
call format; the replay cannot recover an execution that the importer deduplicated.

## What is excluded, and what is carried

| Span | Treatment | Reason |
|---|---|---|
| `gen_ai.operation.name` is not `execute_tool` | excluded | Instrumentations often attach `gen_ai.tool.name` to the **chat** span that requested the call. Counting it doubles the value of one refund |
| A repeat of a `gen_ai.tool.call.id` within one trace | excluded | One call instrumented at both client and server is one call |
| Status is an error, on an **effect-bearing** tool | **carried as `errored`** | see below |
| Status is an error, on a read | carried, no finding | A read that failed changed nothing |

Every exclusion is counted and reported rather than silently dropped.

### An errored call is incomplete evidence, not an absent call

OpenTelemetry's error status means the **operation** ended with an error. It
does not establish that an irreversible effect failed to commit, and a timeout
is precisely the case where the write may already have landed.

So an errored write or value-bearing call produces an `errored_effect` finding
and a non-zero exit:

```text
VIOLATION  errored_effect   issue_refund   line 2
           the call ended in an error, and an error does not establish that
           the effect was not applied. This evidence cannot show the control
           held. Record whether the effect committed, or replay an
           authoritative effect log.
```

Its value is not accumulated either, because whether it was spent is exactly
what the evidence fails to establish. Retain authoritative evidence of whether
the effect committed. The current OTel adapter has no `committed` mapping;
adding an application attribute alone does not resolve `errored_effect`.
Use the authoritative effect log to prepare a reviewed neutral call record
when it establishes the outcome. Keep ambiguous outcomes unresolved.

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

Spans are sorted by recorded start time; ties keep document order. This is a
deterministic replay order, not proof of causal order or completed settlement.
Overlapping calls and inconsistent clocks require separate evidence before
the replay can be interpreted as the actual execution sequence.

## Scope

This reads an OTLP `ExportTraceServiceRequest` in JSON, either as one object or
as newline-delimited objects, which is what OpenTelemetry's file exporter
writes. It does not read protobuf, and it does not query a backend.

AgentMandate consumes traces. It does not become an observability backend,
store them, or query one.

The convention attribute names are pinned in one place in `agentmandate/otel.py`,
because most `gen_ai.*` attributes still carry Development stability badges and
can change without a major version bump.

## Machine-readable output

`--json` returns the conversion counts alongside the conformance result, so CI
sees the warnings that explain a suspiciously clean report:

```json
{
  "schema": "agentmandate.verify/v1",
  "conversion": {
    "total_spans": 5, "tool_calls": 3, "observations": 3,
    "traces": 1, "errored": 0, "duplicates": 0, "unmapped": []
  },
  "conformance": {
    "observed": 3,
    "conformant": false,
    "violations": [{
      "kind": "ceiling_exceeded",
      "tool": "issue_refund",
      "line": 3,
      "message": "cumulative 750 against scope 'case-4471' exceeds the declared ceiling 500"
    }]
  }
}
```
