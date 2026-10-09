# Capture clock audit

Audited 9 October 2026 against repository baseline `a719b44`. This is a bounded
audit of six AgentCore event files and their capture/sanitization paths. It
does not certify every timing field in the evidence corpus or determine which
host clock implementation ran the older principal and retransmission drivers.

## Finding

The two reported anomalies are part of a wider retained pattern: **six negative
UTC call intervals across 510 calls in six event files**. Four are in the
continuation campaign and retain positive monotonic endpoint differences.
There are 300 retained monotonic pairs, none with a negative difference; the
other 210 calls have no retained monotonic endpoints. Missing endpoints do not
mean zero duration or failed execution.

| Event file | Calls with UTC endpoints | Retained monotonic pairs | Negative UTC intervals |
|---|---:|---:|---:|
| Principal continuity | 44 | 0 | 1 |
| Completed retransmission | 62 | 0 | 1 |
| Continuation revision matrix | 228 | 228 | 4 |
| Continuation diagnostic | 72 | 72 | 0 |
| Earlier temporal transition | 100 | 0 | 0 |
| Earlier transition metadata | 4 | 0 | 0 |

[`scripts/audit_capture_clocks.py`](../scripts/audit_capture_clocks.py) pins all
six source digests, checks the expected call counts, and computes differences
from retained endpoints. The [replayable report](../tests/fixtures/capture-clock-audit-v1.json)
includes every affected event pointer and both UTC endpoints:

```sh
python scripts/audit_capture_clocks.py
```

Successful execution means the bounded audit ran, not that the clocks or
continuity claims passed. The script reports missing endpoints and negative
intervals; it is not a timing validator for new campaigns.

| Capture and event pointer | UTC delta (ms) | Monotonic delta (ms) | Separately recorded duration (ms) | Native outcome |
|---|---:|---:|---:|---|
| Principal `/trials/12/calls/1` | -127.880 | unavailable | 450.186783 | deny |
| Retransmission `/trials/10/calls/1` | -152.115 | unavailable | 516.247859 | allow |
| Continuation `/trials/2/predecessor_after_call` | -187.785 | 423.058251 | — | stale session |
| Continuation `/trials/8/recovery_after_call` | -117.443 | 492.848454 | — | deny |
| Continuation `/trials/10/predecessor_after_call` | -234.645 | 375.589518 | — | stale session |
| Continuation `/trials/17/recovery_call` | -83.975 | 526.498144 | — | allow |

## What the code establishes

The older files named `capture_principal_continuity.py` and
`capture_retry_continuity.py` are sanitizers of externally supplied raw captures,
not the live request drivers. They do not establish which clock API the older
drivers used or retain host clock-service logs.

- **Principal sanitizer:** `_call` checks raw `started_ns <= finished_ns`,
  computes duration from their difference, and keeps the UTC strings and their
  signed delta. `events` checks each pair's monotonic ordering. The returned
  records omit both raw monotonic endpoints. That information loss is directly
  visible in code; the retained duration cannot reproduce the cross-call check.
- **Retransmission sanitizer:** `_call` checks a supplied positive `duration_ms`
  and preserves the supplied UTC strings. It neither requires nor retains
  monotonic endpoints. The retained contract attests completed-response order;
  this sanitizer cannot independently prove that order from its timing fields.
- **Continuation driver and projector:** the committed live driver's `_now`
  reads UTC and `time.monotonic_ns()` separately. `Live.call` reads the full
  response body before its finish stamp. `project_continuation.py` retains
  both monotonic endpoints, and the consolidation projector checks cross-call
  ordering from them. This path already retains the data needed to replay
  timing arithmetic despite UTC regressions. The two clock reads are not atomic;
  their differences must not be treated as an exact host-clock correction log.

The original files are linked from the
[AgentCore evidence directory](evidence/agentcore-refund-policy/README.md).
They remain frozen: repairing timestamps or editing a pinned sanitizer would
change the historical record rather than recover missing measurements.

## Root-cause limit and interpretation

The proven defect is **incomplete retention of timing evidence** in the older
sanitization paths. The physical cause of the negative UTC intervals is not
established. A wall-clock adjustment is consistent with the pattern, but NTP,
virtualization, suspend/resume, a manual adjustment, and a driver timestamp
assignment defect cannot be distinguished from the committed artifacts. These
are separate capture campaigns, not proven independent hosts or clock domains.
The fact that principal corrections already described a host UTC regression
is a recorded interpretation, not a retained clock-service diagnosis.

A negative UTC difference and a positive monotonic duration are not inherently
contradictory: they measure different clocks. For continuation, both differences
can be recomputed. For principal, only the UTC difference can be recomputed
from retained endpoints. For retransmission, even the API used to produce the
copied duration is not established by its sanitizer. Those are three different
levels of timing evidence, not one verdict about whether every timestamp is usable.

Python documents that wall time can decrease after the system clock is set
back, while monotonic time is intended for elapsed differences. Its undefined
reference point is also a reason to identify the clock domain before comparing
timestamps. See the [Python clock documentation](https://docs.python.org/3.12/library/time.html#time.monotonic)
and [wall-time documentation](https://docs.python.org/3.12/library/time.html#time.time).
This explains a plausible mechanism, not the cause of these six observations.

Native decisions and distinct retransmission execution markers do not depend
on subtracting UTC timestamps. For continuation, the retained monotonic pairs
also support replay of ordering checks. For principal and retransmission,
ordering retains the attestation limits already documented in the
[consolidation record](continuity-evidence-consolidation.md). A positive copied
duration alone does not repair those missing endpoints. No accepted evidence
metadata or continuity verdict changes as a result of this audit.

## Required before another live campaign

The [capture plan](continuity-evidence-plan.md#timing-retention-gate) now requires
review of the actual driver/sanitizer pair and a replayable timing fixture
before further live collection. New event records must retain integer
monotonic endpoints, a non-secret clock-domain alias and clock metadata, UTC
endpoints, and explicit response-completion/next-send boundaries. Sanitization
must preserve those endpoints or apply one documented common offset per clock
domain; it must never independently zero each call or derive them from UTC.

No selected new driver has passed that gate in this change. Existing frozen
captures are not regenerated, provider calls are not repeated, and no host
clock configuration is changed. A future campaign should also retain scoped
clock-adjustment diagnostics where available, without copying host identifiers,
credentials, or unrelated logs into the evidence bundle.
