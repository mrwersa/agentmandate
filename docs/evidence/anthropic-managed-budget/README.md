# Anthropic Managed Agents evidence: preregistered session-budget replication

This package will test whether a second managed architecture places cumulative
authority at a session boundary that is not joined natively to a reviewed
mandate. No live result has been captured yet. Issue #143 tracks execution.

## Evidence boundary and provenance

- **Subject:** Anthropic Managed Agents under beta
  `managed-agents-2026-04-01`.
- **Mechanism:** the managed service's `budget.max_list_cost`, not Claude Code's
  client-side `--max-budget-usd` option.
- **Model:** `claude-haiku-4-5`, frozen in `protocol.json`.
- **SDK:** `anthropic==1.2.0`, pinned in `requirements-capture.txt`.
- **Completeness:** no empirical claim is complete before the pilot and ten
  confirmatory trials per measurable cell have merged.

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

`confirm` refuses to run while `confirmation.cap_minor_units` is null. Pilot
outputs remain private and excluded from confirmation. After pilot review, the
chosen whole-cent cap and capture date must be committed before confirmation.

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

## Result and consequence

No result yet. Expected outcomes must not enter this file or the manuscript
while the capture is incomplete or under review.
