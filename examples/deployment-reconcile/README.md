# Captured decision and telemetry joins

From the repository root:

```bash
mandate deployment reconcile examples/deployment-reconcile/manifest.json \
  --config examples/deployment-reconcile/config.json --root . \
  --decisions examples/deployment-reconcile/decisions.json \
  --otel examples/deployment-reconcile/telemetry.json \
  --mapping examples/deployment-reconcile/mapping.json --as-of 2026-10-11
```

The three synthetic pairs exit 0. Replace the telemetry and mapping filenames
with `denied-effect-telemetry.json` and `denied-effect-mapping.json` to report an
applied effect associated with a denial and exit 1. The revised mapping pins
those different synthetic bytes; changing only the capture causes a separate
source-mismatch finding.

These are format examples, not live-service captures or authenticated approval.
The [reconciliation guide](../../docs/deployment-reconciliation.md) explains
instrumentation, completeness, masking, native OPA checks and the distinction
between matched observations and runtime continuity.
