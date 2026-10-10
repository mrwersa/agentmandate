# Import a tool catalogue or API description

Use a local export to start a manifest or document a dynamic tool boundary.
The importer reads JSON without contacting the service or running agent code.
It extracts candidates for review; it cannot determine what this deployment
permits or what a tool actually does.

Choose the output you need:

| Task | Command | Next step |
|---|---|---|
| Start a manifest | `mandate scan FILE --format FORMAT` | Review every proposal and fill the missing intent |
| Record observed membership | `mandate inventory import FILE --format FORMAT …` | Review the draft against one source binding and deployment |
| Inspect inventory provenance | Add `--ir` to the import command | Validate or inspect the existing inventory IR profile |

`FORMAT` is `mcp`, `openapi`, or `a2a`. The explicit readers require UTF-8 JSON.
They reject ambiguous JSON keys, non-finite numbers, duplicate names, malformed
membership, and unsupported versions with exit 2 and no standard output.
They extract a documented subset; they are not full protocol/schema validators.

## Start with a manifest

Run these examples from a repository checkout with AgentMandate installed:

```console
$ mandate scan examples/catalogue-import/mcp.json --format mcp --agent refunds > mandate.yaml
$ mandate scan examples/catalogue-import/openapi.json --format openapi --agent refunds > api-mandate.yaml
$ mandate scan examples/catalogue-import/a2a.json --format a2a --dispatch-tool ask_refund_agent --agent refunds > delegated-mandate.yaml
$ mandate scan examples/catalogue-import/a2a-1.0.json --format a2a --dispatch-tool ask_refund_agent --agent refunds > delegated-v1-mandate.yaml
```

The files are synthetic examples, not live service captures. The generated
comments identify the source format and SHA-256 of its exact bytes, then
state the interpretation limits. Untrusted prose stays in inert comments and
names are quoted. A digest identifies bytes; it does not authenticate their
origin or establish that their description is true.

Before running analysis, confirm the tools available to **one agent** and
review effects, principals, scope production, value arguments, ceilings,
approvals, and mandate-wide limits. See the [manifest reference](manifest.md).
An unedited skeleton is loadable but does not establish reviewed intent:
missing producers or limits can make its reachability result uninformative.

The [annotated synthetic manifest](../examples/catalogue-import/manifest.json)
shows the additional work. It declares a case-producing search and a £500
per-case refund under a £500 mandate-wide limit. Two separate cases permit
two refunds, so `reach` finds a breach. These annotations are example intent;
the importer does not derive them from protocol metadata.

## Record a dynamic inventory

If the source builds its tool list at runtime, import a draft for that binding:

```console
$ mandate inventory import examples/catalogue-import/mcp.json --format mcp --boundary example-mcp --target-source agent.py --target-binding resolver --locator examples/catalogue-import/mcp.json --selection '{"environment":"example"}' > inventory.json
$ mandate inventory validate inventory.json
valid dynamic inventory v1
```

`--target-source` is relative to the source root later given to `drift`.
`--target-binding` names the selected constructor/tool-list binding there.
`--locator` is a safe repository-relative identifier for the captured bytes;
it is not a URL to resolve. `--selection` records the explicit deployment
context using the existing [selection vocabulary](dynamic-inventory.md).
The command does not check that these caller-supplied mappings are true.

Every import uses `inventory_version: 1`, a provider boundary, `review:
unreviewed`, no reviewer, and no expiry. Completeness is `unknown`, or `partial`
when an MCP continuation cursor is present. Producer revision is `unknown`
until reviewed; an API or agent version string alone does not identify the
deployed tool producer. MCP name extraction has `confidence: exact` for the
supplied payload. OpenAPI/A2A tool mappings have `confidence: heuristic` because
the application adapter must be checked separately.

These drafts can contribute observed names to drift comparison but cannot
prove absence, resolve dynamic membership, or yield a clean drift gate:

```console
$ mandate drift examples/catalogue-import/manifest.json --source examples/catalogue-import --binding resolver --inventory-declaration inventory.json --inventory-capture examples/catalogue-import/mcp.json --inventory-selection '{"environment":"example"}' --inventory-as-of 2026-10-10
```

Expect exit 1: membership is not complete or accepted and has no current review.
Tampered capture bytes prevent even observed membership from being used.
Structure validation succeeds separately; that exit 0 is not acceptance.
Accountable review follows the [dynamic-inventory contract](dynamic-inventory.md),
including adapter registration, exact selection, completeness evidence,
source bytes, reviewer, and expiry. Do not make a draft eligible by changing
its flags without the evidence those flags assert.

