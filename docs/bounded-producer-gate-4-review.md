# Bounded Producer Gate 4 Review

Status: **review complete; public exposure deferred**. The public-boundary
review was performed against merged commit `11ee72e` on 3 September 2026.
Gates 1 through 3 establish a strict artifact, closed standalone Authority IR
profile, and fail-closed private analysis. They do not yet establish a stable
command or public presentation contract. A subsequent private implementation
now satisfies the presentation-stability prerequisite recorded below without
approving exposure.

Structural validity remains separate from authority. Parsing a producer
boundary proves neither that its source evidence is reviewed nor that its
finite capacity applies to the selected agent deployment and partition.

## Decision summary

| Review | Verdict | Evidence or remaining condition |
|---|---|---|
| Structural validation | Passed privately | Boundary v1 uses exact fields, canonical set-like values, closed enums, safe locators, typed errors, caller-byte digests, and a closed IR profile |
| Trusted bounded search | Passed privately | Maximum two preserves the first two IAM productions and removes the rejected third transition before binding or effect accounting |
| Conservative failure | Passed privately | Missing, duplicate, competing, expired, incomplete, unreviewed, mismatched, lifecycle-ambiguous, and source-unverifiable inputs retain the baseline manifest authority |
| Default compatibility | Passed privately | With no producer records, the existing `analyse(mandate)` result remains byte-identical across the complete suite |
| Accepted clean fixture | Passed synthetically | A complete fixture explicitly labels its producer, partition, reviewer, catalogue, outcomes, and adapter as synthetic; the real IAM migration remains `unreviewed` |
| Presentation stability | Passed privately | `agentmandate.producers/v1` fixes stable finding codes, input identities, applied capacity semantics, complete Authority output, canonical SHA-256, and five canonical state fixtures |
| Composition boundary | **Open** | Producer, condition, and delegation consumers cannot yet share one analysis/result envelope; Authority IR, SARIF, and Mermaid cannot preserve producer uncertainty |
| CLI failure behavior | **Open** | No parser, pairing, complete-output, exit-code, or no-partial-output contract has been implemented for producer inputs |

## Closing verdict

**Do not expose a producer CLI or public Python API yet.** The private
cardinality semantics pass their implementation gate, but the public contract
would otherwise be inferred from internal dataclasses and English messages.
That would make unstable selection, finding, and composition behavior part of
the supported interface without the replay boundary required of other
authority consumers.

The deferral does not reopen Gates 1 through 3. The reader, migration, IR
profile, and private analysis remain useful experimental foundations. The
roadmap should keep finite producer cardinality active and name the two
remaining public exit conditions above rather than describing analysis as
unfinished. Completing a private presentation prerequisite does not make its
module, records, or schema a supported interface.

## Reproduced private semantics

The merged consumer serializes and strictly rereads every supplied boundary,
regenerates and validates its complete closed IR profile, verifies its exact
source bytes, and compares all deployment, producer-revision, output, and
partition fields with caller selections. Eligibility additionally requires:

- an existing mandate tool that produces the same scope with `unbounded: true`;
- complete selected inventory containing that tool;
- complete release classification with no reachable release transition;
- no competing reachable producer of the same output scope;
- exact, accepted evidence with reviewer and unexpired review; and
- a caller-supplied calendar date, never the wall clock.

An eligible maximum of two leaves calls one and two successful. Once two live
bindings exist, the search makes call three unavailable before recording
reachability, an effect call, or a new binding. A separate one-call effect
budget still breaches on the successful second call, proving that the bound
does not erase accepted work. Test-only maxima one and three exercise the two
sides of the transition without becoming evidence claims.

Every failed eligibility condition produces a `ProducerFinding` carrying the
complete boundary-profile support set and leaves the stronger baseline
authority in place. Applied decisions additionally cite the manifest
producer's `produces` and `unbounded` facts. No-boundary analysis uses the
existing search without producer caps.

## Accepted-fixture requirement satisfied synthetically

The canonical IAM migration correctly emits `review: unreviewed`. Digest
identity and deterministic migration prove which bytes were interpreted; they
cannot identify a person accountable for accepting that interpretation or set
its review lifetime. Unit tests promote an in-memory copy solely to exercise
the eligibility rule. That is a test control, not a reviewed artifact suitable
for a public clean-path claim.

The review allowed either:

1. an accountable accepted review of the version-pinned IAM boundary, naming
   reviewer and expiry without adding raw identifiers or credentials; or
2. a clearly synthetic accepted boundary plus its source bytes, while keeping
   the real IAM migration as the public unresolved case.

