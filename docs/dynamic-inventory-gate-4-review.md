# Dynamic Inventory Gate 4 Review

Status: **approved for CLI exposure**. The public-boundary review was
reproduced against `137f987` on 23 August 2026. Its tree is byte-identical to
the merged commit `2c42475`. Structural validity remains separate from
eligibility: parsing a declaration does not grant authority or prove that its
membership is complete.

## Decision summary

| Review | Verdict | Evidence |
|---|---|---|
| Structural validation | Passed | AgentKit and Sentry v1 declarations validate; malformed and missing inputs return exit 2 with no stdout |
| Eligible reconciliation | Passed | Exact, accepted, current AgentKit evidence reconciles 20 distinct tools and returns clean |
| Fail-closed behavior | Passed | Expired, mismatched, tampered, partial, and unpaired inputs cannot authorize removal or a clean result |
| Output compatibility | Passed | Existing drift output is unchanged; dynamic text and JSON record the explicit evaluation date |
| Side-effect boundary | Passed | The CLI receives capture bytes and selection explicitly; it does not follow locators, read the clock, import code, or access the network |

## Closing verdict

**All four gates passed.** The real CLI reproduced the complete AgentKit path,
the structural Sentry path, and the full ineligibility matrix. The suite passed
with 766 tests and 100% statement coverage. Ruff and whitespace checks were
clean.

The public surface is deliberately narrow:

```text
mandate inventory validate DECLARATION
mandate drift MANIFEST --source SOURCE \
  --inventory-declaration DECLARATION \
  --inventory-capture CAPTURE \
  --inventory-selection JSON \
  --inventory-as-of YYYY-MM-DD
```

`inventory validate` establishes transport and structural validity only.
`drift` separately requires target and selection agreement, matching captured
bytes, a complete membership claim, exact evidence, accepted review, and a
review that is current at the caller-supplied date. A valid but ineligible
declaration is a finding, not a usage error and never a silent omission.

## Reproduced trust matrix

The complete AgentKit declaration was paired with its pinned capture and a
matching Python binding. With the reviewed provider selection and
`2027-01-01`, drift discovered all 20 distinct tools, reported no findings,
recorded the evaluation date, and exited 0.

Each failed trust condition remained observable:

- an evaluation date after the 2030 review expiry produced an unresolved
  finding and withheld removals;
- tampered capture bytes named the digest mismatch;
- a different selector named the reviewed-context mismatch;
- partial Sentry membership remained unable to establish absence in private
  reconciliation;
- an unpaired declaration was a usage error with empty stdout.

The date is mandatory rather than read from the wall clock. This makes expiry
reproducible and permits a previously clean review to become unresolved only
when the recorded evaluation date crosses its declared expiry.

## Interface decisions

Repeatable declaration and capture options are paired by position. A count
mismatch is rejected before reading artifacts, and two declarations cannot
supply different bytes for the same locator. This is sufficient for v1; any
future grouping syntax must preserve the same explicit association.

Selection is one JSON object rather than repeated `key=value` flags. It
round-trips scalar and list-valued selectors through the declaration's closed
selection vocabulary, allowing equality to be checked mechanically.

`inventory_as_of` is emitted only for dynamic drift. Existing text and JSON
remain unchanged when no inventory options are supplied, so the change is
additive within the new minor series.

## Sentry boundary and non-goals

The Sentry declaration crosses structural validation, and private
reconciliation proves that its eight visible tools are partial. It does not
cross public reconciliation because its target is a JavaScript capture binding
outside the current Python source collector. That limitation does not weaken
the trust gate: the CLI refuses to construct a selected binding from the
declaration it is supposed to verify.

A future non-Python inventory adapter may supply that independent binding
evidence. This initiative does not add one, execute the capture script, query
Sentry, infer hidden dispatch effects, or treat the captured catalogue as
policy. Those remain separate evidence and importer work.

## Release and sequencing

The new command, drift options, and conditional JSON field require a minor
release under `RELEASING.md`. The dynamic-inventory initiative is otherwise
complete. Foundation now has three delivered rows; format import experiments
remain deliberately evidence-gated rather than being folded into this CLI.

