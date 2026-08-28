# Roadmap

AgentMandate is moving from a single-repository authority analyzer toward an
open policy control plane for platform-security teams. The centre remains the
same: derive what an agent may do, find unsafe combinations of permitted
actions, and show how effective authority changes. The wider product will
connect that analysis to inventory, existing policy decision points, and
runtime evidence. It will not become the traffic proxy.

## Positioning: the authority gap

The category language for everything below is **the authority gap**: the
distance between what a review approved, what an agent can actually reach by
combining its tools, and what deployed enforcement really checks. Every
initiative in this document either widens what the tool can see across that gap
(model depth), or shortens it (inventory, policy export, reconciliation).
Scanner and gateway vendors watch behaviour at one point; the gap itself is the
unoccupied position, and vendor-neutral provenance is what lets this tool stand
across frameworks and enforcement points.

This is strategic judgment from the August 2026 landscape survey, not a
verified absence of competitors; it is revisited each time the survey updates.

The name follows the positioning, not the reverse. "AgentMandate" stays until
company formation or adoption scale makes a rename worth its release cost;
product surfaces should lead with the gap framing (what approval cannot see)
rather than the artifact name.

This is an 18–24 month direction, not a release promise. Research supporting
the choices is in [the agentic AI landscape](docs/agentic-ai-landscape.md).

## Outcomes and boundaries

The target workflow is:

```text
agents + tools + identities + policy
                  ↓
       versioned authority IR
                  ↓
   reachability + effective diff
          ↙                 ↘
policy exports          test obligations
          ↓                   ↓
 existing enforcement → decisions and traces
                  ↓
        drift and reconciliation
```

The open-source core will include the authority format, analysis engine, CLI,
validation, import/export adapters, and local evidence reconciliation. A future
commercial layer may add hosted fleet views, enterprise RBAC, managed
connectors, retention, and support. The public format must remain usable
without that layer.

Three boundaries remain firm:

- no general LLM firewall or prompt-injection classifier
- no bundled behavioral judge, scenario runner, or benchmark
- no mandatory MCP/A2A proxy, credential broker, or runtime enforcement point

Exporting policy is not enforcing it. AgentMandate must report the target,
version, unsupported semantics, and later evidence of activation; it must never
turn a successful compilation into a claim that a deployment is protected.

## How work earns a place

Every model feature needs two things before it becomes a default: a committed
real graph that the current model distorts, and a counterexample a reviewer can
understand. Every integration needs a versioned fixture, an explicit
completeness boundary, and a maintainer. High-confidence work has evidence in
the repository; medium-confidence work has a verified ecosystem need but not
yet a model fixture; low-confidence work is a hypothesis and stays behind an
experiment or design note.

## 0–3 months: authority foundation

Goal: make the current analysis a stable hub for evidence from more than one
manifest shape.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Two additional real graphs** ([delivered under the reassessed evidence gate](docs/evidence-metric-review.md); high confidence) | Coinbase AgentKit and GitHub MCP are too small a basis for a general IR. Add one data system and one SaaS/operations agent, preserving raw inventory, review corrections, and unrepresentable concepts. | Published, versioned sources and a reproducible extraction; choose graphs that are not primarily monetary. | Four independent graphs with explicit boundaries, preserved raw evidence, classified reviewer corrections, and linked model or product outcomes. Scanner precision is tracked separately and is not declared solved. Not a synthetic benchmark corpus. |
| **Canonical authority IR with provenance** (delivered; high) | Today the manifest mixes reviewed intent and extracted facts. Represent every agent, tool, scope, principal, constraint, and source observation with origin, version, confidence, and review state. | Compatibility design for existing manifests and JSON; migration fixtures for every schema version. | Existing manifests round-trip without semantic change; every derived edge names its source. Not a universal agent execution format. |
| **Dynamic inventory declarations** ([delivered](docs/dynamic-inventory-gate-4-review.md); high) | Static scan cannot enumerate provider-built tool lists and must fail closed. Add reviewed inventory boundaries for factories, providers, registries, and deployment configuration. | The [versioned contract](docs/dynamic-inventory.md), reader, inventory IR profile, drift reconciliation, and reviewed CLI preserve complete AgentKit and partial Sentry evidence. | Public drift proves the AgentKit boundary complete and names the evaluation date; every ineligible variant remains a finding. Sentry's JavaScript binding remains an explicit collector limitation, not a fabricated clean result. Never import or execute application code. |
| **Import experiments: MCP, A2A, OpenAPI, Cedar, Rego** (medium) | Tool and policy facts live in incompatible formats. Prototype read-only import into the IR while preserving unknowns and unsupported semantics. | Version-pinned fixtures and a mapping note for each format. | At least MCP/A2A/OpenAPI inventory and one policy language produce useful, reviewable IR. Not automatic trusted annotation or production policy compilation. |

