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
- Exit codes are part of the contract: `0` clean, `1` finding, `2` usage or a
  malformed manifest. CI depends on these, so they will not move in a patch.
- `--json` output is additive within a minor series. Fields may be added;
  existing fields will not change meaning.

Production users should pin the current minor series:

```text
agentmandate~=0.9.0
```

## Experimental authority artifacts

The private Authority IR and analysis-result envelope are not public package or
CLI contracts yet. Their explicit versions establish the rules to apply before
exposure:

- `ir_version` changes when graph records, relations, or canonicalization
  change incompatibly.
- Source adapter versions change when projection logic changes; that may alter
  semantic and result digests without changing either JSON format.
- `result_version` changes when a hashed envelope field is added, removed,
  renamed, reinterpreted, or canonicalized differently. The strict reader does
  not treat additional fields as silently additive.

Future presentation metadata may be additive only if it is explicitly outside
the canonical envelope. Once the CLI exposes these artifacts, adding support
for a new format version or changing command behavior also requires a package
minor release and migration notes. These standalone artifact rules are stricter
than the additive guarantee for existing `--json` command output.

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
