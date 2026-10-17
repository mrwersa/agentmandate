# Discover quantity repair ceilings

Use `mandate remediate --discover-ceiling TOOL=STEP` to find usable ceiling
repairs without guessing amounts or writing a range. It keeps every tool and
the declared total/effect budgets. It can also add approval to currently
ungated irreversible tools. Required workflows screen proposals before their
full graph recheck.

From the repository root:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --discover-ceiling issue_refund=0.01 --required-workflows examples/remediation/required-refund.json
```

The example derives £125, preserving the required £100 refund. Six probes
resolve a 50,001-point domain. The original quantity breach remains in
`baseline`, so exit 1 is expected. The candidate is clean at depth eight and
truncated; it breaches at depth ten. Completing a ceiling frontier at one depth
does not prove safety at greater depths.

Without [required workflows](required-workflows.md), zero can be a candidate:
reachability alone does not establish useful quantity behavior. The command
does not infer requirements from a trace or apply changes to source files.

## Define the domain and read trade-offs

Repeat the option to discover several ceilings together:

```bash
mandate remediate examples/ceiling-discovery/two-tools.json --discover-ceiling pay=1 --discover-ceiling other=1 --required-workflows examples/ceiling-discovery/required-two-tools.json --json
```

This example returns four non-dominated trade-offs, each retaining the two
required £1 payments. Greater allowance on one tool can cost allowance on the
other. Candidates require human selection; their ranking is not business utility.

For original ceiling C and positive step Q, the choices are zero, multiples of Q
strictly below C, and unchanged C. For C=3.5 and Q=1, those are 0, 1, 2, 3 and
unchanged 3.5. Only the unchanged ceiling may be off-grid. Unselected ceilings
stay fixed. This granularity constrains proposed ceilings, not runtime request
amounts; the numeric model still allows any amount within headroom.

Each tool retains its unit. Exact integer/Decimal-tuple arithmetic is
independent of caller precision, rounding and traps. Discovery supports at most
eight tools and eight edits. Selected ceilings and steps require at most 100
digits and exponents from −100 to +100; step text has at most 128 characters.
Duplicate tool options and nonpositive/non-finite steps are usage errors.

Discovery cannot combine with `--ceiling` or `--ceiling-grid`. Its computed results
use a Pareto frontier, with or without `--pareto`. It does not remove tools or edit
conditions, delegation, total budgets, effect budgets or evidence attachments.

## Keep completeness and limits separate

| Control or result | Meaning |
|---|---|
| `--max-edits` (default 2) | Changed ceilings plus added approvals per proposal |
| `--max-evaluations` (default 128) | Unique probed ceiling/approval combinations, including rejected points |
| `--max-candidates` (default 5) | Displayed non-dominated proposals |
| `--depth` (default manifest depth) | Call depth for baseline and all candidate reachability checks |

An unchanged ceiling costs no edit. Cached probes do not spend another
evaluation. `search.candidates_analyzed` counts additional reach calls; the
unchanged point reuses the original baseline. Every emitted proposal carries
its full manifest, Authority, lint and supplied-workflow results.

`discovery.frontier_complete_within_domain` becomes true only when every domain
region is resolved by a recheck, feasibility screen or valid dominance argument.
If an attempted uncached probe would exceed the evaluation limit, status is
`evaluation_limit` and `remaining_points` stays positive. Partial candidates
are rechecked but may omit, or later be dominated by, unexplored alternatives.

`search.exhaustive_point_enumeration` separately means every Cartesian point was probed.
It can be false when the frontier is complete because pruning avoids exhaustive
enumeration. `frontier.display_complete` separately means all found alternatives
fit the display cap. None of these extends reachability depth or changes an
Authority's `truncated` flag. Clean or structurally invalid baselines do not
claim a computed frontier.

## Why pruning preserves the frontier

For fixed manifest-v2 tools, scopes and approval choices, lower ceilings cannot
introduce a reachable breach. Enablement and production do not depend on amounts;
effect-budgeted calls count even at zero spend. The
[headroom argument](headroom-abstraction.md) states the quantity model. Adding
approval removes an ungated-effect breach without changing quantity enablement.
Amount-dependent outputs and guards remain outside this model.

The search splits integer index ranges into disjoint boxes and checks corners:

- A feasible clean upper corner dominates feasible lower points, retaining at
  least as much allowance with no more changed ceilings.
- An upper corner failing a workflow or edit limit makes every lower point
  infeasible. Lower ceilings cannot repair missing approval or required spend.
- A feasible breached lower corner makes every higher point unsafe at the same
  depth. Raising ceilings cannot repair ungated or effect-count breaches.
- A known rechecked proposal with no more approvals and ceilings at least as
  high as an upper corner dominates that box's feasible proposals.

Other boxes split at an index midpoint. Every emitted proposal is a real probe,
never a value inferred from a corner. Retained-tool reachability is checked too;
unexpected amount-dependent reachability is refused. These rules cover Pareto
alternatives in the discrete domain and edit limit at the fixed depth. They do
not certify a globally minimal policy or business success. Objectives are fewer
edits/approvals and greater retained allowance on each named tool.

## Reproduce the checks

```bash
python -m pytest tests/test_ceiling_discovery.py -q
python scripts/benchmark_ceiling_discovery.py --output /tmp/ceiling-discovery.json
```

Tests compare small complete domains with an independent Fraction/call-allocation
oracle and exhaustive graph rechecks over different producers and scopes. They
cover joint approvals, workflows, off-grid unchanged values, numeric contexts,
effect budgets, malformed input, cutoffs and display limits.

The [five-case benchmark](ceiling-discovery-benchmark.json) pins input and source
hashes. Cent and micro-unit refund domains contain 50,001 and 500,000,001 points;
both use six probes and four additional reach calls. The two-tool example finds
four alternatives in eleven probes; a four-probe run stays incomplete. These are
fixed synthetic cases with one local timing each, not a performance guarantee.
Worst-case work can remain exponential in edit dimensions, and each recheck
inherits the [search cost](search-performance.md). Evaluation limits do not
replace process time or memory limits.

## Current contract and exit codes

Discovery uses the same `agentmandate.remediation/v6` result as other repair
modes. There are no v1–v5 output readers or preservation branches. Current
fixtures exercise complete and cutoff searches, joint approval, two-tool
trade-offs, display caps and clean baselines. Numeric steps use unsigned decimal
literals; whitespace, underscores and a leading plus sign are rejected.

Exit 1 retains original breaches or lint errors, exit 0 means the original
baseline is clean, and exit 2 means malformed/unsupported input or arithmetic.
Finding a proposal never turns an original breach green. A complete result with
no proposal means the declared lattice and constraints have no feasible repair;
finer steps may change it. Evaluation cutoffs have the explicit
`search.truncated_by_limit` flag. The result authenticates no decision and
supplies no runtime enforcement.

The [condition-aware repair mode](remediation.md#recheck-repairs-within-reviewed-conditional-effects)
also supports discovery. Classification evidence stays fixed across the domain;
only ceilings and approval requirements vary. Each probe reruns the condition
reader and workflow checks. The report retains ordinary findings separately,
and unresolved condition evidence prevents discovery. Exit codes apply to the
selected scope; a discovered repair never clears its breached baseline.

[Delegation-aware discovery](delegation-remediation.md) also rechecks fixed
grant surfaces. Because it retains all tools and changes neither required scopes
nor effects, a tool's known excess cannot be repaired anywhere in that domain.
The report distinguishes this fixed constraint from an insufficiently fine
ceiling lattice. Chain or trust defects stop discovery with review required.
