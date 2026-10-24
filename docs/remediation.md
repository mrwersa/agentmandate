# Find and review repair candidates

`mandate remediate` proposes changes that remove reachable breaches within a
selected call-depth bound. It rechecks the complete changed manifest and reports
what each proposal costs. It leaves source files unchanged; a person selects
whether a proposal matches the intended mandate.

```bash
mandate remediate examples/dispute-resolver-v2.yaml --keep-tool issue_refund --json
```

The baseline breach remains visible and the command exits 1 even when a repair
is found. A proposal labelled `no_reachable_breach_within_bound` is a bounded
analysis result, not a declaration of safety at every depth.

## Choose a repair domain

| Option | Meaning |
|---|---|
| `--released FILE` | Also remove widening against a released manifest; required workflows pin that file |
| `--keep-tool NAME` | Preserve a named reachable tool; repeat for more tools |
| `--ceiling TOOL=AMOUNT` | Supply a strictly lower ceiling; repeat for alternatives |
| `--ceiling-grid TOOL=MIN:MAX:STEP` | Expand a finite exact domain, including MAX only if on-grid |
| `--discover-ceiling TOOL=STEP` | Derive and search the finite domain from zero to the original ceiling |
| `--required-workflows FILE` | Preserve explicit positive paths and their amounts |
| `--pareto` | Return non-dominated trade-offs among rechecked proposals |
| `--depth N` | Set the same reachability bound for baseline and proposals |
| `--max-edits N` | Limit edits per proposal; default 2 |
| `--max-evaluations N` | Bound examined combinations; default 128 |
| `--max-candidates N` | Limit displayed proposals; default 5 |

Without discovery, the search considers tool removals and approval requirements,
plus any supplied ceilings. It rejects proposals that break required-scope
production or leave a ceiling unbound. Removing the sole producer is not a
valid way to hide a breach. Surviving role memberships and tool contracts are
retained; findings and lost reachable tools remain visible per proposal.

Discovery retains every tool and searches only selected ceilings plus eligible
approval additions. It cannot combine with explicit ceilings or grids. See the
[discovery guide](ceiling-discovery.md) for its domain, pruning argument and limits.

## Keep useful workflows

