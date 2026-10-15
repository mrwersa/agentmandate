# Record a temporary delay to a fleet review

Use `mandate fleet exceptions` when a previously accepted inventory review is
overdue and its owner has a documented, temporary agreement to delay the next
review. It checks that agreement and routes the original findings to owners.
It leaves the indexed review, its expiry and every inventory finding unchanged.

Try the synthetic example from the repository root:

```bash
mandate fleet exceptions examples/fleet-exceptions/index.json \
  --exceptions examples/fleet-exceptions/exceptions.json \
  --root . --as-of 2026-10-11 --json
```

The inventory reports `fleet.review-not-current` for `release/prod`. The new
gate exits 0 because its named review-delay record is eligible through
18 October, inclusive UTC. At `--as-of 2026-10-19`, it exits 1 and the review
finding is uncovered again. No file is updated or renewed. All names and
decisions in this example are synthetic, not a maintainer acceptance.

## Prepare the record

First run [fleet inventory](fleet-inventory.md) against the exact index you
intend to review. Confirm its owner and investigate the finding. A review-delay
exception is available only for a previously accepted review whose expiry has
passed. An unreviewed, contested, future-dated or incomplete review cannot use
this exception to become accepted.

Record the owner, reviewer, reason, decision date, expiry and evidence through
your organization's review process. Protect those records and authenticate the
people outside AgentMandate. Someone who can replace both the documents and
their pins can replace the reported decision; digest equality supplies byte
identity, not authorization or truth.

The strict portable input has `exceptions_version: 1`, a `fleet_index_sha256`
pin and an `exceptions` array. Each record contains exactly:

| Field | Meaning |
|---|---|
| `id` | Unique exception identifier |
| `entry_id` | Exact indexed deployment identifier |
| `owner` | The same nonempty owner recorded in that entry |
| `reviewer`, `reason` | Named decision maker and explicit rationale |
| `decision` | `accept_review_delay`, the only supported disposition |
| `issued_at`, `expires` | Inclusive ISO date window, evaluated at `--as-of` |
| `finding_sha256` | Canonical digest of this entry's current overdue-review finding |
| `evidence` | Nonempty map of named local `{path, sha256}` references |

Identifiers and rationale use nonempty printable ASCII strings. Paths must be
normalized relative paths inside `--root`; escaping symlinks are usage errors.
Evidence files are captured once per path and hashed, with contents omitted
from the result. Missing files or wrong digests make the exception ineligible.
Duplicate JSON keys and unsupported fields are rejected. Multiple exception
records targeting the same entry make all of those records ambiguous.

To calculate the finding digest from an inventory JSON result:

```python
import hashlib
import json

finding = next(f for f in report["findings"]
               if f["code"] == "fleet.review-not-current"
               and f["subject"] == "release/prod")
finding_sha256 = hashlib.sha256(
    json.dumps(finding, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
```

The [example record](../examples/fleet-exceptions/exceptions.json) pins the
index and a short decision note. A new index revision requires a new decision
record joined to those bytes, even if the tool names appear unchanged. This
gate does not infer permission to reuse or extend an earlier decision.

## Read the result and its blockers

`agentmandate.fleet-exceptions/v2` embeds the unchanged inventory result.
`routes` retains each finding and its canonical digest, identifies its entry
and owner where available, and reports either `blocked` or
`accepted_review_delay_within_recorded_scope`. Global membership/window
findings have no entry owner; use their scope to assign an organizational owner
outside the input format. Entries without an owner remain visible and blocked.

`exceptions` reports each record's eligibility and evidence hashes.
`uncovered_findings` retains baseline findings with no eligible exception;
`findings` reports problems in the exception records themselves. `gate_passed`
requires both lists to be empty. A clean inventory with no exceptions reports
`no_exception_needed`; an irrelevant or stale submitted exception is checked
and can still block the gate.

Only an overdue accepted review on an eligible snapshot in a current,
complete declared index can receive the initial disposition. Missing owners,
digest or IR mismatches, unavailable artifacts, incomplete membership, stale
snapshots and ambiguous deployments remain blockers. A valid exception on one
entry cannot clear a failure elsewhere. There are no query filters on this
gate; [inventory queries](fleet-inventory.md) remain available separately.

The human output prints every original finding, its routing/disposition and
the exception owner, reviewer and expiry. The result always says
`review_authentication: not_verified` and `renewal: not_performed`. Passing
this gate does not change `review_current`, renew evidence acceptance, approve
deployment, or alter reachability or deployment-drift results.

## Use it in CI

Exit 0 means the current recorded disposition is eligible or no exception is
needed. Exit 1 means an uncovered inventory finding or an ineligible exception.
Exit 2 means malformed input, unsafe paths or an I/O error reading the supplied
index/exception documents, with empty stdout. Missing referenced evidence is
an ineligible record and exits 1.

Load the index and exception records from protected review materials and supply
today's UTC date from the workflow. Run reachability and deployment checks as
their own gates. Preserve the embedded inventory report in CI artifacts so a
temporary disposition remains visible to reviewers.

Owner/reviewer names, reasons and source paths can expose internal information.
Keep evidence notes minimal, use repository-relative references and apply your
organization's artifact retention and access rules. The command reads local
files only, uploads nothing and does not include evidence bodies. This scope
review does not substitute for independent privacy or security review.

This first slice provides local ownership routing and temporary review-delay
records. Broader exception kinds, authenticated approval, RBAC, ticketing and
fleet workflow integrations remain open. These are initial v1 baselines, not
migrations from an earlier exception contract.
