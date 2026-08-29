# Cedar effective-diff contract

Status: **proposed and experimental**. This is gate 5a of
[#116](https://github.com/mrwersa/agentmandate/issues/116). It defines the
trust boundary before records or analysis make the choices expensive. No
current command consumes managed Cedar evidence or changes reachability from a
policy decision.

## Question and invariants

The effective diff answers two distinct questions:

1. For one reviewed agent and one concrete mapped request, did managed policy
   allow or deny authority that the manifest makes reachable?
2. For the same request and mapping across two managed-policy revisions, did
   enforcement widen, tighten, or remain stable?

These results must not be collapsed. A Deny can make enforcement narrower than
reviewed intent for one request. A Deny-to-Allow revision is policy widening.
Neither result changes the manifest's compound authority, and an Allow never
adds a missing tool. Unknown input retains the strongest manifest result and
produces an unresolved finding.

The native service decision is the oracle. AgentMandate does not parse the
policy condition, infer that `amount < 1000` describes a complete domain, or
reimplement Cedar evaluation.

## Two oracle profiles

The existing `CedarBundle` v1 is a **local-native oracle**: it pins a Cedar
implementation plus policy, schema, entities, request, validation, and native
diagnostics. The AgentCore capture is a **managed-enforcement oracle**: the
Gateway returns a decision while AWS retains parts of the Cedar request and
validation boundary.

They are not interchangeable. A managed record must not invent a Cedar schema,
entity set, determining-policy diagnostic, or `schema_checked: true`. A local
replay must not be labeled proof that AgentCore attached or enforced a policy.
Gate 5 uses a separate versioned managed profile; it does not weaken
`CedarBundle` v1's required sources.

## Managed capture record

The candidate `managed_oracle_version: 1` index is canonical JSON with exact
fields for:

- provider, region, protocol, capture date, capture adapter, and version;
- authorizer type, Gateway and policy-engine state, attachment mode, complete
  tool inventory, complete policy inventory, and policy lifecycle states;
- request and response locators, lowercase SHA-256 digests, outcome
  (`allow` or `deny`), and reason (`managed_allow`, `default_deny`, or
  `explicit_deny` only when the service supplies that distinction);
- the strict Cedar deployment mapping, reviewed mandate, tool schema,
  `tools/list`, sanitized policy, and managed-state locators; and
- sanitization declarations: omitted field classes, whether decision messages
  changed, and which live identifier was replaced by which reviewed binding.

The reader hashes caller-supplied bytes only. It does not resolve locators,
read AWS credentials, call the network, inspect the wall clock, or accept raw
identifiers. Structure and digest validity mean the artifact is transportable;
they do not make it eligible.

## Eligibility at consumption

Every consumer serializes and strictly re-reads the record, verifies all source
bytes, then validates the closed managed profile. It requires:

- `AWS_IAM`, MCP, READY Gateway, ACTIVE engine and policies, and `ENFORCE`;
- exactly the declared complete tool and policy inventories;
- exact action-to-tool, principal-type-to-manifest-principal, and
  resource-type-to-reviewed-binding joins;
- a mapping target whose source bytes and agent equal the mandate being
  analyzed;
- exact, accepted mapping evidence with reviewer and expiry, evaluated against
  a caller-supplied `date`; expiry is inclusive (`as_of <= expires`). This
  extends the [authority IR evidence-state rule](authority-ir.md#evidence-and-review-state)
  with the same date comparison already used by reviewed condition and
  inventory evidence;
- unchanged decision messages and an explicit reviewed alias for every
  redacted operand that participates in the join; and
- one canonical request identity: protocol method, mapped tool, and canonical
  argument object. JSON-RPC transport IDs are evidence locations, not request
  identity.

Missing bytes, stale or contested review, incomplete inventory, `LOG_ONLY`, a
different authorizer, unknown outcome reason, changed decision operand, or
unresolved alias makes the decision ineligible. The tool stays in manifest
analysis at its strongest declared effect and the result names the failing
locator or join. Ineligibility never deletes a tool or becomes Deny.

`request_domain: representative` remains load-bearing. An eligible decision is
valid for its exact canonical request only. Two values do not establish all
values satisfying a condition, even when the sanitized policy text appears to
describe them.

## Effective result

The private result envelope records its own version, `as_of`, manifest semantic
digest, managed-profile semantic digest, mapping digest, source digests, and
ordered findings. Each request result contains:

- canonical request key and mapped agent/tool/principal/binding;
- manifest reachability and shortest enabling path;
- managed outcome and reason;
- alignment: `aligned_allow`, `enforcement_narrows_request`, or `unresolved`;
- policy revision change, when a comparable baseline is supplied:
  `stable_allow`, `stable_deny`, `widens`, `tightens`, or `unresolved`; and
- minimum provenance sufficient to replay every join and native outcome.

An eligible Allow for a reachable mapped tool is `aligned_allow`. An eligible
Deny for that exact request is `enforcement_narrows_request`; it does not prove
the tool unreachable. A manifest-absent or unreachable mapped tool is a mapping
finding even if policy allows it—policy cannot manufacture reviewed authority.

## Revision comparison

Baseline and candidate decisions are comparable only when provider and oracle
profile, authorizer class, protocol, mapping, mandate digest, complete tool
inventory, canonical request key, principal type, resource binding, and
enforcement mode match. Policy inventory and policy digest may differ; that is
the revision under test.

For a comparable request:

| Baseline | Candidate | Classification |
|---|---|---|
| Allow | Allow | `stable_allow` |
| Deny | Deny | `stable_deny` |
| Deny | Allow | `widens` |
| Allow | Deny | `tightens` |

Default deny and explicit deny remain distinct provenance even though both are
the Deny side of this table. If either service response does not support the
claimed distinction, the record cannot upgrade it by reading policy text.
Changed request arguments are different requests, not a policy diff.

The current live fixture proves alignment transport: `amount: 500` is allowed,
and `amount: 2000` is default-denied for that exact call. It does not itself
prove a revision. Gate 5 requires a second sanitized live AgentCore capture in
which the same `amount: 2000` request is allowed under a candidate policy. A
synthetic pair may develop the analyzer but cannot close the gate.

## IR boundary

Managed captures project through a standalone closed profile. Candidate
relations are `maps_to_tool`, `enforces_for`, and the existing
`decides_request`; endpoint kinds, cardinality, merge mode, and minimum source
support must be registered before projection. Derived `widens` or `tightens`
edges cite both decision edges, the exact request facts, comparable mapping
facts, and policy/source identities.

The generic IR reader establishes structure only. The managed profile validator
establishes its closed semantics. `_analyse_ir` continues to reject the profile
at the manifest-v1 boundary; only the explicit effective-diff consumer may
combine it with reviewed authority.

## Delivery gates

1. **5a — contract:** review this document and the managed/local oracle split.
2. **5b — records and migration:** add a strict private managed reader,
   canonical gate-4 fixture, digest verification, profile projection, and
   adversarial reader tests without changing analysis.
3. **5c — private effective diff:** implement eligibility, exact-request
   alignment, revision comparison, provenance, and conservative defaults;
   develop widening with clearly synthetic fixtures.
4. **5d — live widening evidence:** capture the same managed request changing
   from Deny to Allow, preserve sanitized evidence, and prove the private
   widening counterexample.
5. **5e — exposure review:** challenge tampering, expiry, incomplete inventory,
   changed joins, representative-domain overclaim, default-deny attribution,
   profile conflation, output stability, and no-partial-output behavior before
   any CLI or public Python surface.

Every gate proves all six manifest evidence graphs, existing Cedar fixtures,
and legacy CLI output remain byte-identical when no policy evidence is supplied.

Gate 5b is split at its review boundary. The first PR adds the managed reader
and canonical migration record; IR projection and relation registration remain
the second half of 5b. The managed record's closed field sets deliberately
exclude `schema_checked` and `determining_policies`, so local-oracle claims
cannot leak through optional defaults.

## Explicit non-goals

No Cedar parser or evaluator, symbolic condition analysis, global proof from a
representative corpus, inferred mapping, wildcard-as-mapping, managed/local
oracle conflation, credential handling, live discovery in core, runtime proxy,
automatic policy compilation, mutation of manifest authority, or public CLI
before the exposure review.
