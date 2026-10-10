# External security and trace-retention review

Status: **commissioning deferred at the maintainer's request on 10 October
2026; reviewer and review date unassigned**. This is a
brief for the remaining external-review gate, not evidence that the gate has
passed. Maintainer and agent implementation reviews do not replace it.

When commissioning resumes, nominate an independent reviewer with experience in
authorization tooling and untrusted evidence parsing, agree a pinned commit
and scope, and record the completed review. No review has been commissioned
or performed by preparing this document.

## Scope to agree

Review the boundaries that could cause a user to trust an unsupported result:

| Boundary | Question | Starting points |
|---|---|---|
| Untrusted local input | Can a catalogue, schema, name, description, path, or attachment inject output, invoke code, read an unintended file, or cause misleading partial output? | [Catalogue import](catalogue-import.md), [source inventory](inventory.md), CLI and strict artifact readers |
| Observations versus intent | Can unreviewed, heuristic, expired, incomplete, or tampered evidence narrow authority or clear an unresolved gate? | [Authority IR](authority-ir.md), [dynamic inventory](dynamic-inventory.md), attachment eligibility tests |
| Manifest and search | Do defaults, scopes, principals, approvals, numeric bounds, shortest paths, and truncation communicate the actual model? | [Design](../DESIGN.md), [search bounds](search-performance.md), [manifest](manifest.md) |
| Repair candidates | Can a suggestion erase baseline findings, silently drop unsupported inputs, or imply global safety from a capped search? | [Repair guide](remediation.md), result and exhaustive-edit tests |
| State and identity | Can attestations suppress independent authority findings, conflate principals/sessions/mandates, or imply live freshness and safe continuation? | [Continuity](authority-continuity.md), [principal accounting](principal-accounting.md), [scalar handover](scalar-handover.md) |
| Trace and report retention | Which identifiers and amounts can inputs, diagnostics, SARIF, JSON, and CI summaries expose, and does guidance cover their handling? | [Security policy](../SECURITY.md), [trace guide](traces.md), [CI guide](ci.md) |
| Packaging and integrations | Do bare installation, optional YAML, static source scanning, wheel contents, and the GitHub Action preserve these boundaries? | [Releasing](../RELEASING.md), `.github/workflows`, package and no-dependency CI jobs |

The library performs offline declared-model analysis. Operational enforcement,
live provider authentication, distributed fencing, signature verification,
and correctness of human acceptance decisions are not implemented guarantees.
The reviewer should assess whether code and documentation make those limits
clear, rather than certifying services outside this repository.

## Review record

Before review, record the reviewer identity/independence, agreed scope and
exclusions, and full commit SHA. Give the reviewer a clean checkout and
reproduction commands from [AGENTS.md](../AGENTS.md). Include the pinned
inventory/IR compatibility fixtures and the search measurement sources.

Record findings with severity, affected boundary, reproduction, and disposition.
Fix blocking findings through normal PRs and ask the reviewer to confirm the
fixes against their actual final commits. If scope changes or public surfaces
change afterward, state which portions need further review.

The closing record must say what was reviewed, what remains unreviewed, and
whether the reviewer considers the agreed gate satisfied. Passing tests and
100% coverage support reproducibility; they do not constitute an external
security assessment. Use [private vulnerability reporting](../SECURITY.md#reporting-vulnerabilities)
for any unpatched issue rather than publishing sensitive reproduction details.
