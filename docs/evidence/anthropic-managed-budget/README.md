# Anthropic Managed Agents evidence: preregistered session-budget replication

This package tests whether a second managed architecture places cumulative
authority at a session boundary that is not joined natively to a reviewed
mandate. Issue #143 tracks the staged execution.

## Evidence boundary and provenance

- **Subject:** Anthropic Managed Agents under beta
  `managed-agents-2026-04-01`.
- **Mechanism:** the managed service's `budget.max_list_cost`, not Claude Code's
  client-side `--max-budget-usd` option.
- **Model:** `claude-haiku-4-5`, frozen in `protocol.json`.
- **SDK:** `anthropic==1.2.0`, pinned in `requirements-capture.txt`.
- **Completeness:** the three single-agent cells have ten confirmatory trials
  each. The preregistered subagent cells remain pending and are not implied by
  these results.

Primary documentation:

- <https://platform.claude.com/docs/en/managed-agents/sessions>
- <https://platform.claude.com/docs/en/managed-agents/session-operations>
- <https://platform.claude.com/docs/en/managed-agents/events-and-streaming>
- <https://platform.claude.com/docs/en/managed-agents/multi-agent>

## Capture and safety

The capture has two mechanically separated stages:

```console
python -m venv .capture-venv
.capture-venv/bin/pip install -r requirements-capture.txt
.capture-venv/bin/python capture.py capability --output private-capability
.capture-venv/bin/python capture.py pilot --output private-pilot
```

The initial harness made `confirm` refuse to run while
`confirmation.cap_minor_units` was null. Pilot outputs remain private and
excluded from confirmation. The chosen whole-cent cap and capture date are now
committed before confirmation implementation.

The valid excluded pilot completed on 30 August 2026. Its three sessions first
reported a non-zero whole-cent cost after 2, 3, and 2 frozen work units. All
three sessions were deleted and verified absent. The preregistered selection
rule therefore fixes the confirmation cap at one cent. `pilot-summary.json`
contains only these aggregate pilot facts and no live identifier. The protocol
file remains byte-identical to its pre-confirmation state; its status records
the point at which it was frozen rather than being rewritten after observation.

The first confirmation stage implements only the three single-agent cells:
sequential enforcement, fresh-session replication, and live cap revision.
Their order was randomised with the committed seed and each ran ten trials.
Subagent handoff and concurrent overshoot remain unimplemented until a separate
review of prompt-driven thread creation.

`multiagent-protocol.json` freezes that separate stage before execution. Its
excluded capability probe requests one, two, and four child threads with the
same worker instruction. Confirmation permits no replacement trials: a prompt
that produces the wrong child count or parentage is retained and reported.
Concurrent cells additionally require every child-creation event to precede
the first child-idle event; prose instructions alone do not establish overlap.

The excluded capability probe succeeded for all three requested topologies.
`multiagent-capability-summary.json`, SHA-256 `5d24b64b6950915d69ef318b56cf74529fde0b3a92f96c76f3d027081d8121fa`,
records one primary thread plus exactly one, two, and four child
threads. Every child named the primary as its parent, and all child-creation
events preceded the first child-idle event. The uncapped sessions ended at two,
four, and six cents respectively. These observations validate the frozen
prompts; they are not confirmation trials and do not answer budget behavior.

The confirmation runner uses the same frozen prompts and a one-cent session cap
for ten randomized trials per cell. It never retries a nonconforming topology.
Each trial retains the full private native snapshot, exact child count and
parentage, creation-before-idle check, session cost, native idle reason, and
post-budget refusal. The implementation strengthens the frozen minimum for
concurrent cells by also requiring every child `thread_status_running` event to
precede the first child-idle event. Every session is deleted and verified
absent before the next trial begins.

`multiagent-confirmation.json`, SHA-256 `7300038f4aeb13fc1b9b35c6a06b6eee9a86d0907bdc3a6af46fd8cc8b2819f7`,
is the identifier-free reduction of the 30 confirmatory trials. All 30 had the
requested child count and primary parentage. In both concurrent cells, every
child was created and running before any child idled. Every session eventually
reported `budget_reached`, and every subsequent message was refused.

