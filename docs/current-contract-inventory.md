# Check compatibility before changing a contract

From a checkout, run:

```bash
python scripts/audit_contracts.py
```

The check compares the current package with the committed inventory. Exit 0
means the recorded surfaces and fixture bytes match; exit 1 lists changed
locations; exit 2 means the inventory or its files could not be read. This is
repository maintenance tooling, not a mandate-analysis command or a deployment
approval.

This inventory was prepared against `0c43066`, the merged `0.22.0` contract
baseline, on 10 October 2026. It supplements the
[historical 0.17.0 audit](pre-1.0-consolidation-audit.md), whose bytes and
decision remain unchanged. **The maintainer supplied an out-of-band execution
review of #230 on 10 October 2026.** This is not a GitHub approval.
It does not supply the [external security review](external-security-review.md).

## What is pinned

The [machine inventory](../tests/fixtures/current-contract-inventory.json)
records all 51 root Python exports, callable signatures, declared public class
methods/properties and constant values. It also records all 29 CLI command paths
(including intermediate groups), arguments, defaults, choices and mutually
exclusive groups. The package release number is
excluded from comparison; `__version__` remains an exported name.

The inventory also records version constants, literal presentation schemas,
version-field names and inline integer version checks from the runtime source.
These markers detect additions and version changes. They do not describe every
field or prove that a validator implements its contract. Existing semantic,
malformed-input, expiry and trust tests remain necessary.

The [coverage index](../tests/fixtures/contract-coverage.json) links each family
to its contract guide, existing fixtures and executable tests. Its contents and
the referenced fixture bytes are pinned by digest. Initial result fixtures are
baselines, not migrations from earlier versions. Historical converters preserve
the source-to-canonical link and remain separate from runtime readers.

| Family | Contract and replay checks |
|---|---|
| Manifest, defaults and Authority IR adapters | [Manifest](manifest.md), [IR](authority-ir.md); `test_manifest.py`, `test_ir_compatibility.py`, `test_ir_profile.py` |
| Authority IR results | [IR](authority-ir.md); `test_ir_result.py` |
| Inventory and protocol imports | [Dynamic inventory](dynamic-inventory.md), [catalogue imports](catalogue-import.md); `test_dynamic_inventory.py`, `test_catalogue_import.py` |
| Conditions and delegation | [Conditions](conditions-delegation.md), [delegation](delegation-v2.md); `test_conditions.py`, `test_delegation.py` |
| Managed Cedar and mapping | [Cedar](cedar-import.md); `test_managed_cedar.py`, `test_cedar.py` |
| Producer bounds | [Producer contract](bounded-producers.md); `test_producer.py` |
| Continuity profiles and results | [Continuity](authority-continuity.md); `test_continuity.py` |
| Principal observations and accounting | [Observations](principal-continuity.md), [accounting](principal-accounting.md); `test_principal_continuity.py`, `test_principal_accounting.py` |
| Revision and scalar cutover | [Revision review](revision-review.md), [handover](scalar-handover.md); `test_revision_review.py`, `test_scalar_handover.py` |
| Obligations, scenarios and decision suites | [Obligations](test-obligations.md), [evaluation](evaluation-loop.md); `test_obligations.py`, `test_scenarios.py` |
| Trace verification and SARIF | [Traces](traces.md), [CI](ci.md); `test_verify.py`, `test_otel.py`, `test_findings.py` |
| Historical readers, projections and acceptance | [Historical audit](pre-1.0-consolidation-audit.md), [acceptance](continuation-evidence-acceptance.md); converter, replay and acceptance tests named in the coverage index |

The new [legacy output baseline](../tests/fixtures/legacy-json-results.json)
pins twelve complete CLI runs: lint, clean/breached reach, widening diff, source
drift, recorded/OTel verification, obligations, reviewed/refused decision-suite
export, scenarios and malformed input. Each case records exact stdout, stderr,
exit status and input digests. Some outputs have a schema marker and others
predate versioned envelopes; both are public contracts. These runs supplement
the existing attachment and IR result fixtures. They are a fixed regression
corpus, not exhaustive coverage of every command combination.

The fixture's JSON root is an array of twelve case objects, each with `name`,
`argv`, `exit`, `stdout`, `stderr` and `inputs`; inspect `argv` for the exact
command rather than looking for top-level command keys.

## Review a change

When the check reports a difference, first decide whether it is an intentional
contract change, a regression, or an internal change to a recorded declaration.
Apply [the stability rules](../STABILITY.md) and add affected before/after
fixtures where a format changes. A changed digest identifies different bytes;
it does not decide whether those bytes are compatible.

To inspect a proposed replacement without modifying the baseline:

```bash
python scripts/audit_contracts.py --candidate /tmp/contract-candidate.json
git diff --no-index tests/fixtures/current-contract-inventory.json /tmp/contract-candidate.json
```

The tool refuses to write a candidate over either inventory file. Review the
coverage index and candidate together before deliberately replacing a baseline
in a PR. Updating a snapshot solely to clear CI would defeat the check. The
existing semantic replay tests must still pass.

## Preserve raw scanner evidence

The four committed raw scanner skeletons retain their original bytes and
expected missing-producer findings:

| Raw skeleton | Tool findings | Missing scope names |
|---|---:|---|
| AWS IAM access keys | 2 | `access_key`, `version` |
| AWS Postgres MCP | 1 | `job` |
| Initiative MCP | 22 | `guild`, `calendar` |
| Sentry MCP | 3 | `resource`, `projectslugor`, `issue` |

That is 28 tool-level findings across eight names in four raw files. The seven
reviewed `mandate.yaml` files have no missing-producer findings. The regression
test pins these diagnostics and the inventory pins the file bytes; it does not
claim that all other lint findings are absent or that each missing requirement
is independently established to be an extractor defect. This is a diagnostic
count over preserved proposals, not a scanner-precision estimate.

Follow the [evidence preservation rule](../CONTRIBUTING.md#contributing-a-real-authority-graph):
review the separate mandate, and exclude raw skeletons from any future
corpus-wide clean-manifest gate. Do not repair historical proposals to clear CI.

No runtime schema, Python export, command, result enum or package version is
changed by this inventory. Its replay tests do not accept evidence, renew an
expiry, establish a deployment mapping, or complete external security review.
