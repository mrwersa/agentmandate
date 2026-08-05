# GitHub MCP server evidence: the minting chain models, but nothing bounds it

The roadmap's second-graph item is aimed away from money, and this graph has no
money anywhere. `github/github-mcp-server` is GitHub's own MCP server, tools
defined statically in Go, grouped into toolsets and released against versioned
images. This directory is the evidence run that item 1 asked for.

## The graph

- Framework: `github/github-mcp-server`, release **v1.8.0** (tag dated
  2026-07-30).
- Scope: `GITHUB_TOOLSETS="repos,actions"`, recorded in this directory as the
  reviewed inventory boundary. The full toolset is too large to stay
  reviewer-comprehensible, so this is class-scoped the way the AgentKit graph
  was: to what one real deployment wires in. **Every number below is scoped to
  the repos and actions toolsets.**
- Catalogue: `catalogue-repos-actions.json`, captured by running the published
  `ghcr.io/github/github-mcp-server:v1.8.0` image and reading its live
  `tools/list` payload over the MCP stdio protocol. 23 tools. The server's own
  scope model (`pkg/scopes`), which maps tools to OAuth scopes such as `repo`,
  `security_events` and `admin:org`, is the anchor for the read/write/admin
  effect classes the roadmap expected.

## The scan skeleton and what the review corrected

`mandate scan catalogue-repos-actions.json` guesses effects conservatively and
marks every guess with a `REVIEW` line. The reviewer corrections, recorded in
the header note of `mandate.yaml`:

1. **The `requires` guesses were wrong.** The scan treats any `*_id` argument
   as a resource a prior tool produces, so `actions_get`, `actions_list`,
   `actions_run_trigger` and `get_job_logs` picked up `requires: [resource]`,
   `[resource]`, `[run]` and `[job]`. Those are method-dispatch input
   parameters, not scopes any tool mints, so they were removed.
2. **`fork_repository` is not irreversible.** A fork is deleted as easily as
   it is created; corrected to a write.
3. **`push_files` is not irreversible.** One commit adding several files,
   revertible like any commit; corrected to a write.
4. **`create_or_update_file` and `push_files` mint a `workflow` scope.**
   This is the roadmap's predicted minting chain: an agent with `contents:write`
   can commit a workflow file, and that file then executes with a token and
   repository secrets. The manifest expresses it as `produces: workflow`,
   `unbounded: true`.

## What the run found, against the prediction

The roadmap predicted a *partial* success and that is what happened:

```
$ mandate lint docs/evidence/github-mcp-server/mandate.yaml
no single-manifest findings

$ mandate reach docs/evidence/github-mcp-server/mandate.yaml
no reachable breach within depth 8 (search truncated). 23 tool(s) reachable
```

The prediction said reach would find the path but have no way to bound how
many times it may be walked. Verified two ways:

- **The path is found.** `actions_run_trigger` is reachable, and it is only
  reachable because the file writers mint the `workflow` scope it requires.
  The authority walk reports the effects `(write, workflow)` from the minters
  and `(irreversible, workflow)` from the trigger.
- **Nothing bounds the walk.** `max_extractable` is `None`: there is no
  currency, so no total ceiling and no per-scope ceiling has anything to
  attach to. The model finds write-then-trigger and cannot say how many times
  a workflow-with-secrets may run in one session.
- **The counterfactual.** Remove the `produces: workflow` anchors and
  `actions_run_trigger` disappears from the reachable set entirely (22 tools).
  The tool that executes code with repository secrets becomes invisible, which
  is the probe's silence reproduced on a real published graph: the analysis
  either over-expresses the mint or cannot see the trigger at all.

Two checks added while reviewing the run, because the result above is easy to
read as broader than it is.

**The truncation is not load-bearing.** The search reports itself truncated at
depth 8, so the reading "searched everything and found nothing" would be wrong.
Re-running at 12 and 16 gives the same 23 reachable tools and the same zero
breaches, so a deeper walk is not hiding one and the conclusion does not rest
on where the search stopped.

**This graph is not one the tool has nothing to say about.** Drop the two
conservative `requires_approval` flags, which distortion 3 below argues are
themselves an over-call, and the analysis speaks immediately:

```
ERROR   effect.ungated-irreversible actions_run_trigger
ERROR   effect.ungated-irreversible delete_file
```

Two lint errors and two reachable breaches. So the silence is narrow and worth
stating precisely: the approval and irreversibility axis works on this graph,
and the axis that has nothing to attach to is the cumulative one. The model
cannot say "at most three workflow triggers in a run". It can say the trigger
is irreversible and ungated, which is a different and smaller claim than the
one a reader takes from "no reachable breach".

## The distortions

Recorded in full in the end-note of `mandate.yaml`:

1. **The minting chain models, and the walk is unbounded.** The produces/
   requires mechanism handles the chain; the cumulative-value mechanism has
   nothing to attach to. This is roadmap item 6 (non-monetary effect budgets)
   with a real published graph behind it instead of a hypothetical.
   Narrower than it first reads: the approval and irreversibility axis does
   work here, as the dropped-approval check above shows. What is missing is a
   count, not a voice.
2. **The mint is conditional and value-dependent.** Only a path under
   `.github/workflows/` mints an executing workflow, and the path is a free
   argument, so the anchor over-expresses every file write as a mint. The
   mirror of the AgentKit under-expression: there the value tools could not be
   anchored, here the producer over-produces because argument values are not
   readable.
3. **Consolidated tools flatten effect classes.** `actions_run_trigger` carries
   `run_workflow` (a write) beside `cancel_workflow_run` and
   `delete_workflow_run_logs` (irreversible) behind one `method` argument, and
   the manifest cannot split them. The conservative irreversible + approval
   choice hides that running a workflow is ordinary.

## What this changes on the roadmap

Item 6 stays, but it no longer waits on a hypothetical: the unbounded-walk
finding is exactly the distortion it exists to express. The path to that item
remains unchanged in shape. It needs a real graph to justify the schema change;
this is a second real graph, so the candidate can now be investigated with
both it and AgentKit as evidence. Nothing is shipped from this directory.

## Re-run

```sh
mandate lint docs/evidence/github-mcp-server/mandate.yaml
mandate reach docs/evidence/github-mcp-server/mandate.yaml
mandate scan docs/evidence/github-mcp-server/catalogue-repos-actions.json --agent gh-mcp-agent
```