For a release rejected by `diff`, use [release-aware remediation](release-remediation.md).
It can start from widening without a reachable breach and requires every
candidate to pass the released-manifest comparison, workflow and ordinary checks.
`--released` can use reviewed conditions or fixed delegation grants for proposal
checks; [release scope](release-remediation.md#use-reviewed-proposal-evidence)
explains the independent declared comparison. Conditions and delegations remain
mutually exclusive.

A reachable refund tool with a zero ceiling cannot issue a useful refund.
`--keep-tool` preserves tool reachability; it does not invent an amount that the
application needs. Supply that requirement explicitly:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --ceiling issue_refund=0 --ceiling issue_refund=50 --ceiling issue_refund=125 --required-workflows examples/remediation/required-refund.json --json
```

The required £100 refund screens zero and £50 proposals. £125 passes its
depth-eight graph recheck, which is truncated; at depth ten it breaches again.
Required paths establish model conformance, not business success or live
resource identity. Their author/reviewer annotations are caller-supplied.

## Recheck repairs within reviewed conditional effects

Supply the same four condition flags accepted by `reach` to repair a manifest
within an existing reviewed input domain:

```bash
mandate remediate examples/conditional-remediation/manifest.json \
  --condition examples/conditional-remediation/condition.json \
  --condition-context examples/conditional-remediation/context.json \
  --condition-capture examples/conditional-remediation/capture.sql \
  --condition-as-of 2026-10-16 \
  --required-workflows examples/conditional-remediation/required-export.json \
  --discover-ceiling export_rows=1 --keep-tool run_query --keep-tool export_rows
```

This synthetic example finds a two-record ceiling that preserves two required
exports within depth four. The query tool's declared effect remains
`irreversible`; only the separately reviewed select-only context permits a
`read` interpretation. The scoped baseline still has a quantity breach, so the
command exits 1. Explicit ceilings, grids, approval/removal edits and Pareto
ranking support the same flags.

The existing [condition reader](conditions-delegation.md#gate-3-conditional-trust-semantics)
reruns for the baseline and every candidate it analyzes. Conditions and contexts
are copied into immutable records through canonical JSON; captures are kept as
bytes. Dates, review status,
completeness, operand joins and capture digests retain their existing checks.
Any unresolved baseline condition returns `input_requires_review` with no
recommendations. It cannot be repaired by deleting the disputed tool.

`baseline`, `baseline_lint`, candidate `authority`, workflow checks and ranking
use the reviewed conditional effects. Each `conditions` record also retains the
complete `unconditional_authority` and `unconditional_lint`, applied conditions,
findings and input identities. Artifact hashes identify canonical JSON rather
than original file whitespace; capture hashes identify exact bytes. They do
not authenticate reviewers or independently verify source enforcement.

Candidate manifests retain their declared effects, budgets and identities.
Reproduce a candidate's scoped result with the same condition inputs and date;
running its manifest alone can still report ordinary breaches. Removing a tool
makes only its already-validated attachments inactive, with their IDs reported
in `inactive_conditions`; the original input identities remain visible.
Ordinary unresolved evidence produces exit 1 and `input_requires_review`.
The current edits cannot change condition eligibility; a violation of that
invariant aborts analysis with exit 2 and no partial report, as an unsupported
internal repair state. Discovery's pruning remains scoped to the fixed
classification and unchanged evidence; it does not search condition domains.

Required paths still pin the original manifest. Their calls are assessed under
the selected effect domain, including effect-count budgets. They carry no SQL
or dispatch arguments, so they do not prove that a particular live call belongs
to that domain. This mode consumes existing restrictions; it does not propose
new predicates, edit captures, create review acceptance or change grants.

## Recheck fixed delegation grants

For fixed grant constraints, use [delegation-aware remediation](delegation-remediation.md).
It rechecks the existing delegation records alongside ordinary reachability
and required paths. It can propose removing an excessive tool without editing
the grant; unresolved evidence and chain widening stop recommendations.
Conditional and delegation modes cannot be combined.

## Quantity accounting and trade-offs

Ceilings inherit the tool's named quantity and unit. Proposals do not change
`limits.quantities`, effect budgets, quantity assignments, units, identities or
scope relationships. Every named budget is rechecked. Different quantity names
and units are never summed to rank a repair.

```bash
mandate remediate examples/dispute-resolver-v2.yaml --ceiling-grid issue_refund=0:200:25 --pareto --json
```

The frontier minimizes edit count, lost reachable-tool sets and added-approval
sets, while maximizing each original tool's retained ceiling. No proposal is
better on all axes unless it dominates another under those explicit objectives.
A deterministic display order is not business utility. Outside frontier mode,
ties prefer lower lost effect classes and then named quantity/lexical order.

All amounts use exact decimals. Explicit grids expand at most 512 points before
deduplication. Discovery has its own eight-tool/eight-edit bounds. Decimal input
uses unsigned decimal literals; underscores, leading plus signs and surrounding
whitespace are rejected.

## Read the current result

Every option uses `agentmandate.remediation/v6`; there are no old presentation
modes. The JSON includes baseline Authority and lint, search controls, proposed
edits, complete candidate manifests, candidate Authority, lint and optional
workflow/frontier/discovery assessments.
With `--released`, `release` additionally retains the original comparison and
each candidate's comparison; required-workflow annotations pin the released file.

- `search.exhaustive_point_enumeration` means every Cartesian combination was
  literally examined. Discovery can resolve a complete frontier through pruning
  while this remains false.
- `search.truncated_by_limit` explicitly reports an evaluation-budget cutoff.
- `discovery.frontier_complete_within_domain` concerns the discrete domain and
  fixed depth, including edit and workflow constraints.
- `frontier.display_complete` concerns only the display cap.
- Each Authority's `truncated` concerns the call-depth bound.

`no_feasible_candidate_in_declared_domain` is a complete discovery result for
those steps and constraints. Finer steps or different constraints may change it.
`no_candidate_found_within_limits` leaves an unresolved search region or reports
an exhausted explicit edit search. Neither establishes that no useful repair exists.

Malformed domains, incompatible units within one quantity or unsupported
arithmetic exit 2 without a partial result. Exit 1 retains baseline breaches,
lint errors, unresolved conditions or delegation findings. Exit 0 means the
baseline is clean within
the selected analysis scope. Conditional reports retain the ordinary findings
separately; finding a repair never clears a breached baseline.

## Apply a selected proposal

After reviewing its lost capabilities, workflows, lint and truncation, save the
chosen `manifest` field and rerun ordinary checks:

```bash
mandate lint /tmp/candidate.json
mandate reach /tmp/candidate.json --depth 8
mandate diff examples/dispute-resolver-v2.yaml /tmp/candidate.json --depth 8
```

Application-level tests and deployment controls remain necessary. Generating
new condition restrictions, editing delegation grants, timed quotas, multiple
simultaneous charges on one call and global policy synthesis remain outside
this repair family.
