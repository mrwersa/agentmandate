# Find repairs for a rejected release

Use `mandate remediate --released FILE` when a proposed manifest widens authority
against a released manifest. A release can widen a ceiling or add a tool without
having a reachable breach. Ordinary breach repair alone does not address that
case; this mode also requires each candidate to pass the release comparison.

To show proposals inside a pull-request job, use the Action's opt-in
[repair suggestions](action-repairs.md). The original gate remains blocking.

## Run the example

```bash
mandate remediate examples/release-remediation/proposed.json \
  --released examples/release-remediation/released.json \
  --required-workflows examples/release-remediation/required-export.json \
  --keep-tool select_rows --keep-tool export_rows \
  --ceiling-grid export_rows=0:2:1 --pareto
```

This synthetic proposal has **no reachable breach** at depth four. It still
widens authority: it adds an approved purge tool and raises an export ceiling
from two to three records. The planner proposes removing purge and restoring
the two-record ceiling. Both required one-record exports remain conformant.
The candidate comparison is neutral, while the original widening remains in
the report and the command exits 1.

For automatic ceiling discovery, use the proposal without the added tool:

```bash
mandate remediate examples/release-remediation/ceiling-only.json \
  --released examples/release-remediation/released.json \
  --required-workflows examples/release-remediation/required-export.json \
  --discover-ceiling export_rows=1
```

The discovered two-record ceiling passes the comparison and preserves the paths.
Discovery retains every tool. If run on `proposed.json`, it cannot remove the
added purge tool and reports no feasible candidate within that declared domain.

## Select the reference and requirements

The positional manifest is the **proposal being repaired**. `--released` is
the **comparison reference**; both must name the same agent. Protect the reference
using your existing release workflow. A matching filename or checksum does not
authenticate its author or establish that it is the deployed version.

With `--released`, the existing [required-workflow file](required-workflows.md)
pins the released file's exact bytes. It must conform to that reference. A
stale pin, wrong agent or invalid released path exits 2 without a partial report.
The proposed manifest may already break a required path: that is a release
finding, recorded with the first failing call. The planner never drops it or
changes its required amount or approval to make an edit pass.

The current edits only remove tools, add approval or lower ceilings. They cannot
restore a missing tool, raise a broken ceiling, remove required approval or
repair other existing path failures. Such a proposal may have no feasible repair
in this domain. `breaking.json` illustrates a ceiling below the required amount.
Change the proposal or revisit its intent explicitly; do not refresh the
requirements pin merely to obtain a clean result.

Without `--depth`, both releases and all candidates use the larger declared
depth. An explicit depth applies to every check. Reducing the proposal's declared
depth remains a widening finding even when an explicit analysis depth is larger.
To remove that finding, restore the proposal's declared `limits.depth` to at
least the released value; increasing `--depth` alone does not change that field.
The planner cannot propose this edit. Rejected comparisons may still appear
when other supplied edits reach the comparison check.
Structural defects in the released reference must be reviewed before comparison.

## Understand the checks and result

Each returned candidate has:

- No widening under the ordinary `compare` rules, including declared budgets,
  common-tool contracts, newly reachable authority and quantity maxima.
- No reachable breach at the selected depth and no lint error. Warnings remain
  visible. An existing breach in the released version is not an allowance.
- Every supplied required path preserved within the manifest model.

This is not general policy equivalence, business success, runtime enforcement
or deployment approval. `compare` is conservative: its widening rules also govern
which repairs qualify. The reference's findings remain visible, and no accepted
change-review record substitutes for removing widening in this mode.

The current remediation/v6 result includes:

| Field | Meaning |
|---|---|
| `baseline`, `baseline_lint` | Original proposed-manifest analysis and lint |
| `requirements.baseline` | Original proposal's workflow assessments; the repair starting point |
| `release.comparison` | Full released-to-proposed comparison, including both Authority results and optional workflow rows |
| `release.comparison.required_workflows[].baseline` | Released reference's workflow status; the comparison starting point |
| `release.gate_passed` | No widening, proposed breach, lint error or workflow regression within the reported scope |
| `release.released_lint` | Reference lint, retained separately |
| `candidates[].release` | The same comparison checks for that candidate |
| `release_rejections` | Rechecked edits that still fail the comparison/lint gate |
| `search.release_rejections` | Number of those rejection records |
| `input.manifest_sha256`, `input.released_sha256` | Exact proposed and released file identities |

Candidates carry `no_widening_or_reachable_breach_within_bound`, their changed
manifest, capability losses, lint and per-side truncation. Human output includes
the original changes, required-path failures and rejected comparisons too.
The comparison reader reruns bounded analysis; `candidates_analyzed` counts
candidate probes, not every internal kernel invocation.
For candidates, the workflow screen and comparison reader assess the same
paths under the same model. The repeated check preserves a complete comparison
record; it is not independent corroboration. For the original proposal, the
comparison's workflow-regression check can itself block the release.

Explicit ceilings, grids, removals, approval edits and Pareto ranking are
supported. Discovery reuses its existing reachability, workflow and dominance
pruning rules. A release-rejected corner introduces **no additional pruning**;
its box is split until other rules resolve it or the evaluation limit stops work.
This can cost more probes than ordinary discovery. Frontier completion, literal
point enumeration, evaluation cutoff, display cap and call-depth truncation
retain their [separate meanings](ceiling-discovery.md).

Original budgets, quantity assignments, identities, tool effects and scope
relationships stay fixed. Widening in those fixed dimensions may leave no repair.
Release mode cannot combine with condition or delegation inputs; those have
separate evidence scopes and are refused before input reads.

Exit 0 means the original proposal passes these scoped checks. Exit 1 retains
its findings even when a repair exists. Exit 2 means malformed, unsupported,
unreadable or mismatched inputs. Proposals remain unapplied. After choosing a
candidate, save its `manifest` and rerun lint, reach and diff with the same
released reference, depth and required workflows before further review.
