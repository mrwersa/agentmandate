# Security and data handling

## Reporting vulnerabilities

Please report a suspected vulnerability privately through
[GitHub's security advisory form](https://github.com/mrwersa/agentmandate/security/advisories/new).
Do not open a public issue for an unpatched vulnerability.

## What a manifest contains

A mandate manifest describes an agent's authority: tool names, effect classes,
scope names, value ceilings, and the identity a call runs as. Taken together
that is a map of where the money and the irreversible actions are, which is
useful to an attacker who has other access. Treat a manifest as you would an
IAM policy document rather than as ordinary configuration.

Manifests should not contain credentials, endpoint secrets, or real account
identifiers. Scope names are types, not instances: use `case`, never
`case-4471`.

## What the tool reports

Findings echo tool names, scope names, and amounts from the manifest, and a
`reach` counterexample spells out a working sequence of calls that breaches a
limit. That output is a description of a real weakness in a real system. Store
CI logs and JSON reports under the same controls as vulnerability scan results.

`verify` reads recorded tool calls. Those records may carry real scope
identifiers and real amounts from production runs, so the input file deserves
the same handling as the traces it came from. Nothing from the trace is written
back into a report except the tool name, the line number, and the violation.

## What this tool is not

AgentMandate is static analysis over a declaration. It does not enforce
anything at runtime, and a clean report is evidence about the manifest, not
proof about the deployed system. `verify` exists precisely because the two
drift apart. An unchanged manifest does not mean unchanged authority when the
tool implementation, a connector, or a downstream IAM role changed underneath
it.
