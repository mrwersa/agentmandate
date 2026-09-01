# Repeated transition confirmation

The confirmation ran on 1 September 2026 against one short-lived AWS
IAM-authenticated AgentCore Gateway in `us-east-1`, one inert Lambda tool, and
an ENFORCE-mode temporal policy. A fixed external mandate digest identified the
same experiment mandate throughout. The managed Gateway did not inspect that
digest; it is the protocol's independently fixed unit of authorisation.

The temporal policy refused a request when the sum of completed `amount`
values in the preceding hour plus the current request reached 1,000. Each call
used amount 600. The request domain is representative rather than complete.

Two preregistered arms ran ten times each:

1. The byte-identical arm issued 600, submitted the exact active statement,
   polled the policy until ACTIVE, and issued 600 again in the same session.
2. The alpha-equivalent arm issued 600, alternated two statements that differed
   only in bound-variable names, required a distinct exact ACTIVE revision,
   retried the predecessor session, then followed the managed diagnostic by
   retrying through a fresh session.

`temporal-transition-events.json` preserves sanitized call bodies, every
submitted `UpdatePolicy` request, its managed response, policy status polls,
statement digests, and pseudonymous revision and session identities. The two
submitted policy forms are committed separately, so the projector checks each
trial's named form and digest rather than accepting a style label on faith.
`temporal-transition-confirmation-summary.json` is derived from those events by
`capture_transition_repetition.py`: the preregistered trial shape and outcomes
are validation conditions, while every reported count is computed from the
validated rows. The earlier
`temporal-semantic-noop-repetition.json` remains unchanged as a historical
migration input.

The first attempt was excluded because the generated Gateway role lacked the
workload-token permission required for policy-session evaluation. The exact
deployment-policy correction and the strict native validation refusal are
preserved separately. Cleanup removed the Gateway, generated role, target,
engine, policies, Lambda, Lambda role, and log group. The committed cleanup
record contains the operation-level `Get*` not-found results and empty log-group
query; only the reusable CDK bootstrap remains.
