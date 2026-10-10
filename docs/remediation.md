# Find repair candidates for a breach

Use `mandate remediate` after `reach` finds a breach in a reviewed manifest. The command
explores tool removals, approval requirements, and explicitly supplied lower monetary
ceilings. It rechecks the whole remaining graph and ranks candidates by edit count, lost
reachable tools and their effect classes. It leaves the source file unchanged.

## Try the refund example

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund
```

The baseline permits two refunds against different cases, exceeding the 500 GBP total.
With `issue_refund` kept reachable, the first candidate removes `search_cases`. The
remaining `open_case` tool produces one binding, so the refund ceiling now bounds the
total in this declared model. Removing the refund tool is another possible repair when
`--keep-tool` is omitted; it has an obvious functional cost.

The command still exits **1**, because the original manifest has a breach. Finding a
candidate does not accept or apply it. Adding approval to an ungated irreversible tool
can remove its ungated-effect finding, but approval does not stop cumulative spending or
repeated effects in manifest v1. Each candidate must survive the full reachability
check, including those budgets.

For machine-readable results:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund --json
```

Without ceiling or workflow options, the result uses `agentmandate.remediation/v1`.
Supplying `--ceiling` selects `agentmandate.remediation/v2`; supplying
`--required-workflows` selects v3. See the [compatibility rules
below](#compatibility-and-remaining-scope). `input.manifest_sha256` identifies the exact
source bytes. `baseline` is the unchanged Authority result at the selected depth;
`baseline_lint` keeps the separate single-manifest findings. Each candidate includes
edits, authority impact, a complete semantic manifest, its rechecked Authority, and
remaining lint findings. The manifest retains identity, limits, principals, effects,
scope declarations, monetary ceilings except those explicitly edited, and surviving role
assignments. Removing a tool also removes its role memberships, listed explicitly under
`impact.removed_role_members`. Comments and other source formatting are not retained.

## Keep search and refund by testing lower ceilings

If search is required, retaining the refund tool alone is insufficient. Keep both
capabilities and supply the lower ceilings you want considered:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool search_cases --keep-tool issue_refund --ceiling issue_refund=100 --ceiling issue_refund=125 --ceiling issue_refund=250
```

The £250 option still permits a breach and is rejected. Both £100 and £125 pass the
depth-eight recheck; £125 ranks first because it retains more reachable monetary value
within that bound. All four tools remain reachable and the maximum is £500 within eight
calls. A normal approved £100 refund remains within that ceiling. This is a concrete
candidate for review, not a guarantee that every required refund workflow survives.

The candidate is **truncated**: at depth ten, five different cases can reach £625. A
lower per-case ceiling does not enforce the run total. Review the application's
total-budget control and required workflows separately; the candidate label and
`authority.depth` do not permit a global safety claim.

Amounts come from the reviewer, not inferred business requirements. A candidate can
reduce a tool to zero spend if zero was explicitly supplied; keeping that tool reachable
does not preserve a useful monetary operation. The search never invents a minimum useful
amount, changes currency, raises the total limit, removes a limit, or treats the limit
as a runtime guard.

## Combine approval and ceiling repairs

The [synthetic example](../examples/remediation/README.md) has an ungated irreversible
refund tool and an unbounded producer. It needs two distinct edits:

```bash
mandate remediate examples/remediation/ungated-refund.json --keep-tool seed --keep-tool pay --ceiling pay=2 --max-edits 2
```

Requiring approval alone leaves the monetary breach. Tightening the ceiling alone leaves
the ungated-effect finding. The joint candidate clears both within four calls while
retaining both tools. Its [supplied normal
trace](../examples/remediation/normal-refund.jsonl) replays conformantly after the
edits; that check covers the recorded calls, not live execution, producer lineage, or
business success. The trace itself does not become a requirement; the explicit
workflow input below supplies separate positive constraints.

## Preserve a required ordered path

`--keep-tool` preserves reachability. To require a normal £100 refund rather
than merely a callable refund tool, supply a reviewed path explicitly:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --ceiling issue_refund=0 --ceiling issue_refund=50 --ceiling issue_refund=125 --required-workflows examples/remediation/required-refund.json
```

The zero and £50 ceilings are screened out for breaking the supplied refund.
Removing search or refund also fails that requirement. Passing candidates keep
all supplied paths conformant within manifest v1 and still undergo the full
bounded breach check. Rejection records name the workflow, step and failure;
requirements never replace the original Authority result or its exit.

This selects the opt-in v3 presentation. The [workflow guide](required-workflows.md)
defines the strict source-bound format, cumulative and program-order checks,
and the boundary between model conformance and business success. Requirements
are authored intent, not observations inferred from a trace. The earlier
synthetic trace remains a separate conformance illustration.

## Choose what the search may change

| Option | Default | Meaning |
|---|---:|---|
| `--depth` | Manifest depth | Reachability depth for the baseline and every candidate |
| `--max-edits` | 2 | Maximum tool edits per combination |
| `--max-evaluations` | 128 | Maximum combinations examined, including rejected combinations |
| `--max-candidates` | 5 | Maximum ranked candidates returned |
| `--keep-tool NAME` | None | Preserve this tool's reachability at the selected depth; repeat as needed |
| `--ceiling TOOL=AMOUNT` | None | Include this strictly lower monetary ceiling; repeat for other tools or alternatives |
| `--required-workflows FILE` | None | Preserve explicitly supplied ordered paths bound to the original manifest bytes |

A kept tool must exist and be reachable in the baseline. Reachability does not establish
that a required business scenario still succeeds. Check those scenarios separately
before choosing a candidate.

Supported edits are `remove_tool`, `require_approval` and `tighten_ceiling`. Approval
applies only to currently ungated irreversible tools. Ceiling options must name spending
tools and give finite, nonnegative amounts strictly below the current ceiling. The
tool's existing currency is retained. Numeric duplicate options form one choice, using
the first lexical spelling independently of flag order. For tool names containing `=`,
the last `=` separates the amount.

Combinations enumerate increasing edit counts. The existing removal/approval actions
come first in tool-name order, followed by supplied ceilings sorted by tool and numeric
amount. Thus a low examination cap may miss a ceiling option or a joint repair; inspect
enumeration completeness. Candidates rank by fewer edits, fewer lost reachable tools,
then the effect classes of those lost tools: prefer losing reads over writes over
irreversible capabilities. For multiple losses, compare the strongest lost effect first,
then the next strongest. Fewer removals follow. With ceiling options, ties then prefer
the greater rechecked `authority.max_extractable` within the same depth, followed by a
lexical tie-break. Its Decimal comparison is exact and independent of caller settings,
including for compact large exponents. Without ceiling options, v1 retains its original
lexical tie-break. Reachable monetary value is not a measure of business utility or
behavior beyond the bound. This heuristic does not establish business priority; use
`--keep-tool` to preserve named capabilities and check required scenarios separately.
Candidates can include redundant combinations; the output does not claim globally
minimal repairs.

Two alternative ceilings on one tool, removal plus another edit on that tool, empty tool
lists, and dangling scope requirements are rejected. Approval and ceiling tightening on
one tool are independent and may combine; they count as two edits. Removing the only
declared producer of a required scope is rejected while its consumers remain declared. A
producer cycle can retain declarations yet leave consumers unreachable; those losses are
reported, and `--keep-tool` rejects candidates that strand a kept consumer. Removing the
producer and all affected consumers may be a valid combination. Inputs with missing
producers, unbound monetary ceilings, or mixed currencies report `input_requires_review`
and produce no candidates.

## Read both completeness limits

`no_reachable_breach_within_bound` means exactly that. A candidate's
`authority.truncated: true` leaves behavior beyond the selected depth unexamined. A
clean baseline can likewise be truncated and produces no repair claim. The [search
guide](search-performance.md) explains that boundary.

`search.enumeration_complete` addresses a different question: were all edit combinations
in the configured domain examined? `false` means the enumeration cap stopped the search;
a better candidate or any candidate may remain unseen. `null` means no edit search ran:
the baseline had no reachable breach or its structural lint findings require review.
`true` says nothing about edits beyond `--max-edits`, unsupported repair kinds, or
reachability beyond the depth. `combinations_total` includes conflicting and
structurally rejected combinations. `candidates_analyzed` counts only combinations that
reached the analyzer, and `candidates_found` may exceed the display limit.

For T tools, C unique supplied ceiling options and at most K edits, there are at most N
= 2T + C actions and the sum of binomial(N, k), k=1..min(K, N), combinations before the
examination cap. The baseline and each admitted combination run the ordinary bounded
search. The default cap limits the number of searches, not their individual time or
memory. Use the same process resource limits described in the search guide. The current
implementation retains successful candidate records before ranking, so peak storage also
grows with successful combinations and manifest size.

## Review and apply a choice

Copy a chosen `candidates[n].manifest` from JSON into a separate manifest file. Review
its edits, removed role members, lost tools, and remaining lint findings. Run `lint`,
`reach` at the same depth, and `diff` against the original. Exercise your required
scenarios, then change the application and its reviewed mandate together through the
normal review process. The command never edits a source, accepts mandate intent, or
approves a deployment.

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

This writes only a separate candidate for inspection. In this example the candidate is
untruncated, lint-clean and narrower; the original manifest is still breached and
unchanged.

Exit codes follow the [CI contract](ci.md): 0 when baseline reach has no breach and
baseline lint has no error; 1 for a baseline breach or lint error, even with repair
candidates; 2 for malformed input, I/O, or invalid options. No candidate found does not
change the baseline exit. Remaining candidate lint errors are visible and prevent
treating a candidate as a clean overall policy.

## Compatibility and remaining scope

The CLI and v1/v2/v3 JSON presentations are public; `_remediation` Python records are
private. Results are not accepted as authority inputs. The four initial [result
fixtures](../tests/fixtures/remediation-kept-v1.json) cover breached, kept-tool,
enumeration-limited, and clean runs; these are v1 baselines, not migrations from an
earlier result schema. Commands without `--ceiling` retain exact v1 result bytes and
exit behavior.

V2 is opt-in because `tighten_ceiling` is a new edit kind that a closed v1 consumer may
not understand. It retains the existing fields and adds the full `ceiling_options`
domain. A tightening edit carries `before` and `after` money records as well as `tool`
and `kind`; removal and approval records keep their existing shape. Candidate manifests
carry the resulting ceiling. A valid domain selects v2 even when the baseline is clean
or requires structural review.

The four [v2 baselines](../tests/fixtures/remediation-ceiling-kept-v2.json) cover a
kept-tool repair, a joint approval/ceiling repair, enumeration cutoff, and a clean
baseline. A [v1-to-v2 compatibility case](../tests/fixtures/remediation-v1-to-v2.json)
pins the unchanged baseline, lint, input digest, scope and kept tools alongside the new
explicit option. Existing edit semantics remain unchanged; new candidates may displace
older candidates at the display cap. Consumers should handle v2 explicitly before adding
`--ceiling`; no result is accepted as an authority artifact. The preceding inventory and
all older fixture bytes remain pinned.

Tests compare small-graph enumeration against an independent exhaustive edit oracle and
replay existing graph semantics. Explicit hypothetical zero-call budgets on the
committed Postgres and GitHub graphs exercise repair and capped no-candidate paths; they
do not establish new observed or accepted policy intent. The unchanged IAM graph remains
clean under an irrelevant irreversible budget, retaining its separate service-principal
lint finding.

Automatic ceiling selection, effect-budget repairs beyond removal, conditions,
delegation changes, application execution and business-scenario success remain outside
this slice. Ordered positive paths are checked only within manifest v1. Total
and effect limits are properties the analyzer checks,
so making those declarations stricter is not a mechanism that stops calls. Even a zero
monetary ceiling does not erase a budgeted effect. Evidence attachments, IR, runtime
continuity, and source inventory are not composed with this command. Unsupported flags
are usage errors rather than inputs whose uncertainty is silently discarded.
