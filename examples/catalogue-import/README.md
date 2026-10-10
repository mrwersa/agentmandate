# Local catalogue imports

These synthetic JSON files demonstrate MCP tools/list, OpenAPI path operations,
and an A2A Agent Card. No service is deployed and the importer makes no network
requests. `agent.py` represents one dynamic source binding and is read
statically; its example framework is deliberately not installed.
`a2a.json` uses the legacy 0.3.0 card; `a2a-1.0.json` uses interface-based 1.0.
Both produce one dispatch candidate without choosing an endpoint.

Start with the [import walkthrough](../../docs/catalogue-import.md) for the
commands and review process. A2A needs `--dispatch-tool ask_refund_agent`:
its two advertised skills do not become two callable tools.

The separately annotated `manifest.json` declares example refund intent.
`mandate reach examples/catalogue-import/manifest.json` finds two £500 refunds
exceeding its £500 total and exits 1. Those intent annotations were not extracted.
An imported unreviewed inventory also leaves `drift` at exit 1; structural
validation may exit 0 without resolving its review or completeness gaps.

[Pinned skeletons and inventory/IR baselines](../../tests/fixtures/catalogue-import/README.md)
record the compatibility boundary, not live deployment facts.
