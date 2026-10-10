# Catalogue import baselines

For each `mcp`, `openapi`, `a2a`, and `a2a-1.0` source in
[`examples/catalogue-import`](../../../examples/catalogue-import/README.md):

- `*-skeleton.yaml` pins the review-marked proposal for agent `refunds`.
- `*-inventory-v1.json` pins the unreviewed dynamic-inventory declaration.
- `*-inventory-ir-v1.json` pins that declaration's existing inventory IR profile.

All targets use `agent.py`, binding `resolver`, selection
`{"environment":"example"}`, and boundary `example-FORMAT`. A2A explicitly
uses dispatch tool `ask_refund_agent`. Source digests identify the synthetic
input bytes; they do not authenticate a service or validate adapter mappings.

`tests/test_catalogue_import.py` checks canonical bytes, input digest joins,
partial pages, malformed/ambiguous input, trust refusal, and mode separation.
The files pin existing v1 output contracts, not a migration from an older
import schema. No additional IR relation, artifact version, or accepted
evidence boundary is introduced.
