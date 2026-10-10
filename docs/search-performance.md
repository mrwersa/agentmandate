# Search bounds and performance

Use `--depth` to bound a reachability run by modeled calls. It does not bound
elapsed time, memory, or the number of states. Independent tools and fresh
resource bindings can make the state space grow quickly even at a small depth.
The measured corpus below makes that distinction concrete.

This guide covers the manifest-v1 search kernel, including the private finite
producer-cap input. Attachment validation, file parsing, Authority IR
construction, and multiple searches performed by `diff` or other consumers add
their own costs. It does not certify a whole command pipeline or provider run.

## What the depth and truncation fields mean

The kernel uses breadth-first search. It starts at depth zero, expands states
whose shortest path has fewer than `D` calls, and records transitions through
call `D`. Consequently, a breach on call `D` is reported. A newly discovered
state at depth `D` is retained but not expanded, and sets `truncated: true`.

The flag means the walk reached its boundary. It does not prove that an
additional tool or breach exists beyond it: the cutoff state might have no new
successor. Conversely, reaching no boundary makes the walk exhaustive for this
declared abstraction, not for unmodeled runtime behavior. Read-only calls that
change no tracked state and transitions to already seen states are not queued.
Tool order breaks ties between equally short enabling paths and witnesses.

`reach` retains its existing exit contract: a reachable breach exits 1;
truncation alone does not. A clean bounded result can therefore exit 0 with
`truncated: true`. A release gate needing an exhaustive model result must check
the JSON flag as well as the exit code. The separate scalar handover command
already requires clean, untruncated Authority before exit 0.

## Conservative state-space bound

Let `T` be the number of tools and `D` the chosen depth. Each expanded state
generates at most one candidate per tool: the current kernel chooses one
binding greedily rather than branching over all possible request amounts.
Every visited state has an enabling sequence of at most `D` calls, so:

```text
S <= 1 + T + T² + ... + Tᴰ
```

The [maximum-headroom argument](headroom-abstraction.md) explains when that
single monetary choice preserves the bounded maximum and breach result. It
does not equate the greedy and exhaustive searches' state sets or truncation.

This bounds distinct discovered states, including the start and cutoff states.
It is a worst-case ceiling, not an estimate of practical work. Canonicalization,
disabled tools, repeated states, and producer caps usually make it much looser
than the actual state count.

A second conservative ceiling follows from the representation. Let `R` be
distinct produced scope types, `E` declared effect-budget classes, and `V`
value-spending tools. Scope and effect counts each have at most `D+1` values.
There are at most `V*D` tool/binding spend slots; the value in each slot follows
the deterministic greedy-fill rule, with at most `D` updates. Under the fixed
numeric context of one search, each slot therefore has at most `D+1` values
including absence. Thus:

```text
S <= min(sum(Tᵏ, k=0..D), (D+1)^(R + E + V*D))
```

The study checks observed states against this bound. The bound relies on the
current deterministic transition rule; adding arbitrary amounts or binding
choice would require a new argument. No public API computes or promises to
allocate this ceiling in advance.

## Memory and time costs

Let `B` be reported breaches and `S` visited states. Each state stores at most
`O(D)` count/spend records: one call can add at most one scope, one spend slot,
and one effect count. The seen set retains these states. Frontier nodes share
parent links, and paths are materialized only for enabling paths and findings.
Storage in record units is therefore:

```text
O(S*D + S + (T+B)*D)
```

Earlier search code stored a full path tuple in every queue entry. With peak
frontier size `Q`, that added up to `O(Q*D)` path references. Parent links remove
that repeated prefix storage; they can retain ancestors, so this is not a claim
that queue length alone describes memory. Private states also use slots to
avoid per-instance dictionaries. Public `Authority`, `Breach`, and `Step`
records retain their existing representation.

For time, there are at most `S*T` tool checks. Let `A` be the maximum number of
required scopes on one tool. Requirements scan held scope counts; binding
selection can scan up to `D` bindings and `D` spend records; updates sort at
most `O(D)` records; finding de-duplication scans up to `B` breaches. A
conservative unit-cost bound is:

```text
O(S*T*(A*D + D² + D*log(D+1) + B) + (T+B)*D)
```

Numeric precision, integer sizes, tool names, and Python object overhead affect
the actual byte and operation costs. These formulas count records and ordinary
operations, not constant-size arbitrary-precision arithmetic. Depth alone
does not give a useful hard process memory or latency guarantee.

## Reproduce the study

Install the development extras, then run from the repository root:

```bash
python scripts/benchmark_search.py --repeat 5 --compare-baseline --output /tmp/search-study.json
```

