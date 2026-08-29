# AgentCore IAM refund-policy evidence

Captured on 29 August 2026 in `us-east-1`. This fixture is the first live
operational mapping for the [Cedar import contract](../../cedar-import.md): one
AWS IAM-authorized AgentCore Gateway exposed one Lambda tool and enforced one
ACTIVE Cedar policy in `ENFORCE` mode. A second clean deployment preserved the
reviewed boundary and changed the candidate policy threshold. Together the
captures prove a managed Deny-to-Allow revision for one exact request. They do
not make imported policy analyzable authority or expose the private comparison
through the CLI.

## Reproduced controls

The deployed tool was `RefundIamTarget___process_refund`. Its Lambda is a
synthetic echo, not a payment integration: it returns the supplied integer and
performs no refund. The reviewed manifest therefore classifies the tool as
`read`; this fixture tests policy transport and mapping, not a financial side
effect.

| Request | Managed result |
|---|---|
| `tools/list` | exactly one mapped tool |
| `amount: 500` | allowed; Lambda returned `processed: true` |
| `amount: 2000` | denied before execution with AgentCore policy error `-32002` |
| candidate `amount: 500` | allowed again; stable control |
| candidate `amount: 2000` | allowed; live `deny` → `allow` widening |

The policy permits the exact IAM principal type, tool action, and Gateway
resource only when `context.input.amount < 1000`. The committed policy replaces
the live Gateway ARN with `<reviewed-gateway-binding>`; `mapping.json` preserves
that join as the reviewed binding `agentcore-refund-gateway`. The JSON-RPC
request and response bodies are canonical projections of the captured bodies;
their decision fields were not altered. SigV4 headers and all live identifiers
were omitted.

The capture initially requested MCP `2025-11-25`. AgentCore refused it and
advertised `2025-03-26`; the successful calls use the advertised version. The
refusal is retained rather than silently correcting the attempted request. The
candidate reused the supported version and did not repeat the rejected probe.

## Managed comparison controls

A fresh task-scoped deployment tested two negative controls under one logical
Gateway, one IAM authorizer, one Lambda-backed tool, and one ENFORCE policy
engine. The baseline condition admitted amounts below 1,000. A semantic no-op
added `&& true`, while a narrowing revision lowered the threshold to 400.

| Revision comparison | `amount: 500` | `amount: 2000` | Reported changes |
|---|---|---|---|
| baseline → semantic no-op | Allow → Allow | Deny → Deny | `stable_allow`, `stable_deny` |
| baseline → narrowing | Allow → Deny | Deny → Deny | `tightens`, `stable_deny` |

Neither control reports `widens`. Each raw status snapshot contained exactly
one deployed Gateway, target, engine, and policy. The signed MCP responses
establish that the configured policy was enforcing: denied calls retain the
managed `-32002` default-deny diagnostic, while allowed calls contain the
synthetic Lambda result. The reviewed managed-state files combine those two
observations and do not claim a separately retained AWS control-plane export.

The baseline also received two separate calls of `amount: 600`. Both were
allowed and the numeric aggregate is 1,200. This demonstrates compound reach
beyond the policy's 1,000 per-request threshold. It does not claim that the
Cedar condition promised cumulative accounting.

The first no-op attempt encoded a newline as the two characters `\n` before a
comment. Native validation rejected it before activation, so no decision from
that attempt enters the result. The accepted no-op uses a true conjunct and is
classified separately from the rejected extractor defect.

## Temporal session boundary

A separate one-tool AWS IAM deployment tested a Dogwood cumulative sum rather
than the earlier per-request Cedar condition. The active policy included the
current request in a one-hour sum and forbade the tool when the total reached
1,000. Every request supplied a caller-generated policy-session identifier.

| Sequence | First `amount: 600` | Second `amount: 600` | Observed boundary |
|---|---|---|---|
| same session alias | Allow | Deny `-32002` | cumulative sum enforced |
| two fresh session aliases | Allow | Allow | accounting reset between sessions |

