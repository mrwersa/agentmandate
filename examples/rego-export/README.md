# Rego export example

This release-tool manifest has two caller tools and one service tool. Publishing
requires approval. The explicit mapping produces a stateless, default-deny
Rego policy; it does not add cumulative limits or establish deployment approval.

From the repository root:

```bash
mandate rego export examples/rego-export/manifest.json --mapping examples/rego-export/mapping.json --output-dir release-policy --json
```

The committed `generated/` bundle is a reproducible baseline. To validate either
bundle, follow the binary download and checksum instructions in the
[Rego export guide](../../docs/rego-export.md), then run:

```bash
python examples/rego-export/check.py release-policy --opa ./opa
```

For the committed baseline, omit `release-policy`. Native validation is a
separate check; the export report records `native_validation: not_run`.
