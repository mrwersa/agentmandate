# Temporary fleet review delay

These synthetic files keep an overdue review visible while checking a named,
time-bounded exception. From the repository root:

```bash
mandate fleet exceptions examples/fleet-exceptions/index.json --exceptions examples/fleet-exceptions/exceptions.json --root . --as-of 2026-10-11 --json
```

It exits 0 with the original finding retained in `inventory.findings`. Use
`--as-of 2026-10-19` for the expired exit-1 case, or replace the exceptions file
with `examples/fleet-exceptions/none.json` to leave the review finding uncovered.
The records do not renew the review or approve deployment.

See the [format and CI guide](../../docs/fleet-exceptions.md).