The 1,200 aggregate is therefore rejected inside one technical policy session
and permitted across two fresh sessions. This is not a policy-engine defect:
the managed sum behaves correctly at its declared boundary. It shows that the
application-selected policy-session boundary is a load-bearing part of the
effective mandate. A reviewed task or run limit is not established merely by
deploying an equal numeric per-session limit.

The authenticated Gateway was READY, used `AWS_IAM`, ran its engine in
`ENFORCE`, exposed one inert Lambda tool, and had a workload identity. The
experiment did not adversarially test a second principal, and it did not deploy
a Gateway-to-Runtime-to-Gateway path. Principal isolation and multi-hop WAT
continuity therefore remain documented service properties, not live results in
this fixture. The [AgentCore session documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-session-based-temporal.html)
defines both properties and explicitly states that a fresh caller-supplied ID
creates a new evaluation boundary.

Native `FAIL_ON_ANY_FINDINGS` authoring rejected the standalone permit as
overly permissive and the temporal forbid as overly restrictive. The active
recapture used `IGNORE_ALL_FINDINGS`, which still performs schema validation,
and preserves those failed findings in `temporal-authoring-refusal.json`. It
does not claim successful semantic validation.

`temporal-index.json`, SHA-256
`7828b5f55cfcd24f54bcf73b436e2fa756d117e2b2b08aa088b067a5af34a6d0`,
pins the transformation script, reviewed policy and state, tool inventory, four
requests and responses, and the conformance result. Session UUIDs, signed
headers, live identifiers, ARNs, URLs, and service timestamps remained in
temporary files and were deleted after projection.

`controls-index.json`, SHA-256
`1a0c8838a6920c24b260fd3bfc225c3fb5ae2440ffef68c4b804fe5976392585`,
pins the transformation script, three managed oracles, policies, reviewed
state, requests, responses, control results, and sequence. Live identifiers
remained in temporary deployment and status outputs only. Tests regenerate the
reviewed fixture from equivalent raw shapes, re-run both comparisons, verify
every nested digest, and require the two allowed sequence calls.

## Provenance and integrity

[`capture-index.json`](capture-index.json) records the AgentCore CLI version,
npm package integrity, protocol, region, source roles, and digest of every
committed artifact. `capture-index.json`, SHA-256
`e14512037348e0ffc3a6611dc623848cb16ba6e6b03ea11dde78fa64d71917a3`.
Tests recompute all nested digests and require exact set equality across the
deployed schema, `tools/list`, mapping, and manifest.

`analysis-measurement.json`, SHA-256
`dcfef77f517bd782b8c598bb92f1c4f43d329b8e679076192477e60a5226250e`,
records 100 warm-ups and 1,000 measured comparisons on CPython 3.12.3. Input
loading happens before timing. The reported 9.474077 ms is the median
in-process `compare_managed_cedar` wall-clock time on the recorded WSL2 host.
The counterexample length is one because one canonical `amount: 2000` request
is sufficient to witness the managed Deny-to-Allow change. The timing is an
observed host result, not a deterministic build output.

`managed-oracle-v1.json` is the canonical private migration record for gate
5b. It preserves the managed/local-oracle distinction: fields such as
`schema_checked` and `determining_policies` are not part of its closed shape
and are rejected as unknown rather than defaulted.

`candidate-managed-oracle-v1.json` is the independently digest-pinned second
observation. Both request keys equal the baseline keys. Its policy inventory
and policy digest differ, while provider, authorizer, protocol, mapping, tool
inventory, reviewed resource binding, and sanitization semantics remain fixed.

The managed-state snapshot records an IAM authorizer, READY MCP Gateway,
ACTIVE policy engine, `ENFORCE` attachment, exactly one ACTIVE policy, and the
requested `FAIL_ON_ANY_FINDINGS` validation mode. Service responses do not
return a successful validation diagnostic, so ACTIVE status is recorded
separately from the requested validation mode.

