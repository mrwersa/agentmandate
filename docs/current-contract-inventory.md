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
