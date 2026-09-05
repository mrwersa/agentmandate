# API stability and the path to 1.0

AgentMandate is alpha because the authority model has not been pointed at
enough real tool graphs to know where it is too coarse. The label is a scope
statement, not a waiver for silent breakage.

## Guarantees before 1.0

- Patch releases preserve the public Python API and command-line contracts.
- Breaking Python or CLI changes require a new minor release and migration
  notes in `CHANGELOG.md`.
- The manifest carries an explicit `version`. A build rejects a schema version
  it does not understand rather than guessing.
- Exit codes are part of the contract: `0` clean, `1` finding, `2` usage, I/O,
  malformed manifest/IR, or unsupported IR semantics. CI depends on these, so
  they will not move in a patch.
- `--json` output is additive within a minor series. Fields may be added;
  existing fields will not change meaning.

Production users should pin the current minor series:

```text
agentmandate~=0.16.0
```

## Versioned authority artifacts

The `mandate ir`, `mandate inventory`, `mandate conditions`, `mandate delegations`,
`mandate producers`, `mandate continuity`, `mandate cedar`, and reviewed
`mandate reach` attachment surfaces are public. The Python records remain
private and are not exported from `agentmandate`. Their explicit artifact
versions separate compatibility from package releases:

- `ir_version` changes when graph records, relations, or canonicalization
  change incompatibly.
- Source adapter versions change when projection logic changes; that may alter
  semantic and result digests without changing either JSON format.
- `result_version` changes when a hashed envelope field is added, removed,
  renamed, reinterpreted, or canonicalized differently. The strict reader does
  not treat additional fields as silently additive.
- `condition_version` and `context_version` change when their strict artifact
  records change incompatibly. Conditional command output uses the independent
  `agentmandate.conditions/v1` presentation schema.
- `delegation_version` and principal-v2 attachment records change when their
  strict artifact formats change incompatibly. Delegation command output uses
  the independent `agentmandate.delegations/v1` presentation schema.
- `managed_oracle_version` changes when the strict managed-enforcement record
  changes incompatibly. Cedar alignment and revision output use the independent
  `agentmandate.cedar-alignment/v1` and
  `agentmandate.cedar-effective-diff/v1` presentation schemas.
- `producer_boundary_version` changes when the finite-producer evidence record
  changes incompatibly. Producer-aware reach output uses the independent,
  canonical `agentmandate.producers/v1` result schema and closed finding codes.
- Continuity binding, AgentCore, and Anthropic artifact versions change
  independently when their strict records change incompatibly. Reconciliation
  output uses the canonical `agentmandate.continuity/v1` result schema and
  closed finding codes.

Future presentation metadata may be additive only if it is explicitly outside
the canonical envelope. Adding support for a new format version or changing
command behavior requires a package minor release and migration notes. These
standalone artifact rules are stricter than the additive guarantee for existing
`--json` command output.

`mandate ir validate` guarantees structural validity only. Eligibility for
analysis is a separate, stricter check performed by `mandate reach --ir`; this
distinction will not be weakened in a patch release.

The same boundary applies to `mandate inventory validate`: it proves only that
a declaration is structurally valid. `mandate drift` separately checks its
target, reviewed selection, supplied capture digest, completeness, confidence,
review, and expiry against an explicit evaluation date.

`mandate conditions validate` likewise proves structure only. Manifest-mode
`reach` and `drift` separately check profile semantics, reviewed context,
capture digest, explicit evaluation date, and—during drift—the selected live
source binding. Conditional JSON is additive and appears only when conditional
inputs were supplied; legacy output remains unchanged.

`mandate delegations validate` likewise proves only attachment or chain
structure. Manifest-mode `reach` rechecks closed IR profiles, mapped capture
digests, source binding, reviewed domains, evidence state, expiry, and
hop-to-hop attenuation at an explicit UTC timestamp. Delegation JSON appears
only when delegation inputs were supplied. SARIF, Mermaid, IR, and conditional
composition are refused until they can preserve delegation uncertainty.

`mandate cedar validate` likewise proves managed-oracle structure only. Cedar
alignment and diff separately require explicit source roots and an evaluation
date, verify every declared digest and the closed managed IR profile, and retain
unchanged manifest authority on uncertainty. Their JSON names all input and
per-request evidence digests. The presentation is not accepted as an authority
artifact, and the private Python records remain unsupported.

`mandate producers validate` likewise proves boundary structure only.
Manifest-mode `reach` rechecks every closed producer profile, caller-mapped
source digest, exact deployment and reviewed partition selection, complete
monotone run, evidence state, and expiry. Its canonical result is presentation,
not an authority input. Findings preserve baseline manifest authority and exit
1 after complete output. Malformed or incomplete inputs exit 2 with empty
stdout. IR, SARIF, Mermaid, condition, and delegation composition are refused
before any input is read or output written.

`mandate continuity validate` proves artifact structure only.
`mandate continuity reconcile` rechecks the provider profile, exact caller-mapped source
bytes, optional mandate binding and its source bytes, evidence state, and UTC
evaluation time. Its canonical result is presentation, not an authority input.
Violations and unresolved trust retain complete manifest Authority and exit 1
after complete output. Malformed or incomplete inputs exit 2 with empty stdout.
IR, SARIF, Mermaid, OTel, condition, delegation, producer, and Cedar
composition are refused before any input is read. The Python records remain
private.

## What is most likely to change

The manifest schema and the way standalone evidence profiles compose with it.
Conditional authority, delegation analysis, finite producer cardinality, and
authority continuity have public, versioned validate-then-consume command
surfaces, but remain reviewed attachments rather than new manifest-v1 meanings.
Their Python records remain private, and presentation results are not accepted
as authority input. Explicitly synthetic accepted fixtures supply producer and
continuity clean paths while the real migrations remain unreviewed. Structural
validity never makes any of these records trusted mandate authority.

Three areas remain deliberately under-modelled:

- **Data-flow labels.** Detecting that a read tool feeds an exfiltration path
  needs taint labels the manifest does not carry today.
- **Resource relationships and quantities.** Manifest v1 cannot express fixed
  ownership or containment relationships. Finite producer cardinality stays a
  reviewed attachment rather than manifest meaning; evidence-backed value
  relationships still lack a selected quantity contract.
- **General cross-session reachability.** Continuity reconciliation covers only
  reviewed, named scalar cumulative transitions. It does not search arbitrary
  durable agents, memories, sessions, or asynchronous work.

Integrating any of these into manifest authority may change the schema. The
`version` field is how that will be handled; standalone artifact versions may
instead evolve independently when the manifest meaning is unchanged.
