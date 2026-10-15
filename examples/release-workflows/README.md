# Keep a release from breaking required work

Run from the repository root:

```bash
mandate diff examples/release-workflows/released.json examples/release-workflows/narrowed.json \
  --required-workflows examples/release-workflows/required-export.json
mandate diff examples/release-workflows/released.json examples/release-workflows/breaking.json \
  --required-workflows examples/release-workflows/required-export.json
```

The first release lowers the ceiling and the declared budget but still satisfies the
required 100-record export, so it exits 0. The second lowers the ceiling to 75, so the
same required path no longer conforms; it exits 1 with the failing step named, even
though the release only narrows authority. Without the flag both commands keep their
ordinary output and exits.

`proposed.json` adds a read-only tool, so it widens authority and exits 1 for its own
reason while the required path is preserved. The remaining inputs are usage-error cases:
`impossible-export.json` asks for 400 records against a 300 ceiling, so the released
manifest cannot already satisfy it; the others name a different agent or manifest.

Read the [release-gate guide](../../docs/required-workflows.md) for the matching rules,
the separate findings and the limits.
