# Pre-1.0 compatibility and consolidation audit

Status: **inventory current through `d063f00`; Cedar mapping split complete**.
This is the first step of the consolidation window in `ROADMAP.md`. It records
what must remain compatible before implementation is simplified. It does not
change a reader, schema, command, or result.

## Decision

No public contract needs a new version before the reviewed pre-1.0 baseline.
The manifest, Authority IR, attachments, adapters, and result envelopes already
have independent version boundaries, and their canonical fixtures exercise the
formats currently consumed by the CLI. Consolidation should preserve those
boundaries rather than replace them with one package-wide artifact version.

Five evidence-converter families, implemented by six entry points, and two
superseded private record families are candidates to leave the runtime package.
They are not deletion candidates yet:
each must first move to repository evidence tooling, reproduce its committed
canonical output byte for byte, and leave no runtime caller. The local Cedar
bundle reader is a further split candidate because managed Cedar reuses its
mapping parser.

## Public contracts

### Package and Python API

The distribution contract is one Python 3.10+ package, the `mandate` entry
point, no mandatory runtime dependency, and the package version read only from
`agentmandate.__version__`. YAML remains an optional, lazily imported feature.

`agentmandate.__all__` is the exhaustive Python API. Its current surface is:

- model and result types: `Authority`, `Binding`, `Breach`, `Change`,
  `Conformance`, `Declaration`, `Delta`, `Drift`, `DriftFinding`, `Finding`,
  `Inventory`, `Limits`, `Mandate`, `Money`, `Obligation`, `ObligationSet`,
  `Observation`, `Proposal`, `Scenario`, `ScenarioSet`, `ScenarioStep`, `Step`,
  `Tool`, and `Violation`;
- error and schema names: `InventoryError`, `ManifestError`,
  `OBLIGATIONS_SCHEMA`, and `SCENARIOS_SCHEMA`;
- operations: `analyse`, `check`, `collect`, `compare`, `compare_source`,
  `derive`, `derive_scenarios`, `load`, `loads`, `load_obligations`,
  `load_scenarios`, `propose`, `reconcile`, `reconcile_scenarios`, `render`,
  `replay`, `replay_file`, `save_obligations`, `save_scenarios`, `scan_file`,
  `scan_source`, and `to_decision_suite`; and
- `__version__`.

All records in underscore-prefixed modules remain private even when a public
CLI serializes their versioned artifact. Consolidation must not make those
Python records public accidentally.

### CLI and failure behaviour

The top-level commands are `cedar`, `conditions`, `continuity`, `delegations`,
`diff`, `drift`, `inventory`, `ir`, `lint`, `obligations`, `producers`, `reach`,
`scan`, `scenarios`, and `verify`. The nested command contracts are:

| Command | Public modes |
|---|---|
| `mandate ir` | `export`, `validate` |
| `mandate inventory` | `validate` |
| `mandate conditions` | `validate` |
| `mandate delegations` | `validate` |
| `mandate producers` | `validate` |
| `mandate continuity` | `validate`, `reconcile` |
| `mandate cedar` | `validate`, `align`, `diff` |

The remaining commands are direct analysis or export commands. Analysis
commands retain `--json`; `reach` additionally retains SARIF and Mermaid.
`scan` and `ir export` write artifacts rather than gate results.

Exit status is a public contract across every gate: `0` is clean, `1` is a
complete finding result, and `2` is usage, I/O, malformed input, unsupported
version, or unsupported composition. Paths documented as producing no partial
standard output on exit `2` must retain that property.

### Versioned artifacts and output

Each row is an independent compatibility boundary. “Private reader” means the
Python type is unsupported, not that the CLI format is private.

| Boundary | Current version or schema | Consumer and fixture family | Disposition |
|---|---|---|---|
| Manifest | `version: 1` | `manifest.py`; examples and manifest-v1 default fixtures | Retain |
| Authority IR | `ir_version: 1` | `ir export`, `ir validate`, `reach --ir`; `authority-ir-v1.json` and invalid corpus | Retain |
| Manifest IR adapter | `agentmandate.manifest` adapter 2 | IR canonical and compatibility fixtures | Retain |
| Manifest-default IR adapter | `agentmandate.manifest-defaults` adapter 1 | shorthand and all-default manifest fixtures | Retain |
| Authority IR result | `result_version: 1` | `reach --ir --json`; clean, breached, and truncated fixtures | Retain |
| Dynamic inventory | `inventory_version: 1`; declaration and capture IR adapters 1 | `inventory validate`, `drift`; AgentKit and Sentry fixtures | Retain |
| Tool condition | `condition_version: 1`; IR adapter 1 | `conditions validate`, `reach`, `drift`; condition fixtures | Retain |
| Condition context | `context_version: 1` | `conditions validate`, `reach`, `drift`; context and capture fixtures | Retain |
| Conditional presentation | `agentmandate.conditions/v1` | conditional reach and drift result fixtures | Retain |
| Structured principal | `principal_version: 1`; IR adapter 1 | repository-only historical replay; three condition-era fixtures | Retain outside runtime |
| Delegation chain | `delegation_version: 1`; IR adapter 1 | `delegations validate`, `reach`; chain fixtures | Retain |
| Delegation attachment | `principal_version: 2`; IR adapter 1 | `delegations validate`, `reach`; attachment-v2 fixture | Retain |
| Delegation presentation | `agentmandate.delegations/v1` | canonical CLI fixture and CLI tests | Retain |
| Local Cedar bundle | `bundle_version: 1`; shared mapping 1; IR adapter 1 | repository-only replay; pinned document-cloud evidence | Retain outside runtime |
| Managed Cedar oracle | `managed_oracle_version: 1`; capture and IR adapters 1; mapping 1 | `cedar validate`, `align`, `diff`; AgentCore evidence | Retain |
| Cedar presentations | `agentmandate.cedar-alignment/v1`, `agentmandate.cedar-effective-diff/v1` | canonical alignment and diff fixtures | Retain |
| Producer boundary | `producer_boundary_version: 1`; IR adapter 1 | `producers validate`, producer-aware `reach`; IAM and accepted synthetic fixtures | Retain |
| Producer presentation | `agentmandate.producers/v1` | clean, bounded, breached, unresolved, and truncated fixtures | Retain |
| Continuity binding | `continuity_binding_version: 1`; record and IR adapters 1 | `continuity validate`, `reconcile`; binding and accepted synthetic fixtures | Retain |
| AgentCore continuity | `agentcore_continuity_version: 1`; record and IR adapters 1 | `continuity validate`, `reconcile`; canonical migration fixture | Retain |
| Anthropic continuity | `anthropic_continuity_version: 1`; record and IR adapters 1 | `continuity validate`, `reconcile`; canonical migration fixture | Retain |
| Continuity presentation | `agentmandate.continuity/v1` | eight canonical result fixtures and runnable example | Retain |
| Obligations | `agentmandate.obligations/v1` | `obligations`; reviewed example and round-trip tests | Retain |
| Scenarios | `agentmandate.scenarios/v1` | `scenarios`; round-trip and reconciliation tests | Retain |
| OTel verification | `agentmandate.verify/v1` | `verify --otel`; trace fixtures and conversion tests | Retain |
| SARIF | SARIF 2.1.0 | `reach --sarif`; rendering tests and GitHub Action | Retain |
| AgentVerity decision suite | `agentverity.decision-suite/v1` | `obligations --suite`; external consumer contract | Retain |

