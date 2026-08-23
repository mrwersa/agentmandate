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
The proposed [dynamic inventory declaration contract](dynamic-inventory.md)
defines how reviewed captures may eventually discharge that uncertainty; no
current command accepts those declarations.

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

## One manifest describes one agent

This is the rule everything else follows from. `reach` searches whatever graph
it is given, so a manifest holding two agents' tools produces compound paths
that no single run could take. A gate reporting breaches nobody can reach is a
gate that gets switched off.

So the inventory is the tools passed to **one** agent. Anything declared but
never given to it is excluded and named:

```yaml
# REVIEW: Declared but not given to this agent: draft_email. They are
#         excluded. Add any it reaches through another path.
```

**Two agents in the source is an error, not a warning:**

```console
$ mandate scan --source src/agents
error: the source builds more than one agent, and a manifest describes one
agent's authority. Their union would let `reach` compose a path across tools
that never share a run.

  triage                   agents/support.py:31  (3 tool(s))
  resolver                 agents/support.py:44  (5 tool(s))

Choose one with --binding NAME, or pass --union-bindings if they genuinely
share authority.
```

The name is the variable the agent is assigned to. `--union-bindings` exists
for the case where the agents really do share authority, and it labels the
output so a later reader knows what they are looking at.

**An empty list is also an error.** `Agent(tools=[])` means the agent has no
tools. Listing every declared tool there would grant authority the source
explicitly withholds.

If nothing takes a `tools=` list at all, that is different again: nothing was
said, so every declared tool is listed and the file says the list has not been
narrowed. Over-listing is the safe direction there, because a reviewer
deleting a tool loses nothing while a missing tool means `reach` searches a
smaller graph than the real one.

## Only agent-shaped call sites count

A `tools=` keyword on any function used to decide the inventory, so an
unrelated `render_panel(tools=[...])` could rewrite what the agent was said to
hold. Now the callee has to be a constructor this knows by name: `Agent`,
`create_react_agent`, `AgentExecutor`, `ToolNode`, `bind_tools`, `LlmAgent`,
`SequentialAgent`, `AssistantAgent`, `ChatAgent`, `Crew`, `Swarm`,
`AgentWorkflow`, `ReActAgent`, and the rest of the same shape.

A word test came first and was too loose. `workflow_graph(tools=[...])` and
`team_dashboard(tools=[...])` both matched it. An unlisted callee is not
dropped, it becomes a candidate `--binding` selects, so the cost of the list
being incomplete is one flag rather than a wrong manifest:

```yaml
# REVIEW: app/ui.py:12 passes `tools=` to render_panel, which does not look
#         like an agent, so it was ignored. If it does build one, select it
#         with --binding panel.
```

## The module a tool came from decides which one it is

Two modules declaring `refund` is ordinary. Picking whichever file sorts first
would attribute one agent's signature, scope, and ceiling to another agent's
tool, silently.

Resolution follows what the source actually says, in order: the module named
in a dotted reference (`tools.refund`), then the import the binding file used
(`from .bank import refund`), then a declaration in the binding file itself,
then a single unambiguous declaration anywhere. A name that genuinely could be
either is reported and neither is used:

```yaml
# REVIEW: More than one declaration answers to the same name: refund
#         (bank.py:refund, support.py:refund). None of them was chosen,
#         because picking one would attribute the wrong signature, scope,
#         and ceiling to this agent's tool.
```

## A decorator with the right name and an unknown origin

`@tool` from `internal_helpers` has the right name and no established
meaning. Re-exporting a framework decorator through a local module is common,
so it is still read, and then questioned:

```yaml
# REVIEW: These carry a tool decorator from somewhere this does not
#         recognise as an agent framework: wipe_database (from
#         internal_helpers). They are included, because a re-exported
#         decorator is common, but check they really are agent tools.
```

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
# if the source builds several agents, name the one you mean:
$ mandate scan --source src/agent --binding resolver --agent refunds > mandate.yaml
# review every REVIEW line, then:
$ mandate lint mandate.yaml
$ mandate reach mandate.yaml
$ mandate obligations mandate.yaml
```

`reach` is the point of having the manifest. Until the ceilings, the produced
scopes, and the `unbounded` flags are filled in, it has no cumulative limit to
search against and will report nothing, which is not the same as safe.
