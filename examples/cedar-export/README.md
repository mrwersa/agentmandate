# Release-tool policy export

This synthetic application has a caller who can read a release and publish it
with approval, and a separate service principal who can read build status.
No cumulative or binding-history constraints are declared. The application
mapping is explicit; this example does not establish a deployed integration.

```bash
mandate cedar export examples/cedar-export/manifest.json --mapping examples/cedar-export/mapping.json --output-dir /tmp/release-policy --json
cd examples/cedar-export
npm ci --ignore-scripts
node check.mjs /tmp/release-policy
```

`generated/` contains the deterministic export baseline. `npm run check`
validates it with the pinned native engine. The Python test suite additionally
checks an independent 72-request matrix, including escaped identifiers and
multiple allowed principals. The [export guide](../../docs/cedar-export.md)
explains mapping fields, refusal, partial candidates and exit codes.
