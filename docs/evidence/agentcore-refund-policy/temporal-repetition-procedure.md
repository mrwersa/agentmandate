# Temporal repetition procedure

The 30 session-boundary trials used one READY AWS IAM Gateway, one inert Lambda
tool, one ACTIVE policy engine in `ENFORCE`, and a one-hour Dogwood sum. Every
call supplied `amount: 600`. Each of ten rounds ran three independent cells:

1. two sequential calls under one fresh session identifier;
2. two sequential calls under two fresh identifiers; and
3. two calls under one fresh identifier, released together by a two-party
   barrier and checked for overlapping client-side intervals.

The update experiment ran ten further rounds. A no-update same-session pair was
the control. One call then started a second session, the active policy threshold
alternated between 1,000 and 1,001, and the control plane was polled until a new
ACTIVE revision contained the exact requested statement. The client retried the
old session once, retained the native stale-session diagnostic, then followed
that diagnostic by issuing one request under a fresh session.

The binding experiment used the repository's reviewed Ed25519 adapter. Each of
ten rounds generated independent signed mandate records. Separate client
processes invoked twice with one record, once with a different record, and
locally tested tampered and expired variants. A separate 30-pair latency run
randomised bound/unbound order within each pair and used a fresh identity for
every call. No warm-up or failed call entered that vector.

The capture transformer accepts the temporary raw envelopes, verifies all
reviewed cell outcomes, removes request identifiers, session identifiers,
signatures, URLs, AWS identities and service timestamps, and writes the
committed projections. Raw live files were deleted after projection because
they contained those excluded values. The two policy files replace the live
Gateway ARN with one reviewed logical binding; only the threshold differs.
