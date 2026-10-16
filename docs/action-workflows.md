# Preserve required work in the GitHub Action

Use the Action when a release must both stay within reviewed authority and keep
declared workflows possible. The same required-workflow input used by `diff`,
`review` and `remediate` is checked against both manifests. A narrowing release
that breaks a required path still fails.

## Select the released annotation

For a pull-request job, stage the baseline from its base commit and read the
annotation from that same commit:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
- name: Stage the released manifest
  env:
    BASE_COMMIT: ${{ github.event.pull_request.base.sha }}
  shell: bash
  run: |
    test -n "$BASE_COMMIT"
    git show "$BASE_COMMIT:mandate.json" > "$RUNNER_TEMP/released.json"
- id: authority
  uses: mrwersa/agentmandate@v0.40.0
  with:
    manifest: mandate.json
    baseline: ${{ runner.temp }}/released.json
    required-workflows: .agentmandate/required-workflows.json
    required-workflows-ref: ${{ github.event.pull_request.base.sha }}
    depth: '8'
```

The annotation must already pin the exact staged manifest bytes. A separately
protected ref can supply it instead, provided its manifest digest matches the
selected baseline. Refs must be available locally; the Action does not fetch them.
Pin the Action release to a reviewed commit for your production integration.

Both workflow inputs and `baseline` are required together. `required-workflows`
is a canonical relative Git path, not a path to a working-tree file. The reader
accepts regular Git blobs, refuses symlinks, directories and submodules, and
disables Git replacement objects. It resolves the ref once and keeps one
temporary snapshot for both diff and review. Editing, deleting or replacing
the candidate's copy cannot change that snapshot.

The workflow and selected refs must be protected by the caller. A commit digest
identifies content; it does not authenticate who approved that content or enforce
GitHub branch rules. Keep the gate's code and input selection outside the
candidate's control. These checks establish model conformance, not business
success or deployment approval.

## Read the result

The combined JSON report retains the diff's result, exit, widening count and
workflow-regression count. `workflow_selection` identifies the selected ref,
commit, Git path and exact source SHA-256. The diff's workflow metadata also pins
the baseline manifest. The job summary shows these pins and each path's outcome,
including the first failing step.

An otherwise narrowing release with one regressed workflow has a nonzero
`findings` output and a `findings` verdict. SARIF keeps the reachability results
and adds `workflow.regressed` results with the failing step and input metadata.
Invalid workflow inputs produce `workflow.invalid` instead. SARIF is not a
complete representation of every check: use the combined report and verdict
for named review, drift and trace-conformance results.
When no workflow findings are appended, the reachability SARIF bytes are preserved.

Missing configuration or an unreadable ref/file retains an ordinary authority
comparison, when a baseline is available, beside a workflow-input failure.
If review was configured, its check reports `skipped: true` with exit 2 and the
selection failure as its reason; no fallback annotation is evaluated.
Malformed, mismatched or baseline-infeasible annotations retain the CLI's exit-2
diagnostic in the diff check. The Action itself reports a failed step with
`findings`; its step exit convention remains success/failure, distinct from
each CLI check's 0/1/2 result.
Every failed CLI check contributes at least one finding, including usage errors
that return no analysis findings.

`fail-on: never` deliberately lets the step succeed while retaining its findings
verdict, counts, summary and SARIF. It does not convert the analysis to clean.

## Combine with named review

Add the existing [protected-ref review inputs](ci.md#review-decisions-from-a-protected-git-ref)
to the same Action step. Diff and review use the same annotation snapshot. A
review record must match the comparison including that annotation's exact bytes;
adding the workflow check invalidates a record pinned without it. Even a matching
acceptance cannot waive a workflow regression, reachable breach or other check.

## Run the examples

The [example guide](../examples/action-workflows/README.md) explains the bounded
release cases. Repository tests run the actual CLI subprocesses. The Action's
own CI jobs exercise a preserved release, a narrowing regression, an attempted
working-tree annotation substitution and report-only mode through the composite
Action. The fixture jobs select `HEAD` solely for these committed synthetic
examples; production input selection should use your reviewed baseline or
protected material ref.
