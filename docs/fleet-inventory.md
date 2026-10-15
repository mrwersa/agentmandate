# Query agents and tools across repositories

Use `mandate fleet inventory` to combine local manifest and Authority IR
snapshots into a searchable inventory. It answers which repository declares a
tool, who owns that entry, which environment it belongs to, and whether its
recorded review is current. It verifies each pair independently and keeps
repository and environment identities separate.

From the repository root, try the synthetic two-repository example:

```bash
mandate fleet inventory examples/fleet-inventory/index.json --root . --as-of 2026-10-11
mandate fleet inventory examples/fleet-inventory/index.json --root . --as-of 2026-10-11 --tool read_release --json
mandate fleet inventory examples/fleet-inventory/index.json --root . --as-of 2026-10-11 --owner billing-security --environment prod
```

The example contains three entries: release in production and staging, and
billing in production. All three declare `read_release`; they remain three
separate tool occurrences. Their eight declared tools are not eight unique
tool names, a reachable combined capability set, or a shared budget.

Inspect an index with an unassigned owner, an unreviewed entry, an expired
review and a mismatched IR digest:

```bash
mandate fleet inventory examples/fleet-inventory/findings.json --root . --as-of 2026-10-11 --owner release-security
```

It exits 1 even though the selected release entry is healthy. Filters change
the displayed entries; every entry is validated first, all findings remain in
the result, and the gate evaluates the whole index. A tool query cannot match
an unreadable snapshot, so zero matches does not establish that no agent has
the tool.

## Build an index from your repositories

Collect each reviewed manifest and run `mandate ir export` to produce its
snapshot. Keep the captured files under one local artifact root. The
[example index](../examples/fleet-inventory/index.json) shows every field of
`fleet_version: 1`:

| Field | Meaning |
|---|---|
| `fleet` | Name of the indexed collection |
| `coverage` | Caller-declared `complete`, `partial` or `unknown` membership |
| `observed_at`, `expires` | Inclusive date window for that membership declaration |
| `entries` | Independent repository/environment entries |

Each entry supplies a unique `id`, `repository`, `revision`, `environment`,
`owner`, `review`, `manifest` and `ir`. Repository and revision values are
labels; the command does not fetch Git references or authenticate their
association with the files. Use distinct environments or repository labels
for independent deployments. Two entries for the same repository, environment
and agent produce `fleet.deployment-ambiguous`, including when their revisions
differ. Both remain visible; the command does not select the newest revision
or silently discard a duplicate.

The owner may be null, which produces `fleet.owner-unassigned`. Review fields
are `state` (`accepted`, `unreviewed` or `contested`), `reviewer`, `reviewed_at`
and `expires`. The last three may be null. A current review requires declared
acceptance, a named reviewer and a complete inclusive date window containing
`--as-of`. Incomplete, contested, future or expired reviews produce
`fleet.review-not-current`. These declarations do not authenticate a person's
decision; the application must control who can change the index and snapshots.

The manifest and IR references each contain `path` and `sha256`. Paths must be
normalized relative paths inside `--root`; absolute paths, parent traversal,
drive prefixes and escaping symlinks are rejected. Pin lowercase SHA-256
digests of the exact file bytes. Hash equality detects changed files relative
to the index. Someone able to change both files and pins can replace the
record; it is not a signature.

## Read the integrity and review results separately

The command checks file digests, validates the existing closed manifest-v1 IR
profile, joins its source digest to the exact manifest bytes, and reconstructs
the mandate to compare its meaning with the manifest. It accepts the profile
already used by `reach --ir`, including its accepted, exact fact requirements.
Other IR profiles stay ineligible for this inventory consumer. New profiles
need their own compatibility decision; structural validity is insufficient.

Missing files, changed digests and malformed or unsupported snapshot contents
produce findings for their entries. Other repositories remain queryable.
An ineligible entry retains metadata and artifact status but reports its
agent, identity and declared tools as null. It never turns unavailable tools
into an empty, trusted list. An expired review can leave a valid snapshot
queryable, with `review_current: false`; snapshot integrity and current review
are different properties.

The result is `agentmandate.fleet-inventory/v1`. `summary` counts the whole
index and separately counts selected entries. Tool occurrences are counted per
eligible entry, without summing monetary limits or composing mandates.
`inventory_complete_within_declared_index` requires a current, complete
membership declaration, eligible pairs and no ambiguous deployments. It says
nothing about unlisted real repositories or authenticated review.

Exit 0 means consistency within the supplied index. Exit 1 means findings or
unresolved membership, ownership, review or artifact joins. Malformed index
fields, duplicate keys or IDs, unsafe paths and unreadable index/root inputs
exit 2 with empty stdout. Referenced files that are missing, cyclic or unreadable are
entry findings, not a reason to discard the rest of the index.

`signatures` is always `not_verified`. This first slice uses local declarations;
it does not discover running agents, import registry membership, validate
signed bundles, infer runtime exposure or search across agents. Use
[deployment drift](deployment-drift.md) for supplied gateway/policy joins and
`reach` on each manifest for bounded authority analysis. No network access,
application imports or runtime dependencies are required.

Use [fleet release comparison](fleet-diff.md) to compare two supplied indexes
and identify per-deployment authority widening, membership changes and review
findings without combining mandates.
