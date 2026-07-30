# AgentMandate

> **What is your AI agent actually allowed to do?**

[![PyPI](https://img.shields.io/pypi/v/agentmandate.svg)](https://pypi.org/project/agentmandate/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20--%203.14-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/mrwersa/agentmandate/actions/workflows/ci.yml/badge.svg)](https://github.com/mrwersa/agentmandate/actions/workflows/ci.yml)
[![Coverage: 100%](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](#development)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](https://github.com/mrwersa/agentmandate/blob/main/LICENSE)

A Python library and CLI that reads a short description of your agent's tools,
called a **manifest**, and finds the limits it can slip past by combining
actions that are each permitted on their own. It also tells you when a release
widened what the agent can reach, before that release ships.

Policy engines decide one call at a time. This looks at the whole tool graph
offline, so it catches the gaps that only appear across a sequence.

| What you run | Question it answers |
|---|---|
| Cedar, OPA, AgentCore Policy, AgentWard | May this agent make this call, right now? |
| **AgentMandate** | **What can it reach by combining permitted calls, and did this release widen that?** |
| [AgentVerity](https://github.com/mrwersa/agentverity) | Were the reviewed decision routes exercised repeatably? |
| Your tests and runtime traces | Did the tools execute and the declared controls hold? |

Imagine a payment-dispute agent that can open a case and issue a
human-approved refund. Each refund is capped at 500 GBP per case, and the
whole run is capped at 500 GBP. Release 2 adds one read-only tool:
`search_cases`.

That tool spends nothing. It does, however, let the agent get hold of more
cases, and the 500 GBP cap is measured *per case*. Two separately valid refunds
become reachable under the manifest, so reachable extraction doubles to 1,000 GBP
while every individual call still looks permitted.

![A read-only case search makes two approved refunds reachable and breaches the run limit](https://raw.githubusercontent.com/mrwersa/agentmandate/main/docs/assets/authority-path.svg)

AgentMandate builds the tool graph and answers the questions a per-tool check
cannot:

- **What legal sequence breaks a limit?** `mandate reach` returns the path, not
  a risk score.
- **What did this release make possible?** `mandate diff` compares effective
  authority, not configuration text.
- **Does runtime evidence match the declaration?** `mandate verify` fails
  closed when a required control field is absent.
- **What must the tests exercise?** `mandate obligations` turns reachable
  authority into reviewable test obligations.
- **Which compound risks need scenarios?** `mandate scenarios` preserves each
  counterexample as a neutral test skeleton without inventing an agent prompt.

Alpha. Apache-2.0.

## Try it

```bash
pip install "agentmandate[yaml]"
```

The repository includes that payment-dispute agent. In release 1, refunds are
capped at 500 GBP per case, every refund requires human approval, the whole run
is capped at 500 GBP, and nothing spends through a service account. It passes:

```console
$ mandate lint examples/dispute-resolver.yaml
no single-manifest findings

$ mandate reach examples/dispute-resolver.yaml
no reachable breach within depth 8. 3 tool(s) reachable, most extractable 500 GBP
```

Release 2 adds one read-only tool so the agent can find existing cases instead
of always opening a new one. A conventional review sees no write effect:

```yaml
  - name: search_cases
    effect: read
    produces: case
    unbounded: true
```

```console
$ mandate lint examples/dispute-resolver-v2.yaml
no single-manifest findings

$ mandate reach examples/dispute-resolver-v2.yaml
BREACH  cumulative value 1000 GBP exceeds limit 500 GBP
  1. open_case(case#1)
  2. search_cases(case#2)
  3. issue_refund(case#1, 500 GBP)
  4. issue_refund(case#2, 500 GBP)
```

The lint is still clean because no single tool is wrong. The refund ceiling is
measured against one case, and the new tool lets the agent obtain fresh cases,
so the per-case ceiling no longer bounds the whole run. In CI:

```console
$ mandate diff examples/dispute-resolver.yaml examples/dispute-resolver-v2.yaml
authority diff  v1 -> v2
  + tool: gained search_cases
  + extractable value: 500 -> 2000 GBP
  + reachable breach: gained cumulative_value

verdict: WIDENING
a widening change needs named review before release
```

Exit code 1. The configuration change was read-only. The effective authority
was not.

## Why a config diff is not an authority diff

A pull request shows what somebody typed. It does not show what the agent can now do, because reachability composes and text does not. Adding a read tool, relaxing an enum in a schema, or removing one precondition can each open a path that did not exist, and none of them look like a permission change in review.

That is the same reason `git diff` never replaced type checking. The question is not what changed, it is what the change makes possible.

## Starting from an existing agent

You do not have to write the first manifest by hand:

```console
$ mandate scan examples/mcp-tools.json --agent dispute-resolver > mandate.yaml
```

The skeleton is loadable straight away, and every judgement the catalogue could
not supply is marked:

```yaml
  - name: issue_refund
    # REVIEW: effect guessed from the name. read | write | irreversible
    effect: irreversible
    # REVIEW: does this spend the caller's authority or a service account?
    principal: caller
    requires: [case]
    # REVIEW: amount looks like a value argument. A ceiling needs scope_key too.
    # value_arg: amount
    # scope_key: case
    # ceiling: { amount: 0, currency: GBP }
    requires_approval: true
```

Unrecognised verbs are proposed as `irreversible`, because under-calling an
effect is the more expensive mistake.

## The manifest

Reachability needs three facts per tool that an ordinary tool schema does not carry: the effect class, which argument spends value, and which scope the ceiling is measured against.

```yaml
version: 1
agent: dispute-resolver
identity: spiffe://bank/agents/dispute-resolver

limits:
  total: { amount: 500, currency: GBP }
  depth: 8

tools:
  - name: open_case
    effect: read              # read | write | irreversible
    produces: case            # mints a binding of scope "case"

  - name: issue_refund
    effect: irreversible
    principal: caller         # caller | service
    requires: [case]
    value_arg: amount
    scope_key: case           # the ceiling is per case
    ceiling: { amount: 500, currency: GBP }
    requires_approval: true
```

Asking for full preconditions and postconditions would be more expressive and would not get written. This is the minimum that makes compound analysis possible.

A ceiling is the maximum **cumulative** value one tool may spend against one binding of its `scope_key`. `unbounded: true` marks a tool that can be called repeatedly to mint fresh bindings, which is what turns a per-scope ceiling into no ceiling at all.

## Commands

| Command | What it does |
|---|---|
| `mandate scan` | Derives a manifest skeleton from an MCP `tools/list` catalogue, with a `REVIEW` marker on every guess |
| `mandate lint` | Single-manifest control checks: separation of duties, ungated irreversible effects, service-account principals, ceilings scoped to nothing |
| `mandate reach` | Bounded search for a legal call sequence that breaches a limit, reported as a counterexample |
| `mandate diff` | Effective-authority comparison of two manifests, including limits, preconditions, approvals, effects, and scope minting. `--record` emits a change record |
| `mandate verify` | Replays recorded tool calls against the manifest and fails closed when evidence required by a declared control is missing. Reads [OpenTelemetry traces](https://github.com/mrwersa/agentmandate/blob/main/docs/traces.md) with `--otel` |
| `mandate obligations` | Derives reviewable test obligations from reachable authority, and renders reviewed ones as an [AgentVerity](https://github.com/mrwersa/agentverity) decision suite |
| `mandate scenarios` | Exports reachable breach paths with blank environment, agent-input, and expected-control fields for human review and execution by an external evaluation harness |

Every analysis command takes `--json` and exits non-zero on a finding, so they drop into CI unchanged. `scan` writes a manifest to standard output and is a one-off, not a gate.

| Exit code | Meaning |
|---|---|
| `0` | Clean |
| `1` | A finding: lint error, reachable breach, widening diff, or a non-conformant replay |
| `2` | Usage error or a malformed manifest |

In a pull request, the useful gate is `diff` against the manifest on the default
branch, so a change that widens authority stops and gets a named reviewer:

```yaml
- name: Authority diff
  run: |
    git show origin/main:mandate.yaml > /tmp/released.yaml
    mandate diff /tmp/released.yaml mandate.yaml
```

`verify` is what keeps the rest honest. A manifest nobody checks is a wish, and the declaration drifts from the implementation the moment someone ships a connector change.
For a spending tool, each trace record must carry the scope, value, currency,
approval state, and executing principal. Missing or malformed control evidence
does not pass as an empty value.

## From authority to evaluation

AgentMandate produces two different test inputs:

- `obligations` names consequential decision points that reviewed bounded
  decision tests should reach
- `scenarios` preserves compound counterexample paths that a multi-step
  scenario test should attempt

It does not execute either test. Promptfoo, LangSmith, AgentCore Evaluations,
pytest, or an internal harness owns behaviour and outcome grading. AgentVerity
can qualify the repeated bounded decisions after correctness passes.

```text
reachability -> reviewed obligations and scenarios -> external evaluation
      ^                                               |
      |                                               v
manifest <- reviewed production incidents <- runtime policy and traces
```

[Read the complete evaluation-loop workflow](docs/evaluation-loop.md).

## Where it fits, and what already exists

This is analysis, not enforcement. It runs in CI against a manifest, it does not sit in the request path.

| Tool | What it does | Relationship |
|---|---|---|
| [Policy in Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) | Evaluates all applicable Cedar policies for each gateway tool invocation, with default-deny, forbid-wins, and analysis that flags always-allow and always-deny policies | Enforces each invocation. Its documented analysis is policy-level, not a model of a sequence of permitted calls |
| [AgentWard](https://github.com/agentward-ai/agentward) | Runtime proxy enforcing policy per call, diffs two policy files | Enforces. Diffs declared text rather than reachable authority |
| [AgentShield](https://github.com/affaan-m/agentshield) | Scans agent configuration and MCP servers, drift gate over findings | Scans. Drift is over finding counts, not permission direction |
| [AgentGuard](https://github.com/WhitzardAgent/AgentGuard) | Attribute-based access control for tool calls | Enforces |
| [OPA](https://www.openpolicyagent.org/docs), [Cedar](https://docs.cedarpolicy.com/) | Decide one authorisation at a time | Enforces |

Use those to enforce. AgentMandate is the offline half: it analyses sequences of individually permitted calls and compares *effective* authority across releases.

**If you already run AgentCore Policy**, the gap is specific. The policy engine
answers "may this principal invoke this tool now" by evaluating all applicable
policies, and its documented analysis catches policy-level problems such as an
unconditional allow. It does not model whether four separately permitted calls
compose into a 1,000 GBP breach or whether a release widened what the agent can
reach. AgentMandate is vendor-neutral and runs in CI before deployment, so it
complements the gateway rather than duplicating it.

The closest prior art in a neighbouring domain is [IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-concepts.html), which derives reachable access from policy by automated reasoning rather than waiting for a log event. This is that idea pointed at agent tool graphs.

The `lint` command deliberately overlaps the scanners above. A tool that reported only compound findings would need one of them running alongside it to be usable at all.

## Scope

Read every finding as **permitted by the reviewed manifest within this bounded
abstraction**. It is not proof that the model will choose the path or that an
undeclared downstream invariant will accept it.

What this does not do, on purpose:

- **No enforcement.** No proxy, no runtime interception, no blocking.
- **No data-flow reachability.** Finding that a read tool feeds an exfiltration path needs taint labels the manifest does not carry. Cumulative value and scope minting are what the current model supports honestly.
- **No model behaviour.** Whether the agent *would* take a path is a different question from whether it *may*. This measures permission.
- **No inference of the fields that matter.** `mandate scan` reads an MCP catalogue and writes the skeleton, but it cannot know whether an effect is reversible or what a ceiling is measured against. It guesses conservatively and marks every guess `REVIEW`. Extract then annotate, never extract and trust.

Search is bounded by `limits.depth`. No breach at depth 8 is not proof that none exists at depth 20, and the report says when it truncated.

## Documentation

- [DESIGN.md](DESIGN.md) — the authority model, why the search is shaped this way, and what was left out
- [docs/evaluation-loop.md](docs/evaluation-loop.md) — how authority analysis, scenario evaluation, runtime policy, and production feedback remain distinct
- [docs/test-obligations.md](docs/test-obligations.md) — decision-point obligations and the AgentVerity bridge
- [CONTRIBUTING.md](CONTRIBUTING.md) — branch and review workflow
- [SECURITY.md](SECURITY.md) — reporting, and what a manifest may contain
- [STABILITY.md](STABILITY.md) — what is guaranteed before 1.0
- [ROADMAP.md](ROADMAP.md) — adoption work, planned model extensions, and the path to 1.0
- [CHANGELOG.md](CHANGELOG.md)

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest -q --cov=agentmandate --cov-fail-under=100
ruff check .
```

`main` is protected. Every change lands through a pull request with CI green.

## Status

Alpha, version 0.4.0. The authority model is the part most likely to change,
because it has not yet been pointed at enough real tool graphs to know where it
is too coarse. Issues describing a graph it models badly are the most useful
thing you can file.
