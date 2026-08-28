# Resource Relationship Evidence Audit

Status: **evidence gate not met**. This audit was completed on 28 August 2026.
It tests whether the committed graphs already justify a resource-relationship
schema. They do not. No manifest, IR, or analysis change should start from the
candidate shapes below.

## Gate under review

The roadmap requires one real false positive or missed path caused by losing
resource identity, ownership, containment, or binding lineage. A suggestive
API shape is insufficient: the relationship must change a reproduced authority
result. Synthetic policy cannot be promoted into deployment evidence.

## Existing graph audit

| Graph | Candidate relationship | Decision |
|---|---|---|
| GitHub MCP | A workflow file and its trigger share repository identity | Not qualifying. With unconstrained `owner` and `repo` arguments, reachability is existential and both calls can select the same repository. A cross-repository false path would require an unobserved deployment restriction. |
| AWS PostgreSQL | Connection details, AWS visibility, secret mappings, network reachability, and PostgreSQL grants jointly bound a database | Not qualifying yet. These facts constrain targets, but the reproduced effect-budget breach can execute twice against one valid database. Adding relationships would improve explanation without removing that path. |
| AgentKit | Assets, allowances, wrapped tokens, loans, and collateral have ownership and conversion relationships | Routed elsewhere. The reproduced false paths depend on finite cardinality, collateral, 1:1 conversion, and gross-versus-net accounting, which are the bounded-producer and quantity initiative rather than evidence for a generic relation vocabulary. |
| Sentry MCP | Resources belong to projects and organizations | Not qualifying. The visible inventory is partial and the destructive meta-tool hides the operation selected at runtime. Dynamic inventory and dispatch conditions must establish the operation before a relationship can be load-bearing. |

The rejected GitHub hypothesis is important. The captured
[`create_or_update_file`](evidence/github-mcp-server/catalogue-repos-actions.json)
and `actions_run_trigger` schemas both carry repository coordinates, while the
reviewed manifest reduces them to a fungible `workflow` scope. That is a real
loss of lineage, but the current deployment profile permits choosing matching
coordinates. The analyzer reports that *some* write-then-trigger path exists;
it does not claim that an arbitrary workflow can be triggered in every
repository. Calling this a false positive would change the question after
seeing the answer.

## Next capture candidate

[Initiative v0.63.4](https://github.com/Morelitea/initiative/releases/tag/v0.63.4)
is the best next target found in this audit. Its in-app MCP server is
route-backed, default-deny, and forwards the caller credential into the real
API rather than reimplementing authorization. The pinned implementation
exposes task creation, editing, movement, and comments alongside project,
task, initiative, and status reads ([MCP source](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/mcp_server.py),
[curation tests](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/mcp_server_test.py#L52-L77)).

The real handlers contain several explicit relationships:

- task creation accepts a project and optional status, then rejects a status
  that is not in that project
  ([source](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/api/v1/tenant_endpoints/tasks.py#L1846-L1883));
- task updates likewise resolve a new status only inside the task's current
  project
  ([source](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/api/v1/tenant_endpoints/tasks.py#L1986-L2027)); and
- task movement requires access to both projects, selects the target project's
  default status, and removes property values when the move crosses initiative
  boundaries
  ([source](https://github.com/Morelitea/initiative/blob/234f0fd864df2a90d02ae4851b6615102207a650/backend/app/api/v1/tenant_endpoints/tasks.py#L2135-L2202)).

Those checks prove that containment changes accepted calls and side effects.
They still do not prove an AgentMandate false path. The next evidence package
must cross that final boundary rather than treating source complexity as a
finding. [Issue #104](https://github.com/mrwersa/agentmandate/issues/104)
tracks the capture against the acceptance test below.

## Acceptance test for the next evidence package

The Initiative capture counts toward the roadmap gate only if it includes:

1. a pinned, digest-verified `tools/list` capture from the published release,
   with raw scanner output preserved;
2. a reviewed deployment and identity boundary with no live credentials or
   customer data;
3. one pair of concrete resource bindings for which current analysis reports a
   path that the pinned API rejects solely because the relationship is false;
4. the matching control pair, accepted by the same API and analysis;
5. the shortest current counterexample plus the upstream rejection evidence;
   and
6. correction notes using the repository's extractor-defect, source-ambiguity,
   model-gap, and deployment-policy taxonomy.

If a safe local API probe cannot reproduce both directions, the candidate is
rejected. A hand-written `contains` edge or a hypothetical access matrix may
supplement the package, but cannot satisfy item 3.

## Decision

Do not design the relation vocabulary yet. Capture Initiative or another real
deployment first, then test only the minimum relations needed by its
counterexample against OpenFGA concepts. This preserves the roadmap's intended
order: evidence selects the abstraction; the abstraction does not select
convenient evidence.
