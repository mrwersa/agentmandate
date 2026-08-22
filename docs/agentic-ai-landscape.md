# Agentic AI tooling, security, and governance landscape

Research cutoff: **23 August 2026**. This is a category map, not a directory of
every vendor. Product claims come from first-party documentation unless marked
as analysis. `GA`, `preview`, and `draft` describe the cited capability at the
cutoff, not the vendor as a whole.

## Executive view

The market is converging on a layered architecture:

```text
governance and evidence
        ↓
inventory → design-time analysis → policy distribution → enforcement point
                                                    ↓
identity and delegation → agent / MCP / A2A → tools and resources
                                                    ↓
                                  decisions, traces, incidents, evaluations
```

No one layer answers every security question. Framework guardrails influence or
block a call inside one runtime. IAM and policy decision points decide one
request. Gateways observe or enforce traffic. Scanners inspect code, packages,
and tool descriptions. Evaluation systems measure what an agent *does* under
selected tests. Governance frameworks organize accountability and evidence.

AgentMandate's defensible question sits between these layers: **what outcomes
can a sequence of individually permitted actions reach, and did that effective
authority widen?** Mature authorization engines do not answer it because their
unit is one decision. Runtime security products may detect action chains, but
their public material does not establish a portable, review-time authority diff
with short constructive counterexamples.

The strategic opportunity is therefore not another proxy. It is an open
authority intermediate representation (IR) that can ingest agents and policy,
analyze compound reachability before deployment, export constraints to existing
enforcement systems, and reconcile their decision evidence afterward.

## Standards and policy baseline

### Risk and governance

