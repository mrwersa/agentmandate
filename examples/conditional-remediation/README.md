# Conditional repair example

Follow the [repair guide](../../docs/remediation.md#recheck-repairs-within-reviewed-conditional-effects)
for the complete command and result interpretation.

All review annotations here are synthetic. `condition.json` and `context.json`
attest a complete select-only domain for `run_query`; `capture.sql` supplies the
pinned bytes, not independent proof of that domain's completeness. Nothing in
this example is deployment approval.

The manifest declares the query tool irreversible and allows three records per
exported binding against a four-record run budget. `required-export.json` asks
for two independent two-record exports. Discovery proposes a two-record ceiling
within depth four while preserving both tools and both exports. It leaves the
manifest's declared query effect intact and retains unconditional findings.
The command exits 1 because the scoped baseline breaches its quantity budget.
