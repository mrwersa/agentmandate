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
arithmetic exit 2 without a partial result. Exit 1 retains original breaches or
lint errors. Exit 0 means the original baseline is clean.

## Apply a selected proposal

After reviewing its lost capabilities, workflows, lint and truncation, save the
chosen `manifest` field and rerun ordinary checks:

```bash
mandate lint /tmp/candidate.json
mandate reach /tmp/candidate.json --depth 8
mandate diff examples/dispute-resolver-v2.yaml /tmp/candidate.json --depth 8
```

Application-level tests and deployment controls remain necessary. Conditions,
delegation bounds, timed quotas, multiple simultaneous charges on one call and
global policy synthesis are outside this repair family.
