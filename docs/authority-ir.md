# Authority IR compatibility contract

Status: **proposed and experimental**. This document defines the contract to
test before an Authority IR becomes a public format. It does not change
manifest schema version 1 or the guarantees in `STABILITY.md`.

## Why a separate IR

A mandate is reviewed intent. An MCP catalogue, source scan, policy document,
and runtime observation are evidence. Combining them directly in `Mandate`
would erase which claims a reviewer accepted and which a tool merely observed.
The Authority IR is the boundary between those inputs and reachability. It must
preserve disagreements and unknowns instead of choosing a convenient value.

The IR is an analysis interchange format, not an agent execution protocol. It
does not carry prompts, model configuration, tool implementations, credentials,
or request payloads.

## Candidate record model

An IR snapshot contains four deterministic tables:

- **Sources** identify an input by kind, locator, format version, producer
  version, and digest. A missing producer version is recorded as unknown, not
  an empty string. Locators should be repository-relative or stable URIs;
  machine-specific absolute paths are presentation metadata, not identity.
- **Entities** name agents, tools, scopes, principals, roles, and constraints.
  IDs are snapshot-local and derived from kind plus the declared name. They do
  not claim global identity.
- **Facts** assign a typed predicate and value to an entity. Every fact carries
  one or more evidence references, each naming a source and a JSON Pointer or
  equivalent source location.
- **Edges** connect entities with a closed relation such as `requires`,
  `produces`, `acts_as`, `role_contains`, or `ceiling_on`. An input edge cites
  facts; a derived edge cites the complete set of input fact or edge IDs that
  supports it.

Each evidence reference has independent `confidence` and `review` fields:

| Field | Values | Meaning |
|---|---|---|
| `confidence` | `exact`, `heuristic`, `unknown` | How directly the source establishes the claim |
| `review` | `unreviewed`, `accepted`, `contested` | What a human review has concluded |

`accepted` does not upgrade a heuristic observation to exact, and `exact` does
not make an observation approved policy. A contested claim remains visible but
cannot silently grant authority. Resolution is explicit: reviewed intent uses
accepted facts; inventory comparison also considers unreviewed observations;
conflicting single-valued facts stop analysis instead of selecting one.

For example, a reviewed manifest effect would become a fact shaped like:

```json
{
  "id": "fact:tool:issue_refund:effect",
  "subject": "tool:issue_refund",
  "predicate": "effect",
  "value": "irreversible",
  "evidence": [{
    "source": "source:mandate",
    "location": "/tools/1/effect",
    "confidence": "exact",
    "review": "accepted"
  }]
}
```

IDs are readable here for review. The serializer must escape names and reject
collisions rather than silently suffixing them.

## Unknowns and conflicts

Missing, false, and unknown are different states. Importers must emit an
explicit unknown observation when the source claims a concept but its meaning
cannot be represented. They must not invent `caller`, `read`, zero, or an empty
set. Defaults required by manifest version 1 are facts supported by the
manifest-version source, so their origin remains visible.

Multiple active facts for a single-valued predicate are a conflict. Analysis
fails closed until one is accepted or a conservative rule is explicitly
defined for that predicate. Unsupported source material is retained as a
digest-bound observation, not copied wholesale into the core IR.

Edges are positive, multi-valued assertions and combine by union with their
provenance. Omitting an edge is not evidence that the relation is absent. A
source may separately declare that a named relation is complete for a named
subject; only then may omission produce a negative observation. An accepted
positive edge and an accepted complete-source negative observation conflict
and stop analysis. Unreviewed or heuristic evidence may widen an inventory
view, but it cannot cancel an accepted edge. The relation registry must declare
cardinality and these merge semantics before reachability consumes a new
relation.

The private v1 registry separates source and derived relations. Manifest source
relations are `acts_as`, `ceiling_on`, `produces`, `requires`, and
`role_contains`. `contains_tool` belongs to the dynamic-inventory profile.
The experimental condition/principal profiles add `has_condition`,
`uses_context`, `narrows_to`, `constrained_by`, and `under_grant`; none can make
a graph eligible for manifest-v1 analysis. Derived relations are closed and
purpose-specific:

| Relation | Endpoints | Required support |
|---|---|---|
| `can_reach` | agent → tool | Declared tool membership and source records for its shortest enabling path |
| `has_effect` | tool → scope | The reachability edge, effect fact, and matching requirement or production edge |
| `transitions_to` | tool → tool | Reachability of both tools and the next tool's requirements |
| `has_breach` | agent → breach | The first reachability edge, each distinct counterexample transition, and the violated limit or approval facts |

Snapshot validation checks canonical IDs, endpoint kinds, relation-specific
support, and an acyclic support chain rooted in source records. It also
requires every relationship-valued source fact to have its edge, so deleting
an edge cannot silently narrow analysis.

## Compatibility and serialization

The IR has its own integer `ir_version`, independent of manifest versions and
package releases. Canonical JSON uses UTF-8, sorted object keys, stable table
ordering, decimal strings for monetary values, and no generated timestamp in
the hashed body. A separate envelope may record creation time and signatures.

A source distinguishes `content_sha256`, calculated over captured source bytes,
from `semantic_sha256`, calculated over the canonical facts produced from it.
The latter is always available; the former is omitted when a caller supplies
an already-parsed `Mandate`. The adapter never labels a normalized projection
as the original artifact. Supplying source bytes adds the content digest; it
does not recover syntax that parsing already discarded.

For a parsed `Mandate`, schema-default evidence means that the normalized value
equals the manifest v1 default. It does not claim the source key was omitted:
an explicit `principal: caller` and an omitted `principal` therefore both cite
the semantic projection and the manifest-version default. A future raw-syntax
importer may additionally record explicitness and a raw source location, but
must not rewrite this semantic fact. Default-definition locations point to the
manifest-version source, never to a raw key that may not exist.
Every semantic digest records the adapter identifier and adapter version that
produced the projection. Projection changes require a new adapter version even
when `ir_version` is unchanged, so consumers can distinguish changed source
semantics from changed importer logic.

The first adapter must satisfy semantic round-trip compatibility:

```text
Mandate v1 -> Authority IR v1 -> Mandate v1
```

The result must compare equal for agent, identity, tools, roles, and limits and
must produce identical `analyse(...).as_dict()` output. YAML comments, key
order, shorthand spellings, and whether a default was omitted are not semantic
and need not round-trip. Any captured content digest and source locations remain
in the IR even when the manifest is re-rendered.

Every supported `ir_version` needs a committed migration fixture. A reader
rejects a newer version; it never guesses. Until a second version exists, the
migration test is a canonical v1 fixture that must remain readable.

The private reader exposes one `IRFormatError` boundary. It checks JSON syntax,
root and table shapes, exact record fields, scalar types, evidence enums,
relation names, and duplicate IDs before returning a snapshot. Errors identify
the table, record index, and field but never repeat the rejected value.

## Analyzable manifest profile

Structural validity is deliberately weaker than eligibility for analysis. A
valid snapshot may preserve contested evidence, unknown predicates, or future
entity kinds for archival and transport. The private manifest-v1 analysis
profile accepts only snapshots produced by the exact supported manifest and
schema-default adapters, with their semantic digests intact.

The profile has a closed registry of predicates and value schemas for agents,
constraints, principals, roles, scopes, and tools. It requires the complete
manifest-v1 predicate set, one agent, the `run` constraint, and exact agreement
between declared and referenced entity sets. Money, effects, principals,
references, limits, and tool ceiling fields are type- and relationship-checked
before projection.

Every consumed fact must cite the reviewed manifest source, and every evidence
reference on that fact must be both `exact` and `accepted`. This conservative
first resolution rule means contested, unreviewed, heuristic, unknown, or
unsupported evidence remains serializable but cannot grant authority. Profile
failure raises `IRFormatError`; it never falls through to manifest construction
or the reachability kernel. Future source types need their own explicit profile
and resolution rules rather than becoming trusted through successful parsing.