- [NIST AI RMF 1.0 and its Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)
  organize voluntary work around govern, map, measure, and manage. NIST's May
  2026 agent-security RFI analysis reports broad agreement that established
  cybersecurity practices remain relevant but need adaptation for agents
  ([NIST AI 800-5](https://www.nist.gov/publications/summary-analysis-responses-request-information-regarding-security-considerations-ai)).
- NIST launched an [AI Agent Standards Initiative](https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure)
  and a separate [agent identity and authorization project concept](https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd).
  These are direction-setting initiatives, not finished technical profiles.
- [OWASP's Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
  and Agentic Top 10 supply a developer-facing threat vocabulary. [MITRE
  ATLAS](https://atlas.mitre.org/) now distinguishes an Agentic AI platform and
  includes tool invocation, tool poisoning, context poisoning, configuration
  modification, credential harvesting, and tool-mediated exfiltration or
  destruction.
- Singapore's [Model AI Governance Framework for Agentic AI](https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai)
  is deployment-specific guidance: bound autonomy and tool/data access, define
  human checkpoints, test throughout the lifecycle, and preserve human
  accountability. [ISO/IEC 42001](https://www.iso.org/standard/42001) remains
  the broader AI management-system standard rather than an agent authorization
  specification.
- The EU AI Act is horizontal, risk-based regulation rather than an agent
  policy language. Its governance and general-purpose-model obligations are in
  force, while the official timeline for high-risk systems has changed
  ([European Commission](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)).

**Analysis:** control mappings can make evidence reusable, but claiming that a
manifest or a clean reachability result is itself "AI Act compliant" would be
misleading. Regulations govern organizations and use cases; AgentMandate can
produce evidence for selected technical controls.

### Interoperability and telemetry

- MCP standardizes host-to-tool discovery and invocation. Its current
  authorization model is OAuth-based, requires resource-bound tokens, and
  forbids token passthrough
  ([MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)).
  The 28 July 2026 release further hardened issuer validation and client
  registration ([release notes](https://blog.modelcontextprotocol.io/posts/2026-07-28/)).
- MCP tool annotations such as read-only, destructive, and idempotent are
  useful hints, not trustworthy policy. The protocol's own security guidance
  keeps consent and enforcement with implementations. The [official MCP
  Registry](https://github.com/modelcontextprotocol/registry) standardizes
  discovery and namespace ownership, creating a practical upstream for private
  registries and inventory enrichment; it is not a security certification.
- A2A standardizes agent cards, skills, tasks, and agent-to-agent messaging.
  Authentication requirements are advertised in the card and enforced using
  standard web mechanisms; identity is outside A2A semantics
  ([A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)).
  This makes agent cards a useful inventory source but not proof of effective
  delegated authority.
- MCP's [August 2026 roadmap](https://blog.modelcontextprotocol.io/posts/mcp-roadmap/)
  prioritizes workload identity, DPoP, ID-JAG, token exchange, and delegation.
  Its stable [Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization)
  extension centralizes enterprise MCP access through an identity provider.
  IETF work on identity assertion and agent delegation remains draft work
  ([ID-JAG draft](https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-assertion-authz-grant/03/)).
- OpenTelemetry is the strongest neutral telemetry substrate. Its [agent and
  framework span conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
  cover agent invocation, workflows, planning, and tool execution, but remain
  under development.

**Likely convergence:** MCP for tools, A2A for remote-agent collaboration,
OAuth/OIDC plus workload identity for principals and delegation, and OTel for
evidence. Their objects should be imported with source and version provenance,
not collapsed into an AgentMandate-only discovery protocol.

## Tooling map

### Agent frameworks and managed runtimes

OpenAI Agents SDK, LangGraph, Google ADK, Microsoft agent stacks, CrewAI, and
similar frameworks define agents, tools, handoffs, state, and execution. They
are authoritative inventory sources when statically readable. For example,
OpenAI's SDK provides tool approvals, tool guardrails, multi-agent handoffs,
and detailed tracing ([tools](https://openai.github.io/openai-agents-python/tools/),
[guardrails](https://openai.github.io/openai-agents-python/guardrails/),
[tracing](https://openai.github.io/openai-agents-python/tracing/)). Those are
runtime-local controls and observations, not a cross-framework authority model.

Cloud platforms increasingly bundle identity, gateways, policy, secrets,
runtime, and observability. Amazon Bedrock AgentCore Policy evaluates Cedar at
the gateway with default-deny and forbid-wins semantics and can detect
always-allow or always-deny policies
([core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html)).
Google's agent platform exposes centralized identity, agent gateways, and MCP
egress governance
([Google Cloud governance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern)).
These platforms are enforcement and deployment partners, not formats
AgentMandate should attempt to replace.

### Authorization and enforcement

- [OPA](https://www.openpolicyagent.org/docs) is a general-purpose policy
  decision point using Rego. It separates decisions from enforcement, supports
  bundles and APIs, and emits auditable
  [decision logs](https://www.openpolicyagent.org/docs/management-decision-logs).
- [Cedar](https://docs.cedarpolicy.com/) models principal, action, resource,
  and context with permit/forbid policies. It has schema validation and a
  formally developed specification
  ([validation](https://docs.cedarpolicy.com/policies/validation.html)).
- [OpenFGA](https://openfga.dev/) is strongest for relationship-based
  authorization: users or agents related to resources through typed tuples.
  Its own documentation frames agent delegation as a graph-shaped ReBAC use
  case ([ReBAC](https://openfga.dev/docs/learn/rebac)).
- Microsoft's MIT-licensed [Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit)
  is a public-preview runtime governance layer with policy enforcement,
  framework/MCP adapters, scanning, budgets, and developer tooling
  ([Microsoft introduction](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit-open-source-runtime-security-for-ai-agents/)).
- [AgentWard](https://github.com/agentward-ai/agentward),
  [AgentGuard](https://github.com/WhitzardAgent/AgentGuard), Prompt Security,
  and similar products intercept tool calls and apply
  allow/block/approval or data rules. They compete directly if AgentMandate
  becomes a proxy, and complement it if they consume compiled policy and return
  decisions.

Per-decision engines answer "may P perform A on R in context C now?" They do
not inherently answer whether several allowed decisions create a new scope,
accumulate an effect, transfer data, or delegate authority into a later breach.
That difference—not a new policy syntax—is the technical wedge.

### Scanning, supply chain, and posture

This is a crowded category. [Snyk Agent Scan](https://github.com/snyk/agent-scan)
discovers agent components and scans MCP servers and skills for prompt
injection, tool poisoning, toxic flows, malware, and secrets. [AgentShield
(aiconnai)](https://github.com/aiconnai/agentshield)
performs offline SAST across several agent frameworks and produces SARIF.
[MCTS](https://github.com/MCP-Audit/MCTS) combines static and live MCP analysis.
Enterprise suites including [Cisco AI Defense](https://www.cisco.com/c/en/us/products/collateral/security/ai-defense/ai-defense-ds.html)
and [Palo Alto Prisma AIRS](https://www.paloaltonetworks.com/ai-security/agent-security)
combine discovery, posture, supply-chain scanning, red teaming, and runtime
protection. [Prompt Security](https://prompt.security/solutions/agentic-ai-security-and-governance)
positions an MCP/AI gateway between applications and servers.

AgentMandate should ingest their inventories or findings where formats are
available. Rebuilding malware detection, CVE intelligence, prompt-injection
classification, or a proprietary asset-discovery network would enter mature,
data-intensive markets without strengthening compound analysis.

### Observability, evaluation, and evidence

Observability products capture trajectories; evaluation products score them.
[LangSmith](https://docs.langchain.com/langsmith/evaluation) supports offline
datasets, online evaluators, human/code/model judges, and production traces.
OpenAI Agents SDK traces model calls, tools, handoffs, and guardrails. Cloud
runtimes and OPA also emit OTel-correlated telemetry. AgentMandate already
replays OTel and neutral call records; the opportunity is to correlate policy
decision IDs, delegated principals, and manifest versions without retaining
sensitive payloads.

Behavioral security evaluation is adjacent, not equivalent. [AgentDojo](https://arxiv.org/abs/2406.13352)
tests utility and prompt-injection resistance in stateful tool environments.
Red-team systems ask whether a model can be induced to take an unsafe path.
AgentMandate asks whether the path is permitted at all. The clean integration
is to export counterexamples as evaluation scenarios and import observed
failures as evidence—not to bundle a model judge.

## Representative capability matrix

`Yes` means the cited product explicitly supplies the capability. `Partial`
means narrower or deployment-specific coverage. `—` means no supported claim
was found; it does not prove absence.

| System/category | Stage | Deploys as | Policy model | Agent/delegated identity | Multi-step authority | Data flow | Enforces | Evidence/audit | Open |
|---|---|---|---|---|---|---|---|---|---|
| AgentMandate today | Design, CI, replay | Local CLI/action | Authority manifest | Caller/service; no delegation | **Yes** | No | No | JSON, SARIF, graphs, trace replay | Apache-2.0 |
| OPA/Rego | Runtime, CI | PDP/sidecar/library | General rules over JSON | Input-defined | No native sequence model | Input-defined | Via PEP | Decision logs, OTel | Yes |
| Cedar/Verified Permissions | Runtime, design | Library/service | PARC ABAC/RBAC | Principal/context | No native sequence model | No | Via PEP | Diagnostics/service logs | Language/spec yes |
| OpenFGA | Runtime, design | ReBAC service | Typed relationship graph | Strong relationship model | Authorization graph, not action history | No | Via PEP | Checks/logs | Yes |
| AWS AgentCore Policy | Runtime | Managed gateway/PDP | Cedar over MCP tools | IAM or OAuth user | Per-call analysis | Tool inputs only | Yes | CloudWatch decisions | Cedar yes; service no |
| Microsoft AGT (preview) | Build, runtime | Library/sidecar/adapters | Agent control policy | Identity components | Budgets/chaining controls | Inspection/sanitization | Yes | Events/audit | MIT |
| AgentWard | Build, runtime | Proxy/CLI | Tool/argument/data rules | Partial | Chaining rules/probes | Runtime inspection | Yes | Audit/SIEM | Source-available |
| AgentShield (aiconnai) / Snyk Agent Scan / MCTS | Build, CI | Local scanner/action | Detectors/risk rules | Partial inventory | Toxic-flow variants | Static heuristics | No | SARIF/JSON/reports | Yes |
| LangSmith / agent observability | Test, runtime | SDK/SaaS/self-hosted tiers | Evaluators | Trace metadata | Trajectory evaluation | Payload observation | No | Traces/datasets/scores | Mixed |
| OpenAI Agents SDK | Build, runtime | Framework/library | Guardrail callbacks/approvals | Handoffs/context | Executes trajectories | Guardrail-specific | In-process | Rich traces | Yes |
| Cisco AI Defense / Prisma AIRS | Lifecycle | Enterprise platform/gateway | Vendor policy/guardrails | Yes, product-specific | Vendor claims action-chain/runtime analysis | Yes | Yes | Central inventory/audit | No |
| NIST/OWASP/MITRE/IMDA/ISO | Governance | Guidance/taxonomy | Risks and controls | Requirements-level | Threat/control framing | Requirements-level | No | Evidence expectations | Public; ISO text paid |

## Gaps that remain valuable

1. **Policy composition across time.** Mature PDPs evaluate requests; few tools
   construct the shortest sequence of allowed requests that violates a
   cumulative, relational, delegation, or data boundary.
2. **Portable effective-authority diff.** Policy text diff is vendor-specific.
   Teams need to know whether changing tools, policy, identity, or delegation
   widened reachable outcomes even when each file looks harmless.
3. **Declared-to-enforced correspondence.** Inventory, policy, gateway
   configuration, and agent bindings drift independently. A clean analysis
   needs provenance for every edge and evidence that the intended PEP was
   actually on the path.
4. **Delegation attenuation.** MCP, A2A, and IETF work are standardizing how
   identities and tokens move. They do not prove that a delegation chain only
   narrows effective authority when tool composition is considered.
5. **Evidence portability.** OTel spans, OPA decision logs, cloud audit events,
   and evaluation trajectories can describe the same action with incompatible
   identifiers and retention risks.
6. **Actionable least privilege.** Inventory products can label an agent
   overprivileged. A more useful result is the smallest tool, condition, budget,
   or delegation change that removes a demonstrated counterexample.

## Adoption constraints

- **Annotation cost:** tool schemas omit reversibility, business scope, and
  cumulative meaning. Conservative proposals plus explicit review must remain
  the workflow; silent model inference would turn ambiguity into false proof.
- **Dynamic systems:** tools, credentials, and remote agent cards can change at
  runtime. Snapshots need provenance, expiry, and a fail-closed completeness
  signal.
- **State explosion:** relationships, time, data labels, and multiple agents
  increase search cost. Each model extension needs a bounded abstraction and a
  reviewer-readable counterexample.
- **Enforcement gap:** exported policy is useful only if a PEP received and
  activated it. Deployment receipts and decision reconciliation are required;
  compilation alone is not control.
- **Sensitive evidence:** traces and decision inputs may contain prompts,
  identities, resource IDs, or data. Default ingestion should minimize,
  normalize, and redact rather than create another data lake.
- **Standards churn:** MCP auth, A2A, agent identity, and OTel agent conventions
  continue to move. Versioned adapters must isolate that churn from the core IR.

## Strategic choices

### Build

- The versioned authority IR, provenance model, compound search, effective
  diff, counterexample minimization, and policy/trace reconciliation.
- Importers that preserve uncertainty and exporters that emit target-specific
  validation artifacts rather than promising semantic equivalence silently.
- A local-first CLI and library so sensitive authority maps need not leave the
  repository.

### Integrate or partner

- OPA/Rego and Cedar as initial policy targets; OpenFGA when resource
  relationships enter the model.
- MCP Registry, MCP catalogues, A2A agent cards, OpenAPI, and framework source
  as inventory inputs.
- OTel, OPA decision logs, and cloud audit formats as evidence inputs.
- Existing gateways and policy enforcement points for runtime blocking.
- Evaluation systems for executing generated scenarios and replaying incidents.

### Avoid

- A mandatory MCP/A2A proxy, hosted credential broker, or general IAM service.
- Another prompt firewall, malware feed, vulnerability scanner, agent runtime,
  tracing backend, or LLM-as-judge benchmark.
- Universal compliance scores or automatic policy generation presented as
  reviewed intent.

## Product thesis

AgentMandate should become the **open analysis and translation plane for agent
authority**. It should let a platform-security team answer four connected
questions with evidence:

1. What agents, identities, tools, resources, and enforcement points exist?
2. What compound outcomes does the reviewed policy permit?
3. Did a release or delegation widen those outcomes?
4. Did deployed enforcement and observed execution remain consistent with the
   reviewed authority?

That position is broader than the current CLI but preserves its core
discipline: deterministic analysis outside the model, short counterexamples,
fail-closed uncertainty, and no claim about what a model is likely to do.
