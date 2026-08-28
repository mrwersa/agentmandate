# Initiative MCP evidence: containment does not yet change reachability

This graph tests whether project/status containment produces a real
AgentMandate false positive. Initiative enforces the relationship, but the
candidate does **not** pass the roadmap gate: its generic tools admit a valid
related assignment, while current analysis never claims that an arbitrary
caller-chosen pair is valid.

## Evidence boundary and provenance

- **Subject:** [Initiative v0.63.4](https://github.com/Morelitea/initiative/releases/tag/v0.63.4),
  published 27 August 2026 under AGPL-3.0. The published amd64 container
  manifest has digest
  `sha256:dd4ae3def9cc9a5545223c6f93f6faa25f2ce927aa51277fd7b934b66116a070`.
- **Source:** commit
  [`234f0fd864df2a90d02ae4851b6615102207a650`](https://github.com/Morelitea/initiative/tree/234f0fd864df2a90d02ae4851b6615102207a650),
  the commit behind the release tag. Its `backend/uv.lock` SHA-256 is
  `1e272c47f93cd7b3068496832951ad9b759730e4969aa87186d266afebc0a82f`.
- **Deployment profile:** the in-app MCP surface with its default-deny route
  map and caller PAT forwarding. No database or server lifespan was started.
- **Inventory boundary:** the 25 tools returned by the pinned app's
  `build_mcp_server(app).list_tools()`, converted through FastMCP's
  `to_mcp_tool()`. This is complete for that builder and source revision, not
  for routes excluded by its allow-list.

## Capture and safety

`catalogue.json`, SHA-256
`8b4ed6c280909909a7445bd575a2c22907d77ee837b4696dc6f0e1682ea6d7eb`,
is reproducible from the release source and its locked dependencies:

```sh
git clone https://github.com/Morelitea/initiative.git /tmp/initiative-capture
git -C /tmp/initiative-capture checkout 234f0fd864df2a90d02ae4851b6615102207a650
python -m venv /tmp/initiative-uv
/tmp/initiative-uv/bin/pip install uv==0.11.21
cd /tmp/initiative-capture/backend
/tmp/initiative-uv/bin/uv sync --frozen --no-dev
env PYTHONPATH=. \
  DATABASE_URL_APP=postgresql+asyncpg://app:placeholder@localhost/initiative \
  DATABASE_URL_ADMIN=postgresql+asyncpg://admin:placeholder@localhost/initiative \
  SECRET_KEY=capture-only-placeholder-key-000000 \
  STATIC_DIR=/tmp/initiative-static UPLOADS_DIR=/tmp/initiative-uploads \
  .venv/bin/python \
  /path/to/agentmandate/docs/evidence/initiative-mcp/capture_catalogue.py \
  --output /path/to/agentmandate/docs/evidence/initiative-mcp/catalogue.json
mandate scan /path/to/agentmandate/docs/evidence/initiative-mcp/catalogue.json \
  --agent initiative-agent
```

Cloning and dependency installation use the network. Capture imports pinned
upstream code to construct FastAPI routes, but it does not start the lifespan,
connect to PostgreSQL, call an MCP endpoint, or send telemetry. Environment
values are explicit placeholders. The catalogue contains schemas only: no
credentials, customer data, account identifiers, or trace identifiers.

## Review corrections

`scan-skeleton.yaml` is the byte-exact scanner output. Review made these
material corrections in `mandate.yaml`:

1. **Source ambiguity:** integer `guild_id` and `calendar_id` parameters were
   guessed as authority scopes. They are caller-supplied bearer values; the
   API's PAT, permission checks, and RLS decide authority.
2. **Source ambiguity:** `limit` and `property_values` were guessed as possible
   monetary value arguments. They bound result count and carry custom-property
   data, respectively; neither spends money.
3. **Source ambiguity:** `favorite_projects`, `project_activity_feed`, and
   `autocomplete_tasks` were guessed irreversible from their names. The pinned
   route map exposes them through GET, so they were reviewed as reads.
4. **Model gap:** `move_task` remains conservatively irreversible. Moving
   within an initiative is reversible, while a cross-initiative move clears
   incompatible property values. The relationship changes the effective
   branch, but current manifest v1 has only one tool-level effect.
5. **Deployment policy:** guessed approval flags were removed. The upstream
   comments describe a Claude Code client prompt, not an MCP-server guarantee
   that applies to every caller.
6. **Source ambiguity:** caller principals were retained after source review:
   the MCP adapter explicitly forwards the caller's authorization header into
   the route-backed request rather than spending a fixed service credential.

## Relationship probe decision

The pinned task handler looks up a requested status by **both** status ID and
project ID, returning `400 STATUS_NOT_FOUND` when they do not match
([handler](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/api/v1/tenant_endpoints/tasks.py#L1846-L1883),
[lookup](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/services/tenant/task_statuses.py#L93-L101)).
A status belonging to the selected project is accepted by the same branch.

That real containment check is not yet a qualifying counterexample. The MCP
tool `list_task_statuses(project_id)` obtains statuses for the selected
project, and `create_task(project_id, task_status_id)` can consume a matching
pair. Reachability asks whether **some** consistent permitted assignment
exists. It does not assert that every arbitrary pair of bearer IDs succeeds.
Choosing project A with project B's status demonstrates the upstream check,
but not an AgentMandate false positive.

```text
$ mandate reach docs/evidence/initiative-mcp/mandate.yaml
BREACH  move_task_api_v1_g is irreversible and needs no approval, reachable in 1 call(s)
  1. move_task_api_v1_g
$ mandate lint docs/evidence/initiative-mcp/mandate.yaml
ERROR   effect.ungated-irreversible move_task_api_v1_g
        an irreversible effect with no approval requirement
```

The one-step breach is real under the reviewed deployment; a relationship does
not remove the cross-initiative branch that can clear property values. The
absence of a relationship-specific false path is not scanner precision: review
made six material decisions. It also is not evidence that relationships are
unnecessary.
Resource relationships would improve provenance and explanation here, but the
roadmap gate requires a fixed binding or other real deployment in which no
consistent assignment exists and current analysis nevertheless reports a
path. No schema change is justified by this graph. Issue
[#104](https://github.com/mrwersa/agentmandate/issues/104) closes as a
falsified candidate; [#106](https://github.com/mrwersa/agentmandate/issues/106)
tracks the stricter fixed-binding evidence search.

## Submission checklist

- [x] Subject, source, deployment, and completeness boundaries are explicit.
- [x] Raw inventory, scanner output, reviewed manifest, and capture pins are present.
- [x] Digests reproduce and capture commands are safe and documented.
- [x] Every correction is enumerated, classified, and linked to evidence.
- [x] The result and the negative product consequence are reproducible.
- [x] No secret, customer datum, account identifier, or real trace identifier is present.
- [x] Tests pin the catalogue, scanner output, corrections, and reviewed analysis.
