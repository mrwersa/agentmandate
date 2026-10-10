# A recorded acceptance does not clear a breach

`before.json` allows one £5 binding. `after.json` lets `seed` mint fresh
bindings, reaching £10 in four calls despite a £5 run limit.

```bash
mandate review examples/change-review/before.json examples/change-review/after.json --decision examples/change-review/accepted.json --source review-note=examples/change-review/decision-note.txt --as-of 2026-10-10
mandate diff examples/change-review/before.json examples/change-review/after.json
mandate reach examples/change-review/after.json
```

The review gate exits 0. The unchanged diff and reach commands exit 1.
The acceptance is explicitly synthetic and covers the bounded comparison only;
it is not deployment approval. Using `--as-of 2026-11-09` makes it expired and
the review gate exits 1 too. `deferred.json` demonstrates a non-accepted record.

Read the [contract and trust boundary](../../docs/change-review.md) before
adopting this gate. Review sources and the UTC evaluation date must come from
a trusted workflow; named strings and matching hashes do not authenticate a
human or prove that an enforcement policy works.