Dependencies: the IR design follows the new graph evidence, not the reverse.
Policy experiments may remain disposable until the provenance representation is
accepted.

Evidence progress: the four-graph diversity gate is delivered. The
[metric review](docs/evidence-metric-review.md) retires “one clean result” as a
misleading proxy, without reclassifying any extraction as clean: every current
graph required material correction, and scanner precision remains separately
open. The data-system graph is captured in
[`docs/evidence/aws-postgres-mcp`](docs/evidence/aws-postgres-mcp/README.md).
It exposes the need to model conditional SQL effects, intersecting AWS/database
principals, multi-output tools, and deployment-bound resource relationships. The
independent SaaS/operations graph in
[`docs/evidence/sentry-mcp`](docs/evidence/sentry-mcp/README.md) exposes a
skill-filtered authority catalogue hidden behind a destructive meta-tool, fixed
user-token delegation, tenant constraints, and unlabelled operational data.
The later [Initiative MCP capture](docs/evidence/initiative-mcp/README.md) adds
a fifth real graph and falsifies a proposed relationship counterexample rather
than weakening the relationship gate to fit it.

IR design progress: the proposed compatibility and provenance contract is in
[`docs/authority-ir.md`](docs/authority-ir.md). Private records and the
manifest round-trip gate now cover every example, all five evidence graphs, all
v1 shorthand/default paths, and a canonical migration fixture. Private
IR-backed reachability now preserves the existing authority result while
emitting validated, provenance-bearing reachability, effect, transition, and
breach edges. A private, closed manifest-v1 profile now separates structurally
valid archival records from records eligible for analysis: only supported
adapters, complete typed predicates, verified semantic digests, and exact,
accepted evidence can reach the search kernel. All four delivery gates now
pass; artifact evolution follows the explicit version rules in `STABILITY.md`.

Gate 4 review is recorded in
[`docs/authority-ir-gate-4-review.md`](docs/authority-ir-gate-4-review.md). It
held public exposure until all three explicit gates passed. The trust-aware
analyzable profile and versioned result envelope now sit behind the reviewed
`ir export`, `ir validate`, and `reach --ir` CLI contract. Structural IR
validity alone is not treated as authority approval, and a canonical checksum
is not treated as a signature. The Python records remain deliberately private.

## 3–6 months: model real authority

