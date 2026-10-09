# Reviewed accounting across principals

Use this experimental binding when a reviewer can establish that calls by
different authenticated principals belong to the same mandate run. A session
identifier alone cannot establish that relationship. Without a binding,
[principal observations](principal-continuity.md) keep their existing v1 result.

The binding supports one question: do the distinct, observed completed calls
in each trial exceed the manifest's total monetary limit? It does not resolve
provider state continuity, admission, or safe continuation. Reconciliation
therefore still exits 1, even when the observed amount is below the limit.

## Try the synthetic example

From a repository checkout with AgentMandate installed:

```bash
mandate continuity validate examples/principal-continuity/accounting-binding.json
mandate continuity reconcile examples/principal-continuity/manifest.json \
  --continuity-provider examples/principal-continuity/profile.json \
  --continuity-source observations.json=examples/principal-continuity/observations.json \
  --continuity-binding examples/principal-continuity/accounting-binding.json \
  --continuity-binding-source accounting-review.json=examples/principal-continuity/accounting-review.json \
  --continuity-as-of 2026-10-09T12:00:00Z --json
```

Validation exits 0. Reconciliation exits 1 and reports:

| Trial | Shared completed amount | Compared with GBP 1,000 |
|---|---:|---|
| Changed principal, same session | 1,200 | Exceeded |
| Same principal, fresh session | 1,200 | Exceeded |
| Same principal, same session | 600 | Not exceeded by the observed calls |

The example's identities, binding, review, and source material are explicitly
synthetic. Removing the two binding flags restores the original observation
result, including its refusal to sum across principals. No historical capture
has acquired a binding or a new acceptance through this feature.

## Review before use

The observation profile and the accounting binding require separate exact,
accepted, unexpired reviews and matching source bytes. A binding reviewer must
check:

1. Each principal alias maps to an authenticated subject and the selected
   manifest tool's principal role. Subject names are local evidence aliases,
   not credentials or account identifiers.
2. All calls within each trial belong to one mandate run and one budget,
   across the observed principal and session changes. Trials are independent
   runs, never pieces of an aggregate total.
3. The provider boundary and deployment actually associate the captured calls
   with that intent. The mediation claim covers every listed call. Changes to
   policy configuration or counter selection must not be hidden by a stable
   session or boundary alias.
4. Each captured occurrence identifies a distinct execution or refused
   attempt. Request IDs are insufficient. Repeated observations of one
   execution must be removed before authoring this format; it has no deduplication
   algorithm. The amount, completion classification, tool contract, value
   argument, and currency must agree with the pinned sources and manifest.

The reader checks structure, exact joins, review status, expiry, and hashes.
It does not authenticate a reviewer, parse provider-specific identity proofs,
verify signatures, or prove the truth of the review. An accepted binding is a
reviewed attestation, not a cryptographically verified provider binding.

## Binding contract

The strict marker is `principal_accounting_binding_version: 1`. All fields
below are required; unknown fields and versions are rejected.

| Field | Contract |
|---|---|
| `id` | Nonempty binding identifier |
| `manifest_sha256` | Digest of the exact supplied manifest bytes |
| `profile_sha256` | Digest of the canonical principal profile, including its review metadata |
| `provider`, `boundary` | Exact matches to the observation profile |
| `measurement` | `profile_tool`, `manifest_tool`, `value_arg`, `dimension`, `unit`; maps the observed tool to a manifest value-spending tool without conversion |
| `limit` | Nonnegative integer `amount`, `unit`, `comparison: inclusive`, `scope: per_trial_run`; must equal `limits.total` in the manifest |
| `intent` | `kind: shared_mandate_per_trial`, a nonempty `statement`, and binding `sources` references |
| `mediation` | `kind: complete` or `unknown`, and binding `sources` references; unknown cannot authorize accounting |
| `principals` | Exactly the profile's aliases, each with `alias`, `subject`, `manifest_principal`, and binding `sources` references |
| `trials` | Exactly the profile's trial IDs, each with `id`, a distinct `account`, binding `sources`, and `executions` |
| `sources`, `evidence` | Existing continuity source and review records; supplied independently from observation sources |

Each execution has `source`, `pointer`, and `id`. Source and pointer identify
an observation-profile call. Every call must have exactly one entry; entries
outside the profile are refused. Execution IDs are unique across the binding,
including refused attempts. Accounts are unique across trials. IDs and account
names are reviewed local aliases; uniqueness of strings does not establish
uniqueness of real executions or budgets.

Canonicalization sorts sources, principal mappings, trials, and execution
mappings. It does not reorder the observation calls. The profile digest pins
the complete canonical profile rather than its original JSON formatting.

This first binding supports integer monetary observations in `dimension: value`,
one manifest tool and currency, and an inclusive manifest total per run. It
does not support cost conversion, multiple mandates in one trial, effect counts,
policy amendments, rolling windows, or reconstructing an initial balance.

## Result contract

Binding input selects `agentmandate.principal-accounting/v1`; it does not change
`agentmandate.principal-continuity/v1`. The result retains all observation fields
and the full independent manifest Authority analysis. It adds the canonical
binding digest, the complete binding, `binding_eligible`, and per-trial
`accounting` records.

With eligible observations, a current binding, matching joins, and known
completion for every call in the trial, accounting reports the shared completed
amount and limit. `budget: exceeded_by_observed_calls` means this observed subset alone exceeds
the limit. `not_exceeded_by_observed_calls` says nothing about missing earlier
spend, reservations, other tools, future admissions, or safe continuation.
It is not a compliance verdict. Equality is within an inclusive limit.

Unknown completion withholds that trial's total. Any global trust or binding
join gap withholds all shared totals, while preserving the per-principal
observations. An eligible trial has `mandate_identity: bound_by_review`;
`state`, `admission`, and `safe_continuation` remain unresolved in every case.

Summation does not require temporal order. The original `ordering` field and
session uncertainty remain visible; this consumer neither repairs clocks nor
turns attested program order into independently verified order.

Malformed bindings, missing or extra source locators, unsupported binding/profile
combinations, and I/O errors exit 2 with empty stdout. Digest, review, expiry,
mediation, and semantic join failures produce complete unresolved output and
exit 1. No binding is inferred or synthesized from historical acceptance.

`binding_eligible` describes the binding's own sources, review, and joins;
it can remain true when observation review has expired. A shared total requires
both eligibility flags and known completion. Finding codes distinguish
`continuity.accounting-source-untrusted`,
`continuity.accounting-evidence-untrusted`, and
`continuity.accounting-binding-mismatch`. A withheld trial also retains
`continuity.shared-mandate-unresolved`. An observed breach adds
`continuity.observed-budget-exceeded`; every result retains
`continuity.continuation-unresolved`.

## Compatibility and remaining work

The [example binding](../examples/principal-continuity/accounting-binding.json)
round-trips through its strict reader. Complete
[eligible](../tests/fixtures/principal-accounting-result-v1-eligible.json) and
[expired](../tests/fixtures/principal-accounting-result-v1-expired.json) results
are fixed CLI baselines in `tests/test_principal_accounting.py`. The existing
observation v1 baselines remain byte-identical and tested. This is a new opt-in
contract, not a migration of the existing result.

The historical principal capture remains unreviewed and unbound. An accountable
reviewer still needs contemporaneous evidence for its identity mappings,
shared intent, deployment, mediation, and execution uniqueness. Binding
approval remains deferred. Policy-revision comparability, issuer amendments,
state transfer, and continuation safety need separate contracts and evidence;
an observed monetary total cannot supply them.
