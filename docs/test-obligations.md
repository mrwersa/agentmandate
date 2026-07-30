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

Both `decision` and `cases` are blank on purpose. The command exits non-zero
until every row maps the authority fact to an application decision and carries
at least one probe written by a reviewer.

`irreversible on case` is an **authority fact**. `refund_approved` is an
**application label** somebody chose when designing the router. No parsing
turns one into the other, and inventing the mapping would be a confident guess
about someone else's domain. Extract then annotate, the same discipline `scan`
follows.

Identifiers are stable, so regenerating after a manifest change does not lose
the mapping work already done. Dropped authority disappears, while newly
reachable authority returns as unreviewed and blocks suite generation.

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
    {"input": "A customer disputes a duplicate charge of 40 GBP and asks for a refund.",
     "expected": "refund_approved"},
    {"input": "A supervisor is asked to approve a 480 GBP goodwill refund.",
     "expected": "refund_approved"},
    {"input": "A merchant chargeback for 120 GBP needs a refund decision.",
     "expected": "refund_approved"}
  ]
}
```

That file loads straight into AgentVerity. Irreversible and value-bearing
obligations become `critical` decisions; approval gates and service principals
are control concerns rather than consequence classes, so their decisions are
required but not critical.

Case inputs come from the review file. Authority analysis cannot invent a
probe that reaches an application decision, and placeholder text would let a
test runner produce impressive numbers about nothing.

## What does not cross the bridge

**Compound breaches.** A cumulative-value path is a multi-call sequence —
open a case, refund, open another, refund again. That is scenario testing, not
decision coverage, and pushing it into a decision suite would drag a test
adequacy tool into a job it does not do. Those findings stay out of the
decision suite. Use `mandate scenarios` to preserve the static witness as a
neutral scenario skeleton, then supply the environment, agent input, and
expected control boundary by human review. See the
[evaluation-loop guide](evaluation-loop.md).

**Correctness.** Neither tool judges whether a decision was right.
AgentMandate says what may happen; AgentVerity says whether the evidence is
repeatable and the contract was exercised. Whether `refund_approved` was the
correct answer is still yours.

**Tool execution.** Decision coverage shows that the reviewed decision point
was reached. It does not prove that a downstream refund tool ran or that its
approval and ceiling controls held. Use `mandate verify` on runtime records for
that separate claim.
