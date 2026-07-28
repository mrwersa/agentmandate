# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.3.1 - 2026-07-28

### Changed

- The README opens with the compound-authority problem in plain language and
  separates per-call policy, reviewed decision evidence, and runtime-control
  evidence without weakening their boundaries.

## 0.3.0 - 2026-07-28

### Added

- `mandate obligations` derives reviewable test obligations from the authority
  a manifest actually makes reachable: irreversible effects, approval gates,
  service-account principals, and value-bearing calls. A tool nobody can reach
  produces no obligation, because listing it would pad a review with work that
  protects nothing.
- `--reviewed` accepts an obligations file whose decisions have been mapped by
  a human, and `--suite` renders those into an `agentverity.decision-suite/v1`
  skeleton that AgentVerity loads directly.
- `docs/test-obligations.md` walks the whole path, including what deliberately
  does not cross it.

- `README` and `DESIGN` name Policy in Amazon Bedrock AgentCore alongside the
  other enforcement tools, and say precisely where it stops: the engine
  evaluates all applicable Cedar policies for one invocation, while its
  documented analysis is policy-level. Neither models a sequence of permitted
  calls or a release-to-release comparison of reachable authority.

### Fixed

- `--reviewed` reconciles against the live manifest by stable identifier
  instead of replacing it. A stale or unrelated review previously generated a
  suite for authority the agent no longer had, which is the drift this package
  exists to catch.
- A generated suite carries probes the reviewer wrote. It previously shipped
  `REVIEW:` placeholder inputs that AgentVerity accepted and ran, producing
  numbers about nothing. An obligation now needs both a decision and at least
  one probe before it counts as reviewed.
- A malformed reviewed file produces a usage error rather than a traceback.

### Notes

- Decisions are never invented. An effect class such as `irreversible on case`
  is an authority fact; a decision such as `refund_approved` is an application
  label somebody chose. No parsing turns one into the other, so the command
  exits non-zero until every row carries a reviewed decision.
- Compound breaches do not cross the bridge. A cumulative-value path is a
  multi-call sequence, which is scenario testing rather than decision coverage.

## 0.2.0 - 2026-07-28

### Added

- Tests for every control the fail-closed work introduced. The diff rules for
  effect-class changes, `unbounded` flips, produced-scope changes, ceiling
  add and remove, extractable-value appearance and disappearance, and a
  declared workload identity all shipped without one, and an untested
  widening rule is a gate that might not be there.

### Changed

- The coverage floor is 100%, up from 90%. The package was at 100% and drifted
  to 97% in a single change without CI noticing, and the lines that slipped
  were the new controls rather than incidental code.

### Fixed

- `verify` now rejects malformed trace fields and reports missing principal,
  scope, value, or currency evidence instead of silently treating an
  incomplete record as conformant. Empty traces no longer pass vacuously.
- `diff` now compares run limits and reachable tool contracts, including
  preconditions, approvals, effects, ceilings, produced scopes, and unbounded
  minting. Cross-currency amounts are sent for review rather than compared as
  bare numerals.
- `diff` now searches both releases at one depth, blocks reductions to the
  manifest's default search depth, rejects comparisons between different
  agents, and reports workload-identity or value-argument changes.
- `scan` now quotes catalogue-derived YAML scalars, flattens untrusted
  descriptions to comments, and rejects duplicate or control-character tool
  names.
- Manifest parsing now rejects non-finite amounts, string-valued booleans,
  empty scope names, and Boolean search depths, and wraps JSON or YAML parser
  failures as `ManifestError`.

### Documentation

- The README now opens on the worked payment-dispute path and includes a
  diagram showing how a read-only case search makes two valid refunds
  reachable.
- `ROADMAP.md` separates adoption work from planned extensions to the
  authority model.

## 0.1.0 - 2026-07-28

First release.

### Added

- `mandate reach`, a bounded breadth-first search over the authority graph that
  reports a legal call sequence breaching a declared limit, as a counterexample
  rather than a score.
- `mandate diff`, a comparison of the effective authority of two manifests,
  classified widening, narrowing, or neutral, exiting non-zero on widening.
- `mandate lint`, single-manifest control checks covering separation of duties,
  ungated irreversible effects, service-account principals, ceilings scoped to
  something the tool does not require, and mixed currencies.
- `mandate verify`, replay of recorded tool calls against the manifest,
  reporting undeclared tools, exceeded ceilings, missing approvals, wrong
  principals, and run totals.
- A manifest schema carrying the three facts an ordinary tool schema omits:
  effect class, the value-bearing argument, and the scope a ceiling is measured
  against.
- Worked examples for a payment-dispute agent, including the release pair where
  adding one read-only tool takes extractable value from 500 to 2000 GBP.
- `--json` on every analysis command, and exit codes suitable for a CI gate.
- `mandate scan`, which derives a manifest skeleton from an MCP `tools/list`
  catalogue. Effects are guessed from the tool name and default to
  `irreversible`, and every guess carries a `REVIEW` marker, because a tool
  schema cannot supply reversibility, the value argument, or the scope a
  ceiling is measured against.
- A second breach class in `reach`: an irreversible effect reachable with no
  approval is now reported with the call sequence that reaches it, rather than
  only as a name in the authority summary.
- `mandate diff --record`, a markdown change record for a change advisory
  board, with the authority section derived rather than asserted.
- A `currency_mismatch` violation in `verify`, so a call spending one currency
  against a ceiling declared in another is reported rather than silently summed.
- Status badges, an exit-code table, and the pull-request workflow snippet for
  gating on an authority diff against the default branch.
