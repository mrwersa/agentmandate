# Compare Rego decisions across releases

Use `mandate rego diff` when a release changes the generated stateless policy or
its tool mapping. It reports which exact captured requests change from Deny to
Allow, while retaining the independent manifest authority comparison. A stable
captured decision cannot hide a newly reachable breach.

From the repository root:

```bash
mandate rego diff --baseline examples/rego-diff/baseline.json \
  --candidate examples/rego-diff/candidate.json \
  --baseline-root . --candidate-root . --as-of 2026-10-12
```

The synthetic candidate removes `publish_release`'s approval requirement.
Three requests match across revisions: read and approved publication remain
allowed, while publication without approval changes from Deny to Allow. The
command exits 1 and names that tool, both decision IDs and the request digest.
It also retains the separate manifest widening and ungated-publication breach.
This demonstrates the implementation; it is not accepted deployment evidence.

## Point at the materials already used for reconciliation

Each side takes a capture-set index with exactly these fields:

```json
{
  "rego_capture_version": 1,
  "manifest": "release/manifest.json",
  "configuration": "release/config.json",
  "decisions": "release/decisions.json",
  "telemetry": "release/telemetry.json",
  "mapping": "release/reconciliation-mapping.json"
}
```

Paths are relative to that side's explicit root. Absolute paths, traversal,
missing files and symlinks escaping the root are refused. The index groups
existing inputs; it supplies no new approval or capture-trust assertion.

The command recomputes [deployment reconciliation](deployment-reconciliation.md)
on each side. That reader checks exact manifest/configuration/OPA/OTLP pins,
generated policy and schema bytes, bundle revisions, mapped tool attempts,
masking and inclusive observation/expiry windows. It requires the existing
application correlation and telemetry attributes. Bare OPA logs without these
joins do not satisfy this slice. It does not launch OPA or contact a service.

Provide complete current captures on both sides. Protect the capture indexes,
mapping and source files in your review process: replacing both the files and
their declared pins can replace the record. Digests identify supplied bytes;
they do not authenticate a principal, driver, loaded policy or human review.

## Read the comparison at its actual scope

Requests match by an exact, value-normalized JSON representation of the entire
policy input, excluding only the mapping's application correlation object.
Principal, action, resource, context
and every other input field must agree. The correlation key cannot replace
one of the four policy request fields. Request digests and decision IDs make
the match replayable without printing raw context or payloads. Digests are not
an anonymization mechanism; low-entropy inputs may be guessable.

Exactly one selected decision per request is required on each side. Repeated
requests are ambiguous even with distinct execution IDs; they are never paired
by array order, summed or averaged. A request present on only one side remains
unresolved. Changes to an input value are different requests, even when the
generated policy ignores that field. Object key order is ignored; array order
and JSON types are preserved. Numbers use their exact decimal value: `1`, `1.0`
and `1e0` match, as do `0` and `-0`. Distinct decimals such as `0.1` and
`0.1000000000000000055511151231257827` stay distinct. Boolean `true` does not
match numeric `1`. No binary-float rounding or currency conversion is involved.
This is the comparator's exact-number representation, not RFC 8785's
IEEE-754 number serialization.

The reports use scoped relations:

| Relation | Meaning for the exact matched request |
|---|---|
| `widens_within_captured_scope` | Deny becomes Allow |
| `narrows_within_captured_scope` | Allow becomes Deny |
| `stable_allow_within_captured_scope` | Both allow |
| `stable_deny_within_captured_scope` | Both deny |
| `unresolved` | No eligible unique comparison; both comparison values are null |

Both records must agree with their independently rebuilt generated subset.
Any reconciliation finding on either side blocks positive comparisons for the
capture set, including incomplete coverage, expiry, policy-file drift,
contradictions and unsupported controls. The original reports remain unchanged
so a reviewer can inspect each finding and eligible observation separately.
Masking any policy-input field blocks that request's equality claim, including
payload fields that reconciliation otherwise permits masking.

Agent, declared identity, environment, gateway, bundle, correlation key and
query path must agree across sides. Changes to those boundaries are unresolved,
rather than attributed to a policy revision. A shared revision label with
different policy bytes is likewise unresolved. Changed policy bytes with a new
revision label are permitted and checked through each side's configuration.

The result is `agentmandate.rego-effective-diff/v1`. It contains both original
reconciliation reports, capture/input digests, scoped request comparisons and
the independently recomputed `authority_diff`. Different agent names cannot
have an authority diff: that field is null and both original Authority reports
remain present. No agent is silently renamed to make the join work.

## Gate a release in CI

```bash
mandate rego diff --baseline baseline/capture.json --candidate candidate/capture.json \
  --baseline-root baseline --candidate-root candidate --as-of 2026-10-12 --json \
  > rego-review.json
```

Use a date selected by your pipeline; the example date is fixed for reproducible
fixtures. Retain the JSON as a build artifact and inspect these exits:

- **0:** no widening within the matched captured scope, no unresolved capture
  or comparison findings, no manifest authority widening and no candidate
  reachable breach. This is not a completeness or deployment-approval verdict.
- **1:** observed widening, unresolved comparison, inherited capture findings,
  manifest widening or a candidate breach. Narrowing sampled requests cannot
  override a manifest finding.
- **2:** malformed, unsupported or unreadable input, invalid dates or unsafe
  paths. The command emits no partial JSON.

Native OPA tests reproduce the example's recorded decisions against the exact
generated policies and the existing pinned target. These finite tests do not
establish every possible request or authenticate a live capture. The command's
`native_validation` remains `not_run`; ordering, accounting and runtime
continuity remain `not_assessed`.

The unchanged and narrowing examples can be tried by using the baseline index
on both sides, or swapping the two indexes. Initial widening, unchanged,
narrowing and expired [v1 baselines](../tests/fixtures/rego-effective-diff-v1.json)
pin the result; earlier exporter and reconciliation outputs are preserved.
Arbitrary Rego import, general policy equivalence, state migration and live
enforcement authentication remain outside this contract.