At the one-cent session cap, the one-child handoff trials ended at one cent in
four trials and two cents in six. The two-child concurrent trials ended at two
cents in nine trials and three cents in one. All ten four-child concurrent
trials ended at four cents. The result therefore shows one shared session
account, but not a strict one-cent run bound: work already executing across
child threads can carry the final total beyond the cap before the next request
is refused. This is reported as a measured enforcement boundary, not as a claim
that the service promises transactional cancellation of in-flight work.

The script reads `ANTHROPIC_API_KEY` and `ANTHROPIC_WORKSPACE_ID` from the
environment. The workspace ID is required explicitly because identity-linked
keys may span workspaces. The script creates managed agents, cloud environments,
and sessions, makes calls only to Anthropic's API, and attempts cleanup in
`finally`. Native private output may contain live IDs and timestamps. It must
not be committed. The later publication step assigns stable aliases and
preserves event order, costs, caps, stop reasons, agent versions, and thread
parentage while removing credentials and live identifiers.

## Pre-capture correction

The supported session-update API can replace tools and MCP servers but cannot
switch an existing session to another saved agent version. The preregistered
agent-revision cell is therefore retained as `unmeasurable`, not replaced with
a different experiment. This is a source-boundary correction discovered before
any result.

The first excluded pilot attempt exposed an **extractor defect** before usable
data was recorded. `events.send` acknowledges queued work, so accepting the
session's pre-start `idle` state captured three still-running sessions with zero
cost. The invalid private output is excluded. The reader now waits until the
specific sent event has a non-null `processed_at` value and the session is idle.
Cleanup interrupts a running session when necessary, deletes it, and requires a
typed not-found response as the absence proof.

That corrected attempt still produced two pre-completion snapshots because a
queued user event may be marked processed before its model request ends. The
completed trial also showed that the API rounds the reported list cost to whole
cents. A second **extractor defect** correction therefore requires a
session-level idle event ordered after the sent message. The excluded pilot now
repeats the frozen work unit until the first non-zero whole-cent cost, up to the
precommitted maximum of eight, so it can select a cap without borrowing values
from confirmation.

## Single-agent result

`confirmation.json`, SHA-256 `f2b70d732f94ee3381b377fdac58ccb6150922dd5f96a057a9ee66505cfabe51`,
is the
deterministic, identifier-free reduction of 30 private trial files. It pins the
digest of every raw file while withholding live session identifiers and
timestamps. `sanitize_confirmation.py` defines the reduction.

- **Sequential control:** all 10 sessions reached the native `budget_reached`
  state at the one-cent cap. A subsequent message was refused in all 10 trials.
- **Fresh-session replication:** both fresh sessions reached one cent in all 10
  paired trials. The same reviewed mandate digest and principal therefore had
  two cents of aggregate capacity across the pair. This is a session-boundary
  result, not evidence that Anthropic accepts or verifies the binding record.
- **Live cap revision:** all 10 sessions retained their consumed one cent
  immediately after their cap was raised to two cents. All then reached the
  revised budget. Nine ended at two cents and one at three cents; the latter is
  retained as observed between-request overshoot, not reclassified as a policy
  revision failure.
- **Cleanup:** all 40 sessions were deleted and verified absent, the agent was
  archived, and the cloud environment was deleted.

This establishes a second managed implementation in which a cumulative bound
is scoped to a provider session rather than to the reviewed mandate identity.
It also supplies a positive design control: within a live Anthropic session,
raising the cap preserved consumed cost in every trial. It does **not** yet
establish how the same budget behaves across subagent handoff or concurrent
threads, and it does not replicate AgentCore's policy-revision transition.

The later multiagent result closes the thread questions left open above. It
shows shared accounting across handoff and a concurrency-dependent overshoot
inside one correctly identified session. It still does not replicate
AgentCore's policy-revision transition, and Anthropic still does not verify the
reviewed mandate binding.
