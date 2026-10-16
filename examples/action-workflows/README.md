# Required workflows in the Action

Use the baseline and annotation from `../release-workflows/`:

- `preserved.json` lowers the export ceiling to 250 records. At depth four the
  maximum is 500, equal to its original budget, and the required 100-record
  export remains possible. The Action passes.
- `../release-workflows/breaking.json` lowers the ceiling to 75. Its bounded
  authority is below the budget, but the required export fails at step two.
  The Action fails with one workflow regression.
- `widened.json` retains the 250-record ceiling and adds a read-only tool. The
  workflow conforms, but the widening needs a separately recorded review.

The baseline's own bounded breach remains visible in the authority comparison;
the Action runs `reach` against the candidate. All these inputs are synthetic.

The [Action guide](../../docs/action-workflows.md) shows how to load the annotation
from a pinned baseline commit, combine it with named review, and read the job
summary, combined JSON and SARIF. The repository's Action matrix executes the
preserved/regressed cases, working-tree substitution and report-only mode.
