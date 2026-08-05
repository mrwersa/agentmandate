# Probes

Shaped questions, not evidence. A probe is a catalogue written here to ask
whether the model can express a domain at all. It cannot justify shipping a
schema change, because the manifest was not found in the wild and nothing
stops it from being written to produce the answer it produces.

Real graphs live beside this directory, in their own folder, with the
catalogue as found and every reviewer correction recorded.

## `filesystem-catalogue.json`

Six tools in the shape a filesystem MCP server publishes: `list_directory`,
`read_file`, `search_files`, `write_file`, `move_file`, `delete_file`. Three
reads and three irreversible writes, no money anywhere.

`scan` handles it well. Effects are guessed correctly from the names, the three
destructive tools default to `irreversible` and pick up `requires_approval`,
and every guess carries a REVIEW line.

Then both checks pass clean:

```console
$ mandate lint filesystem.yaml
no single-manifest findings

$ mandate reach filesystem.yaml
no reachable breach within depth 8. 6 tool(s) reachable
```

An agent that can read every file it can reach and then delete them is not a
clean bill of health. The result is honest about the model rather than about
the agent: `Limits` carries `total`, which is money, and `depth`. A graph with
no currency has no cumulative bound for `reach` to search against, so
"no reachable breach" is true and says nothing.

**What this is for.** It does not justify building non-monetary effect budgets,
because the catalogue is synthetic. It says the second real graph should not be
another payments integration. Both graphs the project has reasoned from,
AgentKit and the payment-dispute example, carry money, and the whole cumulative
model is shaped by that. Filesystem, git, database and browser servers are a
large share of published MCP tools and none of them have a currency.

Reproduce it:

```console
$ mandate scan docs/evidence/probes/filesystem-catalogue.json --agent file-assistant
```
