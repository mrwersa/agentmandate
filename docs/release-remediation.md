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

With reviewed proposal evidence, the breach and lint claims are limited to that
scope, as described below. Declared widening and ordinary released-workflow
checks remain binding.

This is not general policy equivalence, business success, runtime enforcement
or deployment approval. `compare` is conservative: its widening rules also govern
which repairs qualify. The reference's findings remain visible, and no accepted
change-review record substitutes for removing widening in this mode.

The current remediation/v6 result includes:

| Field | Meaning |
|---|---|
| `baseline`, `baseline_lint` | Original proposal's analysis and lint within the selected analysis scope |
| `requirements.baseline` | Original proposal's workflow assessments; the repair starting point |
| `release.comparison` | Full released-to-proposed comparison, including both Authority results and optional workflow rows |
| `release.comparison.required_workflows[].baseline` | Released reference's workflow status; the comparison starting point |
| `release.gate_passed` | No widening, proposed breach, lint error or workflow regression within the reported scope |
| `release.released_lint` | Reference lint, retained separately |
| `candidates[].release` | The same comparison checks for that candidate |
| `release_rejections` | Rechecked edits that still fail the comparison/lint gate |
| `search.release_rejections` | Number of those rejection records |
| `input.manifest_sha256`, `input.released_sha256` | Exact proposed and released file identities |

## Use reviewed proposal evidence

Combine `--released` with the existing condition flags or delegation flags to
recheck repairs within that reviewed proposal scope. Conditions and delegations
remain mutually exclusive. All supported edits, grids, discovery, required paths
and Pareto ranking use the same rules. The
[worked examples](../examples/release-scoped-remediation/README.md) reuse the
existing synthetic condition and delegation materials with separately pinned
released manifests and workflows.

Evidence applies to the **proposal and each candidate only**. It is not applied
to the released reference or treated as proof of its enforcement. No new
restriction, grant, review or capture is generated. All baseline evidence must
be eligible before search; expired, incomplete or mismatched inputs return
`input_requires_review`, retain the ordinary release comparison and examine no
edits. Removing a disputed tool cannot bypass eligibility.

Every candidate must pass the unchanged ordinary `compare` rules for declared
widening and workflow preservation. A reviewed condition cannot excuse a raised
declared budget, a broader tool effect or a broken ordinary released path.
The required workflow must conform to the released manifest **without borrowing
the proposal's condition evidence**. If it does not, the input is a usage error;
this mode does not support a separately conditioned reference. Scoped workflow
checks are additional to those ordinary comparisons.

Conditions qualify proposal breach and lint analysis. Fixed grants do not
project Authority; candidates must satisfy their unchanged tool surfaces as
well as ordinary breach and lint checks. Only a previously validated attachment
for a removed candidate tool becomes inactive. No supplied attachment means
no delegation claim for that tool, as in the existing delegation reader.

Scoped release records add:

| Field | Meaning |
|---|---|
| `unconditional_gate_passed` | Original declared comparison, breach, lint and workflow gate result, retained unchanged |
| `reviewed_analysis.kind` | `conditions` or `delegations` |
| `reviewed_analysis.authority`, `lint` | Proposal/candidate analysis within the selected scope |
| `reviewed_analysis.evidence` | Reader findings, input identities and scope limits |
| `gate_passed` | No declared widening or ordinary workflow regression, and eligible, breach-free, lint-clean proposal analysis within the reviewed scope; fixed-grant findings must also be absent |

The full unconditional `comparison` and `lint` remain present. A conditional
candidate can have `gate_passed: true` and `unconditional_gate_passed: false`;
its ordinary Authority may still contain breaches. This is an explicitly scoped
model result, not a clean ordinary release gate. The candidate status is
`no_declared_widening_or_breach_within_reviewed_scope`, and human output prints
the unconditional gate result and evidence boundary. The original proposal's
findings still determine exit 1 when a repair is found. If the proposal already
passes within the reviewed scope, no edits are suggested.

The GitHub Action's repair inputs remain unchanged: it does not pass conditions
or grants into the planner. Choosing a scoped CLI proposal does not waive any
ordinary Action finding or recorded-review requirement.

## Keep the search limits visible

Ordinary release candidates carry `no_widening_or_reachable_breach_within_bound`;
reviewed candidates use the scoped status above. Both retain their changed
manifest, capability losses, lint and per-side truncation. Human output includes
the original changes, required-path failures and rejected comparisons too.
The comparison reader reruns bounded analysis; `candidates_analyzed` counts
candidate probes, not every internal kernel invocation.
For unscoped candidates, the workflow screen and comparison reader assess the
same paths under the same model. With conditions, the workflow screen also
checks the projected effects while the comparison keeps the declared model;
both must pass. Repeated checks are not independent corroboration. For the original proposal, the
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
Condition evidence and delegation grants stay fixed; they are consumed rather
than edited. Scope eligibility and all original release findings remain visible.

Exit 0 means the original proposal passes these scoped checks. Exit 1 retains
its findings even when a repair exists. Exit 2 means malformed, unsupported,
unreadable or mismatched inputs. Proposals remain unapplied. After choosing a
candidate, save its `manifest` and rerun lint, reach and diff with the same
released reference, depth and required workflows before further review. Also
rerun the selected condition or delegation reader with the same evidence if
using that scope. An ordinary gate may still refuse a condition-scoped proposal;
the repair report does not accept it on the gate's behalf.
