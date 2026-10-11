# Check policy and gateway configuration drift

Use `mandate deployment drift` when you already have a manifest and a
[Cedar](cedar-export.md) or [Rego](rego-export.md) export. It compares that
intent with a supplied bound-tool inventory, gateway routes and active policy
files. A tool can still exist in source while its gateway stops checking
approval or points at a different policy; this gate checks those configuration
joins separately from ordinary source `drift`.

Try the aligned example from the repository root:

```bash
mandate deployment drift examples/deployment-drift/manifest.json --config examples/deployment-drift/rego-aligned.json --root . --as-of 2026-10-11 --json
```

For Cedar, substitute `cedar-aligned.json`. Both examples exit 0 with
`status: consistent_with_declared_configuration`. Inspect the broken release:

```bash
mandate deployment drift examples/deployment-drift/manifest.json --config examples/deployment-drift/rego-drifted.json --root . --as-of 2026-10-11
```

It exits 1 and identifies an undeclared tool, bypassed mediation, lost approval,
a different policy revision, an extra principal and an additional policy module.
The main policy still matches its export. The extra module actually turns an
OPA denial into an allow in the native test, demonstrating why matching one
policy file alone is insufficient.

## Supply the deployment configuration

The [example configuration](../examples/deployment-drift/rego-aligned.json)
shows the complete `deployment_version: 1` format. An application-owned adapter
must produce this normalized view from its actual configuration. The command
does not read a vendor's gateway syntax, query a service or infer deployment
membership from a source catalogue.

| Field | What your adapter supplies |
|---|---|
| `agent`, `identity`, `environment` | Intended agent, declared identity and deployment label |
| `observed_at`, `expires` | Inclusive date window for this configuration snapshot |
| `export` | `cedar` or `rego`, plus relative paths to the exact mapping and export receipt |
| `inventory` | Bound tool names and `complete`, `partial` or `unknown` coverage |
| `gateway` | Boundary ID, coverage and one active route per tool |
| `policy` | Revision label, coverage and the complete active authorization artifact list |

Each route declares its tool, principals, action, resource, approval-context
key, mediation state and policy revision. Rego uses string IDs; Cedar uses
qualified entity objects with `type` and `id`. `approval_context` is null for
an ungated route. `policy_revision` can be null when it is not known. Mediation
is `required`, `bypassed` or `unknown`; only `required` can match the intended
gate. Empty principal lists are analyzed as narrowing rather than ignored.
Multiple routes for one tool are unsupported and rejected instead of merged.

The active artifact labels are `policy.rego` and `schema.json` for Rego,
or `policies.cedar` and `schema.json` for Cedar. List additional active modules
under distinct labels too: they produce findings. Generated Cedar entities are
test data, not a directory that deployments must reproduce, and are not part
of this file comparison. Include all authorization layers your adapter claims
to cover; mark the policy or gateway partial when it cannot enumerate them.

All file paths are normalized, relative to `--root`, and must resolve to files
inside that directory. Absolute paths, parent traversal and escaping symlinks
are rejected. In the configuration, duplicate JSON keys, tool names and routes, unknown fields,
invalid dates and malformed IDs are usage errors.

## Understand the result

The gate independently recompiles the manifest with the supplied mapping. It
compares the receipt with that result and hashes the active policy/schema
bytes. A well-formed receipt object with different fields or values produces
`deployment.export-mismatch`; invalid JSON or a non-object receipt is a usage
error. Editing a receipt cannot erase an unsupported constraint; even a valid
partial receipt retains `deployment.control-uncompiled` findings. Monetary
ceilings do not become per-call checks.

Byte equality is deliberately conservative. Even a whitespace-only policy
change is reported as different; a changed file is not labeled equivalent or
wider without a native semantic comparison. Extra modules remain findings
even when the expected policy matches. Revision labels are compared for
internal route association, not authenticated against a live provider.

Complete, current inventory and gateway lists permit absence findings. Partial,
unknown or expired lists leave absent tools and routes unresolved; known extra
tools still produce findings. Missing policy artifacts are likewise unresolved
when policy coverage is incomplete or the snapshot is not current. Observation
dates and expiry are caller annotations, not authenticated freshness evidence.
An evaluation date before observation or after expiry prevents a clean result.

The versioned result is `agentmandate.deployment-drift/v1`. It retains separate
per-tool comparisons, artifact digests, source digests and the independently
computed manifest `authority`. Deployment findings do not modify reachable
breaches. The command does not run a policy engine: `native_validation` stays
`not_run`, and `runtime_continuity` stays `not_assessed`.

Exit 0 means consistency within the supplied configuration and byte-comparison
scope. It does not prove that a gateway actually evaluated a call, enforced
approval, retained accrued state or activated the intended revision. The
adapter remains responsible for authenticated identities, complete snapshots
and trusted approval data. Run native export checks, `lint` and `reach`
separately. Ordinary `mandate drift --source` remains unchanged.

Exit 1 means configuration drift, unsupported controls or unresolved coverage
or dates. Exit 2 means malformed input, unsupported mapping, unsafe paths or
I/O failure, with empty stdout. No credentials, network access, policy
interpreter or runtime dependencies are required.
