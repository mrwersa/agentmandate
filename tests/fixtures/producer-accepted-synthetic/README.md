# Accepted Synthetic Producer Fixture

This fixture exercises the accepted clean path without converting provider
evidence into an accountable review. Every input says `synthetic`; the producer,
partition, reviewer, and outcome are invented test identities. They make no
claim about AWS IAM, another provider, or runtime enforcement.

The fixture is complete for a later validate-then-consume command: `manifest.json`
declares an unbounded producer, `boundary.json` records an accepted concurrent
maximum of two, `selection.json` binds the reviewed synthetic partition, and the
three source files supply all bytes named by the boundary.

Source pins:

- `catalogue.json`, SHA-256 `3babbbfe9aeff2e40d1c4d154131403d1cfb2bd4b197c36ea45e268e3d9ea975`
- `outcomes.json`, SHA-256 `a9b00aa32fc10933f7160c478cbb1fbdc0d5c8c83f1306742d6f6f29ca5b2362`
- `adapter.py`, SHA-256 `722475ae5cbb10b4fbb344728b57895df5893e24bcbb41ff69f7efde1e4bd3d9`

The expected analysis applies the maximum, preserves successful calls one and
two, removes the modeled rejected third call before its effect, and reports no
producer finding or breach. The real IAM migration remains separately
`unreviewed`.
