# AWS PostgreSQL MCP evidence: one tool hides compound authority

This graph validates the roadmap's need for conditional authority, delegation
chains, and resource relationships. The server publishes only seven tools, but
one of them can range from a read to destructive SQL and the effective boundary
is spread across MCP configuration, AWS credentials, Secrets Manager, network
reachability, and PostgreSQL grants.

## Evidence boundary and provenance

- Subject: [`awslabs.postgres-mcp-server` 1.1.11](https://pypi.org/project/awslabs.postgres-mcp-server/1.1.11/),
  published 10 August 2026 under Apache-2.0. The captured wheel SHA-256 is
  `3de8064631b7b31bd63abfbc8ca5f0cb0643047fdcb681d74bbdf7607e7807b6`.
- Source reference: AWS Labs commit
  [`ebcafaed`](https://github.com/awslabs/mcp/tree/ebcafaed027f56a2fc3faaa9ee6e95476b62adae/src/postgres-mcp-server),
  which sets the package version to 1.1.11.
- Deployment profile: no startup database, `--allow_write_query`,
  `--privilege_check=enforce`, and a dedicated least-privilege PostgreSQL role.
  These are reviewed assumptions, not facts found in `tools/list`.
- Inventory: `catalogue.json`, captured from the published package's FastMCP
  registry. Importing the module registers tools but makes no AWS or database
  connection. No credentials or live infrastructure were used.

The upstream [security guidance](https://github.com/awslabs/mcp/blob/ebcafaed027f56a2fc3faaa9ee6e95476b62adae/src/postgres-mcp-server/README.md#security-consideration)
calls its SQL blocklist best-effort and identifies a least-privilege database
role as the real boundary. The reviewed graph therefore does not treat the
read-only flag as authorization.

## Capture and review

```sh
python -m venv /tmp/agentmandate-postgres-capture
/tmp/agentmandate-postgres-capture/bin/python -m pip install \
  -r docs/evidence/aws-postgres-mcp/requirements-capture.txt
/tmp/agentmandate-postgres-capture/bin/python \
  docs/evidence/aws-postgres-mcp/capture_catalogue.py \
  --output docs/evidence/aws-postgres-mcp/catalogue.json
mandate scan docs/evidence/aws-postgres-mcp/catalogue.json \
  --agent aws-postgres-agent
```

`scan-skeleton.yaml` preserves the unreviewed output. Review made four material
corrections:

1. `run_query` was upgraded from read to irreversible for the write-enabled
   profile; its `sql` value determines the real effect.
2. `connect_to_database` and `is_database_connected` were corrected from
   irreversible to write and read respectively.
3. Every tool was changed from caller to service principal because calls spend
   fixed AWS credentials and/or a configured PostgreSQL role.
4. The guessed `get_job_status requires: [job]` was removed. A caller can supply
   a job ID directly, while `create_cluster` logically produces both that ID
   and a cached connection and the v1 format can retain only one.

## Result

The reviewed one-statement policy produces an actionable counterexample:

```text
$ mandate reach docs/evidence/aws-postgres-mcp/mandate.yaml
BREACH  irreversible calls reach 2, above the declared budget of 1 in one run
  1. connect_to_database(database_connection#1)
  2. run_query
  3. run_query
```

`mandate lint` also reports three error-level and four warning-level
`identity.service-principal` findings. Those findings are directionally right,
but “service” loses the important intersection: AWS decides which infrastructure
and secrets are reachable, while the database role decides which SQL succeeds.

This evidence supports the roadmap sequence rather than a schema change in this
PR: provenance-aware authority IR first; conditional effects, delegation chains,
multi-output producers, and resource relationships only after more graphs test
the abstractions. It does not justify executing SQL, importing AWS policy, or
turning AgentMandate into an MCP proxy.
