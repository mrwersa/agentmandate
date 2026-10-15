# Join decisions to tool attempts

Use `mandate deployment reconcile` after [deployment drift](deployment-drift.md)
to check whether captured policy decisions and tool attempts describe the same
request under the reviewed configuration. This first slice reads decompressed
OPA decision-log arrays and OTLP JSON for the generated Rego stateless subset.
It preserves the separate deployment report and manifest Authority result.

From the repository root, run the synthetic three-attempt example:

```bash
mandate deployment reconcile examples/deployment-reconcile/manifest.json \
  --config examples/deployment-reconcile/config.json --root . \
  --decisions examples/deployment-reconcile/decisions.json \
  --otel examples/deployment-reconcile/telemetry.json \
  --mapping examples/deployment-reconcile/mapping.json --as-of 2026-10-11 --json
```

It exits 0 for one read, one refused publication and one approved publication.
Each attempt joins exactly one decision. Change `--otel` to
`denied-effect-telemetry.json` and `--mapping` to `denied-effect-mapping.json`;
the command exits 1 for `reconciliation.denied-effect-observed`. The attempt
reports an applied effect associated with a denial. Its identifiers do not
establish causal order, and the finding does not become a manifest reachability
breach. Both examples are synthetic, not accepted live-service evidence.

## Capture the joins your application knows

OPA's [decision-log format](https://www.openpolicyagent.org/docs/management-decision-logs)
includes decision IDs, query paths, inputs, results and bundle revisions.
This consumer selects the generated package's `/allow` path, allowing one
leading slash. It requires Boolean results and the bundle selected by the
mapping. Other policy paths are counted as ignored; missing paths remain
findings. A repeated decision ID is ambiguous, including when the repeated
event queried a different path. Upload retries and repeated instrumentation
are not automatically treated as one operation.

Your policy input must also carry an application correlation object. The
example uses `input.agentmandate`, selected by `input_key` in the mapping:

| Correlation field | What the application records |
|---|---|
| `run_id`, `invocation_id` | Explicit run and tool-attempt identities |
| `manifest_sha256`, `configuration_sha256` | Exact source bytes used by that attempt |
| `manifest_version` | Integer manifest schema version |
| `gateway` | Enforcement-boundary label from the deployment configuration |

The policy request's principal, action, resource and approval context retain
their exporter meanings. The configured bundle revision must match the
deployment revision label. If your installation logs no bundle revision, this
consumer leaves that join unresolved; a matching policy file does not supply
the missing event metadata.

Tool telemetry uses the [OTLP JSON format](https://opentelemetry.io/docs/specs/otlp/),
either one request or one request per line. A selected span must have
`gen_ai.operation.name: execute_tool` and `gen_ai.tool.name`. The mapping names
application attributes for all the correlation fields above, plus
`decision_id`, `policy_revision`, `principal`, `action`, `resource`, `approved`
and `effect_applied`. Standard tool names alone cannot establish these joins.
The [example mapping](../examples/deployment-reconcile/mapping.json) contains
the complete `reconcile_version: 1` format.

String identifiers, integer schema versions and Boolean approval/effect claims
must use their corresponding OTLP AnyValue variants. Strings such as `"true"`
and numeric truthy values never become approval. Unsupported attribute variants
remain unknown. Duplicate attribute keys are rejected, rather than allowing
one value to overwrite another. Duplicate tool spans sharing a decision or
run/invocation pair stay ambiguous.

`effect_applied` is an explicit application observation. Span success or error
does not supply it; an error does not establish that nothing happened. Emit
false only when your application can support that claim. This consumer neither
checks effect quantities nor accumulates spending across attempts or runs.

## Keep completeness and freshness visible

The mapping pins exact manifest, configuration, decision-log and telemetry
bytes. It supplies `complete`, `partial` or `unknown` coverage independently
for decisions and telemetry, plus inclusive `observed_at` and `expires` dates.
The deployment configuration must also be current at the caller's `--as-of`
date. These are caller declarations, not independently authenticated membership
or freshness. Protect the mapping and captured materials outside the library;
someone who can replace both files and pins can replace the record.

Complete current captures permit a finding that an identifier has no matching
record *within the supplied capture*. Partial coverage leaves absence unresolved.
An existing masked, malformed or conflicting record is likewise unresolved,
not reported as absent. Nonempty selected decisions and tool attempts are
required; empty captures cannot provide a clean demonstration.

Source-pin mismatch or expired materials prevent positive joined-result
claims: decision values and reported effects remain null. Masking or erasing a
protected identity, path, bundle, input or result field also makes that decision
ineligible. Unrelated
payload masking can remain compatible with the join. The output retains hashes
and selected identifiers/comparisons, not raw policy inputs, payloads, resource
attributes or arbitrary telemetry attributes. Capture minimization and access
control remain the application's responsibility.

## Interpret a consistent join narrowly

The result is `agentmandate.deployment-reconcile/v2`. It checks exact request
joins and compares recorded decisions with the *generated stateless subset*.
Native OPA tests check this comparator against the pinned exporter; the command
does not evaluate arbitrary Rego or launch a policy engine. A decision that
contradicts that subset produces `reconciliation.decision-contradiction`.
Unsupported budgets and other exporter losses remain deployment findings even
when all telemetry joins match. A matched request cannot erase those limits
or the independent manifest breach.

`matched_within_captured_scope` means the supplied identifiers and request
fields agree. It does not authenticate the driver, principal, approval,
gateway, loaded policy or observed effect. A captured denial associated with a
reported effect is a contradiction worth investigating, not proof that a
particular live enforcement point was bypassed. The result always states
`ordering`, `accounting` and `runtime_continuity: not_assessed`, plus
`native_validation: not_run`. UTC and span interval fields are not used to
establish ordering. Equivalent per-call decisions do not prove retained state.

Exit 0 means consistency within this captured join. Exit 1 means deployment or
reconciliation findings, including unresolved joins or coverage. Exit 2 means
malformed input, unsupported target, unsafe paths or I/O errors, with empty
stdout. Cedar, cloud decision logs, signed/authenticated captures, causal
ordering and accrued-state joins remain open. This first slice does not complete
the broader decision/OTel reconciliation roadmap initiative.
