# Recheck repairs against fixed delegation grants

Use this mode when a reviewed tool mapping must fit an existing delegated grant.
It uses the [current delegation contract](delegation-v2.md), keeps the chain and
captured evidence unchanged, and checks proposed manifest edits against it.
The ordinary Authority report still includes every declared reachable tool;
delegation does not prune a tool or lower its effect to hide a breach.

## Run the worked example

```bash
mandate remediate examples/delegated-remediation/manifest.json \
  --delegation-attachment examples/delegated-remediation/select_rows-attachment.json \
  --delegation-attachment examples/delegated-remediation/export_rows-attachment.json \
  --delegation-attachment examples/delegated-remediation/purge_rows-attachment.json \
  --delegation-chain examples/delegated-remediation/chain.json \
  --delegation-capture examples/delegated-remediation/capture.json=examples/delegated-remediation/capture.json \
  --delegation-as-of 2026-10-17T12:00:00Z \
  --delegation-target-source src/export_service.py \
  --delegation-target-binding export_agent \
  --required-workflows examples/delegated-remediation/required-export.json \
  --keep-tool select_rows --keep-tool export_rows \
  --ceiling-grid export_rows=0:2:1 --pareto
```

The synthetic chain permits reads and writes. The declared purge tool is
irreversible, so it exceeds that surface even though approval is required.
Exports separately reach six records against a four-record run budget. The
returned candidate removes purge and lowers the export ceiling from three to
two records, preserving both required exports within depth four. The original
grant and quantity findings remain visible, so the command exits 1.

All six delegation flags have the same meaning as in `reach`. Repeat attachments,
chains and locator/capture mappings as needed. The timestamp and source binding
are explicit; the command does not follow locators, fetch grants or read a clock.
Conditions and delegations cannot be combined, even in discovery mode.

## Separate tool excess from a defective chain

Only the shared reader's **tool-versus-referenced-hop** excess is a repairable
manifest finding. `repairable_tool_findings` identifies those findings without
matching diagnostic prose. Removing that tool is a possible proposal; changing
approval or a numeric ceiling does not change its granted tool/scope/effect set.

An upstream hop regaining authority is a chain defect. Partial actor history,
unknown or incomparable surfaces, expired evidence, invalid validity windows,
wrong bindings and failed source verification also prevent recommendations.
These return `input_requires_review` before any edit is examined. Deleting a
disputed tool cannot bypass this gate. An unexpected change to that eligibility
during rechecking aborts analysis with exit 2 and no partial result.

Each surviving candidate must have no delegation findings, conform to every
required workflow and have no reachable breach within the selected depth.
Structural screening still refuses removal of a producer that another retained
tool needs. Required paths and `--keep-tool` can rule out removing an excessive
tool; the result then offers no repair rather than enlarging its grant.

The grants cover scopes, tool names and effects, not numeric quantity budgets.
All original manifest budgets and surviving tool effects remain fixed. A result
does not authenticate an issuer or reviewer, prove live enforcement, or establish
delegation for tools with no supplied attachment.

## Read and reproduce a result

The existing remediation result gains `delegations` at the baseline and each
candidate. It retains all findings, attenuation decisions, selected source
binding, canonical artifact hashes and exact capture hashes. Canonical hashes
identify normalized record JSON, not original whitespace or authenticated authors.
`delegation_rejections` lists refused edits; its search counter counts screens,
not completed reachability analyses.

Removing a tool marks only its baseline-checked attachments inactive. Their IDs
appear in `inactive_attachments`, and all original input identities remain in
the report. To reproduce a candidate's grant check, supply the original chains
and captures with only attachments whose target tools remain. Keep the baseline
report to show why the others became inactive. Do not silently omit an unresolved
attachment from an initial review.

Explicit ceilings, grids, removals, approval edits and Pareto ranking all support
this mode. Discovery retains every tool, so a fixed grant excess makes its
ceiling/approval domain infeasible. The report says so explicitly; finer steps
cannot repair that grant excess. A rejected upper corner can cover its whole box
because these edits leave grant membership, required scopes and effects unchanged.
Depth, evaluation and display bounds retain their separate meanings.

Exit 0 means the baseline has no blocking lint, authority or delegation finding.
Exit 1 retains those findings even when a repair is found. Exit 2 means malformed,
unsupported or unreadable inputs, including condition/delegation composition.
Proposals remain unapplied and require human selection; no grant authoring or
runtime authorization service is supplied.
