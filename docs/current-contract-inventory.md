# Check the current contract inventory

From a checkout, run:

```bash
python scripts/audit_contracts.py
```

Exit 0 means the current declarations and pinned fixture bytes match the
committed inventory. Exit 1 lists changed locations. Exit 2 means the inventory
or a material could not be read. This repository check supplies no deployment
approval or evidence acceptance.

The [inventory](../tests/fixtures/current-contract-inventory.json) records root
Python exports and signatures, public class members, CLI paths and arguments,
version markers and fixture hashes. The
[coverage map](../tests/fixtures/contract-coverage.json) connects each artifact
family to its guide, boundary tests and executable fixtures. Semantic tests
remain necessary: a matching signature or digest cannot establish correct behavior.

Condition-aware remediation adds the existing four condition flags to
`mandate remediate`. The current remediation result gains condition decisions,
canonical artifact identities, capture digests and unconditional reports when
those inputs are supplied. The same result schema and condition readers serve
all repair modes; no compatibility branch or new acceptance format is added.
The [repair example](../examples/conditional-remediation/README.md) and exact
grid/discovery/expiry results are pinned with their replay tests.

Delegation-aware remediation adds the existing six delegation options to the
same command. Its shared reader distinguishes repairable tool excess from
chain/trust defects, and result reports retain input identities and rejected
edits. The worked example and complete CLI output hashes are pinned; semantic
assertions and full-domain comparisons live in `tests/test_delegated_remediation.py`.

Release-aware remediation adds `--released` to the same command. Its optional
`release` records preserve ordinary comparisons and workflow regressions;
the input record pins both manifest files. Workflow annotations pin the released
reference. Current examples and complete-output replays are covered by
`tests/test_release_remediation.py`, including full edit-domain frontier checks.
The remediation and required-workflow schemas, root exports and earlier pinned
material bytes remain unchanged.


## Breaking alpha changes

The named-quantity release replaces the money-only model. The current surface
uses `Quantity`, manifest version 2, named `limits.quantities`, Authority
`max_quantities` and one remediation result schema. Unsupported old schemas
fail closed. There are no compatibility aliases, old remediation presentation
branches or historical inventory-replay chains in the active suite.

A deliberate breaking change needs a minor release, a clear changelog entry,
current-contract fixtures and tests for the unsupported boundary. Old releases
remain recoverable in Git and published artifacts; retaining their runtime
readers is not required before 1.0. See [stability](../STABILITY.md).

To inspect a proposed inventory without overwriting it:

```bash
python scripts/audit_contracts.py --candidate /tmp/contract-candidate.json
git diff --no-index tests/fixtures/current-contract-inventory.json /tmp/contract-candidate.json
```

Review the changed surfaces and semantic tests before replacing the baseline.
Updating a snapshot solely to clear CI defeats the check.

## Historical evidence

Original captures, raw scanner proposals, acceptance records and signed bindings
retain their original bytes under `docs/evidence/` and the dated evidence notes.
They describe historical contracts and may use unsupported manifest versions.
Do not edit them to make current lint or analysis pass.

Current graph tests use explicitly identified manifest-v2 projections under
`tests/fixtures/quantity-evidence/`. These are model annotations, not new captures
or a transfer of historical acceptance. Synthetic evidence remains labelled as
synthetic. The external security review and accountable evidence decisions stay
separate from this inventory check.

The release comparison inventory includes `--required-workflows` on `mandate diff` and
`mandate review`, the `Delta.required_workflows`, `required_workflows_metadata`
and `workflow_regressions` public members, and release-side required-path rechecks.
Metadata binds the exact workflow annotation bytes into the comparison digest.
Fixtures from the preceding release, root exports and earlier command arguments
are unchanged. The workflow input format and remediation surface are unchanged;
omitting the flag keeps the previous diff/review output bytes and exit codes.

The Action integration also pins `action.yml`, its wrapper script and live CI
matrix, plus two current candidate manifests. The coverage map links them to
the [Action guide](action-workflows.md) and executable wrapper tests. Root Python
exports and CLI command paths are unchanged by this integration.

The Action repair integration adds eight opt-in/configuration inputs and one
`repair-report` output, plus an advisory `repairs` field in the combined JSON.
It updates the three already-pinned Action materials (`action.yml`, its body
script and its executable workflow). Their changed digests are deliberate
contract changes, not frozen evidence edits. The planner's schema, root exports,
CLI paths and other pinned material bytes remain unchanged. See the
[Action repair guide](action-repairs.md) and `tests/test_action_repairs.py`.

The install/output correction changes only `action.yml` and the wrapper's pinned
bytes, plus the coverage map linking `tests/test_action_delivery.py`. It keeps
all root exports, CLI paths and 240 other material digests unchanged. Successful
report content is unchanged; delivery errors return 2 without changing the
analysis verdict or counts, and failed report paths are empty.

Release-scoped remediation combines existing flags and input contracts without
adding a CLI path, root export or schema version. The current coverage map adds
four synthetic released-manifest/workflow files and six CLI replay cases, reusing
the unchanged condition and delegation materials. Existing 242 material pins
remain unchanged. New scoped release records retain the unconditional gate
beside reviewed proposal analysis; ordinary unscoped output is unchanged.
