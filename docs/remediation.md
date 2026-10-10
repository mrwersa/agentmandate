# Find repair candidates for a breach

Use `mandate remediate` after `reach` finds a breach in a reviewed manifest.
The command explores tool removals and approval requirements, rechecks the
whole remaining graph, and ranks candidates by edit count, lost reachable
tools and their effect classes. It leaves the source file unchanged.

## Try the refund example

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund
```

The baseline permits two refunds against different cases, exceeding the
500 GBP total. With `issue_refund` kept reachable, the first candidate removes
`search_cases`. The remaining `open_case` tool produces one binding, so the
refund ceiling now bounds the total in this declared model. Removing the refund
tool is another possible repair when `--keep-tool` is omitted; it has an
obvious functional cost.

The command still exits **1**, because the original manifest has a breach.
Finding a candidate does not accept or apply it. Adding approval to an ungated
irreversible tool can remove its ungated-effect finding, but approval does not
stop cumulative spending or repeated effects in manifest v1. Each candidate
must survive the full reachability check, including those budgets.

For machine-readable results:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund --json
```

The result uses `agentmandate.remediation/v1`. `input.manifest_sha256` identifies
the exact source bytes. `baseline` is the unchanged Authority result at the
selected depth; `baseline_lint` keeps the separate single-manifest findings.
Each candidate includes edits, authority impact, a complete semantic manifest,
its rechecked Authority, and remaining lint findings. The manifest retains
identity, limits, principals, effects, scope declarations, monetary ceilings,
and surviving role assignments. Removing a tool also removes its role
memberships, listed explicitly under `impact.removed_role_members`. Comments
and other source formatting are not retained.

## Choose what the search may change

| Option | Default | Meaning |
|---|---:|---|
| `--depth` | Manifest depth | Reachability depth for the baseline and every candidate |
| `--max-edits` | 2 | Maximum tool edits per combination |
| `--max-evaluations` | 128 | Maximum combinations examined, including rejected combinations |
| `--max-candidates` | 5 | Maximum ranked candidates returned |
| `--keep-tool NAME` | None | Preserve this tool's reachability at the selected depth; repeat as needed |

A kept tool must exist and be reachable in the baseline. Reachability does
not establish that a required business scenario still succeeds. Check those
scenarios separately before choosing a candidate.

Supported edits are `remove_tool` and `require_approval`; the latter applies
only to currently ungated irreversible tools. Combinations enumerate increasing
edit counts, then tool names and edit kinds. Candidates rank by fewer edits,
fewer lost reachable tools, then the effect classes of those lost tools: prefer
losing reads over writes over irreversible capabilities. For multiple losses,
compare the strongest lost effect first, then the next strongest. Fewer removals
and the same lexical tie-break follow. This heuristic does not establish business
priority; use `--keep-tool` to preserve named capabilities and check required
scenarios separately. Candidates can include redundant combinations; the output
does not claim globally minimal repairs.

Conflicting edits on one tool, empty tool lists, and dangling scope requirements
are rejected. Removing the only declared producer of a required scope is
rejected while its consumers remain declared. A producer cycle can retain
declarations yet leave consumers unreachable; those losses are reported, and
`--keep-tool` rejects candidates that strand a kept consumer. Removing the
producer and all affected consumers may be a valid combination. Inputs with
missing producers, unbound monetary ceilings, or mixed currencies report
`input_requires_review` and produce no candidates.

## Read both completeness limits

`no_reachable_breach_within_bound` means exactly that. A candidate's
`authority.truncated: true` leaves behavior beyond the selected depth
unexamined. A clean baseline can likewise be truncated and produces no repair
claim. The [search guide](search-performance.md) explains that boundary.

`search.enumeration_complete` addresses a different question: were all edit
combinations in the configured domain examined? `false` means the enumeration
cap stopped the search; a better candidate or any candidate may remain unseen.
`null` means no edit search ran: the baseline had no reachable breach or its
structural lint findings require review. `true` says nothing about edits beyond
`--max-edits`, unsupported repair kinds,
or reachability beyond the depth. `combinations_total` includes conflicting
and structurally rejected combinations. `candidates_analyzed` counts only
combinations that reached the analyzer, and `candidates_found` may exceed the
display limit.

For T tools and at most K edits, there are at most 2T actions and
sum(C(2T, k), k=1..K) combinations before the examination cap. The baseline and
each admitted combination run the ordinary bounded search. The default cap
limits the number of searches, not their individual time or memory. Use the
same process resource limits described in the search guide. The current
implementation retains successful candidate records before ranking, so peak
storage also grows with successful combinations and manifest size.

## Review and apply a choice

Copy a chosen `candidates[n].manifest` from JSON into a separate manifest file.
Review its edits, removed role members, lost tools, and remaining lint findings.
Run `lint`, `reach` at the same depth, and `diff` against the original. Exercise
your required scenarios, then change the application and its reviewed mandate
together through the normal review process. The command never edits a source,
accepts mandate intent, or approves a deployment.

For the refund example, after reviewing the first candidate:

```bash
# This command exits 1 for the original breach and still writes the report.
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund --json > /tmp/repairs.json
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("/tmp/repairs.json").read_text())
candidate = report["candidates"][0]["manifest"]
Path("/tmp/candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
PY
mandate lint /tmp/candidate.json
mandate reach /tmp/candidate.json --depth 8
mandate diff examples/dispute-resolver-v2.yaml /tmp/candidate.json --depth 8
```

This writes only a separate candidate for inspection. In this example the
candidate is untruncated, lint-clean and narrower; the original manifest is
still breached and unchanged.

Exit codes follow the [CI contract](ci.md): 0 when baseline reach has no breach
and baseline lint has no error; 1 for a baseline breach or lint error, even with
repair candidates; 2 for malformed input, I/O, or invalid options. No candidate
found does not change the baseline exit. Remaining candidate lint errors are
visible and prevent treating a candidate as a clean overall policy.

## Compatibility and remaining scope

The CLI and v1 JSON presentation are public; `_remediation` Python records are
private. Results are not accepted as authority inputs. The four initial
[result fixtures](../tests/fixtures/remediation-kept-v1.json) cover breached,
kept-tool, enumeration-limited, and clean runs; these are v1 baselines, not
migrations from an earlier result schema. Legacy CLI results remain unchanged.

Tests compare small-graph enumeration against an independent exhaustive edit
oracle and replay existing graph semantics. Explicit hypothetical zero-call
budgets on the committed Postgres and GitHub graphs exercise repair and capped
no-candidate paths; they do not establish new observed or accepted policy
intent. The unchanged IAM graph remains clean under an irrelevant irreversible
budget, retaining its separate service-principal lint finding.

Budget/ceiling tightening, conditions, delegation changes, reviewed positive
obligations, and business-scenario preservation remain outside this slice.
Evidence attachments, IR, runtime continuity, and source inventory are not
composed with this command. Unsupported flags are usage errors rather than
inputs whose uncertainty is silently discarded.
