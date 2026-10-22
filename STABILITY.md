# API stability and the path to 1.0

AgentMandate is alpha. The current release supports one current contract for
each artifact family. Superseded Python aliases, manifest readers and output
modes are removed rather than carried as compatibility code.

## Release rules before 1.0

- Patch releases preserve supported public Python and CLI contracts. Breaking
  changes require a minor release and explicit changelog notes.
- Manifest version 2 is current and is the default when omitted. Unsupported
  versions fail closed; there is no version-1 conversion in the package.
- Exit codes remain `0` clean, `1` finding and `2` usage, I/O or malformed or
  unsupported input. A repair proposal or recorded acceptance does not erase
  the original analysis finding.
- Analysis commands support `--json`. `scan` and `ir export` write artifacts
  and are not gates. Strict hashed results reject unknown fields and versions.
- Existing releases remain recoverable in Git and published artifacts. Their
  continued availability does not require old readers in the current package.

Pin the current minor series when integrating it:

```text
agentmandate~=0.44.0
```

## Current quantity model

`Quantity(amount, unit)` represents exact non-negative additive consumption.
Tools name their accounting pool with `quantity`; `limits.quantities` declares
separate cumulative budgets. Authority exposes `max_quantities`. Units must
match within a pool and are case-sensitive. Different pools are never summed,
even when their units match. No exchange rate, conversion or unit equivalence
is inferred.

The money-only alpha API is replaced. `Money`, `limits.total`, currency-only
manifest/replay inputs and remediation v1–v5 presentation modes are unsupported.
There are no aliases or compatibility readers. See the
[quantity contract](docs/quantity-budgets.md) for examples and exclusions.

The model covers one quantity per tool call, per-tool/per-binding ceilings,
mandate-wide named budgets and effect-class call counts. It does not cover
several simultaneous charges on one call, timed rates, concurrent gauges,
negative consumption, replenishment or argument-dependent production.

## Current artifact boundaries

| Family | Current contract |
|---|---|
| Manifest | `version: 2`; public `Mandate`, `Tool`, `Limits`, `Quantity` |
| Authority IR and hashed result | `ir_version: 2`, `result_version: 2`; private Python records |
| Manifest adapters | Manifest adapter 3, defaults adapter 2 |
| Structural validation | `agentmandate.validation/v1`; structure only, not accepted evidence |
| Remediation | `agentmandate.remediation/v6` for every repair option |
| Required workflows | `agentmandate.required-workflows/v2` |
| Scenarios and verify presentation | `agentmandate.scenarios/v2`, `agentmandate.verify/v2` |
| Conditions and delegations | Current input versions retain independent lifecycles; result presentations use `/v2` |
| Producer and continuity results | `agentmandate.producers/v2`, `agentmandate.continuity/v2`, hashed result version 2 |
| Principal, revision and scalar handover results | Current `/v2` presentations; scalar policy version 2 includes its dimension |
| Managed Cedar alignment and diff | Current `/v2` presentations; captured native request contracts remain separate |
| Cedar/Rego stateless exports | Current `/v1` mappings and export results; cumulative quantities appear in the loss report |
| Change review | `agentmandate.change-review/v1` input, `agentmandate.review/v2` result |
| Deployment, fleet and captured Rego comparisons | Current `/v2` result presentations |

Artifact versions describe their own boundaries. A source adapter change can
alter semantic digests without changing the surrounding graph format. An input
profile does not become accepted evidence because its graph validates. The
[current inventory](docs/current-contract-inventory.md) records actual exports,
command paths, version markers, fixtures and replay tests; it is the detailed
index for this table.

Historical captures keep their native transport and profile formats. A native
artifact whose version is still supported is not an alias for an obsolete
manifest or result. Evidence-only historical projections live in repository
scripts, outside the runtime package.

