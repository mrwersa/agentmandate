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

## Provenance and integrity

[`capture-index.json`](capture-index.json) records the AgentCore CLI version,
npm package integrity, protocol, region, source roles, and digest of every
committed artifact. `capture-index.json`, SHA-256
`b942c984683e4b93327f1f80b3acfe3b8114a4ebf6c4c53f6088f482c9ba9f24`.
Tests recompute all nested digests and require exact set equality across the
deployed schema, `tools/list`, mapping, and manifest.

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
deployment for the candidate revision. Each used an AgentCore Gateway and
policy engine, a Lambda function, a CloudWatch log group, and a task-specific
IAM role. The official [`agentcore remove all`](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html)
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
the `amount: 500` control remains Allow. Public exposure remains gated on the
adversarial gate 5e review and a versioned result envelope.
