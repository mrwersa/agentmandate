# Design

## The problem this exists for

An AI agent is more than its language model. The surrounding runtime supplies
instructions, tools, memory, credentials, and execution. Its authority is not
written down in one place: it is spread across tool schemas, framework
configuration, workload identity, policy, and a prompt that asks nicely. Nobody
can answer "what can this agent do" by reading any one of those, and nobody can
answer "what changed" by reading a pull request, because reachability composes
and text does not.

Many agent scanners check one tool at a time. That finds the tool with no
approval gate, which is worth finding. It cannot find the case where every tool
passes and a sequence of them does not, because that defect does not live in
any one tool.

## The authority model

A mandate is one reviewed, bounded unit of work. Manifest v1 models its tool
authority as a set of tools over a set of scopes.

AgentMandate sits at the action boundary of an agent loop. The model may sense,
reason, plan, and propose a tool call. The platform still owns the workload
identity, authorisation decision, and real-world effect. A prompt can shape
model behaviour, but it is not an authority boundary. This project analyses
the tool authority the platform exposes and the paths that authority permits.

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
| `scope_key` | what a ceiling is measured against. A ceiling with no scope is not a bound |

Full preconditions and postconditions would be more expressive. They would also
not get written, and an unwritten annotation buys nothing. This is the smallest
set that supports the analysis.

### `unbounded` is the whole game

A per-scope ceiling is only a bound when the scope itself is bounded. A tool
marked `unbounded` can be called repeatedly to mint fresh bindings, so a
£500-per-case ceiling becomes £500 times as many cases as the agent cares to
open.

That is the defect the package exists to find, and it is invisible tool by
tool. Both halves look correct in isolation. Only the composition is wrong.

Some deployments enforce a smaller finite producer cardinality. That fact is
not manifest intent and cannot be inferred from a quota document or tool
schema. A standalone reviewed producer boundary may narrow one exact
deployment, output scope, resource partition, and monotone run only after its
selected source bytes and review lifetime verify. Any ambiguity retains the
stronger `unbounded` graph with a finding. The attachment changes design-time
reachability; it is not a runtime reservation or enforcement mechanism.

## The search

Breadth-first over states, where a state is the bindings held and the value
already spent per (tool, scope, binding).

Breadth-first rather than depth-first for one reason: the shortest
counterexample is the most useful one. A four-call sequence gets fixed and a
forty-call sequence gets argued about.

States are canonicalised so the walk memoises, and a transition that changes
nothing is not enqueued. Without that, any manifest with a read-only tool
produces an infinite frontier.

The search is bounded by `limits.depth`. Results are a lower bound: no breach at
depth 8 is not proof that none exists at depth 20, and the report says so when
it truncated. Claiming otherwise would require a completeness argument this
model does not support.

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

- Adding a read-only tool changes no permission and can make a money ceiling
  unenforceable. This is the shipped example.
- Renaming a tool changes every line of the config diff and no authority.
- Relaxing one enum in a schema is one character and can open a scope.

Effective authority is summarised as reachable tools, effect-on-scope pairs,
ungated irreversible effects, service-principal tools, maximum extractable
value, and reachable breach kinds. A gain in any of those is widening.

The diff also compares the contract of every tool reachable in both releases.
Removing a precondition or approval, raising or removing a ceiling, increasing
an effect class, enabling unbounded scope minting, or raising the run limit is
widening even when the set of reachable tool names does not change. Amounts in
different currencies are not ordered. A currency change is sent for review
rather than being called narrower because its numeral is smaller.

Both releases are searched to the same depth, using the larger manifest
default unless the caller supplies `--depth`. Reducing a manifest's default
depth is itself widening because it weakens future analysis. Manifests naming
different agents are not comparable.

## Why `verify` ships in the first version

A declaration nobody checks is a wish. The implementation drifts from the
manifest the moment somebody ships a connector change, and every finding this
tool produces is worthless if the manifest stopped describing the agent six
weeks ago.

`verify` replays recorded calls and reports what the mandate does not permit.
It is the cheapest available answer to "why should I believe your manifest",
and without it the rest would be a YAML linter with opinions.

Conformance is fail closed. A record cannot establish a ceiling without its
scope, finite value, and currency, or establish identity use without the
executing principal. Missing evidence is a violation. Malformed evidence is a
usage error.

## Deliberate overlap

`lint` covers ground that AgentWard, AgentShield, AgentGuard, and Policy in
Amazon Bedrock AgentCore already cover.
That is on purpose. A tool that reported only compound findings would need one
of those running alongside it to be usable at all, and the first thing anyone
does with a new analysis tool is run it on its own.

