# Cedar Effective-Diff Gate 5 Review

Status: **approved for CLI exposure**. The public-boundary review was
reproduced against `89a56b0` on 29 August 2026. Its tree is byte-identical to
the merged commit `68a7504`:

```text
$ git rev-parse '89a56b0^{tree}' '68a7504^{tree}'
bfa16624f43ed2ffa246185dfea32e49e04fe67d
bfa16624f43ed2ffa246185dfea32e49e04fe67d
```

Structural validation remains separate from trusted consumption. A managed
oracle that parses is not thereby evidence that the declared sources, mapping,
managed state, or decisions are eligible.

## Decision summary

| Review | Verdict | Evidence |
|---|---|---|
| Structural validation | Passed | A valid oracle exits 0; malformed or missing input exits 2 with empty stdout |
| Managed alignment | Passed | The baseline reports `aligned_allow` for `amount: 500` and `enforcement_narrows_request` for `amount: 2000` |
| Live revision widening | Passed | Matched managed captures reproduce `stable_allow` for 500 and `widens` for 2000 from native responses |
| Conservative failure | Passed | Expired review, changed joins, incomplete state, and source tampering retain manifest authority and emit unresolved findings |
| Containment and no partial output | Passed | Missing, unsafe, traversing, or symlink-escaping source roots exit 2 before stdout |
| Output stability | Passed | Namespaced JSON is byte-pinned and carries manifest, oracle, profile, mapping, and per-source digests |

## Closing verdict

**Cedar import and effective-diff gates 1–5 passed for the reviewed managed
AgentCore profile.** The real CLI reproduced structural validation,
exact-request alignment, a live Deny-to-Allow widening, complete-output finding
exits, and no-partial-output usage failures. The suite passed with 1,176 tests
and 100% statement coverage. Ruff, evidence-digest lint, and whitespace checks
were clean.

The public surface is deliberately narrow:

```text
mandate cedar validate ORACLE
mandate cedar align MANIFEST --oracle ORACLE --source-root DIR --as-of YYYY-MM-DD
mandate cedar diff MANIFEST \
  --baseline-oracle ORACLE --baseline-root DIR \
  --candidate-oracle ORACLE --candidate-root DIR \
  --as-of YYYY-MM-DD
```

`validate` proves structure only. `align` and `diff` strictly re-read the
oracle, resolve every declared source beneath an explicit root, verify source
digests and the closed managed IR profile, and evaluate reviewed mapping expiry
against the supplied date. They do not read AWS credentials, contact AWS, or
evaluate Cedar policy text.

## Reproduced trust matrix

The live one-tool fixture is representative, not a global proof. Its baseline
allows the canonical 500 request and default-denies the canonical 2000 request;
the candidate allows both. The comparator therefore reports one stable Allow
and one widening for those exact requests. It does not infer the policy's
condition or generalize to every numeric amount.

Every weaker trust state remains observable:

- expired, contested, or non-exact mapping evidence blocks all decisions;
- changed principal, resource binding, authorizer, protocol, enforcement mode,
  complete inventory, or sanitization boundary blocks comparison;
- missing or digest-mismatched source bytes produce `managed.source-untrusted`;
- an unsupported claimed outcome, including invented explicit-Deny evidence,
  remains unresolved rather than being recovered from policy text; and
- changed request arguments are different requests, not a policy revision.

These failures preserve the full manifest authority, emit complete alignments
and named findings, and exit 1 after output. Malformed records, invalid dates,
missing roots, path traversal, absolute locators, and escaping symlinks are
usage failures: they exit 2 with empty stdout.

Local Cedar-WASM bundles and managed AgentCore oracles remain separate closed
profiles. Managed evidence cannot claim `schema_checked` or determining-policy
diagnostics that the service did not return. Both profiles remain ineligible
for general `reach --ir`; only the explicit Cedar consumer performs the
reviewed join.

## Output and interface contract

Human output separates `ALIGNED`, `NARROWS`, `WIDENS`, and `UNRESOLVED` results.
JSON uses `agentmandate.cedar-alignment/v1` and
`agentmandate.cedar-effective-diff/v1`. It records input and profile digests and
per-request support sufficient to replay the mapping, request, and response
claims without exposing local paths or cloud identifiers.

The result schemas are presentation artifacts, not importable authority. No
public Python records were added. SARIF, Mermaid, Authority IR, condition,
delegation, and runtime composition remain unsupported rather than silently
dropping managed-policy uncertainty.

## Release and non-goals

The new commands, options, Authority IR relations, and presentation schemas
require a minor release under `RELEASING.md`. They are ready for the next minor
release train after this review record merges.

This delivery does not add a Cedar parser or evaluator, infer a complete
request domain, attribute managed decisions to individual policies without
native diagnostics, mutate manifest reachability, discover cloud resources,
handle credentials, export policy, or provide a runtime proxy. Rego and the
other inventory-import experiments remain separate roadmap work.
