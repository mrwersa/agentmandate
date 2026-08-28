# Cedar policy import contract

Status: **proposed and experimental**. This document is contract gate 1 of
[issue #108](https://github.com/mrwersa/agentmandate/issues/108). It defines a
read-only Cedar experiment; no current command accepts a Cedar bundle as
reviewed or analyzable authority.

## Why Cedar is first

Cedar is a useful first policy language because its authorization inputs are
explicit: principal, action, resource, context, policies, and entity data. Its
schema describes the entity and request shapes against which policies can be
validated. Cedar's decision algorithm is default deny, gives a satisfied
`forbid` precedence over a satisfied `permit`, and skips policies that error
while returning those errors in diagnostics
([authorization semantics](https://docs.cedarpolicy.com/auth/authorization.html)).
Those properties are precise enough to test without treating Cedar as
AgentMandate's policy language.

The experiment pins the Cedar implementation release
[`v4.12.0`](https://github.com/cedar-policy/cedar/releases/tag/v4.12.0) and the
official `cedar-examples` commit
[`c251f7d`](https://github.com/cedar-policy/cedar-examples/tree/c251f7d1ad171bd12dee5d1d7a1cceaec994518f/cedar-example-use-cases/document_cloud).
The language and SDK versions are separate version axes, as Cedar's
[document history](https://docs.cedarpolicy.com/other/doc-history.html)
explains. Every capture records both rather than deriving one from the other.

## The trust boundary

Five different claims must stay separate:

1. **Parsed:** the files have the expected shapes.
2. **Native-valid:** the pinned Cedar implementation accepts the policies
   against the supplied schema.
3. **Decision-reproduced:** the pinned implementation returns the recorded
   decision and diagnostics for a concrete request and entity set.
4. **Mapped:** a reviewer has connected Cedar principal, action, and resource
   concepts to a selected AgentMandate agent, tool, principal, and binding.
5. **Authority-eligible:** the mapping and request domain are complete enough
   for a Cedar decision to constrain compound reachability.

Each claim requires the preceding one. None implies the next. In particular,
native validation checks consistency with a schema; it does not prove that the
application constructs the represented requests or enforces the returned
decision. Cedar itself describes validation as separate from authorization and
the schema as a contract with the application
([policy validation](https://docs.cedarpolicy.com/policies/validation.html)).

## Candidate capture bundle

A repository fixture is a directory with a canonical `bundle.json` index and
digest-pinned files. The index records:

- `bundle_version`, Cedar language, SDK, implementation package, and package
  integrity versions;
- policy-set, schema, entity, and request-corpus locators with content digests;
- the policy representation (`cedar` text or Cedar's
  [JSON policy-set format](https://docs.cedarpolicy.com/policies/json-format.html));
- native validation output and, per request, decision, determining policy IDs,
  error policy IDs, and diagnostic digest;
- a reviewed deployment mapping, its evidence state, reviewer, expiry, and
  source digest; and
- capture adapter identity/version and an explicit completeness statement.

The core package does not gain a Cedar parser or runtime dependency. A capture
script invokes a pinned official Cedar distribution, preserves its raw output,
and emits the JSON index. The private reader only validates that index and its
digests.
Caller-supplied bytes are hashed; the reader does not fetch policy stores,
execute Cedar, read credentials, or consult the wall clock.

The first fixture uses the official document-cloud schema, policies, entities,
one `ALLOW` request, and one `DENY` request. This proves transport and decision
reproduction. It is not an agent deployment and therefore cannot satisfy the
mapping or authority-eligibility gates.

The gate-2 fixture uses the official `@cedar-policy/cedar-wasm` 4.12.0 Node
distribution because Cedar does not publish a CLI binary release asset. The
npm lock and SRI pin the distributed implementation. The bundle separately
records language 4.5 and SDK 4.12.0, so the adapter does not conflate those
versions.

### Offline and native reproduction

Committed native output is the required offline oracle. Python CI verifies the
strict bundle, every source digest, decision summaries, and the recorded native
schema-check failure without installing Node. When the pinned npm package is
available, a focused test runs `capture.mjs` and requires byte-identical output.
Contributors can reproduce that optional check with `npm ci --ignore-scripts`
and `npm run capture`. CI may later add the same recapture as a non-core job;
the offline gate never trusts a fresh network response.

## Reviewed deployment mapping

Cedar actions are application authorization concepts, not tool names. Entity
IDs are application identifiers, not AgentMandate bindings. A separate mapping
therefore names:

```yaml
mapping_version: 1
target:
  source: examples/reviewed-manifest.yaml
  agent: deployment-agent
principal:
  cedar_types: [Workload]
  mandate_principal: caller
actions:
  - cedar: AgentCore::Action::"run_query"
    tool: run_query
resources:
  - cedar_type: Database
    binding: reporting-db
request_domain:
  completeness: complete
  evidence: reviewed-request-construction
```

This is an illustrative candidate shape, not a schema commitment. Every join
needs exact, accepted evidence. Reusing an action's spelling as a tool name is
not evidence. A schema's `appliesTo` declaration constrains request types, not
which deployed tool submits the request. Entity parents and attributes are
facts supplied to authorization, not proof of the deployment system of record
([schema](https://docs.cedarpolicy.com/schema/schema.html),
[entity input](https://docs.cedarpolicy.com/auth/entities-syntax.html)).

Completeness is scoped to the selected agent, tool inventory, policy set,
entity snapshot, request-construction revision, and context domain. A request
corpus may demonstrate decisions while remaining `representative`. Only a
finite or otherwise mechanically proven `complete` domain may establish that a
tool is always denied or that no `forbid` can override an observed permit.

## Projection and unknowns

The initial Cedar IR profile remains separate from the analyzable manifest-v1
profile. It preserves policy-set, policy, action, entity-type, request, and
decision records plus their sources. Candidate relations such as
`contains_policy`, `maps_to_tool`, and `decides_request` are registered only
when their endpoint and support rules have fixtures. Successful structural
`ir validate` must not make the profile acceptable to `reach --ir`.

The importer records, rather than interprets away:

- static policies, templates, template links, slots, and annotations;
- `permit` and `forbid` effects;
- principal/action/resource scope operators;
- `when` and `unless` expressions, extension calls, and unknown values;
- schema namespaces, entity types, membership types, action groups,
  `appliesTo`, and context shapes;
- entity parents, attributes, tags, and request context; and
- native determining-policy and error-policy diagnostics.

Cedar templates remain dynamically linked to their template, so a capture must
bind template, link, and linked-policy identity rather than flattening them and
losing lifecycle semantics
([policy templates](https://docs.cedarpolicy.com/policies/templates.html)).
Annotations are preserved but never treated as enforcement because Cedar says
they do not affect evaluation
([policy syntax](https://docs.cedarpolicy.com/policies/syntax-policy.html)).

Unsupported expressions or extensions produce explicit loss records tied to
their JSON location. Missing schema, entities, requests, diagnostics, or
deployment mapping produces an unresolved finding. Unknown is not converted to
false, an empty set, or default deny. A skipped-on-error policy is not silently
dropped: its diagnostic remains load-bearing because skipping a broken
`forbid` may change effective authority.

## Decision-to-authority rules

The native Cedar decision is the oracle for the captured concrete request; the
Python adapter does not reimplement Cedar expression evaluation.

- A reproduced `Allow` may support tool authority only when its complete,
  reviewed mapping identifies the tool and every request operand.
- A reproduced `Deny` constrains authority only for the exact mapped request.
  It cannot establish global absence from a representative corpus.
- A satisfied `forbid` remains distinct from default deny, and determining
  policy IDs remain in provenance.
- Any native error, changed diagnostic, unmapped operand, stale evidence,
  incomplete domain, or unsupported semantic keeps the strongest manifest
  authority and emits a named unresolved finding.
- Policy never adds a tool absent from reviewed manifest/inventory authority.
  It may constrain what is already present or expose policy-versus-agent drift.

Compound reachability consumes policy only after the per-call boundary is
sound. The first useful comparison asks whether a reviewed agent path contains
a call that the captured Cedar enforcement mapping denies, or whether Cedar
permits a call outside reviewed agent intent. Export is later: importing a
decision and compiling reviewed intent back to Cedar are different proofs.

## Acceptance gates

1. **Contract:** pin Cedar, select the official allow/deny control pair, and
   review this trust model before records make its choices expensive.
2. **Capture and private reader:** commit the digest-pinned fixture and raw
   native outputs; add strict, canonical bundle and mapping records that verify
   digests, exact fields, version axes, evidence invariants, and typed errors.
3. **IR and oracle:** project a closed Cedar profile, reproduce native
   validation and both decisions, and reject profile use by manifest analysis.
4. **Operational mapping:** capture one real agent enforcement integration with
   a complete action-to-tool/request mapping and both allow and deny controls.
5. **Effective diff:** compare reviewed authority with reproduced policy,
   produce a counterexample for a widening change, and record a gate review
   before public CLI exposure.

Every gate proves all five existing evidence graphs remain byte-identical when
no policy bundle is supplied. Gate 4, not successful parsing, completes the
Foundation import experiment for the policy-language dimension. Rego begins
only after the Cedar loss model and consumption boundary survive this sequence.

## Explicit non-goals

No Python Cedar parser, native-policy replacement, live policy-store discovery,
credential handling, runtime proxy, inferred action/tool join, exhaustive
symbolic Cedar analyzer, generic expression language, or silent best-effort
translation. A valid bundle is evidence about policy; it is not proof that a
production enforcement point received or evaluated it.
