# Review authority changes across fleet releases

Use `mandate fleet diff` when a release changes several repositories or
environments. It compares the supplied manifest/IR pairs in two local fleet
indexes, reports which deployment widened authority, and keeps inventory and
review findings visible. Each mandate has its own search and budget.

From the repository root:

```bash
mandate fleet diff --baseline examples/fleet-diff/baseline.json --candidate examples/fleet-diff/candidate.json --baseline-root . --candidate-root . --as-of 2026-10-14 --json
```

This synthetic example exits 1. Removing production publication approval
widens `release-repo / prod / release-agent` and leaves a reachable ungated
publication breach. Release staging stays unchanged. The candidate also adds
billing staging and leaves billing production's review unreviewed. Its output
contains three matched comparisons, one widening, one addition and the review
finding. A current inventory review does not accept a release's gained authority.

Try an unchanged release or a narrowing rollback:

```bash
mandate fleet diff --baseline examples/fleet-diff/baseline.json --candidate examples/fleet-diff/baseline.json --baseline-root . --candidate-root . --as-of 2026-10-14
mandate fleet diff --baseline examples/fleet-diff/widening.json --candidate examples/fleet-diff/baseline.json --baseline-root . --candidate-root . --as-of 2026-10-14
```

Both exit 0 within the supplied declarations and search bound. Neither result
establishes authenticated deployment, absence of unlisted agents or safety
beyond that bound. See the [search guide](search-performance.md) for truncation.

## Supply two existing fleet indexes

The inputs use the unchanged [`fleet_version: 1` format](fleet-inventory.md).
Export each reviewed manifest's Authority IR, pin both files, and collect the
index and artifacts from each release. Protect those declarations through your
repository review process. `--baseline-root` and `--candidate-root` resolve
their respective relative artifact paths; they can refer to separate checkout
or artifact directories. The command neither fetches Git revisions nor
discovers running agents.

`--as-of YYYY-MM-DD` is required and applies to both sides. Inventory and review
date windows remain inclusive. `--depth N` selects one positive search bound
for every compared or individually analyzed manifest; its default is eight.
Search depth is not inferred from a revision label or a current clock.

Paths must remain normalized and inside their artifact root. Unsafe paths are
usage errors. Missing or malformed referenced snapshots retain the inventory
reader's entry findings and leave their identities unavailable. Before using a
manifest for analysis, the comparator rereads and checks its bytes against the
inventory's observed digest. A changed or unavailable reread leaves that entry
unresolved; other independently verified deployments remain visible.

## Understand which deployments match

A deployment's key is the exact tuple **repository, environment, agent**.
An index may contain several agents in one repository and environment. Entry
IDs and revision strings remain labels: renaming an ID or reordering the index
cannot choose a different pair. A repository, environment or agent rename is a
membership change, with no automatic continuity mapping.

Exactly one entry with the deployment key is required on each side. Duplicate
deployments stay ambiguous even when one ID or revision appears to match.
If any entry's snapshot identity is unavailable, its declared repository and
environment remain a possible conflicting claim. Comparisons for every known
agent in that same repository/environment stay unresolved; the comparator does
not trust an agent name read from an unverified snapshot to narrow the conflict.
Entries elsewhere remain independently comparable. Original inventory reports
stay unchanged; this uncertainty adds `fleet.diff-deployment-ambiguous` to the
comparison findings and retains the unverified IDs in `unresolved_entries`.
Every eligible candidate manifest still gets an independent authority report,
including duplicate and unmatched entries, so ambiguity cannot hide a breach.

Added and removed deployments require both indexes to describe the same fleet,
declare complete current membership, have eligible snapshots and have no
deployment ambiguity or failed reread. Otherwise presence stays unresolved;
an omitted entry cannot establish removal. Completeness is limited to the
supplied declarations, not authenticated real-world membership.

Valid unique matched manifests can still produce a comparison when membership
is partial or a review has expired. The relation is explicitly scoped to those
compared manifests, and inherited findings keep the fleet gate blocked. A fleet
label mismatch prevents paired authority comparisons; individual reports remain.

## Read authority, membership and review separately

The result schema is `agentmandate.fleet-diff/v2`:

| Field | Meaning |
|---|---|
| `baseline`, `candidate` | Complete unchanged inventory reports, including every original finding and index digest |
| `membership_comparable` | Supplied membership supports scoped addition/removal classification |
| `comparisons` | One row per known deployment key, with entry IDs, metadata changes and independently computed authority |
| `unresolved_entries` | IDs whose snapshot identity is unavailable, retained separately on each side |
| `summary` | Deployment and comparison counts; no combined monetary or effect total |
| `findings`, `gate_passed` | Whole-input findings and the gate outcome |

Matched rows carry the unchanged manifest `diff` report in `authority_diff`.
Relations are `widening_within_compared_manifest_scope`,
`narrowing_within_compared_manifest_scope` or
`neutral_within_compared_manifest_scope`. Missing or ambiguous pairs have
`authority_diff: null` and `relation: unresolved`. Scoped additions and removals
use `added_within_declared_index` and `removed_within_declared_index`.

Each row also carries `baseline_authorities` and `candidate_authorities`, keyed
by entry ID. Unavailable analysis has a null value, not an empty trusted result.
These reports retain reachability, breaches and truncation. Baseline breaches
remain visible during a narrowing release; every candidate breach blocks the
gate, including one in an unchanged, new or duplicated deployment.

A removal withdraws an entry from the supplied index. It does not verify that
the deployment stopped or establish what replaced it. A removal alone stays
non-blocking when both membership declarations are complete and current;
baseline breaches remain visible. A CI process that requires approval for
decommissioning should also gate on rows with `membership: removed`.

Authority widening, new deployments and owner changes produce findings.
Ownership changes require a separate handoff review; this command records no
acceptance. Changes to entry ID, revision and review fields are shown in
`metadata_changes`. Current review declarations cannot suppress authority or
membership findings. Use [named change review](change-review.md) for individual
manifest comparison records and your CI process for fleet release decisions;
this command does not consume exceptions or authenticate a reviewer.

Exit 0 means no findings within the supplied fleet declarations and bound.
Exit 1 means widening, candidate breaches, new deployments, owner changes or
unresolved inventory/review/membership. Malformed indexes, unsafe paths, invalid
bounds, unreadable index/root inputs and unsupported analysis arithmetic exit 2
without partial output. Mixed currencies inside one manifest remain unsupported;
different deployments' budgets are never combined or converted.

## Compatibility and limits

This is an experimental result contract and a new command. Existing fleet
inventory, fleet exceptions, manifest diff and Authority results remain
unchanged. The [v1 replay baselines](../tests/fixtures/fleet-diff-v2.json) pin
unchanged, widening, narrowing, membership/review and expired cases. They are
initial baselines, not migrations from an earlier fleet-diff schema.

Digest equality identifies the supplied bytes. It does not authenticate the
index, Git revision, owner, review or live exposure. A caller who can replace
files and their pins can replace the declarations. Signatures remain
`not_verified`. Runtime policy, shared accounting, cross-agent reachability and
state continuity remain separate decisions. This comparison does not close
those fleet-governance measures or the external security-review gate.
