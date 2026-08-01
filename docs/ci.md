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

## Exit codes

Every analysis command takes `--json` and exits non-zero on a finding, so they
drop into CI unchanged. `scan` writes a manifest to standard output and is a
one-off, not a gate.

| Exit code | Meaning |
|---|---|
| `0` | Clean |
| `1` | A finding: lint error, reachable breach, widening diff, or a non-conformant replay |
| `2` | Usage error or a malformed manifest |
