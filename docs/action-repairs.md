# Show release repair suggestions in CI

Enable `repair-suggestions` when a failed release should also show checked
repair options. The Action runs the existing [release repair planner](release-remediation.md)
against the same selected manifests and required workflows. It writes proposals;
it never changes source files or applies a candidate.

## Add suggestions to the release gate

Stage the released manifest and select its workflow annotation from the pull
request's base commit:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0
- name: Stage the released manifest
  env:
    BASE_COMMIT: ${{ github.event.pull_request.base.sha }}
  shell: bash
  run: |
    git show "$BASE_COMMIT:mandate.json" > "$RUNNER_TEMP/released.json"
- id: authority
  uses: mrwersa/agentmandate@v0.44.0
  with:
    manifest: mandate.json
    baseline: ${{ runner.temp }}/released.json
    required-workflows: .agentmandate/required-workflows.json
    required-workflows-ref: ${{ github.event.pull_request.base.sha }}
    depth: '8'
    repair-suggestions: 'true'
    repair-keep-tools: |
      select_rows
      export_rows
    repair-ceiling-grids: export_rows=0:2:1
    repair-max-evaluations: '128'
    repair-timeout-seconds: '60'
- uses: actions/upload-artifact@v4
  if: always() && steps.authority.outputs.repair-report != ''
  with:
    name: authority-repair-suggestions
    path: ${{ steps.authority.outputs.repair-report }}
```

Choose the tool names and domains for your manifest. Pin the Action to a
reviewed commit for production. Protect the workflow, input selection and
selected refs; a matching digest does not authenticate a reviewer or establish
which policy is deployed. The Action does not fetch refs, approve a release,
post comments or upload reports itself. The artifact step above is a caller choice.

The [synthetic export example](../examples/release-remediation/README.md)
adds a purge tool and raises an export ceiling without creating a breach at
depth four. The grid above suggests removing purge and restoring a two-record
ceiling while retaining both required exports. The gate still reports widening.

## Set the domain and processing limits

| Input | Default | Meaning |
|---|---|---|
| `repair-suggestions` | `false` | Explicit opt-in; requires `baseline` |
| `repair-keep-tools` | Empty | Newline-separated reachable tools to retain |
| `repair-ceiling-grids` | Empty | Newline-separated `TOOL=MIN:MAX:STEP` domains |
| `repair-discover-ceilings` | Empty | Newline-separated `TOOL=STEP` discovery domains |
| `repair-max-edits` | `2` | Edits per proposal, 1–8 |
| `repair-max-evaluations` | `128` | Combinations or discovery probes, 1–1,024 |
| `repair-max-candidates` | `5` | Displayed proposals, 1–20 |
| `repair-timeout-seconds` | `60` | Repair subprocess wall-time limit, 1–300 |

Numbers use plain positive integer text, with no whitespace or leading zeros.
Grids and discovery cannot combine. To discover a ceiling, replace the grid
input with `repair-discover-ceilings: export_rows=1`. Discovery retains every
tool and cannot fix widening that requires removing an added tool. Without
numeric options, the planner considers removals and approval additions.
Pareto filtering is enabled. Budgets, quantity assignments, identities and
other unsupported dimensions remain fixed.

The Action's `depth` applies to the gate and every repair check. Evaluation
count, frontier completion, display limits and call-depth truncation retain
their [separate meanings](ceiling-discovery.md). The repair timeout covers the
planner subprocess, not ordinary checks. No partial proposal is retained on
timeout. Runner-level time and memory limits remain the caller's responsibility.

## Inputs and execution boundary

Enabled, valid configuration freezes both manifests once before analysis.
Snapshot failures disable suggestions while ordinary checks still run.
Lint, reach, diff, review, repair and later presentation use those selected
bytes. The workflow annotation is read once from its selected Git commit and
shared by diff, review and repair. Working-tree replacement or a later ref move
cannot substitute another annotation. It must pin the released file's bytes.

Reports identify original paths, manifest SHA-256s, the workflow commit and
source digest. These identify chosen bytes, not authors, review quality or live
activation. Source and trace inputs retain their existing checks; this mode
does not snapshot an entire deployment. Isolated Python imports keep a checkout
package named `agentmandate`, or `PYTHONPATH`, from replacing the installed analyzer.

## Read the result without changing the gate

Suggestions appear in the job summary and the combined report's `repairs`
field. `repair-report` points to a separate JSON copy, or is empty when disabled
or when that artifact could not be written. The combined report retains repair
errors even when the separate artifact is unavailable. SARIF keeps ordinary
findings and original manifest paths and lines; proposals are not applied fixes.

| Repair status | Meaning |
|---|---|
| `completed` | Full planner result available, possibly with no candidate |
| `not_needed` | No blocking manifest/release finding; drift or trace failures alone do not trigger repair |
| `configuration_error` | Invalid repair settings; ordinary analysis still runs |
| `skipped` | No usable comparison or workflow selection; no fallback requirements |
| `timeout` | Time limit reached; no partial proposal retained |
| `error` | Snapshot, planner, output-validation or repair-artifact failure |

The summary includes edits, lost capabilities, lint, truncation and search
limits. Released and proposed call-depth truncation stays visible even when
no candidate is found. Long summaries are shortened with a pointer to the full
report. Full JSON retains candidate manifests, their checks and rejected
comparisons. The wrapper checks that input hashes, the baseline comparison and
search bounds match the gate's selection before presenting a planner result.
`trigger_checks` names the blocking lint, reach or diff checks that motivated
the search. Repairs use uniquely created artifact files rather than overwriting
a predictable checkout filename.

Repair status adds no blocking finding or lint note, clears none and does not
change recorded acceptance. A found candidate leaves the original failure
intact. Errors are visible without becoming new gate checks; they cannot turn
a failing gate green. `fail-on: never` retains its existing report-only behavior
and reports `verdict: findings` when checks failed. Named acceptance can waive
matched widening under the existing contract, never a breach or workflow regression.

Select a proposal yourself, save its manifest, and rerun lint, reach, diff and
the supplied paths before review. Model conformance does not establish business
success or deployment approval.
