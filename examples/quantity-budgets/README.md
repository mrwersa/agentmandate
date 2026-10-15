# Records and tokens in one mandate

From the repository root:

```bash
mandate reach examples/quantity-budgets/manifest.json --json
```

Exit 1 is expected: the search finds separate record and token budget breaches.
Their maxima are not summed and may come from different paths. See the
[quantity guide](../../docs/quantity-budgets.md) for accounting and scope.
