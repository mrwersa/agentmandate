# Synthetic schema-checked Cedar control

This probe exists only to exercise the transport path that the official
document-cloud evidence cannot: both recorded decisions were evaluated with
schema checking enabled. It is hand-authored test material, not evidence of a
deployment or an operational action-to-tool mapping.

Run `npm ci --ignore-scripts && npm run capture` in this directory to
reproduce `native-output.json` byte for byte with the pinned Cedar package.

The allow request is permitted by `policy0`. The deny request is rejected by
the satisfied `forbid` in `policy1`. `mapping` remains `null`, so neither
decision is authority-eligible.
