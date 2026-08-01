# AgentKit evidence: a real graph the model could not describe

The roadmap asks for one thing before any feature is built: a tool graph that
somebody has to distort to express, with the control they actually run and the
counterexample the distortion hides. This directory is that evidence.

## The graph

- Framework: Coinbase AgentKit, `coinbase-agentkit@v0.7.4` (tag dated
  2025-10-03, `pyproject.toml` confirms version 0.7.4) against `v0.1.6`.
- Agent: the Strands example chatbot,
  `python/examples/strands-agents-cdp-server-chatbot/chatbot.py`.
- Provider set wired in `chatbot.py` `action_providers=[...]` and nothing
  else: `cdp_api`, `erc20`, `pyth`, `wallet`, `weth`, `wow`, `compound`.
  The x402, onramp and ssh providers exist in v0.7.4 but the example never
  instantiates them, so they are not here. **Every number below is scoped to
  the seven instantiated providers.**
- Tool sets were enumerated from source, class-scoped to exactly the seven
  instantiated classes at each version. The tool list is dynamic: line 87 is
  `tools = get_strands_tools(agentkit)`, which `drift` cannot enumerate
  without importing the agent.

Two manifests, one per AgentKit version:

| file | AgentKit | actions | distinct | role |
|---|---|---|---|---|
| `mandate-v016.yaml` | v0.1.6 | 18 | 17 | before |
| `mandate.yaml` | v0.7.4 | 21 | 20 | after |

`get_balance` is declared by both the erc20 and the wallet provider; the
manifest keys tools by name and resolves the collision to one entry.

## What changed between the two versions

The corrected, class-scoped diff:

```
authority diff  mandate-v016.yaml -> mandate.yaml
  + tool: gained approve
  + tool: gained fetch_price
  + tool: gained fetch_price_feed
  + tool: gained get_allowance
  + tool: gained get_erc20_token_address
  + tool: gained unwrap_eth
  - tool: lost address_reputation
  - tool: lost fetch_price_feed_id
  - tool: lost get_price
  + effect: gained write on allowance
  + effect: gained read on allowance

verdict: WIDENING
```

Six gained, three lost, a widening beside a narrowing. The interesting gains
are ERC-20 authority tools. `approve` grants an allowance: a third party can
spend the wallet's tokens later, without the agent calling anything again.
That is authority which outlives the run, arriving in a minor bump and
invisible in a config diff. The diff also reports `effect: gained write on
allowance` and `effect: gained read on allowance`: `approve` added a new
scope with new effect classes, an authority-shape change rather than an
inventory change, which a config diff structurally cannot show. The pyth
tools were renamed (`get_price` and `fetch_price_feed_id` became
`fetch_price` and `fetch_price_feed`), and `address_reputation` was dropped.

## The controls, invented but honest

AgentKit itself ships no cumulative ceilings, only wallet balance and CDP API
keys. The per-binding ceiling of 500 USD and the session total of 700 USD are
the controls a team would run; the manifest is the only place they can live.
Nothing in this directory claims Coinbase ships these limits. The counterexample
is "if you declare these limits, this sequence defeats them", never "the
framework has a hole".

## What the distortion found

`mandate reach mandate.yaml` reproduces the compound breach, untouched by the
version change because it is entirely inside the wow provider:

```
BREACH  cumulative value 1000 USD exceeds limit 700 USD
  1. create_token(token#1)
  2. buy_token(token#1, 500 USD)
  3. sell_token(token#1, 500 USD)
```

`mandate lint` is clean on both files. `mandate drift` reports the dynamic
tool list at `chatbot.py:87` as UNRESOLVED and refuses to certify the
manifest.

## The evidence is itself an example of drift

The first draft of these manifests included tools from providers the example
never wires in (ssh, x402, onramp), describing a tool set the release does not
have. `drift` could not catch that error, because the tool list is dynamic and
the comparison could not enumerate it. The limitation this evidence documents
is the reason the evidence itself first went wrong: it argues for making the
tool list declarable more strongly than any abstract statement of the gap.

## The four distortions

Catalogued in full in the end-note of `mandate.yaml`:

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
4. **The `get_balance` collision.** Both erc20 and wallet declare it; the
   manifest resolves to one entry and one real tool disappears silently.

## Re-run

```sh
mandate lint docs/evidence/agentkit/mandate.yaml
mandate reach docs/evidence/agentkit/mandate.yaml
mandate diff docs/evidence/agentkit/mandate-v016.yaml docs/evidence/agentkit/mandate.yaml
mandate drift docs/evidence/agentkit/mandate.yaml --source <checkout of the AgentKit example>
```

## The figure

`authority-shape.png` renders `authority-shape.mmd`. It contrasts the two
changes one minor bump produced: an inventory change a reviewer sees, and an
authority-shape change they do not.

```bash
npx @mermaid-js/mermaid-cli -i docs/evidence/agentkit/authority-shape.mmd \
  -o docs/evidence/agentkit/authority-shape.png -w 1200 -b white
```

The Mermaid source is what gets reviewed. The PNG exists because publishing
surfaces outside GitHub do not render Mermaid.
