# Discover ceilings while retaining required payments

From the repository root:

```bash
mandate remediate examples/dispute-resolver-v2.yaml --discover-ceiling issue_refund=0.01 --required-workflows examples/remediation/required-refund.json
mandate remediate examples/ceiling-discovery/two-tools.json --discover-ceiling pay=1 --discover-ceiling other=1 --required-workflows examples/ceiling-discovery/required-two-tools.json --json
```

Both exit 1 because the original breach remains. The first finds £125 while
preserving a £100 refund at depth eight. The second returns four ceiling
trade-offs preserving two £1 payments. All requirements are synthetic.
See the [discovery guide](../../docs/ceiling-discovery.md) for limits and scope.