AWS documentation defines the request mapping and managed-policy workflow in
the [Policy getting-started guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html),
the [Gateway-policy guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/use-gateway-with-policy.html),
and [policy concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html).

## Trust boundary and corrections

- **Source ambiguity:** the first protocol version was unsupported. The
  advertised version, rejection, and successful version are all preserved.
- **Model/trust gap:** an initial `NONE`-authorizer deployment could exercise
  policy but could not justify the principal mapping. It was discarded and the
  evidence was recaptured with `AWS_IAM` and signed requests.
- **Extractor/process defect:** an earlier run briefly held two policies and
  lacked a final inventory capture. It was discarded. This fixture comes from
  a clean redeployment whose final policy inventory contained exactly one
  policy.
- **Deployment policy:** the observed requests prove two concrete values only.
  `request_domain.completeness` remains `representative`; the `< 1000` domain
  is not promoted to complete authority by inspecting policy text.
- **Extractor/model defect:** the first private comparator included evidence
  filenames in its enforcement-boundary identity. The second capture
  necessarily used distinct managed-state and response locators. Comparison
  now verifies each locator and digest independently but compares the reviewed
  state, inventory, and sanitization facts rather than repository filenames.
- **Deployment identity:** cleanup and redeployment produced a different live
  Gateway identifier. Each capture independently proved the same one-tool IAM
  configuration and was reviewed into the same logical resource binding. The
  comparison claims binding continuity, not equality of omitted AWS IDs.

The sanitized managed snapshot omits account identifiers, ARNs, generated
resource IDs, URLs, service timestamps, credentials, and trace IDs. That makes
it safe to review but not a byte-exact export of AWS control-plane objects. Raw
managed metadata was not retained after verification.

## Side effects, cost, and cleanup

The baseline capture created two short-lived deployments while correcting the
authorizer and inventory boundaries. Gate 5d created one further clean
deployment for the candidate revision. The control study created one more
task-scoped deployment and applied three successful policy revisions; one
invalid no-op update failed before activation. The temporal study created one
more task-scoped deployment with a stateless permit and a Dogwood sum policy.
Each task used an AgentCore
Gateway and policy engine, a Lambda function, a CloudWatch log group, and a
task-specific IAM role. The official [`agentcore remove all`](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html)
workflow and explicit AWS checks confirmed zero task Gateways, policy engines,
Lambda functions, roles, and log groups afterward. The standard regional
`CDKToolkit` bootstrap stack remains for future deployments.

AgentCore pricing is usage-based; the captured request count implies a
negligible charge under the published
[Gateway and Policy rates](https://aws.amazon.com/bedrock/agentcore/pricing/),
plus ordinary Lambda, logging, and bootstrap-storage charges.

## Gate consequence

This fixture satisfies the Cedar contract's operational-mapping evidence gate:
the finite one-tool inventory, IAM principal type, exact action, reviewed
resource binding, managed mode, policy count, and opposite decisions are all
captured. Its private transport profile registers provenance-bearing
`maps_to_tool`, `enforces_for`, and `decides_request` edges but remains rejected
by manifest analysis. It does **not** constrain `reach`, infer all requests
under the policy condition, or prove that a real refund backend enforces
anything. The private gate-5c consumer now verifies the mapping fail-closed and
reports the captured Allow as aligned and the exact default-Deny request as
enforcement narrowing while leaving manifest authority unchanged. The second
managed oracle now clears gate 5d: the same canonical `amount: 2000` request,
mapping, tool inventory, and enforcement class change from Deny to Allow, while
the `amount: 500` control remains Allow. The versioned public result and
adversarial [gate 5e review](../../cedar-effective-diff-gate-5-review.md) now
reproduce that widening without turning the representative request pair into a
complete domain claim.
