# Conditional Authority Gate 4 Review

Status: **approved for CLI exposure**. The public-boundary review was
reproduced against `4b819f4` on 23 August 2026. Its tree is byte-identical to
the merged commit `be486eb`:

```text
$ git rev-parse '4b819f4^{tree}' 'be486eb^{tree}'
8c973f73ac97b0ec36d5a050640f3bd885883738
8c973f73ac97b0ec36d5a050640f3bd885883738
```

Structural validity remains separate from authority. Parsing a condition or
context does not make it eligible to narrow analysis.

## Decision summary

| Review | Verdict | Evidence |
|---|---|---|
| Structural validation | Passed | Valid condition/context artifacts exit 0; malformed or missing artifacts exit 2 with empty stdout |
| Trusted reachability | Passed | A complete, exact, accepted, current, digest-verified singleton context narrows `run_query` from irreversible to read |
| Source reconciliation | Passed | Drift additionally requires matching source, binding, and positive tool membership; multi-agent ambiguity names `--binding` |
| Conservative failure | Passed | Representative, mixed, expired, tampered, missing, mismatched, and conflicting inputs retain the strongest manifest effect and exit 1 |
| Output stability | Passed | Namespaced reach and drift JSON fixtures reproduce byte-for-byte; legacy output has no conditional fields |
| Unsupported formats | Passed | SARIF, Mermaid, and Authority IR composition fail before output rather than dropping condition uncertainty |

## Closing verdict

**All four conditional-authority gates passed.** The real CLI reproduced
structural validation, eligible narrowing, default-effect restoration, source
reconciliation, complete-output finding exits, and no-partial-output usage
failures. The suite passed with 933 tests and 100% statement coverage. Ruff
and whitespace checks were clean.

The public surface is deliberately explicit:

```text
mandate conditions validate --condition CONDITION
mandate conditions validate --context CONTEXT
mandate reach MANIFEST \
  --condition CONDITION \
  --condition-context CONTEXT \
  --condition-capture CAPTURE \
  --condition-as-of YYYY-MM-DD
```

The same reviewed inputs apply to `drift`, which also receives `--source` and
one selected binding. Contexts and captures pair by argument order. A count
mismatch, malformed artifact, missing capture, or non-canonical date is a
usage error. The CLI reads supplied bytes and dates only; it does not follow
artifact locators, classify runtime arguments, or read the wall clock.

## Trust and failure matrix

The eligible fixture is intentionally synthetic. It declares that the entire
admissible PostgreSQL argument domain is the `select-only` class and proves
the analysis rule without claiming that a real deployment enforces that
restriction. Under this reviewed context, `run_query` becomes read and its
ungated irreversible finding disappears.

Every weaker claim remains observable and conservative:

- a representative capture proves examples, not the admissible domain;
- a complete context containing several classes cannot globally select one;
- expired or non-exact/non-accepted review cannot narrow;
- missing or digest-mismatched capture bytes cannot narrow;
- source, binding, operand, tool, or context mismatch cannot narrow;
- one failed condition blocks sibling conditions on the same tool;
- a source union with no attributable binding directs the user to `--binding`.

Sentry's hidden dispatch catalogue still has no sufficient complete context,
so the public surface does not manufacture a clean result for it. AgentKit,
GitHub MCP, AWS PostgreSQL, and Sentry retain their legacy results when no
conditional inputs are supplied.

## Output and verdict contract

Conditional human output has a separate `APPLIED`/`UNRESOLVED` section rather
than relabelling trust failures as source drift. JSON adds `conditions` only
when inputs were supplied. The object identifies
`agentmandate.conditions/v1`, records the explicit date, separates applied
decisions from findings, and carries replay support.

Conditional drift keeps `source_drift_clean` as the source-only verdict and
uses top-level `clean` for the combined result. Thus a clean source inventory
plus an unresolved condition exits 1 and serializes `clean: false` without
claiming that source drift occurred. Reach likewise exits 1 for either a
breach or unresolved condition after emitting the complete requested output.

SARIF and Mermaid currently represent breach paths, not skipped condition
evidence. Authority IR v1 cannot compose standalone condition profiles with a
manifest snapshot. These combinations return exit 2 with empty stdout; partial
rendering would be a false claim of condition-aware analysis.

## Release and non-goals

The new command, reach/drift options, conditional presentation schema, and
additive Authority IR relations require a minor release under `RELEASING.md`.
The implementation is ready for the 0.12.0 release train after this review
record merges.

This initiative does not add a general expression language, runtime SQL or
dispatch classification, per-branch approvals, multi-condition composition,
public Python records, delegation analysis, or condition-aware SARIF/Mermaid.
Delegation remains separately blocked on a genuine OAuth, MCP, or A2A chain
capture.
