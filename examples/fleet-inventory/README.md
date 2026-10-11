# Local fleet inventory example

From the repository root:

```bash
mandate fleet inventory examples/fleet-inventory/index.json --root . --as-of 2026-10-11 --json
mandate fleet inventory examples/fleet-inventory/findings.json --root . --as-of 2026-10-11 --owner release-security
```

The first command exits 0 for three declared entries across two synthetic
repositories and two environments. The second exits 1: filtering the displayed
entries does not hide findings elsewhere in the index. The owner and reviewer
names are synthetic; no actual human acceptance or live deployment is claimed.

The [fleet inventory guide](../../docs/fleet-inventory.md) explains the complete
index format, queries, digest/IR checks and the signing boundary. The snapshots
preserve the release and billing manifests independently; they are not merged
into a combined mandate.
