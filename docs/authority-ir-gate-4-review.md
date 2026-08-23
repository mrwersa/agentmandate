# Authority IR Gate 4 Review

Status: **hold public exposure**. Reviewed against `ed2e19b` on 23 August
2026. Gates 1–3 and reader hardening are complete, but a structurally valid IR
is not yet necessarily safe to analyze or sufficient to export as a result.

## Decision summary

| Review | Verdict | Exit condition |
|---|---|---|
| Unsupported semantics | Blocked | Enforce a closed, trust-aware manifest-v1 analysis profile ([#55](https://github.com/mrwersa/agentmandate/issues/55)) |
| Output stability | Blocked | Define and fixture a versioned result envelope ([#56](https://github.com/mrwersa/agentmandate/issues/56)) |
| CLI failure behavior | Contract ready; implementation blocked | Implement only after #55 and #56 ([#57](https://github.com/mrwersa/agentmandate/issues/57)) |

This is a gate working as intended, not a rejection of the IR design. The
private records preserve manifest semantics and derived provenance. They have
not yet earned the stronger claim that arbitrary valid snapshots can safely
drive authority decisions.

## Unsupported-semantics review

The compatibility contract says contested evidence cannot silently grant
authority. The implementation validates `review` and `confidence` as enums but
does not resolve them before `_to_mandate`. Changing an irreversible tool's
effect evidence from `accepted` to `contested` still produces the same reachable
breach. Public import would therefore contradict the documented trust model.

Facts are also syntactically open. An unknown predicate survives validation and
serialization but is ignored by the manifest projection, so analysis can appear
successful while dropping semantics. Conversely, a known predicate with the
wrong value shape can pass graph validation and raise a raw `TypeError` during
projection. Record-shape safety is not predicate-shape safety.

The first analyzable profile should be deliberately narrow:

- accept only the documented manifest and manifest-default adapter versions;
- enumerate entity kinds, predicates, cardinalities, and value schemas;
- require an explicit evidence-resolution rule for every consumed fact;
- reject contested, unknown, unsupported, or malformed semantics with an
  indexed `IRFormatError`;
- distinguish “valid for archival/transport” from “eligible for analysis.”

MCP, policy, inventory, and runtime sources remain valid future IR inputs, but
must not become trusted policy merely because their records parse.

## Output-stability review

Canonical `AuthorityIR` JSON is byte-stable, and augmented graphs round-trip.
However, the graph is not a complete analysis result. Depth, truncation, the
ordered breach path, and repeated calls live in `_IRAnalysis.authority`.
Different depth arguments can produce byte-identical graphs. A consumer given
only the graph cannot recover which search was run or replay a deduplicated
transition sequence.

Before export, define a separate versioned result envelope containing:

- source graph identity and digest;
- analysis parameters and completeness boundary;
- the existing `Authority` result, including ordered counterexamples;
- the augmented provenance graph;
- an explicit hash/version boundary.

Commit canonical fixtures for clean, truncated, and breached results. Prove
round-trip and byte stability under reordered tables, evidence, and support.
Reject non-finite or otherwise non-canonical fact values before serialization.
`STABILITY.md` must state which envelope changes are additive and which require
a new format or package minor version.

## CLI failure-behavior review

The existing contract is suitable: `0` means clean/success, `1` means a
finding, and `2` means usage or malformed input. IR commands should preserve
it, emit diagnostics to stderr, and leave stdout empty on failure. They must
fully validate before emitting bytes so pipelines never receive partial JSON.

The smallest honest surface is:

```text
mandate ir export MANIFEST
mandate ir validate SNAPSHOT
mandate reach --ir SNAPSHOT
```

`export` writes one canonical source snapshot to stdout. `validate` establishes
format validity, not trust or analyzability. `reach --ir` must be mutually
exclusive with manifest input and must refuse snapshots outside the approved
analysis profile. Avoid a command named `import`: it misleadingly suggests that
any structurally valid evidence has been accepted as authority.

Adding these commands is a public CLI change and therefore a minor release.
Parser/help, stdout/stderr, exit code, future-version, unsupported-profile, and
no-partial-output behavior all need tests before exposure. A public Python API
is a separate decision and is not implied by the CLI.

## Sequencing and non-goals

Implement #55 first, because both analysis safety and CLI error normalization
depend on typed semantics. Implement #56 second, because the CLI must not invent
an output envelope. Implement #57 last, then re-run the four evidence graphs
and migration fixtures before closing the parent initiative.

This review does not expand gate 4 into policy-language imports, runtime
evidence, signatures, arbitrary provenance, or a general execution format.
