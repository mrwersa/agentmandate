# One export, three budget pools

This synthetic model charges every completed export one request and two compute
units alongside its variable record count. It is not deployment evidence.

From the repository root:

```bash
mandate reach examples/fixed-call-charges/manifest.json --json
mandate verify examples/fixed-call-charges/manifest.json --traces examples/fixed-call-charges/trace.jsonl --json
```

Both exit 1. Reach reports independent maxima of eight records, three requests
and six compute units at depth four; these do not all belong to one path.
The trace's exports of four, zero and zero records stay within the variable
ceiling but exceed request and compute budgets.

See the [fixed-charge guide](../../docs/fixed-call-charges.md) for exact semantics,
trace assumptions, comparison and repair behavior, and artifact boundaries.
