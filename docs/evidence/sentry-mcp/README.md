# Sentry MCP evidence: the visible catalogue is not the authority surface

This graph completes the roadmap's first four-framework evidence set. Its main
finding is not a risky tool name: the complete authority surface is hidden
behind a destructive meta-tool. `tools/list` exposes eight tools, while
`execute_sentry_tool` can dispatch by name into a larger, skill-filtered
catalogue that includes issue triage, project/team creation, DSN creation and
configuration, attachments, traces, replays, profiles, and user reports.

## Evidence boundary and provenance

- Subject: [`@sentry/mcp-server` 0.37.0](https://www.npmjs.com/package/@sentry/mcp-server/v/0.37.0),
  published 2 July 2026. The npm integrity is
  `sha512-agZ4KMeYVlTzl4topI6ED6gTmZDtmWZJV4n/nSuoXjNv4i+PNhdx1qJEtTdJdjEh8lPXu1SziEk7zgRCQ4FYbg==`.
- Source: Sentry tag
  [`0.37.0`](https://github.com/getsentry/sentry-mcp/tree/d79490aee755875aef74a9e2647858fde3fd8587),
  commit `d79490aee755875aef74a9e2647858fde3fd8587`. The package uses
  FSL-1.1-ALv2, recorded here rather than described as open source.
- Profile: stdio with an operator-supplied User Auth Token; explicit `inspect`,
  `triage`, and `project-management` skills; no organization or project
  constraint; no embedded model provider.
- Inventory: `catalogue.json`, the live `tools/list` response. The source
  [`execute-tool.ts`](https://github.com/getsentry/sentry-mcp/blob/d79490aee755875aef74a9e2647858fde3fd8587/packages/mcp-core/src/tools/special/execute-tool.ts)
  and [`search-tools.ts`](https://github.com/getsentry/sentry-mcp/blob/d79490aee755875aef74a9e2647858fde3fd8587/packages/mcp-core/src/tools/special/search-tools.ts)
  establish that hidden, session-available tools can be discovered and called.

The capture supplies a placeholder token, routes the unused API host to
localhost, disables Sentry telemetry, removes model-provider environment
variables, and calls only `initialize` and `tools/list`. It makes no Sentry or
model API request and contains no account identifiers.

## Reproduce and review

Node 22.13+ on Linux and the util-linux `script` utility at `/usr/bin/script`
are required:

```sh
cd docs/evidence/sentry-mcp
npm ci --ignore-scripts
npm run capture
cd ../../..
mandate scan docs/evidence/sentry-mcp/catalogue.json \
  --agent sentry-operations-agent
```

`scan-skeleton.yaml` preserves the unreviewed scan. Review corrected four
material distortions:

1. `issueId`, `resourceId`, and `projectSlugOrId` are caller-supplied bearer
   references, not scopes produced in this session. The malformed scanner scope
   `projectslugor` and the other guessed `requires` were removed.
2. Search `limit` fields bound result count, not value. No monetary ceiling was
   invented.
3. The fixed User Auth Token was recorded as `service`, while noting that this
   label loses the token owner and delegation chain.
4. `execute_sentry_tool` was conservatively retained as irreversible. Its
   `name` argument selects hidden reads and writes; v1 cannot expand the
   dispatch or apply effect and approval per selected operation.

## Result and roadmap consequence

```text
$ mandate reach docs/evidence/sentry-mcp/mandate.yaml
BREACH  irreversible calls reach 2, above the declared budget of 1 in one run
  1. execute_sentry_tool
  2. execute_sentry_tool
```

`mandate lint` reports two error-level and six warning-level
`identity.service-principal` findings. The count is reproducible, but the
remediation text is incomplete: exchanging “the caller token” does not model
the token owner, workload, Sentry OAuth/API scopes, granted skills, tenant
constraints, and product permissions that jointly determine authority.

This graph supports dynamic inventory declarations first, then provenance-aware
IR, dispatch-dependent conditions, delegation chains, resource relationships,
and reviewed data-flow labels. It does not justify importing application code,
calling Sentry during analysis, or turning AgentMandate into an MCP proxy.
