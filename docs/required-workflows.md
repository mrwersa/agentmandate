# Keep required workflows during repair

Use `mandate remediate --required-workflows FILE` when a repair must preserve
specific ordered calls. Tool reachability alone is insufficient: a refund tool
with a zero ceiling is reachable but cannot perform a required £100 refund.
The checker rejects candidates that break the supplied path and still runs the
full bounded breach search on every candidate that passes.

The file describes **caller-supplied requirements**, not observations from a
live run. The library checks their conformance within manifest v1. It does not
execute the application, authenticate the reviewer, or prove business success.
Use the [trace guide](traces.md) for observed calls and the
[repair guide](remediation.md) for candidate generation and ranking.

## Try the refund requirement

The [synthetic requirement](../examples/remediation/required-refund.json)
asks to search for a case and issue one approved £100 refund:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool search_cases --keep-tool issue_refund --ceiling issue_refund=0 --ceiling issue_refund=50 --ceiling issue_refund=125 --required-workflows examples/remediation/required-refund.json
```

The £0 and £50 edits fail `workflow.ceiling-exceeded` at step 2 before candidate
reachability analysis. The £125 candidate preserves the supplied calls and
passes the full depth-eight recheck. The original breach remains in `baseline`
and the command exits 1. The candidate is truncated and breaches at depth ten;
workflow preservation does not make a bounded result complete.

The [joint requirement](../examples/remediation/required-joint.json) asks for
an item and two approved £1 payments against it. On the existing synthetic
ungated graph, approval plus a £2 ceiling preserves that path. A £0 ceiling
fails, and a newly required approval would fail a path whose `approved` is false.
The checker never inserts approval or changes an amount to make a path pass.

## Author a requirements file

The strict UTF-8 JSON root has exactly these fields:

| Field | Meaning |
|---|---|
| `schema` | `agentmandate.required-workflows/v1` |
| `agent` | The baseline manifest's agent name |
| `manifest_sha256` | Lowercase SHA-256 of the exact baseline file bytes |
| `reviewer` | Caller-supplied name identifying who chose these requirements |
| `reason` | Caller-supplied explanation of why these paths are required |
| `workflows` | Nonempty list of named ordered paths |

Calculate the baseline digest with `sha256sum` before filling the file. A
comment-only manifest edit invalidates the join too. Review the requirements
again against changed bytes; do not refresh the hash merely to clear the check.
The result separately pins the requirements file's own bytes. Digest equality
identifies the selected materials, not the truth of the annotations or the
identity of their author. There is no automatic acceptance or renewal here.

Each workflow has exactly `name` and a nonempty `steps` array. Names must be
unique. Agent, reviewer, reason, names, tool and principal strings must be
nonblank and contain no carriage return, newline or NUL. Each step has:

| Field | Requirement |
|---|---|
| `tool` | Declared tool name |
| `principal` | Its declared principal label, such as `caller` or `service` |
| `approved` | Explicit boolean; true when this path includes approval |
| `binding` | For spending calls, a zero-based integer selecting a held binding of the tool's `scope_key` |
| `value` | For spending calls, a quoted finite nonnegative decimal string |
| `currency` | For spending calls, the three-letter monetary currency |

A nonspending call omits monetary fields; `binding: null` is equivalent to
omission. A spending call needs all three monetary fields, even for zero value.
`value` and `currency` must appear together. Unknown fields, duplicate JSON keys,
empty paths, duplicate names and unsupported schemas are refused. Unquoted
numeric values are refused, avoiding precision loss during JSON decoding.

Binding indexes refer to model slots, not provider IDs. For a `case` scope,
`binding: 0` corresponds to the search witness label `case#1`; `binding: 1`
corresponds to `case#2`. Do not paste the witness label string into `binding`.
Every workflow starts with empty bindings, zero spend and zero effect counts.
Workflows are separate examples; their consumption is never added together.

## What the path check establishes

