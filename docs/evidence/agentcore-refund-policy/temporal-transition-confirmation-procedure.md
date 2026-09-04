# Repeated transition confirmation

The confirmation ran from 3 to 4 September 2026 against one short-lived AWS
IAM-authenticated AgentCore Gateway in `us-east-1`, one inert Lambda tool, and
an ENFORCE-mode temporal policy. A fixed external mandate digest identified the
same experiment mandate throughout. The managed Gateway did not inspect that
digest. It is the protocol's independently fixed unit of authorisation.

The temporal policy refused a request when the sum of completed `amount`
values in the preceding hour plus the current request reached 1,000. Each call
used amount 600. The request domain is representative rather than complete.

The main capture interleaved ten byte-identical trials with ten bound-variable
renaming trials, then ran ten whitespace-only trials. The two policy forms took
turns as the active successor in the first two arms. Each byte-identical trial
issued 600, submitted the exact active statement, polled until ACTIVE, and
issued 600 again in the same session. Each renaming and whitespace-only trial
issued 600, required a distinct exact ACTIVE revision, retried the predecessor
session, then made two calls through one fresh successor session. A separate
description-only trial supplied no policy definition and retained the exact
statement digest while exercising the same call sequence.

`temporal-transition-events.json` preserves sanitised call bodies, UTC
timestamps, every submitted statement update, its managed response, policy
status polls, statement digests, and pseudonymous revision and session
identities. `temporal-transition-metadata-events.json` preserves the separate
description-only update. The two submitted policy forms are committed
separately, so the projector checks each trial's statement and digest rather
than accepting a style label on faith. It constructs the whitespace-only form
from the committed policy and checks every predecessor-to-successor sequence
against the policy's one-hour window.

`temporal-transition-confirmation-summary.json` is derived from those records
by `capture_transition_repetition.py`. Trial shape and outcomes are validation
conditions. The projector also requires canonical microsecond UTC timestamps,
causal call/update/poll ordering, the stated byte/rename interleaving, and the
overall capture bounds. Every reported count and interval is computed from
those validated events. The earlier `temporal-semantic-noop-repetition.json`
remains unchanged as a historical migration input.

The first attempt was excluded because the generated Gateway role lacked the
workload-token permission required for policy-session evaluation. The exact
deployment-policy correction and strict native validation refusal are preserved
separately. Cleanup removed the Gateway, generated role, target, engine,
policies, Lambda, Lambda role, and log group. The committed cleanup record
contains operation-level `Get*` not-found results and an empty log-group query.
Only the reusable CDK bootstrap remains.
