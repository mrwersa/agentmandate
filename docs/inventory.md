# Starting from agent code

`mandate scan --source` reads the tools an agent declares in Python and writes
a manifest skeleton. It is for the case where there is no MCP catalogue to
scan, which is most agents.

```console
$ mandate scan --source examples/refund_agent.py --agent refunds > mandate.yaml
$ mandate lint mandate.yaml
```

## Nothing is imported

The read is static. Your agent is not executed, its framework does not need to
be installed, and its imports are not resolved.

That matters for where this is meant to run. A review happens on a branch, in
CI, in a checkout whose dependencies are not installed and whose side effects
must not happen. A tool that had to import the agent to describe it could not
run there, and importing a module to find out what it is permitted to do has
the obvious problem that the import already did it.

The cost is that a tool assembled at runtime is invisible. That is reported
rather than hidden. See [What it says it cannot see](#what-it-says-it-cannot-see).

## What it recognises

| Framework | Declaration |
|---|---|
| LangChain, LangGraph | `@tool`, `@tool("name")` |
| Strands Agents | `@tool` |
| OpenAI Agents SDK | `@function_tool`, `@function_tool(name_override=...)` |
| Microsoft Agent Framework | `@ai_function` |
| CrewAI | `@tool` |
| FastMCP | `@mcp.tool()` |

Matching is on the trailing name of the decorator, not on the import path, so
`@tool`, `@tools.tool`, and `@mcp.tool()` are all recognised and an aliased
import still works. `async def` is read the same as `def`.

Bindings are read from any call taking `tools=[...]` and from `.bind_tools([...])`,
which covers `Agent(...)`, `create_react_agent(...)`, `LlmAgent(...)`, and the
rest without naming each one.

## The inventory is what the agent was given

A repository usually declares more tools than any one agent gets. The mandate
covers the tools passed to the agent, and anything declared but never bound is
excluded and named:

```yaml
# REVIEW: Defined but not bound to any agent: draft_email. They are
#         excluded. Add any the agent reaches through another path.
```

If no binding is found anywhere, every declared tool is listed and the file
says so. Over-listing is the safe direction: a reviewer deleting a tool the
agent does not have loses nothing, while a missing tool means `reach` searches
a smaller graph than the real one and reports no path where one exists.

## What it says it cannot see

This is the part worth reading before trusting the output.

**A tool list it cannot enumerate.**

```python
agent = Agent(tools=load_tools())
support = Agent(tools=[search_cases, *partner_tools])
```

```yaml
# REVIEW: A binding passes tools this read cannot enumerate
#         (agent.py:7: load_tools()). Those tools are missing from the list
#         below, and a later diff would report them as newly added
#         authority. Add them by hand.
```

The second sentence is the reason this is not a warning to skim. `mandate diff`
compares reachable authority between releases. A tool silently missing from
today's manifest appears in tomorrow's as new authority, and the widening it
reports never happened.

**A bound tool declared somewhere else.** `tools=[lookup_partner]` where
`lookup_partner` comes from a package outside `--source` is authority this
manifest omits. It is named, with the suggestion to widen the path.

**More than one agent.** Two bindings produce a union, flagged as one:

```yaml
# REVIEW: 2 tool bindings were found (agent.py:7, agent.py:12). This manifest
#         is their union. If they are separate agents, give each one its own
#         manifest, because a union overstates what any single agent can reach.
```

A union is a fiction: it describes an agent holding every tool in the system,
and `reach` will happily find a compound path across two agents that never
share a run. Split them.

**A file it could not parse.** Named, with the rest of the scan kept.

## What the signature gives you

The argument names and annotations are read the same way an MCP input schema
is. An argument ending in `_id` is proposed as the scope. An argument whose
name suggests value and whose type is numeric is proposed as the value
argument.

The annotation is doing real work here:

```python
@tool
def issue_refund(case_id: str, amount: Decimal, currency: str) -> str: ...
```

```yaml
    requires: ["case"]
    # REVIEW: amount looks like a value argument. A ceiling needs scope_key too.
    # value_arg: "amount"
```

`Decimal`, `int`, `float`, `Optional[float]`, and `Annotated[float, ...]` all
read as numeric. A `str` argument called `amount` is not proposed as a value
argument, which a bare catalogue with untyped arguments could not rule out. An
unannotated argument stays a candidate, because no annotation is no evidence
either way.

Framework plumbing is left out. `self`, `ctx`, `tool_context`, and anything
annotated `...Context` or `...ContextWrapper` are not agent input, and reading
them would invent a scope out of a callback handle.

The first paragraph of the docstring becomes the comment above the tool. The
rest does not, because a manifest is not documentation.

## What it will not do

The three fields the analysis actually turns on are not in the source:

- whether the effect can be undone
- which argument spends money, and against what a ceiling counts
- whether the tool runs as the caller or as a service account

Effects are guessed from the name and default to `irreversible`, because
under-calling an effect is the more expensive mistake. Every guess carries a
`REVIEW` marker. Delete the marker once you have confirmed the line under it,
and the remaining markers are your worklist.

Extract then annotate. Never extract and trust.

## Where it goes next

```console
$ mandate scan --source src/agent --agent refunds > mandate.yaml
# review every REVIEW line, then:
$ mandate lint mandate.yaml
$ mandate reach mandate.yaml
$ mandate obligations mandate.yaml
```

`reach` is the point of having the manifest. Until the ceilings, the produced
scopes, and the `unbounded` flags are filled in, it has no cumulative limit to
search against and will report nothing, which is not the same as safe.
