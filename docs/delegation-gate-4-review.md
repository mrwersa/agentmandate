# Delegation Chains Gate 4 Review

Status: **approved for CLI exposure**. The public-boundary review was
reproduced against `1a5e35c` on 28 August 2026. Its tree is byte-identical to
the merged commit `d0c136b`:

```text
$ git rev-parse '1a5e35c^{tree}' 'd0c136b^{tree}'
2049d2f2414752c6ddc9d8b16e00ad99623859bf
2049d2f2414752c6ddc9d8b16e00ad99623859bf
```

Structural validity remains separate from authority. Parsing an attachment or
chain does not make its evidence eligible for attenuation analysis.

## Decision summary

| Review | Verdict | Evidence |
|---|---|---|
| Structural validation | Passed | Valid attachment and chain artifacts exit 0; malformed or missing artifacts exit 2 with empty stdout |
| Trusted attenuation | Passed | Exact, accepted, current, digest-verified synthetic surfaces produce an `ATTENUATED` decision |
| Conservative failure | Passed | Unknown surfaces, duration-only validity, expired windows, partial actor history, and unverifiable captures remain unresolved and exit 1 |
| Widening detection | Passed | Trusted synthetic fixtures detect both tool-to-hop and hop-to-hop surface expansion; untrusted evidence never produces `delegation.widens` |
| Output stability | Passed | Namespaced JSON preserves decisions, findings, and provenance; its canonical fixture is digest-pinned and legacy reach output is unchanged |
| Unsupported composition | Passed | SARIF, Mermaid, Authority IR, and conditional composition fail before output rather than dropping delegation uncertainty |

## Closing verdict

**All four delegation-chain gates passed.** The real CLI reproduced structural
validation, clean synthetic attenuation, unresolved Authorizer evidence,
exclusive expiry, complete-output finding exits, and no-partial-output usage
failures. The suite passed with 1,036 tests and 100% statement coverage. Ruff,
evidence-digest lint, and whitespace checks were clean.

The public surface is deliberately explicit:

```text
mandate delegations validate --attachment ATTACHMENT
mandate delegations validate --chain CHAIN
mandate reach MANIFEST \
  --delegation-attachment ATTACHMENT \
  --delegation-chain CHAIN \
  --delegation-capture LOCATOR=CAPTURE \
  --delegation-as-of UTC_TIMESTAMP \
  --delegation-target-source SOURCE \
  --delegation-target-binding BINDING
```

`delegations validate` establishes transport and structural validity only.
`reach` re-reads the records, projects and validates their closed Authority IR
profiles, verifies caller-supplied capture bytes, selects one declared source
binding, and evaluates half-open validity windows at the supplied timestamp.
The command does not follow locators, read the wall clock, validate tokens, or
contact an identity provider or resource server.

## Reproduced trust matrix

The clean attenuation fixture is intentionally synthetic. Every hop has an
absolute validity window and complete, reviewed scope, tool, and effect
surfaces. The attached `export_records` tool fits the terminal hop and returns
an `ATTENUATED` decision with exit 0. Synthetic widening fixtures independently
prove that scope recovery between hops and a tool exceeding its attached hop
produce `delegation.widens`.

The real Authorizer capture remains unresolved, as required:

- its four ordered actor-bearing OAuth hops and decreasing scopes are retained;
- duration validity cannot establish whether a token is live at an absolute
  evaluation timestamp;
- OAuth scope evidence does not establish deployment tool or effect policy;
- unknown tool and effect surfaces are not treated as empty surfaces;
- no operational scope-to-tool mapping is inferred from the demo application.

Every weaker trust state remains observable. A window is current only when
`issued_at <= as_of < expires_at`; equality at expiry is unresolved. One
partial actor history taints every chain-derived decision. Missing,
digest-mismatched, non-exact, non-accepted, expired, cross-domain, or
source-mismatched evidence produces a named unresolved finding and never a
widening claim or silent omission. Capture failures name the reviewed locator.

AgentKit, GitHub MCP, AWS PostgreSQL, and Sentry retain byte-identical authority
results when delegation inputs are absent.

## Output and interface contract

Human output uses a separate `ATTENUATED`/`WIDENS`/`UNRESOLVED` section. JSON
adds `delegations` only when delegation inputs were supplied. The object names
`agentmandate.delegations/v1`, records the explicit timestamp, separates
attenuated decisions from findings, and carries replay support for each item.
Reach exits 1 for either a reachable breach or a delegation finding, after
emitting the complete requested output.

Capture arguments use `LOCATOR=PATH` mappings rather than the positional
pairing used by condition contexts. A delegation chain may cite several long
locators shared across attachments or chains, so named mappings avoid
order-dependent associations. Duplicate mappings with different bytes,
missing reviewed locators, and undeclared locators are usage errors.

SARIF and Mermaid currently represent breach paths, not delegation hops and
unresolved evidence. Authority IR v1 cannot compose a standalone delegation
profile with a manifest snapshot, and condition output cannot yet express
delegation findings. These combinations return exit 2 with empty stdout;
partial rendering would imply analysis the format cannot preserve.

## Release and non-goals

The new command, reach options, Authority IR relations, strict delegation
artifacts, and presentation schema require a minor release under
`RELEASING.md`. The implementation is ready for the next minor release train
after this review record merges.

This initiative does not verify token signatures, issue or exchange tokens,
infer deployment policy from OAuth scopes, build an identity provider, expose
the private Python records, or add delegation-aware SARIF or Mermaid output. A
real operational scope-to-tool/effect mapping is still required for the first
non-synthetic widening counterexample.