Goal: represent the smallest set of relationships, conditions, delegation, and
data movement needed by the evidence without turning the manifest into an
application specification.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Conditional authority** ([delivered](docs/conditional-authority-gate-4-review.md); medium) | Approval, status, time, and request context can change whether an action is permitted. Add a closed, typed predicate vocabulary with explicit unknown handling. The path now projects and conservatively consumes statement classification and dispatch targets, then reconciles them against the selected live inventory; approval/status/time predicates follow once their operand sources exist. | The contract, profiles, and trust-failure matrix must survive the AWS PostgreSQL and Sentry conditional fixtures before a schema change is proposed. The complete SELECT-only fixture is synthetic and cannot substitute for deployment evidence. | A reviewer can see which condition narrowed a path and every absent, representative, mixed, expired, unverifiable, or source-mismatched value retains the strongest effect. Not arbitrary code or a second general policy language. |
| **Delegation chains and attenuation** ([delivered](docs/delegation-gate-4-review.md); high direction, medium shape) | Caller/service is insufficient when agents act for users or delegate to agents. Track actor, subject, delegator, audience, expiry, and the authority passed at each hop. | The Authorizer capture proves four actor-bearing OAuth hops and fail-closed attenuation. The CLI reuses the private analyzer to re-verify closed IR profiles, preserve ordered actors, apply half-open timestamp windows, and check hop-to-hop plus tool-to-hop attenuation. A real scope-to-tool/effect mapping is still required for the first non-synthetic widening counterexample. Align terminology with stable standards while isolating drafts. | Detect a delegation that widens rather than narrows authority and produce the shortest chain. Not an identity provider, token issuer, or cryptographic verifier. |
| **Resource relationships and provenance** ([evidence audit: gate not met](docs/resource-relationship-audit.md); [Initiative capture: candidate falsified](docs/evidence/initiative-mcp/README.md); medium) | Scope counts forget ownership, containment, and whether two bindings denote the same resource. Add a small typed relation vocabulary and preserve binding lineage. | One real false positive or missed path; validate mapping potential against OpenFGA concepts. Initiative enforces project/status containment, but its generic tools retain a valid existential assignment, so the graph does not change a reproduced authority result. A [fixed-binding operational graph](https://github.com/mrwersa/agentmandate/issues/106) is still required. | The motivating graph becomes more precise without material search regression. Not a complete ReBAC service or arbitrary first-order logic. |
| **Bounded producers and quantities** (medium-low) | `unbounded` versus one binding overstates finite collections and cannot express value relationships such as collateral or 1:1 conversion. Separate cardinality bounds from reviewed quantity relations. | One genuine cardinality distortion and one quantity distortion; AgentKit alone does not satisfy both. | Each feature removes a demonstrated false path while preserving existing breach detection. Not a generic optimization or accounting language. |
| **Reviewed data-flow labels** (medium) | Current analysis cannot connect sensitive reads to external sinks. Add explicit source, transform, classification, trust-zone, and sink labels with conservative propagation. | A real, non-synthetic exfiltration path and an annotation study showing reviewers can supply the labels. | Find the path with a short explanation and no inferred sensitivity presented as fact. Not DLP, content inspection, or prompt-injection detection. |

Dependencies: delegation and relationships build on the provenance-aware IR.
Data flow stays experimental until annotation burden and false-positive rates
are measured. Search limits, canonicalization, and truncation reporting are
part of each feature, not later performance work.

## 6–12 months: policy control-plane preview

Goal: turn reviewed compound analysis into portable enforcement inputs while
making semantic loss visible.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Policy validation and effective diff** (high) | Syntax-valid per-call policy may still permit an unsafe sequence. Analyze imported policy with tool inventory and compare reachable outcomes across revisions. | Stable IR mappings and executable Cedar/Rego fixtures with known decisions. | Equivalent policies produce the same authority summary; a widening policy change yields a counterexample. Not a replacement for native validators. |
| **Cedar and Rego exporters** (medium) | Reviewed constraints otherwise need manual re-entry at each PDP. Compile the enforceable subset, emit tests and a machine-readable loss report, and refuse unsafe approximation by default. | Round-trip semantics suite for the supported subset; target versions pinned. | Generated policies pass native validation and decision fixtures; every unsupported compound invariant is explicit. Not a new runtime PDP or silent best-effort translation. |
| **Policy-versus-agent drift** (high) | Agent bindings, imported policy, gateway exposure, and exported policy can diverge independently. Compare all four and distinguish missing control, stale inventory, and unreachable declaration. | Provenance IR plus at least one gateway configuration fixture. | CI identifies the exact edge and source that drifted without claiming absence from incomplete inventory. Not live asset discovery. |
| **Explainable counterfactual remediation** (medium) | A breach path says what is wrong but not the smallest safe change. Compute candidate removals or tighter approvals, conditions, budgets, and delegation bounds, ranked by authority impact. | Stable compound models and equivalence tests. | Every suggestion is mechanically rechecked to remove the path and labeled as candidate, not intent. Not autonomous policy authoring or auto-application. |
| **Named-review CI workflow** (high) | Authority widening needs accountable acceptance rather than a generic green check. Extend change records with owner, reason, expiry, evidence, and target-policy status. | Stable additive JSON contract and threat review of records. | Widening cannot be marked reviewed without named evidence; expired exceptions fail closed. Not a general ticketing or GRC system. |

Dependencies: validation ships before export; export stays preview until native
target tests and loss reporting are trustworthy. Cedar is first because the
project already has AgentCore evidence and Cedar is analyzable. Rego follows as
the portable general-purpose target. OpenFGA export waits for the relationship
model rather than being forced into this phase by brand coverage.

## 12–18 months: fleet governance

Goal: connect repository decisions to deployed policy and execution evidence
without building an observability backend.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Federated agent and tool inventory** (medium) | Platform teams cannot govern repositories one at a time. Define an open inventory index over signed IR snapshots, owners, environments, and expiry. | Stable IR identities; prototypes against MCP Registry/subregistry and A2A cards. | Local aggregation answers ownership, exposure, and stale-review queries across repositories. Not network discovery or a proprietary CMDB. |
| **Decision and OTel reconciliation** (high) | A policy file does not prove that a PEP evaluated a call. Correlate manifest version, export receipt, principal/delegation, decision ID, tool span, and observed effect. | OTel convention adapter plus OPA and one cloud decision-log fixture. | Detect missing, bypassed, stale, or contradictory enforcement with payload capture disabled by default. Not full trace storage, APM, or SIEM. |
| **Signed evidence bundles** (medium) | Audit evidence loses integrity and context when copied among CI, PDPs, and review systems. Package hashes, provenance, decisions, exceptions, and analysis results with a verifiable manifest. | Threat model, key-rotation design, and one external consumer. | Offline verification detects tampering and missing components. Not a PKI, identity attestation service, or immutable ledger. |
| **Ownership and time-bounded exceptions** (medium) | Fleet findings need accountable routing and temporary risk acceptance. Keep ownership and exception objects portable in the open format. | Named-review workflow and privacy review. | Every exception has scope, owner, reason, evidence, and expiry; local CLI can enforce it. Not a full enterprise RBAC or workflow UI in core. |
| **Control evidence mappings** (medium-low) | Security teams repeatedly translate the same technical evidence into governance language. Map artifacts—not verdicts—to selected OWASP, NIST, MITRE, IMDA, and ISO control concepts. | Review by domain experts and public mapping methodology. | Each mapping states what the artifact establishes and what remains organizational. Never issue compliance scores or certification claims. |

Dependencies: fleet inventory can remain file- and API-based. A hosted control
plane is optional and must consume exactly the same open snapshots and evidence
bundles. Reconciliation precedes dashboards: collecting more data before the
identity joins are reliable would create expensive ambiguity.

## 18–24 months: advanced authority

Goal: reason about authority that crosses agents, sessions, and time, then help
teams reduce it without hiding uncertainty.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Cross-agent and cross-session reachability** (medium-low) | Delegated agents, durable grants, memory, and asynchronous tasks can complete a path no single run contains. Extend state with explicit lifetime and trust boundaries. | Real incident or graph with durable authority plus measured state-space bounds. | Produce a finite, replayable counterexample across named agents/sessions and state the completeness limit. Not simulation of arbitrary model behavior. |
| **Temporal and revocable capabilities** (medium-low) | Expiry, activation, revocation, and approval windows affect whether a path is reachable. Model a small event vocabulary and verify attenuation over time. | Stable delegation standards and decision evidence containing relevant timestamps/status. | Detect use outside a window or after revocation in fixtures without wall-clock nondeterminism. Not a token service or distributed clock protocol. |
| **Least-authority synthesis** (low) | Teams need a practical route from a finding to a smaller safe capability set. Find minimal candidate policy changes that preserve declared required scenarios while removing breaches. | Counterfactual remediation plus reviewed positive obligations and performance study. | Candidates are Pareto-ranked, mechanically checked, and require human selection. Not automatic production mutation or proof of business correctness. |
| **Extension interfaces** (medium) | One project cannot maintain every framework, PDP, and evidence adapter. Publish versioned importer, exporter, finding, and evidence conformance suites. | Three in-tree adapters of each relevant kind and a security model for plugins. | An external adapter can pass conformance without importing private internals. Not arbitrary in-process execution of untrusted plugins. |

Dependencies: these features do not block a useful 1.0. They ship only when
their counterexamples remain understandable and worst-case behavior is bounded
or reported honestly.

## Release and measurement gates

The roadmap is successful when external users can demonstrate outcomes, not
when the feature list is checked off. Track:

- independent real graphs and the modelling distortions they expose
- reviewed manifests that remain drift-clean across releases
- true widening changes caught before merge and accepted with named evidence
- importer completeness and exporter semantic-loss rates
- counterexample length, analysis time, memory use, and truncation frequency
- deployed decisions that reconcile to the reviewed manifest and policy build
- annotation/review time and findings disabled as noise
- external adapters and policy/evidence consumers

AgentMandate reaches 1.0 when the manifest, IR, CLI, and JSON contracts have a
compatibility audit; all schema versions have migration fixtures; search limits
and worst-case behavior are documented; at least four independent graphs cover
more than one framework and authority domain; and security plus trace-retention
guidance has external review. Policy export and fleet features may remain
preview after 1.0 if their contracts have not earned stability.

## Historical evidence retained

The initial adoption loop shipped before this roadmap: `scan` and source
inventory obtain a reviewed manifest; `lint` and `reach` check it; `diff`
compares effective authority; `drift` tests correspondence to source;
`obligations` and `scenarios` hand paths to external evaluation; `verify`
replays calls and OTel; SARIF, Mermaid, and the GitHub Action put findings in
review. Each command fails closed where evidence is incomplete.

Two real graphs shaped the current model:

- The Coinbase AgentKit evidence showed authority that outlives a run through
  token approval, mixed widening and narrowing across releases, dynamic tool
  inventory, and the difference between gross and net value. It also showed
  that collateral and 1:1 conversion are quantity relationships, not bounded
  scope cardinality.
- The GitHub MCP evidence removed currency from the problem. Repeating
  irreversible actions required a count, which led to the shipped
  `limits.effects` model. It also demonstrated tools that mint secret-scoped
  compute and the importance of a reviewed toolset boundary.

That evidence-first rule is not superseded by the control-plane ambition. A
market category can justify an experiment; only a real distortion and a clear
counterexample justify widening the core authority model.
