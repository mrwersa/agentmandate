# Deployment-continuity refusal procedure

The attempted capture ran on 11 September 2026 in `us-east-1` with AgentCore
CLI 0.28.1 and AWS CLI 2.36.8. The intended counterfactual used two
IAM-authenticated, one-tool Gateways attached to one shared ACTIVE policy
engine. It would have held principal, region, policy bytes and revision,
provider session, target name, tool schema, and request sequence fixed while
changing only Gateway deployment identity.

Before any data-plane request, three policy candidates tested whether a
cumulative temporal query could omit Gateway resource identity. The first
used the exact refund action with a Gateway-type resource and was rejected
because tool-specific policies must constrain an exact Gateway. The second
replaced the exact action with an action-type constraint and was rejected
because that form is invalid in an action scope. The third used a valid
unconstrained action scope but was rejected because its exact request event
lacked a tool-specific Gateway schema and every temporal predicate must include
`eventResource: resource`.

Those constraints jointly prevent the intended one-factor experiment. An
exact Gateway resource changes across deployments, and the required
`eventResource: resource` predicate makes that identity the explicit history
partition. A runtime Allow or Deny after cloning the policy would therefore
mix deployment transition with a policy binding change and could not identify
the state-owning boundary.

All candidates used `IGNORE_ALL_FINDINGS`, so the result is not caused by the
stricter analyzer-finding gate. The refusals occurred during managed policy
creation; zero Gateway requests were made and no runtime continuity outcome is
claimed. Live account, resource, request, and deployment identifiers were not
retained.

Each failed CloudFormation stack reached `ROLLBACK_COMPLETE` and was deleted
before the next attempt. The final seven cleanup checks found no named stack,
Gateway, policy engine, Lambda, log group, IAM role, or customer-managed IAM
policy. Reusable account CDK bootstrap resources remain.
