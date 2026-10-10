# Check named acceptance of an authority change

Use `mandate review BEFORE AFTER` when CI needs to check a recorded acceptance
of authority widening. The command recomputes the ordinary diff, then checks
whether a supplied decision matches those exact inputs and has eligible evidence
and dates. It never removes a change or breach from the authority result.

This is a **review-record gate**. Exit 0 means no named review is required within
the comparison bound, or the supplied acceptance is eligible. It does not
authenticate the reviewer, establish runtime enforcement or approve deployment.
Continue running `lint`, `reach` and application tests as separate checks.

## Try the synthetic release decision

The example changes a bounded producer into one that can mint fresh bindings.
It widens reachable spend from £5 to £10 and introduces a cumulative breach.
Inspect the materials needing review:

```bash
mandate review examples/change-review/before.json examples/change-review/after.json --as-of 2026-10-10 --json
```

This exits 1 and reports `review.decision-missing`. Its `inputs` identify both
manifest byte digests, the computed comparison digest and the selected depth.
The [synthetic decision](../examples/change-review/accepted.json) matches them:

```bash
mandate review examples/change-review/before.json examples/change-review/after.json --decision examples/change-review/accepted.json --source review-note=examples/change-review/decision-note.txt --as-of 2026-10-10
```

This exits 0 with `eligible_recorded_acceptance`. The same output still shows
the widening and breach. `mandate diff` on those files and `mandate reach` on
the proposed file both continue to exit 1. Acceptance of a change is a separate
decision from whether its resulting authority meets a mandate's limits.

Replace the date with `2026-11-09` to see expiry refuse the record. Use
`examples/change-review/deferred.json` to see a deferred decision refuse it.
These records are explicitly synthetic; they supply no acceptance for a real
application, historical capture or deployment.

## Record the human decision

The strict UTF-8 JSON record has exactly these fields:

| Fields | Meaning |
|---|---|
| `schema` | `agentmandate.change-review/v1` |
| `agent` | Proposed manifest's agent, which must match the baseline agent |
| `before_sha256`, `after_sha256` | Lowercase SHA-256 of the exact files reviewed |
| `comparison_sha256`, `depth` | Digest of the recomputed diff and its positive integer depth |
| `scope` | Exactly `all_widening_changes_in_pinned_comparison` |
| `owner`, `reviewer`, `reason` | Caller-supplied names and explanation of the decision |
| `decision` | `accept`, `reject` or `defer`; only `accept` can satisfy the gate |
| `reviewed_at`, `expires` | Strict `YYYY-MM-DD`, with expiry on or after the review date |
| `evidence` | Nonempty list of exact byte references supporting the decision |
| `target_policy` | Recorded policy disposition, with its own reason |

Every evidence entry has exactly `locator`, `sha256` and `purpose`. A locator
is an opaque, unique label; it must not contain `=`. The digest is lowercase
SHA-256 and the purpose is `decision` or `target_policy`. At least one entry
must have purpose `decision`. Map every declared label explicitly using
`--source LOCATOR=CAPTURE`; no URLs are followed or paths inferred from labels.
Missing, duplicate or undeclared mappings are usage errors. The capture path
may contain `=`; the first `=` separates the label from that path.

`target_policy` has exactly `status` and `reason`:

- `evidence_recorded` requires at least one `target_policy` evidence entry.
  It means those bytes were supplied and match, not that the library verified
  a deployed enforcement system or the evidence's conclusions.
- `not_applicable` requires an explicit reason. It is the author's disposition,
  not a fact the library establishes about the deployment.
- `unresolved` retains a finding and cannot satisfy the review gate.

Names, labels and reasons must be nonblank strings without newline, carriage
return or NUL. Unknown fields, duplicate JSON keys, unsupported scopes/statuses,
boolean depths and malformed dates/digests are refused. There is no partial
acceptance of selected changes in this contract. Owner and reviewer names do
not establish their identities, independence or authority to approve.

The comparison digest is SHA-256 of the ordinary `Delta.as_dict()` encoded as
UTF-8 JSON with sorted keys, separators `(',', ':')` and default ASCII escaping.
Take it from the first report after reviewing the complete comparison. The
result also pins the decision file's own exact bytes. A comment or whitespace
edit to a manifest invalidates its byte join even if the diff is identical.
Changed depth, changed findings or a future analyzer change that alters the
comparison requires a newly matching review. Never refresh hashes merely to
clear the gate.

## Read the gate result

JSON uses `agentmandate.review/v1`. `comparison` is the unchanged ordinary diff,
including both Authority results, all changes, breach witnesses and truncation.
`inputs` contains the computed materials; `review` retains the caller's record,
its byte digest, per-source digest checks and computed `eligible` flag.
`scope` and `review.attestation` state the claim's limits inline.

The command requires an explicit `--as-of YYYY-MM-DD` and never reads the clock.
Both review and expiry dates are inclusive UTC dates. A future decision,
expired record, rejected/deferred decision, wrong join, changed source bytes or
unresolved policy disposition produces findings and exits 1. Failures remain
separate: an expired record with changed evidence retains both findings.

A neutral or narrowing comparison without a record exits 0 with
`review_not_required_within_bound`. Supplying a record still checks it;
nonwidening does not excuse an expired or rejected supplied decision.
Malformed records, I/O failures, invalid dates/depths and incomplete mappings
exit 2 with empty stdout. Valid finding results exit 1 with complete output.
The existing `diff` output and exit contract are unchanged.

## Establish trust outside the record

A contributor who can replace the decision, its sources and the CI invocation
can fabricate a matching acceptance. Digests identify bytes; they do not
authenticate who chose them or whether the evidence is persuasive. Do not use
unreviewed files from a pull request as their own approval.

The integration must authenticate the human decision, authorize its owner and
reviewer, and protect the workflow and selected review materials. For example,
load decisions from a protected review ref, with enforced owner review, and
bind them to the candidate's exact files. Supply the evaluation date from
trusted CI using UTC; accepting a contributor's backdated `--as-of` bypasses
expiry. The library provides no signature verifier, GitHub-approval lookup,
network authentication or permission to send decisions elsewhere.

Pinned target-policy bytes do not establish live mediation or durable state.
Application behavior, deployment identity and approvals, runtime continuity
and unmodeled authority changes still require separate checks. The gate does
not renew itself and cannot reuse historical continuity acceptance.

## Compatibility

The CLI and input/result contracts are public; `_change_review` Python helpers
are private. The five [result baselines](../tests/fixtures/change-review-accepted-v1.json)
cover accepted, expired, missing, neutral and deferred decisions. These are v1
baselines, not migrations from an earlier review-result schema. Existing CLI
results, root Python exports and historical inventory bytes remain unchanged.
Use the [CI guide](ci.md#named-review-records) for integration alongside the
ordinary analysis gates.
