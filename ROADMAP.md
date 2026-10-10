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
combining its tools, what deployed enforcement really checks, and which reviewed
state survives a session, handoff, or policy revision. Every initiative in this
document either widens what the tool can see across that gap (model depth), or
shortens it (inventory, policy export, continuity, reconciliation).
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

## Current delivery snapshot

**Pre-1.0 scope decision — 10 October 2026:** freeze additional continuity
contracts and prioritize completion of the 1.0 gates. The delivered
experimental surfaces remain supported; corrections, review, evidence
consolidation, and explicit acceptance renewal remain in scope. A new
continuity contract needs an externally motivated counterexample and a scope
decision rather than becoming the default next implementation task. This is
a feature-scope freeze, not a claim that operational continuation is solved.

**Review checkpoint — 6 November 2026, mrwersa:** renew or let lapse the
[six accepted historical AgentCore observations](docs/continuation-evidence-acceptance.md).
Their current acceptance expires 8 November inclusive UTC and is ineligible
from 9 November. Work on mandate binding does not extend this expiry.

**Before further live capture:** the [clock audit](docs/capture-clock-audit.md)
found six negative UTC intervals in 510 inspected calls. Four retain positive
monotonic endpoint differences; older principal/retransmission records do not
retain endpoints. The next driver/sanitizer must pass the
[timing-retention gate](docs/continuity-evidence-plan.md#timing-retention-gate).
The cause of the UTC regressions remains unestablished.

The time horizons below describe dependency order and product direction. They
are not the clearest view of current delivery because several foundation and
model initiatives completed together. The present frontier is:

| State | Initiatives |
|---|---|
| **Delivered** | Real-graph evidence base, Authority IR, dynamic inventory, conditional authority, delegation analysis, the Cedar decision/alignment path, finite producer cardinality, the [authority-continuity CLI](docs/authority-continuity-gate-4-review.md), and the [reviewed pre-1.0 baseline](docs/pre-1.0-consolidation-audit.md) |
| **Active** | Authority-continuity evidence: the [principal-change control](docs/evidence/agentcore-refund-policy/README.md#principal-change-continuity-control) locates tested history at the principal×session boundary; [completed retransmission](docs/evidence/agentcore-refund-policy/README.md#completed-request-retransmission-control) executes and accumulates again despite an identical JSON-RPC ID; and the [continuation revision matrix](docs/evidence/agentcore-refund-policy/README.md#continuation-revision-matrix) shows a tightened revision restoring capacity that carried predecessor consumption would refuse |
| **Active consolidation** | [Continuity profiles and observations](docs/continuity-evidence-consolidation.md): **mrwersa** accepted the six pinned historical AgentCore observations through 2026-11-08 in a separate accepted profile. Retransmission prefixes remain unreviewed with partial-trace and clock limits explicit. Principal-change pairs also have a separate unreviewed runtime profile; the archival observation format remains rejected. The observation consumer leaves mandate continuity unresolved; optional reviewed accounting is implemented for synthetic bound trials, with historical binding still deferred. Archival records and historical migrations remain unreviewed and byte-exact |
| **Implemented extension** | [Reviewed principal accounting](docs/principal-accounting.md) for [#214](https://github.com/mrwersa/agentmandate/issues/214): independently reviewed bindings, exact manifest/profile joins, identity and execution mappings, per-trial observed budget comparisons, and failure/compatibility fixtures. The maintainer supplied an out-of-band execution review on 10 October; this is not a GitHub approval or historical binding acceptance |
| **Implemented extension** | [Scoped revision review](docs/revision-review.md), [#222](https://github.com/mrwersa/agentmandate/issues/222): exact input and policy joins, independent comparison/issuer evidence, retention-only amendments, and fixed result baselines. The maintainer supplied an out-of-band adversarial execution review on 10 October; this is not a GitHub approval or historical evidence acceptance. Global safe continuation and historical binding approval remain unresolved |
| **Implemented extension** | [Scalar handover verifier](docs/scalar-handover.md), [#224](https://github.com/mrwersa/agentmandate/issues/224): two reviewed binding joins, exact closed policy bytes, retained completed/pending state, fencing, and complete next-request integer-domain inclusion at cutover. Synthetic retained/reset/expired baselines pin the new contracts. The maintainer supplied an out-of-band adversarial execution review on 10 October; this is not a GitHub approval. Model conformance does not establish snapshot freshness, global provider continuation, or historical acceptance |
| **Reviewed; search gate complete** | [Search bounds and performance](docs/search-performance.md), [#226](https://github.com/mrwersa/agentmandate/issues/226): conservative state/time/storage bounds, lower-allocation private search storage, 30 pinned pre-change Authority/provenance cases, and a reproducible five-real-graph study. The maintainer supplied an out-of-band differential execution review of #227 on 10 October: 48 baseline/candidate runs had identical JSON and exit codes. This closes the documented-search criterion; it is not a GitHub approval or external security review |
| **Reviewed implementation** | [MCP/A2A/OpenAPI catalogue imports](docs/catalogue-import.md), [#228](https://github.com/mrwersa/agentmandate/issues/228): local JSON readers, review-marked skeletons, unreviewed dynamic-inventory declarations and existing IR profiles, pinned synthetic baselines, and historical MCP compatibility checks. The maintainer supplied an out-of-band review and re-check of #229; the missing-producer lint rule detected over-guessed requirements in four preserved raw evidence skeletons, with unchanged findings on reviewed manifests in that comparison. Raw skeletons remain archival proposals, including expected lint errors. This is not a GitHub approval or external security review. A2A exposes one explicit application dispatch candidate, not one tool per skill; deployment completeness and policy decisions are not inferred |
| **Prepared; awaiting review** | [Current compatibility inventory](docs/current-contract-inventory.md): Python signatures, nested CLI arguments, version markers, fixture digests and twelve legacy-output runs supplement the unchanged historical 0.17.0 audit. Raw scanner proposals retain their expected lint errors. This is an author-prepared inventory with executable checks, not a reviewed 1.0 decision or external security review |
| **Ready next** | Independently review the current compatibility inventory and nominate an independent security/trace-retention reviewer using the [prepared scope](docs/external-security-review.md). Representative A2A/OpenAPI application mappings and decision evidence remain separate from synthetic importer tests; that external review gate cannot be supplied by implementation or an agent's self-review |
| **Deferred continuity extensions** | Operational policy/state/fencing evidence and a versioned settlement/retry contract are prerequisites for extending the scalar cutover model to later execution or a global continuation verdict. Historical binding approval remains deferred pending the [gap audit's evidence and owner requirements](docs/continuation-binding-gap-audit.md); locate contemporaneous mandate/principal/deployment and mediation evidence before applying accounting to those captures. No historical mandate identity, safe-continuation, or deployment approval is established |
| **Deferred adoption pilot** | Workplace integration deferred at the maintainer's request on 9 October 2026. The [pilot below](#near-term-adoption-workflow-publication-review) remains a report-only proposal and supplies no new evidence graph or cleared model gate |
| **Evidence-blocked** | The [deployment-continuity control](docs/evidence/agentcore-refund-policy/README.md#deployment-continuity-authoring-refusal) cannot hold policy and history selection fixed across Gateway identities; resource relationships still lack a fixed-binding counterexample; reviewed data flow still lacks a real exfiltration path and annotation study; quantity relations still lack a reviewed operational input domain |
| **Later** | Policy export, policy-versus-agent drift, fleet reconciliation, and advanced cross-agent or cross-session reachability |

This ordering keeps two analyses distinct. Reachability asks which legal tool-call
sequences a reviewed mandate permits. Authority continuity asks whether consumed
state remains attached to that mandate across a named lifecycle transition.
Neither result substitutes for the other.

The [principal observation consumer](docs/principal-continuity.md) preserves
principal and session relations independently and reports per-principal amounts.
The new [accounting binding](docs/principal-accounting.md) adds the bounded
shared-mandate slice of [#214](https://github.com/mrwersa/agentmandate/issues/214):
a reviewed profile/manifest join, principal mappings, shared intent, mediation,
distinct execution references, and a matching monetary limit can authorize a
shared observed total within each independent trial. It reports an observed
budget breach without claiming a state reset or safe continuation. The unbound
result remains unchanged; old single-principal bindings are not reused.

Implementation and synthetic tests do not supply accountable approval for the
historical capture. Its principal profile remains unreviewed and unbound, and
its archival record remains byte-exact. Issue #214 stays open for the remaining
historical evidence boundary. No additional initiative
is counted complete by this extension. The new
[revision review attachment](docs/revision-review.md) reports separately reviewed
comparison and issuer-treatment claims beside the unchanged continuity baseline.
Its scope stays explicit: retaining-state approval cannot waive a reset, and
finite comparison evidence does not establish global safe continuation.
The [scalar handover verifier](docs/scalar-handover.md) checks two independently
reviewed bindings and retained completed/pending state, then computes complete
next-request inclusion in a closed integer model at cutover. Its clean result
means conformance to that declared model; it does not authenticate live state
transfer, verify signatures, or resolve global provider safe continuation.
Operational policy/state/fencing evidence and later settlement/retry semantics
remain open. This extension completes no additional initiative.
The [consolidation record](docs/continuity-evidence-consolidation.md) owns the
capture-by-capture status and limitations; the [evidence plan](docs/continuity-evidence-plan.md)
owns requirements for further captures. Managed Agents continuation still lacks
a local mandate/principal binding, and deployment continuity remains blocked by
the provider's mandatory Gateway resource binding.

## Near-term adoption: workflow publication review

**Deferred — no active workplace implementation.** Originally planned on
9 October 2026, the first adoption target is one workflow with a human
approval gate and a consequential write, compared with its previous published
revision. This brings inventory reconciliation and a narrow part of
policy-versus-agent drift forward without waiting for policy export or fleet
governance. Consolidating the captured continuity controls remains the next
evidence task. No application source or new operational fixture has yet been
reviewed for this pilot.

Deferred at the maintainer's request on 9 October 2026. The plan below is retained
for a possible restart; its 23 October readiness checkpoint is inactive while
the pilot is deferred. No workplace workflow has been selected or reviewed.

### First increment and decision point

Use an application-owned adapter against a pinned library release. Keep workflow
syntax, product permissions, storage access, and deployment selectors in that
adapter. Begin with reviewed effects and approval requirements. Do not invent
monetary ceilings, effect budgets, classification labels, or residency rules.

1. Record one workflow identifier, baseline and candidate revisions, deployment
   selection, and a responsible reviewer in the private pilot record before
   implementation. No workflow has been selected yet. Open an issue before a
   large extractor, as required by `CONTRIBUTING.md`.
2. Capture the exact bound tool inventory, qualified names, alias resolution,
   and the source of approval declarations. Reuse the dynamic-inventory trust
   contract where its target and selection semantics fit. Existing source
   `--binding` support selects an agent, not a workflow execution model. A YAML
   workflow is not automatically consumable by the current Python collector or
   `drift` CLI. Report unsupported joins rather than manufacturing source code
   to make those checks pass.
3. Reconcile the reviewed manifest with that inventory in the first report,
   alongside lint and effective-authority diff. Use the existing drift consumer
   where supported and identify adapter-only reconciliation otherwise. Missing,
   partial, conflicting, or stale inventory prevents a clean overall review.
4. Exercise controlled tool addition, approval removal, authority reduction,
   unchanged semantics, and incomplete inventory. Record actionable findings,
   false positives, reviewer decisions, and annotation effort. Retain the exact
   inputs needed to reproduce each result.
5. Review pilot readiness on **23 October 2026**. If the workflow or reviewer is
   still unavailable, record the blocker and a new review date. This is a
   decision checkpoint, not an automatic deadline to make findings blocking.
   Promote only individually validated checks after the reviewer accepts their
   completeness boundary and results. Otherwise keep them advisory or stop the
   pilot with the reason recorded.

If pilot work competes with the maintainer's fixed research-submission deadline,
defer the pilot and record a new checkpoint. The pilot is not a dependency of
that submission and must not expand its evidence commitments. At the readiness
review, update the delivery snapshot with the decision and next owner/action.
Once the pilot is completed or stopped, replace this detailed plan with a short
outcome and a link to its issue or decision record, preserving the evidence and
any unresolved model gates there.

The first report covers declared authority, not successful workflow completion.
A tool-set projection loses step order, branches, approval pauses, retries,
parallelism, and compensation. Label reachability through that projection as an
over-approximation only when inventory completeness and the retained semantics
justify that claim. Unsupported steps stay visible and cannot silently disappear
behind a clean workflow verdict. A future execution-aware profile needs a
counterexample where this abstraction materially changes a result.

### Evidence priorities after the first report

**Call-bound approval comes before new entitlement predicates.** Capture which
principal approved which qualified operation, target, reviewed arguments,
validity, and operation identity. Compare that record with the call the executor
can admit. A frozen argument tuple is a candidate fixed binding for the
resource-relationship gate, not proof that the gate is cleared. An alternative
tool needs an authored same-effect relation and evidence that it actually
escapes the intended approval. Establish whether the reproduced distortion is
an approval-binding gap, a relationship gap, or both before extending the model.
The fixed-binding prerequisite in issue #106 remains open.

**Reuse conditional evidence without assuming general predicates already work.**
The current closed predicates classify statement and dispatch effects. They do
not decide arbitrary access entitlement. New operand sources must establish the
principal, resource, evaluation context, completeness, and review lifetime, as
well as the predicate's meaning. Residency checks must say whether they concern
execution, storage, or data transfer. Classification-flow claims require an
explicit data-flow model and retain the existing evidence gate. Unknown controls
retain conservative possible authority and an unresolved finding, not a pruned
path that makes the report look safer.

**Continuity requires a mandate join, not a thread convention.** A mandate may
span threads, workflow runs, and approval records, and a thread may contain more
than one mandate. A new thread does not itself authorise fresh capacity. Reuse
digest-pinned bindings and the three-valued continuity contract, while checking
whether a new provider profile or consumer is required. An open `boundary_kind`
string alone cannot make a new runtime's records analysable. Missing gates or
accounting evidence remain unresolved, never a zero balance. Define when pending
work reserves capacity and how late settlement crosses a handover. Design the
safe export boundary early, but defer runtime verification until those records
exist. Do not add database access to the library.

**Retry evidence concerns operation identity and accounting.** The completed
retransmission capture shows repeated execution and accumulation after a known
response. It does not establish ambiguous-timeout behaviour or a defect in a
different engine. Before adding retry semantics, capture the retry/redrive
boundary, operation-key scope, retention, payload binding, duplicate execution,
and settlement rules. Unknown deduplication retains possible repeated effects.
A Boolean idempotency flag cannot justify collapsing attempts into one effect.
Duplicate settlement of one operation and execution of two distinct operations
are different cases. This remains an evidence-led extension, not a new retry
transition already supported by the continuity consumer.

### Admission and upstream scope

The pilot supplies candidate evidence for workflow projection, approval binding,
conditional operands, and policy-versus-agent drift. It does not yet unblock
resource relationships, deployment continuity, quantity relations, or data flow.
An application-owned accounting boundary could test deployment continuity only
if the experiment holds policy, principal, mandate, and accounting selection
fixed while changing deployment. Another application using the same provider is
not automatically an independent enforcement implementation.

Upstream reusable contracts and releasable evidence rather than application
nouns. Employer permission and a reviewed sanitisation boundary are prerequisites
for releasing workplace material. A graph counts as real evidence only when it
meets `CONTRIBUTING.md`, including the published, version-pinned source boundary.
An unreleasable example or synthetic reproduction must keep that status. A second
independent use case can test generality, but does not replace a reproduced
distortion and explicit semantics.

This roadmap update changes no package contract and needs no release. Future
public behaviour and artifact changes follow `STABILITY.md` independently. Do
not preassign a package release or treat a new closed-vocabulary member as
automatically compatible. The pilot adds no new prerequisite for 1.0. Runtime
enforcement and the decision to publish remain with the application, which may
eventually consume validated analysis checks as part of its existing CI gate.

## Outcomes and boundaries

The target workflow is:

```text
mandates + agents + tools + identities + policy
                  ↓
       versioned authority IR
                  ↓
   reachability + effective diff
          ↙                 ↘
policy exports          test obligations
          ↓                   ↓
 existing enforcement → decisions and traces
                  ↓
 continuity, drift, and reconciliation
```

The open-source core will include the authority format, analysis engine, CLI,
validation, import/export adapters, and local evidence reconciliation. A future
commercial layer may add hosted fleet views, enterprise RBAC, managed
connectors, retention, and support. The public format must remain usable
without that layer.

Four boundaries remain firm:

- no general LLM firewall or prompt-injection classifier
- no bundled behavioral judge, scenario runner, or benchmark
- no mandatory MCP/A2A proxy, credential broker, or runtime enforcement point
- no session broker, distributed budget counter, or transactional scheduler

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
| **Evidence import and alignment: MCP, A2A, OpenAPI, Cedar, Rego** ([Cedar path delivered](docs/cedar-effective-diff-gate-5-review.md); [inventory imports reviewed and merged in #229](docs/catalogue-import.md); medium) | Tool and policy facts live in incompatible formats. Read-only MCP/A2A/OpenAPI imports now reuse inventory v1 and its IR profile while preserving unknown deployment membership and adapter semantics. This foundation layer covers source bundles, native validation, IR projection, deployment mapping, and exact decision alignment; revision comparison is the policy-control-plane consumer tracked below. | Pinned synthetic sources, skeletons, declarations, and IR baselines cover each supported format; four historical MCP payloads preserve legacy scan output. Cedar has a pinned native oracle, a live one-tool IAM AgentCore mapping, and reviewed fail-closed validation and alignment commands. Accountable A2A/OpenAPI application/deployment mappings and native decision evidence remain open; Rego is deferred. | At least MCP/A2A/OpenAPI inventory and one policy language produce useful, reviewable IR and aligned decisions. Extraction alone does not complete this measure. Not automatic trusted annotation, a Python Cedar evaluator, production policy compilation, or by itself an effective-authority diff. |

Dependencies: the IR design follows the new graph evidence, not the reverse.
Policy experiments may remain disposable until the provenance representation is
accepted.

Cedar's evidence-ingestion gates now have a contract, private strict bundle reader,
digest-pinned official allow/deny fixture, and standalone IR projection. The
projection preserves observed native decisions while explicitly marking policy
inventory incomplete; a synthetic probe covers the schema-checked path that
the official fixture cannot. A separate
[live AgentCore capture](docs/evidence/agentcore-refund-policy/README.md) proves
one IAM principal, one Gateway tool, one ACTIVE policy attached in `ENFORCE`,
an exact reviewed mapping, and opposite managed decisions. Its two request
values remain representative. The later policy-control-plane consumer uses
that alignment to report live revision widening without mutating reachability.
This completes the Cedar path across both roadmap layers, not the broader
MCP/A2A/OpenAPI/Rego initiative.

The earlier [operational mapping audit](docs/cedar-operational-mapping-audit.md)
and [source capture](docs/evidence/agentcore-fgac/README.md) remain negative
evidence: the larger sample's unfiltered exporter contains an unresolved
seventh `/health` route, so its documented six-operation policy is not a
complete mapping. Gate 4 was instead cleared by a deliberately finite live
refund-policy fixture; the failed candidate is retained rather than
reclassified.

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
| **Mandate/session alignment and authority continuity** ([delivered](docs/authority-continuity.md); [Gate 4 review](docs/authority-continuity-gate-4-review.md); high) | A provider may correctly enforce every request while a fresh session or policy revision restores capacity already consumed by one reviewed mandate. Define a versioned binding between mandate, principal, enforcement boundary, policy revision, and limits, then distinguish preserved, reset, widened, overshot, and unresolved transitions. For a reviewed comparable revision, report whether the successor can admit work that the predecessor state would refuse. | The [AgentCore fixture](docs/evidence/agentcore-refund-policy/README.md) reproduces same-session enforcement, fresh-session capacity, signed-binding continuity, and revision-triggered loss across ten trials per cell. Ten byte-identical submissions create no revision and retain refusal; ten rename-only submissions create a revision, stale the predecessor session, and let prescribed recovery restore capacity. The independent [Anthropic fixture](docs/evidence/anthropic-managed-budget/README.md) preserves one total across parent and child threads and across a live cap increase. Strict private migrations and separate closed IR profiles pin both source sets without merging their transports. Reconciliation leaves unbound cross-boundary observations unresolved rather than inventing a same-mandate join, and derives comparability, issuer-amendment state, and a three-valued safe-continuation verdict. An explicitly synthetic accepted fixture proves the clean path while both real migrations remain unreviewed. The public validate-then-consume CLI emits `agentmandate.continuity/v1`, preserves complete manifest Authority, refuses unsupported composition before I/O, and implements exit 0/1/2 without exposing Python records. | A reviewer can determine whether one mandate retained one enforcement boundary, whether consumed authority survived a transition, and whether a reviewed comparable revision satisfies safe continuation. Missing bindings, state handoffs, mediation, comparability, expiry, settlement, or issuer-amendment evidence remain unresolved. The initial profile covers evidence-backed scalar cumulative quantities only and does not decide policy equivalence. Not a proxy, session allocator, token issuer, distributed counter, general policy interpreter, or claim of atomic enforcement. This experimental profile does not block 1.0. |
| **Resource relationships and provenance** ([evidence audit: gate not met](docs/resource-relationship-audit.md); [Initiative capture: candidate falsified](docs/evidence/initiative-mcp/README.md); medium) | Scope counts forget ownership, containment, and whether two bindings denote the same resource. Add a small typed relation vocabulary and preserve binding lineage. | One real false positive or missed path; validate mapping potential against OpenFGA concepts. Initiative enforces project/status containment, but its generic tools retain a valid existential assignment, so the graph does not change a reproduced authority result. A [fixed-binding operational graph](https://github.com/mrwersa/agentmandate/issues/106) is still required. | The motivating graph becomes more precise without material search regression. Not a complete ReBAC service or arbitrary first-order logic. |
| **Bounded producers and quantities** ([finite cardinality delivered](docs/bounded-producer-gate-4-review.md); [evidence audit](docs/bounded-producer-evidence-audit.md); medium) | `unbounded` versus one binding overstates finite collections and cannot express value relationships such as collateral or 1:1 conversion. Separate cardinality bounds from reviewed quantity relations. | AgentKit supplies collateral, 1:1 conversion, and gross-versus-net quantity distortions. The [AWS IAM access-key capture](docs/evidence/aws-iam-access-keys/README.md) supplies the independent cardinality half: pinned IAM MCP 1.0.11 returns two authenticated credentials for one user and AWS rejects the modeled third binding solely on exhaustion. Current 1.0.23 redacts the secret and is outside that version-scoped claim. The public validate-then-consume path now rechecks strict boundaries, exact source bytes, explicit selections, and review dates; emits the canonical producer result; and refuses unsupported composition before output. An explicitly synthetic accepted fixture supplies the clean path while real IAM remains unresolved. | Finite cardinality removes the demonstrated false third path while preserving existing breach detection. Quantity remains evidence-blocked on a reviewed operational input domain; this is not a generic optimization or accounting language. |
| **Reviewed data-flow labels** (medium) | Current analysis cannot connect sensitive reads to external sinks. Add explicit source, transform, classification, trust-zone, and sink labels with conservative propagation. | A real, non-synthetic exfiltration path and an annotation study showing reviewers can supply the labels. | Find the path with a short explanation and no inferred sensitivity presented as fact. Not DLP, content inspection, or prompt-injection detection. |

Dependencies: delegation and relationships build on the provenance-aware IR.
Data flow stays experimental until annotation burden and false-positive rates
are measured. Search limits, canonicalization, and truncation reporting are
part of each feature, not later performance work.

Authority continuity is promoted from the former advanced-session hypothesis
because two independent provider-operated systems now expose the session
boundary and one isolates creation of a policy revision as the boundary at
which predecessor consumption stops constraining prescribed recovery. The
delivered bounded evidence and presentation contract keeps identity continuity
separate from state transfer and distinguishes preservation or conservative
translation, fencing and settlement, and an explicit issuer amendment. General
reachability across arbitrary durable agents, memories, and sessions remains
advanced work.

## 6–12 months: policy control-plane preview

Goal: turn reviewed compound analysis into portable enforcement inputs while
making semantic loss visible.

| Initiative | Problem and differentiating outcome | Prerequisite and evidence gate | Success measure and non-goal |
|---|---|---|---|
| **Policy validation and effective diff** ([Cedar decision path delivered](docs/cedar-effective-diff-gate-5-review.md); transition continuity pending; high) | Syntax-valid per-call policy may still permit an unsafe sequence, and a reviewed comparable redeployment may reset accrued state. Analyze imported policy with tool inventory, compare reachable outcomes across revisions, and keep decision change separate from state migration. | Stable IR mappings and executable Cedar/Rego fixtures with known decisions. The reviewed Cedar consumer aligns exact managed requests and reproduces a live AgentCore Deny-to-Allow revision. The continuity fixture additionally distinguishes a byte-identical deduplicated write from a rename-only revision that preserves the tested request meaning but invalidates the old session. Rego remains a separate evidence-gated extension. | Matched requests produce a replayable decision comparison, while a separately reviewed comparable transition produces a scoped safe-continuation result. A widening decision and a state-resetting transition remain distinct findings. Never infer whole-language policy equivalence, migrated state from equivalent decisions, or replace native validators. |
| **Cedar and Rego exporters** (medium) | Reviewed constraints otherwise need manual re-entry at each PDP. Compile the enforceable subset, emit tests and a machine-readable loss report, and refuse unsafe approximation by default. | Round-trip semantics suite for the supported subset; target versions pinned. | Generated policies pass native validation and decision fixtures; every unsupported compound invariant is explicit. Not a new runtime PDP or silent best-effort translation. |
| **Policy-versus-agent drift** (high) | Agent bindings, imported policy, gateway exposure, session identity, policy revision, and accrued-state handoff can diverge independently. Compare them without collapsing a correct per-request decision into proof of mandate continuity. | Provenance IR, the mandate-continuity profile, and at least one gateway configuration fixture. | CI identifies the exact edge or transition that drifted and distinguishes missing control, stale inventory, reset state, and widened policy without claiming absence from incomplete evidence. Not live asset discovery or runtime counter management. |
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
| **Decision and OTel reconciliation** (high) | A policy file does not prove that a PEP evaluated a call or retained the same reviewed boundary. Correlate mandate digest, session identity, policy revision, manifest version, export receipt, principal/delegation, decision ID, tool span, and observed effect. Where providers expose them, keep consumed, reserved, and in-flight authority distinct. | OTel convention adapter plus OPA and one cloud decision-log fixture; mandate-continuity records define the join and its trust states. | Detect missing, bypassed, stale, reset, or contradictory enforcement with payload capture disabled by default. Never infer strict cumulative enforcement from completed-event telemetry alone. Not full trace storage, APM, SIEM, or a distributed counter. |
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
| **Cross-agent and cross-session reachability** (medium-low) | Delegated agents, durable grants, memory, and asynchronous tasks can complete a path no single run contains. Extend state with explicit lifetime and trust boundaries beyond the bounded continuity checks delivered earlier. | Real incident or graph with durable authority plus measured state-space bounds. Parent/child accounting within one managed session is evidence for continuity, not proof of arbitrary cross-session reachability. | Produce a finite, replayable counterexample across named agents/sessions and state the completeness limit. Not simulation of arbitrary model behavior or reimplementation of provider scheduling. |
| **Temporal, revocable, and transferable capabilities** (medium) | Expiry, activation, revocation, approval windows, and policy revisions affect whether authority remains reachable and how already-consumed authority transfers. Model a small event vocabulary and a verifiable handoff without treating an empty successor session as restored authority. | Stable delegation standards plus decision evidence containing timestamps/status; the near-term continuity profile must first distinguish reset, migration, settlement, and reapproval. | Detect use outside a window or after revocation and detect an unaccounted state transition in fixtures without wall-clock nondeterminism. Not a token service, distributed clock protocol, or transaction coordinator. |
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
- mandate/session transitions whose binding and accrued-state outcome reconcile
- annotation/review time and findings disabled as noise
- external adapters and policy/evidence consumers

AgentMandate reaches 1.0 when the manifest, IR, CLI, and JSON contracts have a
compatibility audit; all schema versions have migration fixtures; search limits
and worst-case behavior are documented; at least four independent graphs cover
more than one framework and authority domain; and security plus trace-retention
guidance has external review. Policy export and fleet features may remain
preview after 1.0 if their contracts have not earned stability.

The [current compatibility inventory](docs/current-contract-inventory.md)
extends the historical audit through the merged protocol-import slice. It
pins the current declarations and connects their fixtures to replay tests;
independent review is pending. Initial v1 baselines remain distinct from actual
historical conversions. This addition does not change the phase ledger or
replace external security and trace-retention review.

The [search implementation and study](docs/search-performance.md) now provide
the bounds, storage characterization, measured truncation frequency, and
reproduction tooling for the search criterion. The maintainer's out-of-band
differential execution review of #227 closes that criterion; it is not another
phase initiative or a substitute for external
security and trace-retention review. No new public contract is added by the
private search instrumentation or the repository's benchmark report.

The principal observation surface added in `0.18.0` extends the compatibility
inventory with `principal_continuity_version: 1` and
`agentmandate.principal-continuity/v1`; it does not complete another initiative.
Its [compatibility fixtures](docs/principal-continuity.md#compatibility-fixtures)
pin the initial input and result contracts, including expiry. These are v1
baselines, not evidence of a migration from an earlier principal result schema.
The opt-in accounting surface also adds `principal_accounting_binding_version: 1`
and `agentmandate.principal-accounting/v1`, with separate
[eligible/expired baselines](docs/principal-accounting.md#compatibility-and-remaining-work).
The observation v1 fixtures are retained unchanged. These additions do not
complete the repository-wide compatibility audit. The optional
`revision_review_version: 1` attachment and `agentmandate.revision-review/v1`
envelope add [separate initial baselines](docs/revision-review.md#compatibility),
including comparison with the unchanged nested continuity result.
The separate `scalar_handover_version: 1`, `scalar_policy_version: 1`, and
`agentmandate.scalar-handover/v1` contracts also have
[initial retained/reset/expired baselines](docs/scalar-handover.md#compatibility).
They extend the inventory without supplying a migration or completing another
initiative.
Any later format change needs an explicit compatibility decision and affected
before/after fixtures. The historical pre-1.0 audit remains a record of its
original baseline; neither this addition nor internal code review supplies the
required external security and trace-retention review.

### Pre-1.0 consolidation and repository history

AgentMandate already has public PyPI distributions and GitHub release tags. A
lack of known production adoption does not make those artifacts unpublished.
Released tags, formats, and links must therefore remain recoverable even if the
pre-1.0 implementation is simplified.

Contract consolidation and Git history are separate decisions:

- The manifest version governs reviewed mandate meaning. Authority IR,
  evidence attachments, adapters, and result envelopes retain independent
  versions because they change for different reasons. They must not be
  collapsed into one top-level version.
- `ceiling`, `scope_key`, and `unbounded` are not legacy spellings of `limit`,
  `scope`, and finite `capacity`. They describe a per-tool bound, its partition
  key, and an unbounded producer. Any replacement needs an evidence-backed
  semantic design rather than a mechanical rename.
- Private migration readers and superseded transports may be removed before
  1.0 once their canonical outputs and source evidence remain replayable from
  evidence tooling. Public CLI and artifact changes follow `STABILITY.md`: a
  pre-1.0 minor release, migration notes, and fixtures for every affected
  contract.

The consolidation window opened after the authority-continuity Gate 4 decision
and completed in the reviewed `0.17.0` baseline:

1. inventory every public contract, private compatibility path, fixture, and
   historical reader;
2. remove unused private paths and move evidence-only migrations out of the
   runtime package;
3. decide whether any public contract needs a new version, then migrate it
   independently with byte-pinned before/after fixtures;
4. rerun the zero-dependency, package, evidence, and 100% coverage gates; and
5. cut one reviewed pre-1.0 baseline before declaring the stable surface.

Do not rewrite history after 1.0. If a one-time clean history is still wanted,
the safest remaining window is immediately before 1.0, after consolidation.
Preserve the current graph in an immutable archive tag and an offline bundle;
leave every published release tag on its original commit; update or retain all
gate-review commit references; then replace `main` once under an explicit,
reviewed operation plan. This changes repository presentation only. It cannot
erase PyPI releases or their compatibility obligations. Normal pull requests
continue to use squash merges without rewriting published history.

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
