# Design

## The problem this exists for

An agent's authority is not written down in one place. It is spread across tool
schemas, framework configuration, the IAM roles the tools run under, and a
prompt that asks nicely. Nobody can answer "what can this agent do" by reading
any single one of those, and nobody can answer "what changed" by reading a pull
request, because reachability composes and text does not.

Existing agent scanners check one tool at a time. That finds the tool with no
approval gate, which is worth finding. It cannot find the case where every tool
passes and a sequence of them does not, because that defect does not live in
any one tool.

## The authority model

A mandate is a set of tools over a set of scopes.

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

## Why `verify` ships in the first version

A declaration nobody checks is a wish. The implementation drifts from the
manifest the moment somebody ships a connector change, and every finding this
tool produces is worthless if the manifest stopped describing the agent six
weeks ago.

`verify` replays recorded calls and reports what the mandate does not permit.
It is the cheapest available answer to "why should I believe your manifest",
and without it the rest would be a YAML linter with opinions.

## Deliberate overlap

`lint` covers ground that AgentWard, AgentShield, and AgentGuard already cover.
That is on purpose. A tool that reported only compound findings would need one
of those running alongside it to be usable at all, and the first thing anyone
does with a new analysis tool is run it on its own.

The overlap is the floor. The contribution is `reach` and the diff built on it.

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

**Manifest extraction.** Manifests are hand-authored today. An MCP extractor is
the obvious next piece, and it will only ever get part of the way, because the
three fields the model needs are exactly the ones a tool schema omits. Expect
extract-then-annotate, not extract.
