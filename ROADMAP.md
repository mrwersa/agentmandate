# Roadmap

AgentMandate's centre stays narrow: derive what an agent may do from its tool
graph, then show how that authority changes between releases. Integrations are
useful when they feed that analysis. They are not a reason to become another
runtime proxy or general agent-security scanner.

This is direction, not a release promise.

## Where it is now

As of 0.8.0 the loop closes without leaving the package. A
[worked example](https://github.com/mrwersa/agent-release-gate) runs seven
offline checks against one payment-dispute agent, including source inventory,
compound reachability, release diff, test obligations, and runtime trace
conformance.

| | command | what it establishes |
|---|---|---|
| **obtain** | `scan --source`, `scan` | a manifest skeleton from agent source or an MCP catalogue, every guess marked |
| **check** | `lint`, `reach` | single-tool rules, and whether permitted calls compose into a breach |
| **compare** | `diff` | whether this release widened reachable authority, with a record for named review |
| **stay honest** | `drift` | whether the manifest still describes the implementation |
| **hand off** | `obligations`, `scenarios` | reviewable test obligations, an AgentVerity decision suite, and neutral scenario skeletons |
| **confirm** | `verify --otel` | whether the run that happened stayed inside the mandate |
| **report** | `reach --sarif`, `--graph` | the finding as a code-scanning annotation, or a diagram GitHub renders |

Each one fails closed. Missing control evidence, an unenumerable tool list, an
unreviewed decision, and a currency that cannot be compared all produce a
finding rather than a pass.

The adoption set the roadmap opened is complete: traces in 0.5.0, inventory
in 0.6.0, drift and developer-native findings in 0.7.0, and a GitHub Action
in 0.8.0. These overlap with mature CI and security tooling deliberately. The
new value remains the authority graph and its counterexamples; the packaging
is only there so the counterexamples reach a reviewer.

## The first real graph asked for a more precise model

The first real graph landed in `docs/evidence/agentkit/`: Coinbase AgentKit,
`coinbase-agentkit@v0.7.4` against `v0.1.6`, on the Strands example chatbot.
The tool sets are enumerated from source, class-scoped to exactly the seven
providers the example instantiates (`cdp_api`, `erc20`, `pyth`, `wallet`,
`weth`, `wow`, `compound`). Both manifests, the invented ceilings (500 per
call, 700 per session), and the breach they permit are committed there so the
finding can be re-run.

The release-to-release diff is a widening beside a narrowing: six actions
gained, three lost. The gained ones that matter are ERC-20 authority tools.
The gain that matters is `approve`. It grants an ERC-20 allowance, so a third
party can spend the wallet's tokens later without the agent calling anything
again. That is authority which outlives the run, arriving in a minor bump and
invisible in a config diff. The diff also reports `effect: gained write on
allowance` and `effect: gained read on allowance`: a new scope with new effect
classes, an authority-shape change rather than an inventory change, which a
config diff structurally cannot show.
The other gains (`get_allowance`, `get_erc20_token_address`, `unwrap_eth`,
and the two pyth renames) and the losses (`address_reputation`, the two pyth
names) are routine. A one-way widening story would have missed the narrowing.

**What it asked for:** bounded producers. The manifest can only mark a
producer `unbounded: true` or leave it at nothing, and the real graph makes
both wrong. Compound `borrow` is bounded by the collateral ratio and `wrap_eth`
is 1:1 with the ETH balance, so marking either unbounded makes `reach` report
paths nobody can take. A gate that cries wolf gets switched off, so this
over-expression direction is the expensive failure and it comes first.
The value tools show the mirror problem: `transfer`, `native_transfer`,
`buy_token`, and `sell_token` take the asset as a free argument and no tool
produces an `asset` scope, so a ceiling has nothing to attach to and the
anchor has to be invented.

**What it also asked for:** gross versus net. Buy then sell of the same token
nets to roughly zero but counts the full 1000 USD against the session total,
and the manifest gives no way to declare which the reader is seeing. Gross is
a defensible choice for a wash-trading scenario, but it should be declarable.

**What it asked us not to do:** import the agent to close the dynamic-tool-list
gap. The example binds its tools through `get_strands_tools(agentkit)`, so
`drift` cannot enumerate the list statically. The no-imports design is
deliberate: the command must run in review on a branch whose dependencies are
not installed. The safer direction is an explicit, reviewed inventory for a
dynamic binding, not executing application code during analysis.

The evidence is itself an example of that gap: the first draft of these
manifests included tools from providers the example never wires in, and
`drift` could not catch it because the tool list is dynamic. A tool that
catches release-to-release drift contained undetected drift, for exactly the
reason it could not see it. That is the argument for making the list
declarable.

## Not planned

- A bundled judge, scenario runner, or benchmark. Execution stays in the
  harness a team already has.
- A runtime proxy or enforcement point. This analyses and reports; the control
  belongs where the effect happens.
- Correctness. `reach` reasons about what a reviewed manifest permits under a
  bounded search, not about what a model tends to do.

## Drift is the foundation, not a feature

Every claim this tool makes rests on the manifest describing the agent that
actually ships. `reach` proves a path is permitted by a reviewed document, and
that proof is worth exactly as much as the document's correspondence to the
code. So `drift` is not one entry in the loop above. It is the check that
makes the other six mean anything, and a mandate that has never been drifted
against its source is a claim about a file rather than about an agent.

Stated here because it reads as one bullet among seven and it is not. If a
release has to skip a check, `drift` is the one it cannot skip.

## Next: widen the model only where evidence demands it

Ordered. Do not implement these in parallel, and do not start at item 3
because it is the most interesting. The AgentKit graph earns investigation of
bounded producers, explicit dynamic-tool inventory, and gross-versus-net value
accounting. Shipping any of them still needs a reviewed schema change,
migration fixtures, and a second graph showing that the concept is not
specific to one integration. Other candidates wait for an independent user to
show the distortion and the counterexample it hides.

### 1. A second independent tool graph

Everything below is gated on this, so it is item 1 rather than a precondition
mentioned in passing. One graph cannot distinguish a general modelling gap
from a quirk of one integration, and every candidate extension is currently
justified by the same single source.

This is evidence work rather than code, and the tooling for it already exists:
`scan` reads an MCP `tools/list` payload today, so the cost is finding a graph
and reviewing what the skeleton got wrong, not building an importer.

What the run has to record, following `docs/evidence/agentkit/`: the catalogue
as found, the skeleton `scan` proposed, every guess a reviewer corrected, and
the concepts the model could not express without distortion. A graph that
needed no correction is also a result, and a more useful one than a second
payments example.

**The named target is `github/github-mcp-server`.** GitHub's own MCP server,
tools defined statically in Go, grouped into toolsets and released against
versioned images. It is chosen rather than found convenient, for four reasons
that map onto what this model cannot currently express:

- **No currency anywhere.** GitHub's authority surface has no money in it, so
  the cumulative-value mechanism has nothing to attach to and the filesystem
  probe's silence should reproduce on a real published graph.
- **Irreversible effects are native.** Cancelling a workflow run, deleting run
  logs, force-pushing over history. These carry a clear accumulation rule and
  no currency, which is the non-monetary budget candidate with a real example
  behind it rather than a hypothetical.
- **Read, write and admin are platform concepts**, so the effect classes have
  an anchor instead of a reviewer's invention.
- **Tools mint scopes.** An agent with `contents:write` can commit a workflow
  file, and that file then executes with a token and repository secrets. A
  write mints secret-scoped compute.

That last one is the reason to expect a *partial* success rather than a flat
failure, and it is worth predicting before the run so the result can surprise
us. `produces`, `unbounded` and `requires` already exist and `reach` follows
them, so the minting chain should model correctly and the compound path should
be found. The gap should be narrower than the probe suggested: not that the
analysis says nothing, but that it finds the path and has no way to bound how
many times it may be walked. If the minting chain also fails to model, that is
a bigger finding than expected and changes the order below.

Scope it the way AgentKit was scoped. The full toolset is too large to stay
reviewer-comprehensible, so class-scope to what one real example wires in, and
record the `GITHUB_TOOLSETS` configuration as the reviewed inventory boundary.
That doubles as a live test of the dynamic-tool inventory candidate in item 3.

Runner-up, afterwards and not in parallel: the PostgreSQL MCP server, for
DDL against DML irreversibility and rows-affected budgets.

**Look for a graph with no currency in it.** Both sources the model has been
reasoned from, AgentKit and the payment-dispute example, are monetary, and
`Limits` carries exactly `total` and `depth`. A synthetic filesystem catalogue
in `docs/evidence/probes/` passes `lint` and `reach` completely clean while
holding three irreversible tools, because with no currency there is no
cumulative bound to search against. That probe cannot justify a schema change,
since it was written here rather than found. It can say where to look.

### 2. Bounded scope cardinality

The current `unbounded` flag distinguishes one binding from an unlimited
source. Real tools often expose a finite collection, such as at most ten cases
or one refund per transaction. A reviewed `max_bindings` bound is the first
candidate extension because it sharpens the existing scope model without
turning the manifest into a full application specification.

Per-customer or relational limits come later. They require resource identity
and relationships, not another integer placed beside the current type count.

### 3. Explicit dynamic-tool inventory

The AgentKit graph builds its tool list at runtime, so a static read cannot
enumerate it and `scan --source` says so rather than guessing. A reviewed way
to declare "this list is assembled from these providers" would turn an
unenumerable inventory into a bounded one, and an unenumerable tool list is
currently a finding that stops the analysis rather than a shape it handles.

### 4. Conditional and delegated authority

Ordered inside the bucket, because the third item is the one a reader of any
agent security model asks about first and the other two are not blocking it:

- **a delegated downstream identity.** Caller and service principal are
  already modelled: `principal` is on every tool, `lint` refuses a service
  principal where a caller token belongs, and `reach` tracks which tools spend
  which. A third identity is not. When one agent hands a bounded capability to
  another, the receiving agent's authority is invisible, so a breach reached
  through a delegate reads as the delegator's own.

  External feedback called caller against service principal a missing concept.
  Half of it ships today, and the half that does not is delegation.
- model one agent delegating a bounded capability to another, which is the
  same gap seen from the sending side
- represent selected state predicates such as case status and time windows

The design constraint is the same as today: enough structure to find a real
compound path, without asking teams to formalise the entire application.

### 5. Resource relationships

Scope counts deliberately forget which customer owns a case or whether two
bindings refer to the same object. If real graphs show that this creates false
or missed paths, add a small reviewed relation vocabulary and preserve binding
provenance through tool transitions. Do not jump directly to arbitrary
preconditions and postconditions.

### 6. Non-monetary effect budgets

Some authority limits count irreversible actions rather than currency, such as
accounts closed, credentials rotated, or external messages sent. Generalise
the current cumulative-value mechanism only when those limits share a clear,
reviewable accumulation rule. Confidentiality and data flow remain a separate
model rather than being disguised as a numeric budget.

### 7. Data-flow reachability

Add reviewed source, transform, and sink labels so the analyser can detect a
path such as:

```text
read_customer_record -> summarise -> send_external_message
```

This is distinct from the current value and scope model. It should ship only
with counterexamples that remain understandable to a reviewer.

## Path to 1.0

AgentMandate reaches 1.0 after:

- the manifest and JSON outputs receive a compatibility audit
- fixtures from every supported schema version are exercised in CI
- at least one independent agent integration tests the model against a real
  tool graph
- search limits and worst-case behaviour are measured and documented
- security and trace-retention guidance receive an external review

The most useful contribution is a real graph the current model cannot describe
without distortion. Open an issue with that graph before proposing another
generic scanner rule.
