# AgentMandate

> **Compound-path and cross-release analysis of what an AI agent is permitted to do.**

[![PyPI](https://img.shields.io/pypi/v/agentmandate.svg)](https://pypi.org/project/agentmandate/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20--%203.14-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/mrwersa/agentmandate/actions/workflows/ci.yml/badge.svg)](https://github.com/mrwersa/agentmandate/actions/workflows/ci.yml)
[![Coverage: 100%](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](#development)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](https://github.com/mrwersa/agentmandate/blob/main/LICENSE)

Analyse what an AI agent is permitted to do, and what changed between two releases.

Agent security scanners check tools one at a time. That catches the tool with no approval gate and the one running as a service account, which is worth catching. It misses the defect where every tool passes review and a legal sequence of them does not.

AgentMandate answers two questions that need the whole graph:

- Is there a legal call sequence that breaches a limit, or that reaches an irreversible effect with no approval? `mandate reach` returns the sequence.
- Did this release widen what the agent can reach? `mandate diff` compares effective authority, not configuration text.

Alpha. Apache-2.0.

## Try it

```bash
pip install "agentmandate[yaml]"
```

A payment-dispute agent. Refunds are capped at 500 GBP per case, every refund is gated by human approval, the run limit is 500 GBP, nothing spends a service account. It passes:

```console
$ mandate lint examples/dispute-resolver.yaml
no single-manifest findings

$ mandate reach examples/dispute-resolver.yaml
no reachable breach within depth 8. 3 tool(s) reachable, most extractable 500 GBP
```

Now release v2, which adds one read-only tool so the agent can find existing cases instead of always opening a new one. It reads. It writes nothing. It goes through review as a read-only addition:

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

The lint is still clean, because no single tool is wrong. The ceiling was measured against a case, and the new tool lets the agent obtain cases at will, so the ceiling now bounds nothing. In CI:

```console
$ mandate diff examples/dispute-resolver.yaml examples/dispute-resolver-v2.yaml
authority diff  v1 -> v2
  + tool: gained search_cases
  + extractable value: 500 -> 2000 GBP
  + reachable breach: gained cumulative_value

verdict: WIDENING
a widening change needs named review before release
```

Exit code 1. The config diff was five lines and read-only. The authority diff was four times the money.

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
| `mandate verify` | Replays recorded tool calls against the manifest and fails closed when evidence required by a declared control is missing |

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

## Where it fits, and what already exists

This is analysis, not enforcement. It runs in CI against a manifest, it does not sit in the request path.

[AgentWard](https://github.com/agentward-ai/agentward) is a runtime proxy that enforces policy on each call and can diff two policy files. [AgentShield](https://github.com/affaan-m/agentshield) scans agent configuration and MCP servers, with a drift gate over scan findings. [AgentGuard](https://github.com/WhitzardAgent/AgentGuard) implements attribute-based access control for tool calls. [OPA](https://www.openpolicyagent.org/docs) and [Cedar](https://docs.cedarpolicy.com/) decide one authorisation at a time.

Use those to enforce. AgentMandate complements them by analysing compound sequences and comparing *effective* authority across releases. The closest prior art in a neighbouring domain is [IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-concepts.html), which derives reachable access from policy by automated reasoning rather than waiting for a log event. This is that idea pointed at agent tool graphs.

The `lint` command deliberately overlaps the scanners above. A tool that reported only compound findings would need one of them running alongside it to be usable at all.

## Scope

What this does not do, on purpose:

- **No enforcement.** No proxy, no runtime interception, no blocking.
- **No data-flow reachability.** Finding that a read tool feeds an exfiltration path needs taint labels the manifest does not carry. Cumulative value and scope minting are what the current model supports honestly.
- **No model behaviour.** Whether the agent *would* take a path is a different question from whether it *may*. This measures permission.
- **No inference of the fields that matter.** `mandate scan` reads an MCP catalogue and writes the skeleton, but it cannot know whether an effect is reversible or what a ceiling is measured against. It guesses conservatively and marks every guess `REVIEW`. Extract then annotate, never extract and trust.

Search is bounded by `limits.depth`. No breach at depth 8 is not proof that none exists at depth 20, and the report says when it truncated.

## Documentation

- [DESIGN.md](DESIGN.md) — the authority model, why the search is shaped this way, and what was left out
- [CONTRIBUTING.md](CONTRIBUTING.md) — branch and review workflow
- [SECURITY.md](SECURITY.md) — reporting, and what a manifest may contain
- [STABILITY.md](STABILITY.md) — what is guaranteed before 1.0
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

Alpha, version 0.1.0. The authority model is the part most likely to change, because it has not yet been pointed at enough real tool graphs to know where it is too coarse. Issues describing a graph it models badly are the most useful thing you can file.
