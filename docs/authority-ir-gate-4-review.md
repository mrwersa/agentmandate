# Authority IR Gate 4 Review

Status: **approved for CLI exposure**. The initial review was reproduced against
`ed2e19b` on 23 August 2026. The private analysis-profile and result-envelope
work closed the first two findings. A structurally valid IR is still not
automatically trusted; the reviewed CLI contract preserves that boundary.

## Decision summary

| Review | Verdict | Exit condition |
|---|---|---|
| Unsupported semantics | Passed in private implementation | Closed, trust-aware manifest-v1 analysis profile ([#55](https://github.com/mrwersa/agentmandate/issues/55)) |
| Output stability | Passed in private implementation | Versioned, hashed result envelope with canonical fixtures ([#56](https://github.com/mrwersa/agentmandate/issues/56)) |
| CLI failure behavior | Passed | Canonical output, exit codes, stderr, and no-partial-output contract ([#57](https://github.com/mrwersa/agentmandate/issues/57)) |

## Closing verdict

**All four gates passed.** After the CLI merge at `f50a8a0`, the public-boundary
suite reconfirmed canonical export, structural validation, profile-gated IR
analysis, and verified result reading across AgentKit, GitHub MCP, AWS
PostgreSQL, and Sentry. The canonical v1 migration fixture also crossed both
`ir validate` and `reach --ir`. The full suite passed with 676 tests and 100%
statement coverage.
This closes the parent initiative without widening it into public Python
records, arbitrary evidence trust, or a general execution format. The public
artifact and CLI contracts ship in 0.10.0 under `STABILITY.md`.

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

The private analyzable profile is deliberately narrow:

- accept only the documented manifest and manifest-default adapter versions;
- enumerate entity kinds, predicates, cardinalities, and value schemas;
- require an explicit evidence-resolution rule for every consumed fact;
- reject contested, unknown, unsupported, or malformed semantics with an
  indexed `IRFormatError`;
- distinguish “valid for archival/transport” from “eligible for analysis.”

The profile implements these conditions without narrowing the general reader.
It uses a closed predicate registry with per-predicate value schemas, requires
every consumed evidence reference to be `exact` and `accepted`, verifies the
supported adapter versions and semantic digests, and rejects malformed or
unsupported semantics with `IRFormatError` before projection. Adversarial tests
preserve all three reproduced failures as rejection cases. Passing this review
alone did not complete the result-envelope or CLI gates.

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

The private v1 envelope now supplies that boundary. Its hash covers the result
version, source-graph identity, effective depth and truncation, existing
Authority output, and augmented graph. Its reader recovers the source graph and
re-runs analysis rather than trusting a self-consistent checksum. Canonical
clean, truncated, and breached fixtures round-trip byte-for-byte, preserve
ordered repeated calls, and remain stable under reordered source tables,
evidence, and support. Non-finite JSON and mismatched parameters, authority, or
graphs fail with `IRFormatError`. Passing this review alone still left the CLI
gate open.

## CLI failure-behavior review

The existing contract is suitable: `0` means clean/success, `1` means a
finding, and `2` means usage or malformed input. IR commands should preserve
it, emit diagnostics to stderr, and leave stdout empty on failure. They must
fully validate before emitting bytes so pipelines never receive partial JSON.

The implemented surface is:

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

Adding these commands is a public CLI change and therefore requires a minor release.
Parser/help, stdout/stderr, exit code, future-version, unsupported-profile, and
no-partial-output behavior all need tests before exposure. A public Python API
is a separate decision and is not implied by the CLI.

## Sequencing and non-goals

The #55 → #56 → #57 sequence is complete. Public-boundary tests re-run all four
evidence graphs and the canonical migration fixture through the CLI before
closing the parent initiative.

This review does not expand gate 4 into policy-language imports, runtime
evidence, signatures, arbitrary provenance, or a general execution format.
