# API stability and the path to 1.0

AgentMandate is alpha because the authority model has not been pointed at
enough real tool graphs to know where it is too coarse. The label is a scope
statement, not a waiver for silent breakage.

## Guarantees before 1.0

- Patch releases preserve the public Python API and command-line contracts.
- Breaking Python or CLI changes require a new minor release and migration
  notes in `CHANGELOG.md`.
- The manifest carries an explicit `version`. A build rejects a schema version
  it does not understand rather than guessing.
- Exit codes are part of the contract: `0` clean, `1` finding, `2` usage, I/O,
  malformed manifest/IR, or unsupported IR semantics. CI depends on these, so
  they will not move in a patch.
- `--json` output is additive within a minor series. Fields may be added;
  existing fields will not change meaning.

Production users should pin the current minor series:

```text
agentmandate~=0.12.0
```

## Versioned authority artifacts

The `mandate ir`, `mandate inventory`, `mandate conditions`, and
`mandate reach --ir` CLI surfaces are public. The Python records remain private
and are not exported from `agentmandate`. Their explicit artifact versions
separate compatibility from package releases:

- `ir_version` changes when graph records, relations, or canonicalization
  change incompatibly.
- Source adapter versions change when projection logic changes; that may alter
  semantic and result digests without changing either JSON format.
- `result_version` changes when a hashed envelope field is added, removed,
  renamed, reinterpreted, or canonicalized differently. The strict reader does
  not treat additional fields as silently additive.
- `condition_version` and `context_version` change when their strict artifact
  records change incompatibly. Conditional command output uses the independent
  `agentmandate.conditions/v1` presentation schema.

Future presentation metadata may be additive only if it is explicitly outside
the canonical envelope. Adding support for a new format version or changing
command behavior requires a package minor release and migration notes. These
standalone artifact rules are stricter than the additive guarantee for existing
`--json` command output.

`mandate ir validate` guarantees structural validity only. Eligibility for
analysis is a separate, stricter check performed by `mandate reach --ir`; this
distinction will not be weakened in a patch release.

The same boundary applies to `mandate inventory validate`: it proves only that
a declaration is structurally valid. `mandate drift` separately checks its
target, reviewed selection, supplied capture digest, completeness, confidence,
review, and expiry against an explicit evaluation date.

`mandate conditions validate` likewise proves structure only. Manifest-mode
`reach` and `drift` separately check profile semantics, reviewed context,
capture digest, explicit evaluation date, and—during drift—the selected live
source binding. Conditional JSON is additive and appears only when conditional
inputs were supplied; legacy output remains unchanged.

## What is most likely to change

The manifest schema. Three areas are known to be under-modelled:

- **Data-flow labels.** Detecting that a read tool feeds an exfiltration path
  needs taint labels the manifest does not carry today.
- **Conditional authority.** Real controls depend on case state, time of day,
  and cumulative history. The current model has ceilings and scopes and nothing
  else.
- **Multi-agent delegation.** One agent handing authority to another is common
  and is not represented at all.

Adding any of these will change the schema, and the `version` field is how that
will be handled.
