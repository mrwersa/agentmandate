# Principal-continuity procedure

The capture ran on 11 September 2026 against one short-lived AWS
IAM-authenticated AgentCore Gateway in `us-east-1`, one inert Lambda tool, one
ACTIVE policy engine attached in `ENFORCE`, and a one-hour Dogwood sum. The
reviewed refund mandate, Gateway, target, policy bytes and revision, region,
request sequence, and provider session identifier were fixed within each pair.
Only the authenticated IAM principal changed in the counterfactual arm.

Two temporary IAM users represented principal aliases A and B. The capture
created independent access keys, called STS `GetCallerIdentity` with each key,
required the returned identities to differ, and never wrote either key to disk.
The users received only `bedrock-agentcore:InvokeGateway` on the experiment
Gateway. Their keys, inline policies, and users were deleted in the capture's
`finally` block. Raw identity strings and provider session UUIDs remained only
in temporary files and were deleted after projection.

Twenty pair trials were shuffled with committed seed `20260911`. Ten controls
made two GBP 600 calls through one principal and one fresh policy session. Ten
counterfactuals made the first GBP 600 call through one principal and the
second through the other while reusing the exact same session identifier; the
direction alternated A-to-B and B-to-A. Each principal also made one GBP 500
single-request control and one GBP 1,000 boundary control.

The projector requires canonical UTC timestamps, causally ordered monotonic intervals, exact
MCP request and response shapes, unique UUID session identities per pair, both
principal directions, the shuffled order, zero application or SDK retries,
and the complete provider boundary. It replaces live policy, resource,
identity, request, and session identifiers with stable review aliases. The
provider exposed no consumed, remaining, reserved, in-flight, or completed
state snapshot; those fields remain explicitly unavailable.

One accepted call crossed a host wall-clock adjustment: its UTC finish was
127.88 ms before its UTC start while its monotonic duration was 450.186783 ms and
the pair remained monotonically sequential. Both UTC endpoints and the
negative wall-clock delta are retained. Causal checks use the monotonic clock.

The generated Gateway role initially lacked workload-token permission. The
accepted run added `GetWorkloadAccessToken` for exactly the default workload
directory and the Gateway's own workload identity. Earlier failed calls and
all other corrections are excluded in
`principal-continuity-corrections.json`. Cleanup removed the stack, Gateway,
target, engine, policies, Lambda, two generated roles, the residual log group,
and both temporary principal users. Only the reusable CDK bootstrap remains.
