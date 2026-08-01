# AgentKit evidence: a real graph the model could not describe

The roadmap asks for one thing before any feature is built: a tool graph that
somebody has to distort to express, with the control they actually run and the
counterexample the distortion hides. This directory is that evidence.

## The graph

- Framework: Coinbase AgentKit, `coinbase-agentkit@v0.7.4` (tag dated
  2025-10-03, `pyproject.toml` confirms version 0.7.4).
- Agent: the Strands example chatbot,
  `python/examples/strands-agents-cdp-server-chatbot/chatbot.py`.
- Providers wired in the example: `cdp_api`, `erc20`, `pyth`, `wallet`,
  `weth`, `wow`, `compound`. That is the scope every number below quotes.
- The tool list is dynamic: line 87 is `tools = get_strands_tools(agentkit)`,
  which `drift` cannot enumerate without importing the agent.

Two manifests, one per AgentKit version:

| file | AgentKit | tools | role |
|---|---|---|---|
| `mandate-v016.yaml` | v0.1.6 | 20 | before |
| `mandate.yaml` | v0.7.4 | 25 | after |

The two differ only in the five tools the v0.7.4 providers add: `remote_shell`
(ssh), `make_http_request`, `make_http_request_with_x402`,
`retry_http_request_with_x402` (x402), and `get_onramp_buy_url` (onramp).
That is the example-scoped `diff` result: 5 tools gained.

## The controls, invented but honest

AgentKit itself ships no cumulative ceilings, only wallet balance and CDP API
keys. The per-binding ceiling of 500 USD and the session total of 700 USD are
the controls a team would run; the manifest is the only place they can live.
Nothing in this directory claims Coinbase ships these limits. The counterexample
is "if you declare these limits, this sequence defeats them", never "the
framework has a hole".

## What the distortion found

`mandate reach mandate.yaml` reproduces the compound breach:

```
BREACH  cumulative value 1000 USD exceeds limit 700 USD
  1. create_token(token#1)
  2. buy_token(token#1, 500 USD)
  3. sell_token(token#1, 500 USD)
```

`mandate diff mandate-v016.yaml mandate.yaml` reports WIDENING with the five
gained tools. `mandate lint` is clean on both files. `mandate drift` reports
the dynamic tool list at `chatbot.py:87` as UNRESOLVED and refuses to certify
the manifest.

The three distortions, catalogued in full in the end-note of `mandate.yaml`:

1. **Under-expression.** The value tools take the asset as a free argument and
   no tool produces an `asset` scope, so a ceiling has nothing to attach to.
   The `weth`/`eth`/`token`/`borrowed_asset` anchors are invented producers.
2. **Over-expression.** `borrow` and `wrap_eth` are `unbounded: true` because
   the model cannot express a bounded producer. Compound borrow is bounded by
   the collateral ratio and `wrap_eth` is 1:1 with the ETH balance. This is
   the more serious direction: `reach` reports paths nobody can take, and a
   gate that cries wolf gets switched off.
3. **Gross rather than net.** Buy then sell of the same binding nets to
   roughly zero but counts 1000 USD against the total. The model cannot
   declare which the reader is seeing.

## Re-run

```sh
mandate lint docs/evidence/agentkit/mandate.yaml
mandate reach docs/evidence/agentkit/mandate.yaml
mandate diff docs/evidence/agentkit/mandate-v016.yaml docs/evidence/agentkit/mandate.yaml
mandate drift docs/evidence/agentkit/mandate.yaml --source <checkout of the AgentKit example>
```
