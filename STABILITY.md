# API stability and the path to 1.0

AgentMandate is alpha because the authority model has not been pointed at
enough real tool graphs to know where it is too coarse. The label is a scope
statement, not a waiver for silent breakage.

## Guarantees before 1.0

- Patch releases preserve the public Python API and command-line contracts.
- Breaking Python or CLI changes require a new minor release and migration
  notes in `CHANGELOG.md`.
- The manifest supports an explicit `version`, defaulting to `1` when omitted.
  A build rejects a schema version it does not understand rather than guessing.
- Exit codes are part of the contract: `0` clean, `1` finding, `2` usage, I/O,
  malformed manifest/IR, or unsupported IR semantics. CI depends on these, so
  they will not move in a patch.
- `--json` output is additive within a minor series. Fields may be added;
  existing fields will not change meaning.

Production users should pin the current minor series:

```text
agentmandate~=0.29.0
```

## Versioned authority artifacts

`mandate review` uses the separate public `agentmandate.change-review/v1` input
and `agentmandate.review/v1` result contracts. It checks eligibility of recorded
acceptance against the exact bounded diff; it does not change `diff` or `reach`
findings and exits. [V1 baselines and trust requirements](docs/change-review.md)
cover the new gate. These are initial baselines, not a migration from an earlier
review-result schema; the Python helpers remain private.

`mandate remediate` exposes the public `agentmandate.remediation/v1` JSON
presentation with rechecked, unapplied manifest-v1 repair candidates. Its
Python implementation is private. The command retains baseline Authority and
lint findings and keeps their exit code even when candidates exist. Candidate
reachability is scoped to the same depth; enumeration completeness is a
separate field. Results are not authority inputs. Supplying `--ceiling` opts into `agentmandate.remediation/v2`, which adds a
caller-supplied monetary edit domain and `tighten_ceiling` records with explicit
before/after amounts. Omitting the flag preserves v1 bytes. Neither output is
an authority input; the v1-to-v2 compatibility case pins preserved fields and
existing edit semantics. The
[guide and initial fixtures](docs/remediation.md) describe this new surface;
existing CLI output and root Python exports are unchanged.

Supplying `--required-workflows` opts into `agentmandate.remediation/v3`, with
or without ceiling options. The separate strict
`agentmandate.required-workflows/v1` input joins caller-authored positive paths
to the exact baseline manifest. V3 reports scoped baseline/candidate path
conformance and screened edits; it preserves baseline Authority and its exit.
Omitting the flag keeps v1/v2 bytes. The [workflow contract](docs/required-workflows.md)
and before/after compatibility case cover these additions; the Python records
are private. Annotations do not authenticate a reviewer or prove business success.

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
the documented command contract requires a package minor release and migration
notes. Corrections that restore existing documented behavior may be patch
releases. These standalone artifact rules are stricter than the additive
guarantee for existing
`--json` command output.

`mandate ir validate` guarantees structural validity only. Eligibility for
analysis is a separate, stricter check performed by `mandate reach --ir`; this
distinction will not be weakened in a patch release.

The same boundary applies to `mandate inventory validate`: it proves only that
a declaration is structurally valid. `mandate drift` separately checks its
target, reviewed selection, supplied capture digest, completeness, confidence,
review, and expiry against an explicit evaluation date.

`mandate inventory import` writes a draft declaration or the existing inventory
IR profile. It never marks evidence accepted or membership complete. The
explicit protocol readers in `mandate scan --format` write review-marked
skeletons. The original MCP reader and public Python scan signatures are
unchanged when the format flag is omitted. Protocol mappings and their pinned
v1 baselines are documented in [the import guide](docs/catalogue-import.md).
The same minor release adds the `scope.missing-producer` lint error. Previously
clean manifests with a dangling requirement now exit 1; reachability semantics
and the lint JSON shape are unchanged.

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

Principal/session observations use the separate strict
`principal_continuity_version: 1` profile and
`agentmandate.principal-continuity/v1` result schema through the same continuity
commands. They preserve ordered calls and per-principal totals, with source,
review, and expiry checks. Without an accounting binding, mandate identity and
continuity remain unresolved; reconciliation always exits 1. Single-principal
bindings are refused on this path. The archival `principal_observations_version`
input remains unsupported.
See the [profile contract](docs/principal-continuity.md).

The optional `principal_accounting_binding_version: 1` artifact selects the
separate `agentmandate.principal-accounting/v1` result. It authorizes per-trial
shared monetary totals only with eligible observations, independent binding
review, exact sources and joins, and known completion. An observed budget breach
does not establish reset or resolve continuation safety; this path always exits 1.
Existing unbound v1 output is unchanged. Both new contracts have initial
[compatibility fixtures](docs/principal-accounting.md#compatibility-and-remaining-work);
these are baselines, not migrations or completion of the whole 1.0 audit.

The opt-in `revision_review_version: 1` attachment selects
`agentmandate.revision-review/v1`. It nests the unchanged continuity baseline
and reports separately reviewed comparison and issuer-treatment claims within
an explicit scope. It never promotes these scoped claims to global safe
continuation and always exits 1. Existing commands without review input keep
their result bytes and exit behavior. The [contract and initial fixtures](docs/revision-review.md)
cover this new surface; no historical acceptance or binding is inferred.

`mandate continuity handover` consumes the separate strict
`scalar_handover_version: 1` artifact and closed `scalar_policy_version: 1`
policy captures. Its `agentmandate.scalar-handover/v1` result proves only
conformance to the declared scalar handover at cutover. Exit 0 also requires
clean, untruncated manifest Authority; it does not establish global provider
safe continuation. Eligible contradictions and unresolved evidence exit 1;
malformed artifacts, locator errors, and I/O failures exit 2. Existing
reconciliation results are unchanged. The [contract](docs/scalar-handover.md)
and initial retained/reset/expired fixtures extend the compatibility inventory;
they do not record a migration or complete the repository-wide audit.

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

`mandate cedar export` is an experimental compiler with
`cedar_export_version: 1` mapping input and `agentmandate.cedar-export/v1`
results. It generates only explicitly mapped stateless permissions. Losses
block export by default; `--allow-partial` emits a candidate and still exits 1.
Native validation is separate from compilation. Existing managed Cedar
commands and results are unchanged. See [the export guide](docs/cedar-export.md).

`mandate rego export` adds the experimental `rego_export_version: 1` mapping
and `agentmandate.rego-export/v1` result. It uses Rego v1 with a pinned native
OPA runner, refuses stateful losses by default and keeps partial candidates at
exit 1. This is an initial baseline, not a migration. Existing Cedar output
and prior commands are unchanged. See [Rego export](docs/rego-export.md).

`mandate deployment drift` adds the experimental `deployment_version: 1`
configuration input and `agentmandate.deployment-drift/v1` result. Its clean
status means consistency of supplied configuration and exact policy bytes,
not authenticated deployment enforcement. Initial Cedar/Rego baselines preserve
separate manifest Authority. Existing source drift and exporter results remain
unchanged. See [deployment drift](docs/deployment-drift.md).