The second path is now complete in
`tests/fixtures/producer-accepted-synthetic/`. Its manifest, boundary,
selection, catalogue, outcomes, and adapter are committed; every identity is
explicitly synthetic; every source digest is checked; and private analysis
reproduces the accepted maximum-two clean path. The real IAM migration remains
unreviewed. This supplies deterministic public-boundary test input without
turning IAM MCP 1.0.11 into a claim about current 1.0.23 behavior or inventing
an accountable provider review.

## Private presentation contract implemented

`ProducerAnalysis.to_result()` now creates the strict private
`agentmandate.producers/v1` presentation. It includes:

- the explicit evaluation date;
- the input manifest identity and producer-boundary content identities;
- the exact selected deployment and reviewed partition identities;
- applied bounds with tool, output scope, capacity kind, maximum, and replay
  support;
- findings with stable machine-readable codes rather than message text as the
  discriminator;
- the complete effective `Authority`, including depth and truncation; and
- a version/hash boundary or canonical fixtures sufficient to detect semantic
  output drift.

The strict reader checks exact field sets and types, canonical ordering,
closed finding and capacity vocabularies, calendar dates, reviewed non-secret
partition aliases, manifest and boundary digests, complete Authority shape,
and the envelope checksum. The result is presentation only and is never
accepted as an authority input. Canonical fixtures cover clean, bounded,
breached, unresolved, and truncated states. No class is exported from the
package and no command renders or consumes this schema.

Human output should use a separate `BOUNDED`/`UNRESOLVED` section. It must not
rewrite a missing breach as proof of runtime enforcement. A producer finding
must exit 1 after complete output; malformed structure, invalid dates, missing
argument pairs, or unsupported composition must exit 2 with empty stdout.
Legacy reach output must remain byte-identical when no producer inputs are
supplied.

## Proposed CLI shape, not yet approved

The narrowest plausible surface follows the established validate-then-consume
boundary:

```text
mandate producers validate BOUNDARY
mandate reach MANIFEST \
  --producer-boundary BOUNDARY \
  --producer-source LOCATOR=CAPTURE \
  --producer-selection JSON \
  --producer-as-of YYYY-MM-DD
```

`producers validate` would establish structural validity only. Manifest-mode
`reach` would reread and revalidate the profile, verify all named source bytes,
and apply only eligible boundaries. Boundaries and selections should be
repeatable and paired by an explicit identity rather than positional order.
Named locator mappings are preferable because several boundaries may share
the same catalogue or capture adapter. Conflicting bytes for one locator,
missing declared locators, and undeclared locator mappings should be usage
errors.

This syntax is a review sketch, not a compatibility promise. A public Python
export remains a separate decision.

## Composition decision

Public producer inputs must initially be refused in every output or analysis
mode that cannot preserve their uncertainty:

- `reach --ir`: standalone producer and manifest profiles are deliberately
  distinct, and generic IR analysis rejects the producer profile;
- SARIF and Mermaid: their current schemas render breach paths, not applied
  capacity evidence or unresolved producer findings;
- conditional authority: the condition consumer replaces tool effects before
  its own search, while the producer consumer supplies transition caps to a
  separate search; running them independently or in an undocumented order is
  not a combined authority result; and
- delegation analysis: its attenuation/widening envelope cannot currently
  carry producer decisions or unresolved capacity evidence.

These combinations should fail before output, as existing condition and
delegation combinations do. Supporting condition-plus-producer or
delegation-plus-producer later requires one consumer to validate both closed
profiles, perform one search, retain all findings, and define whether either
uncertainty blocks sibling narrowing on the same tool. It must not be achieved
by feeding one rendered result into another analyzer.

## Exit criteria for a later exposure PR

1. **Complete synthetically:** commit an accountable accepted clean fixture or
   an explicitly synthetic accepted fixture with the real IAM record remaining
   unresolved.
2. **Complete privately:** define stable finding codes and a versioned,
   canonical result envelope with clean, bounded, breached, unresolved, and
   truncated fixtures. Public stability begins only if a later release exposes
   it.
3. Implement parser and renderer tests for success, finding, usage, malformed,
   missing-pair, conflicting-source, and no-partial-output behavior.
4. Reject IR, SARIF, Mermaid, condition, and delegation composition before
   reading or rendering partial authority, unless a reviewed joint consumer
   and combined schema exist.
5. Reproduce byte-identical legacy output with no producer options and rerun
   all evidence graphs through the public boundary.
6. Record the release impact: any new command, reach option, or presentation
   schema is a user-visible minor release under `RELEASING.md`.

## Non-goals

This review does not add a manifest field, public Python record, runtime quota
reservation, release/replacement modeling, provider query, policy compiler,
generic quantity language, or a claim of atomic enforcement. Quantity
relations remain on their separate evidence-driven track.