## Derived authority provenance

A reachability result must be explainable without citing the implementation.
A reachable-tool edge names the facts that enabled the tool. An effect edge
also cites the tool's effect and scope facts. A breach cites every transition
edge in its shortest counterexample plus the limit it violates. Search depth
and truncation are analysis parameters in the result envelope, not source
facts.

The private IR entry point validates the snapshot, projects its exact v1 facts
into the existing search kernel, and returns the unchanged `Authority` beside
an augmented IR graph. The graph does not absorb depth or truncation as facts.
Repeated calls remain explicit in the counterexample path; their canonical
transition edges are deduplicated. Reconstructing call order therefore requires
the result envelope's counterexample path; the graph alone records which
transitions occurred, not their order or repetition count.

Provenance records support an explanation; they are not a proof that a source
was truthful. Artifact signatures and evidence bundles are later roadmap work.

## Versioned analysis result

The private result envelope is distinct from both a source snapshot and its
augmented graph. It contains:

- `result_version`, which selects the envelope contract;
- `source_graph`, naming the source `ir_version` and SHA-256 identity;
- `analysis`, recording the effective search depth and whether that boundary
  truncated exploration;
- `authority`, preserving the existing ordered breach paths, including
  repeated calls;
- `graph`, carrying the validated source and derived provenance records; and
- `result_sha256`, binding the complete canonical result body.

`result_sha256` hashes the compact, key-sorted ASCII JSON object containing
every field above except `result_sha256` itself, with no trailing newline. The
source-graph digest separately hashes canonical `AuthorityIR.to_json()` bytes,
including that format's trailing newline. Neither body contains a timestamp.
The reader recovers the source-only graph, checks both digests, re-runs the
bounded analysis, and requires exact agreement with the authority output,
truncation flag, and augmented graph. A checksum that an importer can recompute
is therefore an identity and corruption boundary, not a substitute for
semantic validation or a signature.

The three version axes are independent. `ir_version` governs graph records and
relations. Adapter versions in source records govern projection semantics and
therefore may change source and result digests without changing either format.
`result_version` governs envelope fields, their meaning, and canonicalization.
The private v1 reader is strict: adding, removing, or reinterpreting a hashed
field requires a result-version change.

## Delivery and acceptance gates

Implementation is deliberately split so review can stop a bad format early:

1. Add private typed records, canonical JSON, and a lossless manifest adapter.
2. Validate exact round-trips on every example and all four real evidence
   graphs; commit one canonical v1 migration fixture. A separate compatibility
   fixture must exercise every manifest v1 shorthand and every omitted default,
   including omitted version, identity, limits, principal, and boolean fields,
   plus string forms of `requires` and role membership.
3. Move reachability to the IR and make every derived edge cite its support.
4. Expose canonical export and reviewed IR input through the CLI only after
   unsupported semantics and output stability have been reviewed.

Gates 1 through 3 are implemented. The committed v1 fixture covers
every manifest shorthand and omitted-default path, and tests preserve both
`Mandate` equality and reachability output across all repository examples and
the four real evidence graphs. Retained paths are replayed against the same
enabling semantics before provenance is derived, and each derived relation has
a registry-enforced support shape.

Gate 4 reader hardening, the manifest-v1 analysis profile, and the
versioned result envelope are complete. Committed canonical result fixtures
cover clean, truncated, and breached analysis, while adversarial fixtures cover
trust, predicate, value-shape, adapter, digest, parameter, graph, and
non-canonical-value failures. The reviewed CLI exposes canonical export,
structural validation, and IR-backed reachability without exporting a public
Python API.

That review is recorded in
[`authority-ir-gate-4-review.md`](authority-ir-gate-4-review.md). It records why
exposure was held and the conditions the implemented CLI now meets.

All four gates now pass. Artifact compatibility follows `STABILITY.md`;
policy-language imports, runtime evidence, signatures, global identifiers, and
arbitrary provenance graphs remain explicit non-goals for this first
initiative.
