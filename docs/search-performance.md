# Search bounds and performance

Use `--depth` to bound a reachability run by modeled calls. It does not bound
elapsed time, memory, or the number of states. Independent tools and fresh
resource bindings can make the state space grow quickly even at a small depth.
The measured corpus below makes that distinction concrete.

This guide covers the manifest-v2 search kernel, including the private finite
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
single quantity amount choice preserves the bounded maxima and budget-breach
results. It does not equate the greedy and exhaustive searches' state sets or truncation.

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

## Reproduce the current study

From the repository root with development extras installed:

```bash
python scripts/benchmark_search.py --repeat 3 --output /tmp/search-study.json
```

The harness checks the current quantity-model Authority and enabling paths
against [`search-baselines.json`](../tests/fixtures/search-baselines.json).
It does not load a historical kernel or need Git. `--case agentkit` selects
that graph's five depths; `--case wide-mint` selects a synthetic stress case.

The corpus has 25 graph/depth runs: AgentKit, GitHub MCP, AWS PostgreSQL,
Sentry and Initiative at depths 1, 2, 4, 8 and 12. Their manifest-v2 annotations
are labelled test projections of the preserved source graphs, not new captures
or transferred evidence acceptance. Five synthetic cases cover a broad frontier,
a 64-call chain, duplicate bindings, pure reads and finite producer capacity.

The [current report](search-performance-results.json) records input, kernel,
harness and baseline digests, environment, work counters, witness lengths,
truncation, three timing samples and a separately measured tracemalloc peak.
Input loading and serialization are excluded. Traced peaks are not RSS or a
hard memory ceiling. These are observations on one machine; CI asserts no timing
or allocation threshold. Earlier before/after optimization measurements remain
recoverable in Git and are not a compatibility path in the current harness.

At the default depth eight in this run:

| Graph | States | Peak frontier | Median ms | Peak KiB | Witness calls | Truncated |
|---|---:|---:|---:|---:|---|---|
| agentkit | 4,537 | 2,045 | 172.053 | 2723.0 | 3 | yes |
| github-mcp-server | 9 | 1 | 0.520 | 18.3 | none | yes |
| aws-postgres-mcp | 9 | 1 | 0.234 | 12.8 | 3 | yes |
| sentry-mcp | 9 | 1 | 0.288 | 13.0 | 2 | yes |
| initiative-mcp | 1 | 1 | 0.188 | 14.4 | 1 | no |

Four of five graphs truncate at depth eight; 20 of 25 graph/depth runs truncate
overall. This is a frequency over the fixed sweep, not a production probability.
Effect counters can keep producing states after the first breach; a short
counterexample does not imply an exhaustive walk. The finite-cap synthetic case
visits 243 states, compared with 6,188 for its unbounded counterpart.

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