Baseline comparison needs Git and the pinned predecessor commit recorded in
[`search-baselines.json`](../tests/fixtures/search-baselines.json). The harness
verifies that source digest before loading its code. A shallow checkout can
run without `--compare-baseline`; it still checks current Authority and enabling
paths against the pinned pre-change digests. `--case agentkit` selects that
graph's five depths; `--case wide-mint` selects a synthetic stress case.

There are 25 real-graph runs: AgentKit, GitHub MCP, AWS PostgreSQL, Sentry, and
Initiative at depths 1, 2, 4, 8, and 12. Five additional synthetic cases cover
wide fresh-scope production, a 64-call chain, duplicate bindings, pure reads,
and a finite producer cap. These synthetic cases do not count as new real
graphs or reviewed operational evidence.

The [recorded report](search-performance-results.json) pins input, baseline,
current kernel, and harness digests, Python/platform details, work counters,
counterexample lengths, truncation, five elapsed-time samples per kernel, and
peak traced Python allocation. Timing uses `perf_counter_ns`; allocation
measurement is a separate run under `tracemalloc`. Input loading and result
serialization are excluded. Allocation peaks are not RSS or a memory ceiling.
Timed kernel order alternates; measurements are observations on this machine,
not CI performance thresholds or guarantees for another workload.

The measured results and practical guidance below belong to the report's pinned
kernels; performance changes or corpus changes require rerunning the study.
The later exact-arithmetic wrapper is covered by semantic replay and a fresh
study recorded in [the arithmetic follow-up](search-arithmetic-results.json).
It retains all 30 Authority/provenance fingerprints and the same 20/25 real-graph
truncation count, with three timing samples per kernel. Small workloads still
have mixed timing and allocation changes; the earlier table remains a historical
measurement of its pinned kernels. Output matching checks behavior, not
operational truth of the reviewed graph annotations.

## Recorded measurements

This CPython 3.12.3 run on Linux/WSL2 compared the revised kernel with the
digest-pinned search in the `0.21.0` merge commit. At the default depth 8:

| Graph | States | Peak frontier | Median ms, before → after | Peak KiB, before → after | Witness calls | Truncated |
|---|---:|---:|---:|---:|---|---|
| AgentKit | 4,537 | 2,045 | 200.302 → 192.753 | 3062.6 → 2689.5 | 3 | yes |
| GitHub MCP | 9 | 1 | 0.453 → 0.436 | 18.3 → 17.4 | none | yes |
| AWS PostgreSQL | 9 | 1 | 0.227 → 0.226 | 12.8 → 12.0 | 3 | yes |
| Sentry | 9 | 1 | 0.242 → 0.216 | 12.6 → 12.1 | 2 | yes |
| Initiative | 1 | 1 | 0.115 → 0.125 | 13.3 → 13.4 | 1 | no |

Four of five graphs truncate at depth 8; 20 of the 25 graph/depth cases
truncate overall. This is a frequency over this fixed depth sweep, not an
estimated probability of truncation in production. Effect-budget counters can
keep creating states even after the first breach is found, so a known short
counterexample does not imply an exhaustive walk.

AgentKit grows from 4,537 states at depth 8 to 31,472 at depth 12. Its measured
allocation peak falls 12.2% at depth 8 and 7.3% at depth 12; the wide synthetic
frontier falls 14.1%. The finite-cap synthetic case visits 243 states instead
of 6,188 for its unbounded counterpart. These improvements retain every pinned
Authority result and shortest enabling path.

Small workloads have mixed timing changes and can allocate slightly more
with the parent-linked representation. The report supports a lower allocation
peak on the broad frontiers measured here, not a universal speedup. No timing
or memory threshold is asserted in CI.

## Practical CI use

Keep the chosen depth explicit and record truncation. Increase depth on the
same input to study sensitivity; do not infer completeness from a flat maximum
or an unchanged breach count. Capture timeouts and memory exhaustion as an
incomplete analysis in your CI wrapper. The kernel has no cancellation,
state-count cap, wall-clock budget, or hard memory ceiling and cannot emit a
complete partial result if the process is killed. Enforce those resource limits
outside the process and preserve its failure status.

For an exhaustive-model gate, save JSON only after a successful analysis and
require both no breaches and `truncated == false`. For a bounded regression
gate, review the chosen depth and keep truncation visible rather than calling
it a proof about all execution lengths. This distinction changes no existing
command or artifact contract. The implementation/study is tracked in
[#226](https://github.com/mrwersa/agentmandate/issues/226); independent review
is required before recording the 1.0 search criterion complete.
