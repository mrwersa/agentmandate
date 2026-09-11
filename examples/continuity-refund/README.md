# Refund continuity example

This runnable, explicitly synthetic example uses a familiar customer-support
control: one reviewed mandate may refund at most **GBP 1,000**. The agent
refunds GBP 600, reconnects in a fresh provider session, and attempts another
GBP 600 refund.

The safe observation is `allow, deny`. The second request is denied because
the first GBP 600 remains consumed, leaving GBP 400. If the reconnect instead
reset consumed state to zero, the second request could be allowed and the one
mandate would complete GBP 1,200—despite both sessions individually appearing
to remain below GBP 1,000.

The example amounts are integer GBP values. It is a deterministic contract
fixture, not evidence about AWS or any deployed refund system. Its accepted
review and platform-verification records name their synthetic role.

Run it from the repository root:

```bash
mandate continuity validate examples/continuity-refund/provider.json
mandate continuity validate examples/continuity-refund/binding.json
mandate continuity reconcile examples/continuity-refund/manifest.json \
  --continuity-provider examples/continuity-refund/provider.json \
  --continuity-source examples/continuity-refund/provider-control.json=examples/continuity-refund/provider-control.json \
  --continuity-binding examples/continuity-refund/binding.json \
  --continuity-binding-source examples/continuity-refund/binding-verification.json=examples/continuity-refund/binding-verification.json \
  --continuity-binding-source examples/continuity-refund/policy.json=examples/continuity-refund/policy.json \
  --continuity-as-of 2026-09-06T12:00:00Z --json
```

The result reports `state: preserved`, `authority_change: stable`,
`admission: within_bound`, and `safe_continuation: satisfied`. It also retains
the ordinary manifest Authority rather than treating provider evidence as new
authority.

Run the counterfactual by replacing `provider.json` and its source mapping with
`provider-reset.json` and `provider-control-reset.json`. It exits 1 with both
`continuity.state-reset` and `continuity.admission-overshot`. Its combined
`safe_continuation` remains `unresolved`, not guessed as violated, because a
changed boundary also needs reviewed comparability and issuer-amendment
evidence. The concrete reset and overshoot findings remain visible.
