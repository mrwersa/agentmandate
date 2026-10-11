# Export a stateless Cedar policy

Use this experimental compiler when you have an explicit application mapping
for an agent's tools, principals and enforcement resource. It generates a
policy set, JSON schema, entity examples and request tests. It does not deploy
the policy or run Cedar inside Python.

From a checkout, try the complete release-tool example:

```bash
mandate cedar export examples/cedar-export/manifest.json --mapping examples/cedar-export/mapping.json --output-dir /tmp/release-policy --json
```

Choose a new output directory. The five files are `policies.cedar`,
`schema.json`, `entities.json`, `tests.json` and `export.json`. The last file
contains the complete report, exact input digests, target versions and losses.
Omit `--output-dir` to inspect the result without writing a bundle; `--json`
returns all generated contents and the normal output shows policies and losses.
An existing output path, including a symlink, is never replaced. Staging errors
leave the destination absent; a concurrent destination is preserved.

## What the compiler supports

The mapping selects one namespace, one exact enforcement resource, explicit
principal entity IDs per caller/service class, a distinct action ID per tool,
and one Boolean approval-context attribute. All tools and used principal
classes must be mapped. Principal checks use equality, so an entity's ancestors
do not grant it the mapped identity's permission. Resource and action checks
also use equality. A tool with `requires_approval` is allowed only when its
approval attribute is present and true; other tools do not acquire that gate.

Mapping keys are closed. `cedar_export_version` must be 1, and `agent` and
`identity` must match the source manifest, including a null identity. Namespaces
and entity types use Cedar identifiers; entity types are local to the namespace.
Action/entity IDs use printable ASCII strings, with quotes and backslashes
escaped. The generated schema defines the mapped entity types and actions,
with optional Boolean approval context. Empty or ambiguous principal lists,
aliases across principal classes, unmapped tools and duplicate actions fail.
The [example mapping](../examples/cedar-export/mapping.json) shows every field.

The mapping is application-supplied configuration, not authenticated evidence.
Your adapter must construct these exact principal/action/resource values and
obtain approval from a trusted source. Passing an arbitrary Boolean supplied
by the agent would not enforce approval. The generated entity file is test
input, not an authenticated directory or a live system-of-record export.

## Stateful constraints block export

Cedar evaluates individual requests; this compiler does not add a history
store. The loss report names each unsupported source control:

| Loss code | What remains unenforced |
|---|---|
| `limits.total` | Accumulated monetary spend |
| `limits.effects` | Accumulated call counts, reported per declared effect |
| `tool.ceiling` | Cumulative spend by one tool against one scope binding |
| `tool.requires` | Availability of bindings produced by previous calls |
| `tool.produces` | Binding creation and finite/unbounded cardinality |
| `roles` | Role views and maker-checker analysis |

A per-request amount check cannot replace a cumulative tool ceiling. The
compiler therefore omits that check and reports the unsupported control.
`limits.depth` is the search horizon, not an enforcement budget, and is not
compiled into a request condition. Effect labels describe the tool; they do
not establish that execution has the declared effect.

Default refusal returns losses with null policy/schema and creates no bundle.
To inspect a partial candidate, add `--allow-partial`. It emits the stateless
subset with the same losses and **still exits 1**. The option is not approval
to deploy that approximation. A native-valid partial policy still lacks the
controls identified by its loss report. Continue running manifest lint,
reachability and release diff separately.

## Validate and exercise the output

The target is Cedar language 4.5 with the official Cedar WASM SDK 4.12.0,
matching the existing repository experiments. Install the pinned test runner:

```bash
cd examples/cedar-export
npm ci --ignore-scripts
node check.mjs /tmp/release-policy
```

The runner parses the policy, calls native schema validation, checks every
request's expected decision without policy-evaluation errors, and checks that a
child principal cannot inherit the explicit principal's permission. Its JSON
output is a separate validation result; compilation records
`native_validation: not_run`. CI requires this native job and also checks a
72-request matrix derived independently from the source tools and mapping.
These finite tests do not prove all possible requests or deployment behavior.

Cedar validation checks consistency with a schema, not whether your application
supplies the intended facts or enforces decisions. See the official
[validation guide](https://docs.cedarpolicy.com/policies/validation.html).
Validate again when adapting the schema, policy, entity data or request builder.

Exit 0 means a complete export of this supported stateless subset; exit 1 means
semantic losses, including an explicitly requested partial candidate. Exit 2
means malformed input, a mapping mismatch or I/O failure, with empty stdout.
No runtime dependencies, credentials, network calls or cloud resources are
required by the Python compiler. Rego export and stateful enforcement are open.