The overlap is the floor. The contribution is `reach` and the diff built on it.

Policy in AgentCore is worth naming precisely, because it is the strongest
reason an AWS team would ask why this exists. It evaluates all applicable
Cedar policies for every gateway tool invocation with default-deny and
forbid-wins semantics. Its documented automated analysis flags policy-level
problems such as policies that always allow or always deny. That is real
analysis, but it does not model a sequence of individually permitted calls.

Cedar has no notion of a call sequence. "May this principal invoke
`issue_refund` now" is a different question from "do four individually
permitted calls compose into a 1,000 GBP breach", and no per-decision engine
answers the second by construction. Neither does any of them answer whether a
release widened reachable authority, because that needs two manifests and a
reachability computation over both.

So the split is enforcement against offline analysis, and per-decision against
compound. Running both is the intended shape.

The same boundary applies to multi-agent systems. A supervisor choosing a
worker is behaviour. The identity and tools delegated to that worker are
authority. Manifest v1 still describes one agent or one deliberately reviewed
union of agents. The public delegation attachment separately represents and
checks actor history, validity, audience, and attenuation without silently
changing that manifest meaning.

## Counting effects, not only value

Two real graphs now say the same thing about the cumulative model, and it took
the second one to make it concrete.

`Limits` carried `total`, a `Money` ceiling, and `depth`. Every cumulative
question the search could ask was therefore a question about currency. On the
Coinbase AgentKit graph that was the right axis, because the authority being
compounded was money. On the GitHub MCP graph there is no currency anywhere,
and `reach` answered "no reachable breach" on an agent that can write a
workflow, run it with repository secrets, and delete the run logs.

That answer was true. It was also empty, and the distinction matters: the
approval and irreversibility axis works fine on that graph. Drop the two
conservative `requires_approval` flags and `lint` immediately reports
`effect.ungated-irreversible` on `actions_run_trigger` and `delete_file`. What
the model could not say is **how many times**. Not a missing voice, a missing
count.

**The decision.** `Limits` gains `effects`, a reviewed maximum number of calls
per effect class in one run:

```yaml
limits:
  effects:
    irreversible: 3
```

Declared only. A manifest that names no effect budget behaves exactly as
before, because inventing a ceiling is the same mistake as inventing a
reversibility label, and this model already refuses that one.

**The part that needed a search change.** An effect count has to be state, and
that is not a detail. The walk skips a tool that neither mints a scope nor
spends against a ceiling, on the correct reasoning that exploring it again
reaches no state the walk cannot already hit. An irreversible tool with no
scope, `delete_file` being exactly that, therefore never extended a path. The
search could not represent deleting twice, so no budget over it could ever have
been exceeded. Counting calls without making the count part of the state would
have shipped a limit that silently never fires.

So a call whose effect class carries a declared budget now progresses the walk,
the same way spending against a ceiling does. The budget makes the repetition
visible, and without a declared budget nothing changes.

**Why a count per effect class rather than per tool.** A per-tool count is a
rate limit, and rate limits belong at the tool. What a reviewer wants to bound
is the blast radius of a class of action, "at most three irreversible things in
one run", independent of which tools reach it. It also composes with the
existing model: effect classes are already declared, already linted, and
already the vocabulary a reviewer reasons in.

**What this is not.** Not a general budget language. The accumulation rule is
one call, one increment, chosen because it is the only rule that needs no
further declarations to interpret. Confidentiality and data flow stay a
separate model rather than being disguised as a numeric budget, which is the
same boundary `total` already respects.

## What was left out, and why

**Data-flow reachability.** Finding that a read tool feeds an exfiltration path
needs taint labels on arguments and returns. The manifest does not carry them,
and inventing them would mean asking for annotations nobody would write. Left
out rather than approximated, because a taint analysis with guessed labels
produces confident false positives, which is worse than no analysis.

**Enforcement.** No proxy, no runtime interception. That is a large maintenance
surface, it is well covered by others, and mixing analysis with enforcement
makes both harder to reason about.

**Model behaviour.** Whether an agent *would* take a path is a different
question from whether it *may*. This measures permission. The behavioural
question needs the agent in the loop and belongs in a testing tool.

**Inferring the fields that matter.** `mandate scan` reads an MCP catalogue and
writes the skeleton, which removes the typing. It cannot remove the thinking,
because the three fields the model needs are exactly the ones a tool schema
omits. It guesses conservatively, defaults anything that is not clearly a read
to `irreversible`, and marks every guess `REVIEW`. Extract then annotate, never
extract and trust. Inferring reversibility from a description with a model was
considered and rejected: a confident wrong answer about whether an action can be
undone is worse than no answer.
