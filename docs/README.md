# Documentation map

Start with the [project overview](../README.md) for the problem, a working
counterexample, installation, and the command summary. The pages below serve
different purposes. A contract page describes a current or experimental data
boundary. A gate review records why a public surface was exposed or deferred.
An evidence page records what was observed and must not be read as a product
guarantee.

## Choose a task

| What you want to do | Start here |
|---|---|
| Run a complete example | [README quickstart](../README.md#run-the-example) |
| Review an existing agent's tools | [Scan and inventory](inventory.md), then [manifest fields](manifest.md) |
| Start from MCP, OpenAPI, or A2A JSON | [Catalogue imports](catalogue-import.md) |
| Block a release that widens authority | [CI integration](ci.md) |
| Check recorded calls against a mandate | [Trace verification](traces.md) |
| Turn reachable authority into tests | [Evaluation loop](evaluation-loop.md) |
| Inspect cross-session consumed state | [Refund example](../examples/continuity-refund/README.md) |
| Compare principal and session observations | [Principal continuity](principal-continuity.md) |
| Account for shared spend under reviewed mandate intent | [Principal accounting](principal-accounting.md) |
| Review policy revisions and issuer treatment | [Revision review](revision-review.md) |
| Verify scalar state and capacity at cutover | [Scalar handover walkthrough](../examples/scalar-handover/README.md) |
| Contribute a fix or evidence graph | [Contributing](../CONTRIBUTING.md) |

Most users need the first four guides. The attachment contracts below address
specific evidence gaps and have additional review and source-byte requirements.

## Use AgentMandate

- [Manifest reference](manifest.md): declare one reviewed mandate.
- [Source and catalogue scanning](inventory.md): derive a manifest skeleton
  without importing agent code.
- [Protocol catalogue imports](catalogue-import.md): extract local JSON into
  review-marked skeletons or unreviewed inventory/IR, keeping adapter gaps explicit.
- [CI integration](ci.md): exit codes, GitHub Actions, SARIF, and rollout.
- [Runtime trace verification](traces.md): replay JSON Lines or OpenTelemetry
  evidence against a mandate.
- [Test obligations](test-obligations.md) and the
  [evaluation loop](evaluation-loop.md): connect authority analysis to external
  agent evaluation without confusing permitted paths with model behaviour.

## Understand the model

- [Design](../DESIGN.md): the authority model, search boundary, and non-goals.
- [Search bounds and performance](search-performance.md): depth semantics,
  worst-case growth, reproducible measurements, and CI resource limits.
- [Authority IR](authority-ir.md): canonical provenance and the reviewed
  manifest-v1 analysis profile.
- [Stability](../STABILITY.md): supported public surfaces and versioning.
  Python callers can use `load`, `analyse`, and `compare` from `agentmandate`;
  the complete public export list is `agentmandate.__all__`. Private attachment
  types are consumed through the CLI, not a supported Python API.
- [External security review scope](external-security-review.md): the prepared
  reviewer brief and required closing record; reviewer nomination is still open.
- [Roadmap](../ROADMAP.md): delivered, active, evidence-blocked, and later work.
- [Pre-1.0 consolidation audit](pre-1.0-consolidation-audit.md): public contracts,
  private compatibility paths, fixture coverage, and the completed baseline
  alongside its historical initial findings.

## Reviewed evidence attachments

These public CLI surfaces validate structure separately from eligibility to
change an analysis result:

- [Dynamic inventory](dynamic-inventory.md)
- [Conditional authority](conditions-delegation.md)
- [Delegation chains](delegation-v2.md)
- [Managed Cedar evidence](cedar-import.md) and
  [effective policy revision comparison](cedar-effective-diff.md)
- [Finite producer cardinality](bounded-producers.md)
- [Authority continuity](authority-continuity.md) and the separate
  [principal/session observation contract](principal-continuity.md)
- [Scalar handover](scalar-handover.md): retained state and full next-request
  integer-domain inclusion within a declared cutover model

Authority continuity remains experimental and its Python records remain
private. Its public CLI asks whether consumed state remains attached to one
reviewed mandate across a session, handoff, or policy revision. A session
identifier is evidence for that question, not the mandate itself. The
[next evidence plan](continuity-evidence-plan.md) defines matched
counterfactual captures for session, revision, process, principal, deployment,
retry, and concurrency boundaries.

## Terms used across the guides

- **Mandate:** one reviewed, bounded unit of work; the manifest describes it.
- **Authority:** actions reachable in the declared model and search bound.
- **Mandate binding:** evidence joining reviewed intent to a particular enforcement
  boundary and identity. Sharing a session identifier is not such a join.
- **Scope binding:** one resource instance available to the modeled agent,
  such as a case on which a per-case ceiling accumulates.
- **Source binding:** the selected agent constructor or tool declaration in
  source code, used to avoid combining unrelated tool lists.
- **Eligible evidence:** exact captured bytes with the required review and
  validity checks. Eligibility alone does not prove a continuity verdict.
- **Unresolved:** required evidence is missing or insufficient. It is a finding
  to investigate, not a successful deployment check.

## Decision records and evidence

Files ending in `-gate-4-review.md`, `-gate-5-review.md`, or `-audit.md` are
dated decision records. They preserve acceptance criteria and negative results;
they are not the shortest route to using the current CLI.

Some reviews retain an initial proposal followed by its later decision. Read
the closing section before treating their opening status as current:

| Historical record | Current reading |
|---|---|
| [Bounded producer audit](bounded-producer-evidence-audit.md) | Cardinality has a [shipped contract](bounded-producers.md); quantity relationships remain evidence-gated |
| [Resource relationship audit](resource-relationship-audit.md#decision) | The candidate capture was completed and did not satisfy the extension gate |
| [Pre-1.0 audit](pre-1.0-consolidation-audit.md#consolidation-sequence) | Converter relocation completed; its opening prerequisites describe the earlier plan |
| [Evidence metric review](evidence-metric-review.md#machine-readable-handoff-audit) | The later audit corrects the classification claim: 16 of 37 records had canonical pre-study labels; no complete class distribution is established |

The [evidence index](evidence/README.md) separates captured source material,
reviewed corrections, synthetic fixtures, and analysis results. Synthetic
fixtures establish implementation behaviour, not operational deployment facts.
