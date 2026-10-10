# Design

## The problem this exists for

An AI agent is more than its language model. The surrounding runtime supplies
instructions, tools, memory, credentials, and execution. Its authority is not
written down in one place: it is spread across tool schemas, framework
configuration, workload identity, and policy. Reviewing those inputs separately
can miss the authority created by combining them. A prompt can influence which
calls the model requests, but it does not enforce their authorization.

AgentMandate records reviewed tool authority and searches permitted call
sequences. For example, opening more cases can make repeated refunds exceed a
total limit while every individual refund stays within its per-case ceiling.
Single-tool checks and compound analysis answer different questions.

For manifest syntax, use the [manifest reference](docs/manifest.md). This page
explains the model, its search and comparison rules, and the evidence behind
its limits.

## The authority model

A mandate is one reviewed, bounded unit of work. Manifest v1 models its tool
authority as a set of tools over a set of scopes.

AgentMandate sits at the action boundary of an agent loop. The model may sense,
reason, plan, and propose a tool call. The surrounding runtime supplies the
workload identity and routes the call through the deployed authorisation
decision point. Application code causes the real-world effect. A prompt can
shape model behaviour, but it is not an authority boundary. This project
analyses the tool authority those components expose and the paths that
authority permits.

That reachability question is separate from authority continuity. A cumulative
constraint depends on both its configured limit and the runtime's consumed
state. Even correct per-request enforcement does not bound one mandate if a
fresh session, handoff, or policy revision restores capacity the mandate has
already spent. The experimental continuity profile reconciles that lifecycle
question without changing manifest-v1 reachability or turning AgentMandate into
a session broker or distributed counter.

A **scope** is a type of resource the agent can hold a binding to, such as
`case` or `ledger`. Scopes are types, not instances: the analysis reasons about
"a case", never about case 4471.

A **tool** may require bindings to act, may produce a binding, may spend value,
and carries an effect class and a principal.

The three fields that make compound analysis possible, and that an ordinary
tool schema does not carry:

| Field | Why it is needed |
|---|---|
| `effect` | read, write, or irreversible. Reversibility is what decides where a gate belongs, and it cannot be inferred from a name |
| `value_arg` | which argument spends money. Without it there is nothing to accumulate |
| `scope_key` | which resource binding partitions a tool's cumulative ceiling |

These fields require human review. General preconditions and postconditions
would express more behavior, but would also require a richer annotation and
evaluation contract than the current tool provides.

### Repeated scope production

A per-scope ceiling bounds each binding; it does not by itself bound the total
across bindings. A producer marked `unbounded` can repeatedly create fresh
bindings. Two cases can therefore permit two £500 refunds despite each case's
£500 ceiling. Search depth still limits the number of calls explored.

The composition breaches a mandate that separately limits the total to less
than £1,000. Without that declared total, these calls are not a cumulative-value
breach of the manifest.

Some deployments enforce a smaller finite producer cardinality. That fact is
not manifest intent and cannot be inferred from a quota document or tool
schema. A standalone reviewed producer boundary may narrow one exact
deployment, output scope, resource partition, and monotone run only after its
selected source bytes and review lifetime verify. Any ambiguity retains the
stronger `unbounded` graph with a finding. The attachment changes design-time
reachability; it is not a runtime reservation or enforcement mechanism.

## The search

The search is breadth-first over states containing held bindings, value already
spent per (tool, scope, binding), and counts for declared effect budgets.

Breadth-first search produces a shortest call sequence witnessing each reported
breach. Short counterexamples are easier to reproduce and review.

Equivalent states are canonicalised and visited once. A transition that changes
no tracked state is not enqueued. This avoids repeatedly exploring read-only
calls that add no bindings or budget consumption.

The search is bounded by `limits.depth`. Results are a lower bound: no breach at
depth 8 is not proof that none exists at depth 20, and the report says so when
it truncated. Claiming otherwise would require a completeness argument this
model does not support.

In the pinned five-graph study, four graphs truncated at the default depth 8,
and 20 of 25 graph/depth runs truncated across the fixed sweep. This is a
measurement of those inputs, not a production probability: truncation means
the walk reached its boundary, not that a breach exists beyond it.

The [search bounds and performance guide](docs/search-performance.md) derives
conservative state-space and storage bounds, measures the five real graphs,
and explains the difference between a call-depth bound and a process resource
limit. The kernel retains private immutable states and shared path prefixes;
shortest witnesses and public Authority output remain unchanged.

### Reachability is existential

A reachable path means there is **some** permitted sequence and some consistent
assignment of bindings that enables it. It does not mean every caller-supplied
resource tuple succeeds. This follows from scopes being resource types rather
than instances: `case` means "a case", not a claim about case 4471.

That distinction is a gate on relationship work. An API rejecting project A
with project B's status is not by itself an analysis false positive when the
same generic tools can select a status belonging to project A. A qualifying
relationship counterexample needs a real fixed or otherwise constrained
binding for which no consistent assignment exists, while the abstraction still
reports the path. Otherwise a relationship may improve explanation, but it
does not make reachability more precise.

## Why effective authority, not declared policy

`diff` compares what two manifests *permit*, computed by running the search over
both, rather than comparing their text. The two come apart routinely, which is
the entire argument for the command:

- Adding a read-only producer can make a cumulative breach reachable. This is
  the shipped example.
- Reformatting a manifest changes its text without changing its authority.
- Removing a prerequisite can make an existing irreversible tool reachable.

Tool names are comparison identities. A rename is reported as a removal and
an addition; the current diff does not infer that two differently named tools
are equivalent. General input-schema constraints are outside manifest v1.

Effective authority is summarised as reachable tools, effect-on-scope pairs,
ungated irreversible effects, service-principal tools, maximum extractable
value, and reachable breach kinds. A gain in any of those is widening.

The diff also compares the contract of every tool reachable in both releases.
Removing a precondition or approval, raising or removing a ceiling, increasing
an effect class, enabling unbounded scope minting, raising the run limit, or
raising/removing an effect-count budget is widening even when reachable tools
and breach witnesses do not change. Adding/reducing an effect budget narrows
that declared allowance; zero is a limit and an absent class is unbounded.
These limit changes are reported separately from gains or losses of breach
diagnostics. Removing a budget can remove its diagnostic without narrowing
the allowance. Conversely, a tighter limit can expose a new breach; the
existing combined verdict still requires review for any newly reachable breach
as well as any widening allowance change. Amounts in
different currencies are not ordered. A currency change is sent for review
rather than being called narrower because its numeral is smaller.

Both releases are searched to the same depth, using the larger manifest
default unless the caller supplies `--depth`. Reducing a manifest's default
depth is itself widening because it weakens future analysis. Manifests naming
different agents are not comparable.

## Reviewing repair candidates

`remediate` searches a separate, bounded domain of tool removals and approval
requirements over the same manifest model. It rechecks every returned candidate
at the baseline depth, reports lost reachable tools and remaining lint, and
retains the original findings. Edit-domain completeness and reachability
truncation are separate. A candidate removes bounded reachable breaches; it
does not prove business correctness or accept a new mandate. See the
[repair guide](docs/remediation.md).

## Checking observed calls

`verify` replays recorded calls and reports what the mandate does not permit.
It helps detect a mismatch between reviewed intent and observed execution.
`drift` separately compares the manifest with the selected source inventory.
Neither proves that the supplied inventory or trace contains every deployed
path; each result retains its input-completeness boundary.

Conformance is fail closed. A record cannot establish a ceiling without its
scope, finite value, and currency, or establish identity use without the
executing principal. Missing evidence is a violation. Malformed evidence is a
usage error.

## Relationship to runtime enforcement

`lint` checks individual controls, `reach` searches their composition, and
`diff` compares the authority of two reviewed manifests. These are offline
analysis steps. The application's policy decision and enforcement points still
decide whether a real request executes.

Request authorization and cumulative accounting need separate treatment.
Ordinary Cedar decisions evaluate a request against policy. The captured
AgentCore temporal policies also query accumulated history within a selected
provider boundary. That stateful behavior does not by itself bind the history
to a reviewed mandate or provide a release-to-release reachability comparison.
The [continuity evidence](docs/continuity-evidence-consolidation.md) records
the tested boundaries and unresolved joins. Use the dated
[landscape survey](docs/agentic-ai-landscape.md) for product comparisons.

The same boundary applies to multi-agent systems. A supervisor choosing a
worker is behaviour. The identity and tools delegated to that worker are
authority. Manifest v1 still describes one agent or one deliberately reviewed
union of agents. The public delegation attachment separately represents and
checks actor history, validity, audience, and attenuation without silently
changing that manifest meaning.

## Counting effects, not only value

`limits.effects` declares a maximum number of calls per effect class in the
modeled run:

```yaml
limits:
  effects:
    irreversible: 3
```

Only declared budgets are checked. Each call in a budgeted class increments
its count, including a call that produces no scope and spends no money. This
allows the search to represent repeated irreversible actions as distinct states.
The count is shared across tools in that effect class; it is not a timed rate
limit or a weighted cost model.

**Historical motivation.** Before effect budgets shipped, the GitHub MCP graph
could express approval requirements and the write-to-workflow chain, but could
not bound its repetition without inventing money. The
[captured graph](docs/evidence/github-mcp-server/README.md) preserves that
earlier limitation. Effect budgets addressed the call-count gap; the graph's
conditional effects and argument-dependent scope production remain separate
modeling questions.

## What was left out, and why

**Data-flow reachability.** Finding that a read tool feeds an exfiltration path
needs labels on arguments and returns. The manifest does not carry them.
The roadmap requires a real path and evidence that reviewers can supply useful
labels before introducing this model.

**Enforcement.** No proxy, no runtime interception. That is a large maintenance
surface, it is well covered by others, and mixing analysis with enforcement
makes both harder to reason about.

**Model behaviour.** Whether an agent *would* take a path is a different
question from whether it *may*. This measures permitted authority. The
behavioural question needs the agent in the loop and belongs in a testing tool.

**Automatic authority annotation.** `mandate scan` reads an MCP catalogue or
Python declarations and writes a skeleton. It proposes effects and scope/value
fields conservatively and marks guesses `REVIEW`. A reviewer must establish
reversibility, principals, approvals, and intended limits before relying on the
manifest. Source extraction does not supply that acceptance.