The `agentmandate.required-workflows/v2` input also gates a release: `remediate`,
`diff` and `review` all consume it. `diff` and `review` recheck each supplied
path against both manifests and report a `preserved` or `regressed` relation with
the first failing call. Omitting `--required-workflows` keeps their previous
output bytes and exit codes. A change-review record's pinned comparison digest
covers the rechecked paths and `required_workflows_metadata`, including the
annotation file's exact source digest, baseline manifest digest, agent, reviewer,
reason and scope. Changing annotation bytes invalidates the old review record
even when the workflow outcomes are unchanged. A record written without the
check cannot accept a comparison that includes it. Digests identify bytes;
they do not authenticate the annotation author.

The GitHub Action consumes these annotations through `required-workflows` and
`required-workflows-ref`, alongside a baseline. It pins a regular Git blob once
and shares those bytes between diff and review. Its combined report identifies
the selected commit and source digests; SARIF includes reachability and workflow
failures. Ref protection and reviewer authentication remain the caller's
responsibility. The Action's success/failure and report-only conventions are
distinct from the CLI exit codes retained in individual check records.

The Action's opt-in [repair suggestions](docs/action-repairs.md) are separate
from those blocking checks. Both manifests are frozen once and the same pinned
workflow annotation serves diff, review and repair. Repair reports, timeouts and
configuration errors cannot waive findings or change the gate's counts or exit
policy. No proposal is applied. Input hashes identify selected bytes, not their
authors or live deployment. Isolated Python imports keep checkout packages and
`PYTHONPATH` from replacing the installed analyzer.

## Repair and bounded-search claims

Every repair is rechecked against the complete changed manifest. Required paths
screen model conformance, not business success. Proposals remain unapplied;
original budgets and named quantity assignments stay fixed. Different units
are never added to rank a proposal.

`remediate --released FILE` also requires each candidate's ordinary manifest
comparison to have no widening or required-workflow regression, and its own
analysis and lint to have no breach or error. Required workflows pin the
released file, which must satisfy them. Both input digests, the original
comparison and rejected comparisons remain visible; proposals never clear the
original finding. Default depth is the larger declared depth and is fixed for
both sides and all candidates. This mode cannot combine with conditions or
delegations. It reuses remediation/v6 and the current comparison reader;
there is no alternate legacy output mode. See [release repairs](docs/release-remediation.md).

Condition-aware remediation reuses the existing reviewed condition contract.
Its baseline and candidate results describe that conditional effect scope;
each condition report also retains unconditional Authority and lint. Candidate
manifests keep their declared effects and require the same inputs to reproduce
the scoped result. Unresolved evidence blocks recommendations. This does not
generate new conditions, authenticate review or verify source enforcement.

Delegation-aware remediation keeps reviewed chains and mappings fixed. Only a
tool's excess against a trusted, complete grant surface may be addressed by
manifest edits; chain widening and unresolved evidence block recommendations.
Grant checks do not remove tools or change effects in Authority. Every returned
candidate passes both ordinary reachability and active-attachment checks.
Conditions and delegations cannot be combined. This does not edit grants or
prove authentication, runtime mediation or that unannotated tools are delegated.

Discovery's domain-frontier completion, exhaustive point enumeration,
evaluation-limit truncation, frontier display cap and each Authority's call-depth
truncation are distinct. A complete frontier at depth eight does not prove
safety at depth ten. See [remediation](docs/remediation.md) and
[search limits](docs/search-performance.md).

## Evidence and 1.0

Historical captures, signed bindings and accountable acceptance records retain
their original bytes, scope and expiry. New model projections do not inherit
acceptance. Current graph tests label their synthetic associations explicitly;
string identity and matching digests do not authenticate an execution or signer.

Continuity, shared accounting and scalar handover readers have their own
reviewed domains and prerequisites. Generic quantity budgets do not establish
runtime enforcement, live exclusivity, atomic accounting or safe continuation.
Missing bindings, state, mediation or policy comparability remain unresolved.

The remaining 1.0 criteria are tracked in [the roadmap](ROADMAP.md). Current
schema boundary fixtures and the contract inventory replace active historical
compatibility replay chains. Independent security and trace-retention review
remains deferred and cannot be supplied by author or agent self-review.
