# Release repairs with reviewed proposal evidence

These are synthetic model examples, not deployment evidence or accepted historical
captures. The released files and workflow annotations are local reference
fixtures. Conditions, grants and captures are reused unchanged from the existing
worked examples. Digest equality identifies selected bytes, not their authors.

Run from the repository root.

## Reviewed conditional effects

```bash
mandate remediate examples/conditional-remediation/manifest.json \
  --released examples/release-scoped-remediation/condition-released.json \
  --condition examples/conditional-remediation/condition.json \
  --condition-context examples/conditional-remediation/context.json \
  --condition-capture examples/conditional-remediation/capture.sql \
  --condition-as-of 2026-10-16 \
  --required-workflows examples/release-scoped-remediation/condition-required.json \
  --keep-tool run_query --keep-tool export_rows \
  --ceiling-grid export_rows=0:2:1 --pareto
```

The proposal's reviewed query domain permits a read effect. The candidate still
declares `run_query` as irreversible and lowers the export ceiling from three to
two records. It removes declared widening and the scoped quantity breach while
preserving two approved one-record exports against one binding. The ordinary
comparison and its breaches remain visible: `gate_passed` is true **within the
reviewed proposal scope**, while `unconditional_gate_passed` is false.

The three-call workflow also conforms to the unconditioned reference. The older
four-call conditional workflow would exceed that reference's irreversible-call
budget and is deliberately not reused. Proposal evidence cannot validate the
released side on its behalf.

Replace `--ceiling-grid export_rows=0:2:1 --pareto` with
`--discover-ceiling export_rows=1` to search the same integer lattice including
the unchanged ceiling. A returned proposal does not change the original exit 1.

## Fixed delegation grants

```bash
mandate remediate examples/delegated-remediation/manifest.json \
  --released examples/release-scoped-remediation/delegation-released.json \
  --delegation-attachment examples/delegated-remediation/select_rows-attachment.json \
  --delegation-attachment examples/delegated-remediation/export_rows-attachment.json \
  --delegation-attachment examples/delegated-remediation/purge_rows-attachment.json \
  --delegation-chain examples/delegated-remediation/chain.json \
  --delegation-capture examples/delegated-remediation/capture.json=examples/delegated-remediation/capture.json \
  --delegation-as-of 2026-10-17T12:00:00Z \
  --delegation-target-source src/export_service.py \
  --delegation-target-binding export_agent \
  --required-workflows examples/release-scoped-remediation/delegation-required.json \
  --keep-tool select_rows --keep-tool export_rows \
  --ceiling-grid export_rows=0:2:1 --pareto
```

The candidate removes purge, which exceeds the fixed grant, and restores the
two-record export ceiling. Its ordinary comparison is neutral and both required
two-record exports remain conformant. No grant is enlarged or rewritten. The
original release, grant and quantity findings still exit 1.

Discovery retains every tool, so it cannot repair the purge excess and reports
no feasible candidate within that domain. Smaller numerical steps do not solve
a grant membership problem.

The [release guide](../../docs/release-remediation.md#use-reviewed-proposal-evidence)
defines the scope and refusal boundaries. Neither example applies evidence to
the released reference, authorizes deployment, combines conditions with grants,
or changes the GitHub Action's inputs.
