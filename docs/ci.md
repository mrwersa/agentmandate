# Running it in CI

The gate is a handful of commands and a set of flags. This is what to wire
where, and which decisions were deliberate.

## The action

```yaml
- uses: mrwersa/agentmandate@v0.8.0
  with:
    manifest: mandate.yaml
    baseline: mandate-released.yaml   # optional: did this widen authority?
    source: src/agent                 # optional: has the manifest drifted?
```

The counterexample lands in the job summary as a rendered graph rather than a
log line, and `sarif-file` is an output you hand to
`github/codeql-action/upload-sarif` so it annotates the diff.

Uploading is deliberately your step, not the action's: it needs
`security-events: write`, and an action that asks for a token permission it
could avoid is one more reason for a security team to say no.

`fail-on: never` reports without blocking, which is how to turn this on over
an existing repository without stopping everyone on the first day.

Only the checks you give inputs for run. A manifest alone is enough for `lint`
and `reach`.

## Findings where you already look

```yaml
# .github/workflows/agent-authority.yml
- run: mandate reach mandate.yaml --sarif > authority.sarif
  continue-on-error: true          # let the upload happen, then fail the gate
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: authority.sarif
- run: mandate reach mandate.yaml   # the actual gate
```

The breach is then annotated on the pull request that introduced it, rather
than sitting in a log somebody has to open. Findings are `error`, not
`warning`: they already exit non-zero, and a UI that disagrees with the exit
code is how a gate stops being believed.

`--graph` emits Mermaid, which GitHub renders inline in a comment:

```mermaid
flowchart LR
  s0(["search_cases<br/>case#1"])
  s1(["search_cases<br/>case#2"])
  s0 --> s1
  s2["issue_refund<br/>case#1 · 500 GBP"]
  s1 --> s2
  s3["issue_refund<br/>case#2 · 500 GBP"]
  s2 --> s3
  breach["cumulative value 1000 GBP exceeds limit 500 GBP"]
  s3 --> breach
```

One node per **step**, not per tool, because the same tool called twice on
different bindings is usually the whole point. Rounded is a read, boxed
changes something.

## The diff gate, without the action

In a pull request, the useful gate is `diff` against the manifest on the
default branch, so a change that widens authority stops and gets a named
reviewer:

```yaml
- name: Authority diff
  run: |
    git show origin/main:mandate.yaml > /tmp/released.yaml
    mandate diff /tmp/released.yaml mandate.yaml
```

## Pinning the analyzed authority artifact

When separate jobs review and analyze a mandate, pass the canonical snapshot
rather than reparsing an unbound copy:

```yaml
- run: mandate ir export mandate.yaml > authority-ir.json
- run: mandate ir validate authority-ir.json
- run: mandate reach --ir authority-ir.json --json > authority-result.json
```

Reviewed conditional authority stays separate from the manifest. Validate the
artifacts structurally, then supply the reviewed context and its captured bytes
with an explicit evaluation date:

```yaml
- run: mandate conditions validate --condition reviewed-condition.json
- run: mandate conditions validate --context reviewed-context.json
- run: >-
    mandate reach mandate.yaml
    --condition reviewed-condition.json
    --condition-context reviewed-context.json
    --condition-capture reviewed-context.capture
    --condition-as-of 2027-01-01
```

The same four flags apply to `mandate drift`. Repeat condition inputs as
needed; pair every context with one capture in the same argument order. SARIF,
Mermaid, and `reach --ir` composition are intentionally refused until those
formats can carry unresolved condition evidence without implying a clean run.

`ir validate` is a structural transport check and exits 0 even when evidence is
contested or heuristic. `reach --ir` is the trust boundary: unsupported
adapters, predicates, value shapes, or non-exact/non-accepted evidence exit 2
without writing partial JSON. A reachable breach still writes the complete
canonical result and exits 1.

## Exit codes

Every analysis command takes `--json` and exits non-zero on a finding, so they
drop into CI unchanged. `scan` writes a manifest to standard output and is a
one-off, not a gate.

| Exit code | Meaning |
|---|---|
| `0` | Clean |
| `1` | A finding: lint error, reachable breach, widening diff, or a non-conformant replay |
| `2` | Usage or I/O error, malformed manifest/IR, unsupported IR version or analysis profile |