Legacy human and JSON output without a `schema` field remains public where the
CLI predates canonical envelopes. It is covered by command tests and the
precondition that adding no attachment inputs leaves existing output
byte-identical. A missing schema marker is not permission to rewrite it during
consolidation.

## Private compatibility and migration paths

These paths are implementation details, but their outputs preserve evidence or
published artifacts. “Relocate” means move the converter to `scripts/` or the
owning evidence directory only after an executable replay replacement exists.

| Private path | Current callers and dependency | Decision |
|---|---|---|
| `_ir._from_mandate`, `_to_mandate`, `_analyse_ir` and `_IRAnalysis.from_json` | Public IR export/reach CLI and result revalidation | Retain in runtime |
| Manifest-default adapter | Required to distinguish schema defaults from observed source facts | Retain in runtime |
| `Grant.from_json` and `DelegationChain.from_grant_v1` / `migrate_grant_v1` | `scripts/migrate_delegation_evidence.py` regenerates the committed grant-v1 chain | Relocated; retain evidence tool |
| `DelegationChain.from_authorizer_capture` / `migrate_authorizer_capture` | `scripts/migrate_delegation_evidence.py` regenerates the canonical Authorizer chain | Relocated; retain evidence tool |
| `ToolPrincipal` v1 reader and IR projection | `scripts/replay_principal_v1.py` round-trips three fixtures and pins their IR digests | Relocated; retain historical replay |
| Shared Cedar mapping-v1 parser | `_cedar_mapping.py`; consumed by local bundles and managed Cedar | Retain in runtime |
| `CedarBundle` v1 reader and local IR projection | `scripts/replay_cedar_bundle_v1.py` verifies the bundle, sources, and pinned IR digest | Relocated; retain historical replay |
| `migrate_aws_iam_access_key_boundary` | `scripts/migrate_producer_evidence.py` regenerates `producer-boundary-iam-v1.json` | Relocated; retain evidence tool |
| `migrate_agentcore_binding` | `scripts/migrate_continuity_evidence.py` regenerates `continuity-binding-v1.json` | Relocated; retain evidence tool |
| `migrate_agentcore_continuity` | `scripts/migrate_continuity_evidence.py` regenerates `agentcore-continuity-v1.json` | Relocated; retain evidence tool |
| `migrate_anthropic_continuity` | `scripts/migrate_continuity_evidence.py` regenerates `anthropic-continuity-v1.json` | Relocated; retain evidence tool |
| Strict private result readers for IR, producer, and continuity envelopes | Canonical fixture validation and recomputation checks | Retain in runtime |

No converter above is called by `cli.py`. Removing one without replacement
would still be a defect because the repository would lose the mechanical link
between captured source bytes and its canonical fixture.

## Fixture and evidence replay coverage

The committed fixture families cover manifest defaults, Authority IR structure
and results, dynamic inventory, conditions and structured principals,
delegation migrations and attachments, finite producers, and continuity. Cedar
canonical inputs live with their evidence because their source bundles are the
fixture. Real-graph evidence directories retain capture inputs, reviewed
corrections, generated manifests, and explicit limits on each claim.

The accepted producer and continuity fixtures are explicitly synthetic. Their
purpose is to prove a clean implementation path. They do not upgrade the real
IAM, AgentCore, or Anthropic migrations from `unreviewed` evidence.

Before relocating any converter, a replacement replay check must:

1. consume the same committed source bytes;
2. regenerate the same canonical artifact bytes;
3. validate every declared source digest;
4. keep the real evidence review state unchanged; and
5. run under the zero-dependency repository checks where practical.

## Consolidation sequence

The next PRs should remain independently reviewable:

1. rerun every release gate and record the reviewed pre-1.0 baseline.

Repository-history cleanup is a separate decision and must not be combined
with any contract or migration change.
