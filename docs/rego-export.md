# Export a stateless Rego policy

Use `mandate rego export` to turn an explicitly mapped toolset into a Rego v1
policy for OPA. The compiler emits a default-deny policy, an input schema,
native request tests and a report identifying constraints it cannot enforce.
It runs locally with no runtime dependencies and does not deploy a policy.

From a checkout, try the release-tool example:

```bash
mandate rego export examples/rego-export/manifest.json --mapping examples/rego-export/mapping.json --output-dir release-policy --json
```

Choose a new directory. The bundle contains `policy.rego`, `policy_test.rego`,
`schema.json`, `tests.json` and `export.json`. The report includes exact source
digests, target versions, mapping and losses. Without `--output-dir`, the
command prints the candidate without writing files. Existing paths and
symlinks are refused; staging errors leave no incomplete destination.

## Map application requests

The [example mapping](../examples/rego-export/mapping.json) assigns:

- A package such as `release_gate` or `platform.release`.
- Explicit principal IDs for each caller/service class used by the tools.
- One exact resource ID and a distinct action ID for every tool.
- A context key that your application supplies from a trusted approval source.

`rego_export_version` must be 1. `agent` and `identity` must match the manifest,
including a null identity. Unknown keys, missing tools, empty principal lists,
duplicate action IDs and shared identities across principal classes fail.
Package segments use ASCII identifiers and cannot be Rego keywords. IDs and
context keys use nonempty printable ASCII; quotes and backslashes are escaped.

The generated policy expects requests with this shape:

```json
{
  "principal": "release-operator",
  "action": "PublishRelease",
  "resource": "release-tools",
  "context": {"approved": true}
}
```

The decision is `data.release_gate.allow`. Principals, actions and resources
must be strings; context must be an object. A missing field, unknown identity,
unknown action or different resource is denied. Extra input fields do not add
permissions. Tools requiring approval also require the mapped context value
to be Boolean `true`; missing, false, numeric and string values cannot satisfy
that condition. Other tools do not acquire an approval requirement.

Principal IDs are exact matches, with no hierarchy or role expansion. Your
adapter must authenticate the principal, construct the intended action/resource
and enforce the returned decision. An agent-supplied approval Boolean is not
an approval mechanism. This mapping declares application intent; the compiler
does not authenticate it or discover live deployment identities.

## Keep sequence controls visible

The supported subset is stateless permission and approval. Accumulated monetary
spend, effect counts, per-binding tool ceilings, produced-binding prerequisites,
binding cardinality and role views remain explicit losses. Both exporters use
the same [loss categories](cedar-export.md#stateful-constraints-block-export).
A tool ceiling cannot safely become a per-request amount check. `limits.depth`
is an analysis horizon and does not become an enforcement budget.

By default, any loss refuses export and creates no bundle. `--allow-partial`
emits only the supported subset with the same loss report and **still exits 1**.
That candidate is available for inspection; it does not establish preservation
of the original mandate's compound constraints. Continue using `lint`, `reach`
and `diff` to review the full manifest.

## Run native validation and tests

The target is Rego v1 with OPA 1.21.1. The example pins the official Linux
x86-64 static binary and SHA-256 in
[opa-target.json](../examples/rego-export/opa-target.json). Download and verify
that binary before executing it:

```bash
curl -fL https://github.com/open-policy-agent/opa/releases/download/v1.21.1/opa_linux_amd64_static -o opa
echo '668506eb17a2eaa1fce6cc0d1f42ef85125d4ac5bda5fc74d1152d0c77145031  opa' | sha256sum -c -
chmod +x opa
python examples/rego-export/check.py release-policy --opa ./opa
```

The runner verifies the pin, runs `opa check --strict --schema` and exercises
every generated request through `opa test`. Its validation result is separate
from the compiler's `native_validation: not_run`. CI requires native validation
and also compares an independently constructed 120-request matrix plus malformed
requests with decisions derived from the source tools and mapping. These finite
checks do not prove every input or authenticate a deployed decision point.

OPA's schema check aids policy compilation; it does not validate every runtime
input. The generated policy contains its own request-shape guards. See the
official [Rego language guide](https://www.openpolicyagent.org/docs/policy-language)
and [default rule reference](https://www.openpolicyagent.org/docs/policy-reference/keywords/default).

Exit 0 means all declared controls fit the supported stateless subset. Exit 1
means semantic losses, whether export was refused or explicitly partial. Exit 2
means malformed input, mapping mismatch or I/O failure, with empty stdout.
Compilation makes no network calls and introduces no Python policy evaluator.
Policy deployment, Rego import/effective diff and stateful enforcement remain
separate work.