Add `--ir` to the import command to emit its canonical inventory graph. The
existing `ir_version: 1` and dynamic-inventory adapter profiles are reused.
`mandate ir validate` checks structure. `mandate reach --ir` rejects an
inventory-only graph with exit 2: membership cannot supply effects or mandate
intent. To analyze a reviewed manifest, use `mandate ir export MANIFEST` and
then `mandate reach --ir SNAPSHOT`. The
[Authority IR contract](authority-ir.md) owns that analysis boundary.

## Mapping limits by format

### MCP tools/list

The strict reader accepts a tool array, a result object containing `tools`,
or a JSON-RPC 2.0 response whose `result` contains `tools`. It rejects error
responses and conflicting result/tool lists. Tool names must be unique;
malformed entries are refused rather than skipped.

Effects and argument hints reuse the existing name/schema proposals. Tool
annotations do not grant read-only status, approvals, ceilings, or principal
identity. Review even read-like names. A `nextCursor` marks a partial page;
no page is fetched. Absence of a cursor does not establish deployment
completeness, especially for filtered or aggregated catalogues. Import one
provider boundary at a time; do not silently merge server namespaces.
The mapping follows the
[MCP tools/list contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
including its pagination and annotation trust limits.

Omitting `scan --format` retains the original MCP skeleton reader and output.
Existing public Python `propose`, `render`, `scan_file`, and `scan_source`
signatures remain unchanged. Use the explicit format for strict extraction,
JSON-RPC responses, source digests, and pagination disclosure.

### OpenAPI 3.0.x and 3.1.x

The reader lists the eight standard HTTP methods in `paths`. `operationId`
becomes a candidate tool name; when absent, the stable fallback is `METHOD
/path`. Confirm that the application uses those names and exposes those
operations to this agent. Naming collisions, including a fallback colliding
with an explicit ID, are refused.

Only document-local Path Item references are resolved. Cycles, missing targets,
external references, and reference siblings requiring ambiguous merges are
refused. Inline parameters and simple `application/json` body properties can
suggest a scope or value argument. Parameter/body/schema references and schema
composition remain unexpanded. Callbacks, webhooks, links, servers, response
schemas, and internal service calls are outside the imported member set.

All effects default to irreversible, including GET and read-like operation
names. HTTP methods and `security` declarations do not prove actual effects
or authorization. Schema maxima are input constraints, not cumulative mandate
ceilings. The mapping follows the
[OpenAPI 3.1.1 operation contract](https://spec.openapis.org/oas/v3.1.1.html#operation-object);
the importer does not evaluate native policy decisions.

### A2A Agent Cards, legacy 0.3.0 and interface-based 1.0

An Agent Card advertises skills and a remote agent interface. Skills are not
independent callable tools. The importer requires `--dispatch-tool NAME` and
emits **one** candidate: the application's tool that delegates to this agent.
Skill IDs stay in review notes; they are not relabelled as tools or used to
infer scope production, monetary limits, or per-skill permissions.

Review the actual wrapper, routing/input mapping, registration in the selected
agent, and delegated authority before accepting membership. A card with no
skills still does not prove the wrapper powerless. URLs, security declarations,
and signatures are not verified, and the remote agent's internal tools and
effects remain unknown. Legacy cards require top-level `protocolVersion:
0.3.0` and `url`, following the
[A2A 0.3.0 definitions](https://a2a-protocol.org/v0.3.0/specification/).
Interface-based cards require a nonempty `supportedInterfaces` array whose
entries each declare version `1.0`, URL, and protocol binding, following the
[A2A 1.0 interface contract](https://a2a-protocol.org/latest/specification/).
Mixed legacy/interface layouts or unsupported interface versions are refused;
the importer does not select a compatible endpoint or negotiate a fallback.

The wrapper's protocol version, transport, URL, tenant, and authenticated
extended-card selection still require separate review. Advertising several
interfaces does not produce several dispatch tools or establish which one
this application uses. The exact card remains available through its pinned
source bytes; no endpoint or signature is checked.

## Compatibility and remaining evidence

The [pinned fixtures](../tests/fixtures/catalogue-import/README.md) cover each
source format, skeleton, declaration, and inventory IR graph. They are v1
baselines for existing contracts, not migrations or deployment acceptance.
Tests also read four historical MCP payloads without changing their bytes or
legacy scan output. The new reader does not expose public Python records.

This implements the offline inventory-import half of
[#228](https://github.com/mrwersa/agentmandate/issues/228). It does not add a
policy evaluator, aligned live decisions for A2A/OpenAPI, or a new independent
operational graph. Cedar decision alignment remains its separate reviewed
path. External security review and the remaining compatibility audit stay
separate 1.0 gates.
