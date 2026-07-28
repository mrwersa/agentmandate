# From authority to test obligations

A mandate says what an agent is permitted to do. A test suite says what was
actually exercised. Nothing connects the two, so a manifest can declare an
irreversible refund that no test ever approaches, and both artefacts look
healthy.

```text
  agentmandate                                    agentverity
  ────────────                                    ───────────
  reachable authority
        │
        │  mandate obligations
        ▼
  test obligations  ──▶  human review  ──▶  decision suite
  (what must be                (map each        (what gets
   exercised)                   to a decision)   measured)
```

## Derive

```console
$ mandate obligations examples/dispute-resolver.yaml
test obligations for dispute-resolver
  irreversible:issue_refund
    why:      an irreversible effect is reachable, so some reviewed case
              should exercise the decision that leads to it
    decision: REVIEW: map a decision
  approval-required:issue_refund
    why:      an approval gate is reachable, and a gate no test reaches has
              never been shown to hold
    decision: REVIEW: map a decision
  value-bearing:issue_refund
    why:      this call spends value up to 500 GBP, so the decision that
              authorises it deserves reviewed cases
    decision: REVIEW: map a decision

3 obligation(s) need a reviewed decision before a suite can be generated
```

Obligations follow **reachability**, not declaration. A tool nobody can get to
needs no test, and listing it would pad the review with work that protects
nothing.

| Kind | Raised when |
|---|---|
| `irreversible` | A reachable effect that cannot be undone |
| `approval-required` | A reachable approval gate |
| `service-principal` | A call spending a service account rather than the caller |
| `value-bearing` | A call that spends money, with its ceiling named |

## Review

The `decision` field is blank on purpose and the command exits non-zero until
every row is filled.

`irreversible on case` is an **authority fact**. `refund_approved` is an
**application label** somebody chose when designing the router. No parsing
turns one into the other, and inventing the mapping would be a confident guess
about someone else's domain. Extract then annotate, the same discipline `scan`
follows.

Identifiers are stable, so regenerating after a manifest change does not lose
the mapping work already done.

## Generate

```console
$ mandate obligations mandate.yaml --reviewed reviewed.json --suite > suite.json
```

```json
{
  "schema": "agentverity.decision-suite/v1",
  "contract": {
    "allowed": ["refund_approved"],
    "required": ["refund_approved"],
    "critical": ["refund_approved"]
  },
  "cases": [
    {"input": "REVIEW: write a case that reaches refund_approved",
     "expected": "refund_approved"}
  ]
}
```

That file loads straight into AgentVerity. Irreversible and value-bearing
obligations become `critical` decisions; approval gates and service principals
are control concerns rather than consequence classes, so their decisions are
required but not critical.

Case inputs are left blank. A probe that reaches a decision is a piece of
domain writing, so the suite ships the shape and leaves the writing.

## What does not cross the bridge

**Compound breaches.** A cumulative-value path is a multi-call sequence —
open a case, refund, open another, refund again. That is scenario testing, not
decision coverage, and pushing it into a decision suite would drag a test
adequacy tool into a job it does not do. Those findings stay in `mandate reach`.

**Correctness.** Neither tool judges whether a decision was right.
AgentMandate says what may happen; AgentVerity says whether the evidence is
repeatable and the contract was exercised. Whether `refund_approved` was the
correct answer is still yours.
