# Synthetic search workloads

These shaped manifests measure the search implementation. They are not new
real authority graphs or accepted provider evidence.

| Input | Purpose |
|---|---|
| `wide-mint.json` | Five independent unbounded producers create a broad frontier |
| `deep-chain.json` | A 64-call dependency chain exercises iterative path reconstruction |
| `duplicate-binding.json` | Two producers reach one canonical state; a pure read adds no state |
| `pure-read.json` | A reachable read leaves only the initial state |

The study also runs the wide workload with a private cap of two bindings per
producer. That exercises the existing capped kernel; the synthetic cap is not
an accepted runtime producer boundary.

Run `python scripts/benchmark_search.py --compare-baseline` from the repository
root. See [search bounds and performance](../../docs/search-performance.md) for
scope, measurements, and practical limits.
