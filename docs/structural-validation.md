# Validate an artifact before reviewing its evidence

Use a structural validator to check that a captured or authored artifact can be
read. It checks fields, types, versions and the format's structural invariants.
A valid artifact can still carry unreviewed, expired or insufficient evidence.
Consume it through the relevant analysis command to evaluate those boundaries.

Every validator supports JSON output:

```bash
mandate ir validate tests/fixtures/authority-ir-v1.json --json
```

```json
{
  "artifact": "authority-ir",
  "schema": "agentmandate.validation/v1",
  "scope": "structure only; evidence trust and deployment approval are not assessed",
  "status": "valid",
  "version": 1
}
```

The version is the artifact's input version, separate from the result schema.
`status: valid` means structural validation succeeded. The scope travels with
the result so consumers cannot mistake it for accepted authority or a release
approval. Omitting `--json` retains the existing one-line human output.

| Command | Input |
|---|---|
| `mandate ir validate FILE` | Authority IR snapshot |
| `mandate inventory validate FILE` | Dynamic inventory declaration |
| `mandate conditions validate --condition FILE` | Tool condition |
| `mandate conditions validate --context FILE` | Condition context |
| `mandate delegations validate --attachment FILE` | Delegation attachment |
| `mandate delegations validate --chain FILE` | Delegation chain |
| `mandate producers validate FILE` | Producer boundary |
| `mandate continuity validate FILE` | One supported continuity artifact |
| `mandate cedar validate FILE` | Managed Cedar oracle |

Append `--json` to any row. Each command exits 0 on valid structure or 2 for
malformed, unsupported, unreadable or excessively nested input. Failed validation
writes an error to stderr and no partial JSON. Structural validators do not
produce analysis findings or use exit 1.

Authority IR requires finite JSON fact values. `NaN`, `Infinity`, overflowing
numbers such as `1e999`, and non-serializable programmatic values are refused.
Programmatic fact values must also survive a JSON round trip unchanged: mappings
with non-string keys and tuples that would become lists are rejected during both
validation and serialization. This is a transport rule;
finite values still need the input profile and evidence checks before analysis.

The [JSON baselines](../tests/fixtures/structural-validation-v1.json) replay
both condition/delegation variants and all seven command groups. Existing
human-output tests and earlier result fixtures remain unchanged. These are
initial v1 results, not migrations from an earlier validation-result schema.

See [Authority IR](authority-ir.md), [the CI contract](ci.md) and
[the documentation map](README.md) for the next consumption step.
