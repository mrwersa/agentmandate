# Deployment-policy drift example

From the repository root:

```bash
mandate deployment drift examples/deployment-drift/manifest.json --config examples/deployment-drift/rego-aligned.json --root . --as-of 2026-10-11
mandate deployment drift examples/deployment-drift/manifest.json --config examples/deployment-drift/rego-drifted.json --root . --as-of 2026-10-11
```

The first command exits 0. The second exits 1 with six actionable findings.
`cedar-aligned.json` exercises the same join with Cedar entity IDs. The files
reference the existing exporter examples and declare synthetic gateway
configuration; they are not observations of a live deployment.

`unmanaged-allow.rego` is deliberately permissive. It shows how an additional
active module can widen OPA decisions even when the exported main policy is
unchanged. The native regression test proves that decision change; the Python
gate detects the additional file without evaluating Rego.

See [the deployment drift guide](../../docs/deployment-drift.md) for the
configuration fields, coverage boundaries, expiry and result contract.