The checker visits calls in order. All declared scope requirements must
already be held before the call. A bounded producer creates its scope's first
binding once; an unbounded producer creates another on each call. As in the
search, production occurs before spending for a tool that does both. A spending
call can select only a binding already held at that point.

Spend is cumulative per **tool, scope and binding**. Two tools sharing one
scope do not share a ceiling. The run total includes every spending call.
Currency, principal and required approval must match their declarations.
Every call counts against its declared effect budget, including pure reads,
zero-spend calls and calls with no new monetary headroom. No-change calls remain
in the supplied path and count toward its full length.

A path must fit the selected search depth and conform to its numeric limits.
These are conformance checks, not new guards in the reachability kernel:
`limits.total` and `limits.effects` remain properties whose violation the
search can find. An invalid baseline requirement is a configuration error,
not a requirement the command silently drops. Fix the path or mandate intent
before requesting narrowing candidates.

Arithmetic uses the same isolated exact-context sizing as the search, extended
to include supplied amounts. Partial amounts are checked exactly; the checker
does not substitute greedy fills. Caller precision, exponent settings, traps
and flags remain unchanged. Representation exhaustion exits 2 without partial
output. Process time and memory limits still matter for widely separated
amounts; see the [search guide](search-performance.md).

## Read the result

Supplying `--required-workflows` selects `agentmandate.remediation/v3`, with or
without ceiling options. The unchanged `baseline`, lint, source digest, edit
semantics and original exit remain separate from requirements:

- `requirements` records the exact source and manifest digests, caller-supplied
  reviewer/reason, scope, and baseline path assessments.
- Each candidate's `required_workflows` contains every supplied path with
  `status: conformant_within_manifest_model`. This qualifies the claim inline.
- `requirement_rejections` lists screened edits and per-workflow assessments,
  with `stage: required_workflow_screen`. These records have not reached the
  full graph analyzer and are not repair candidates.
- `search.required_workflow_rejections` counts combinations refused by that
  screen. They still count in `combinations_examined`, but not in
  `candidates_analyzed`. Existing enumeration and display limits remain explicit.

A failed assessment reports its workflow name, full path length, and the first
failing call in `failure`. Step numbers are one-based; step 0 identifies a
whole-path depth failure. All supplied workflows must pass independently.
A bad path does not hide the other path assessments.

Failure rules cover `workflow.undeclared-tool`, `workflow.scope-unavailable`,
`workflow.principal-mismatch`, `workflow.approval-missing`,
`workflow.unexpected-spend`, `workflow.spend-missing`,
`workflow.binding-unavailable`, `workflow.currency-mismatch`,
`workflow.ceiling-exceeded`, `workflow.total-exceeded`,
`workflow.effect-budget-exceeded` and `workflow.depth-exceeded`.

Malformed files, wrong joins, arithmetic exhaustion or baseline paths that do
not conform exit 2 with empty stdout. Valid requests keep the baseline's exit:
1 for its reachable breach or lint error, 0 for a clean baseline. A valid
requirement never turns original findings into a green result.

## Compatibility and limits

Without the flag, v1 and v2 result bytes and exits are unchanged. Consumers must
support v3 before requesting workflow constraints. The
[before/after compatibility case](../tests/fixtures/remediation-v2-to-v3.json)
pins preserved baseline fields and surviving candidate semantics; the
[v3 baselines](../tests/fixtures/remediation-workflow-monetary-v3.json) cover
monetary, joint, limited and clean runs. Earlier inventories remain pinned.
The Python records are private, and these results are not authority inputs.

This checks the declared graph and supplied calls. It does not establish
provider resource identity, actual output values, fixed ownership, data flow,
amount-dependent tool enablement, live approval, reviewer authenticity,
external policy decisions, durable state or continuation safety. Environment
setup and application outcomes still need their own tests and review. Required
paths do not supply missing mandate-binding evidence or reuse historical
acceptance. Automated business correctness and global policy synthesis remain
outside this slice.
