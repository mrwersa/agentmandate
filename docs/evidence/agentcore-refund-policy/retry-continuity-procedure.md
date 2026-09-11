# Completed-request retransmission procedure

The capture ran on 11 September 2026 against one short-lived,
IAM-authenticated AgentCore Gateway in `us-east-1`, one marker-returning Lambda
tool, and one ACTIVE policy engine attached in `ENFORCE`. An exact-resource
Cedar permit and a one-hour Dogwood sum denied a request when cumulative
synthetic refund input reached GBP 1,000.

The reviewed Gateway invocation documentation exposes a caller-supplied policy
session identifier but no data-plane idempotency token. JSON-RPC `id` was
therefore treated only as the tested correlation-identifier candidate. The
control-plane `clientToken` contract was not projected onto tool calls.

Each of 20 shuffled trials used a fresh provider session and three completed,
sequential requests from one IAM principal. Both arms sent GBP 400, waited 250
ms after receiving the complete response, retransmitted GBP 400, waited
another 250 ms, then sent a fresh-ID GBP 300 probe. The same-ID arm reused the
exact first request bytes for the retransmission. The fresh-ID arm changed only
the JSON-RPC identifier. Ten trials ran per arm with seed `20260911`.

The inert Lambda returned its invocation request identifier as an execution
marker. The projector requires a distinct marker for both admitted GBP 400
calls, replaces every live marker with an ordered alias, and retains no request
identifier. A GBP 500 allow and GBP 1,000 deny used independent sessions as
single-request controls. The provider exposed no consumed, remaining,
reserved, in-flight, or completed state snapshot.

This procedure tests manual retransmission after a completed response. It does
not simulate a lost response or ambiguous timeout, Gateway interceptor retry,
SDK or transport retry, or an application-supplied idempotency key. A result
must not be generalized to any of those mechanisms.

The capture used one temporary IAM user with permission to invoke only the
experiment Gateway. Its access key remained in memory and the user, key, and
inline policy were deleted in `finally`. Policies created after deployment
were deleted before their engine. CloudFormation removed the stack; an exact
residual Lambda log group was detected and explicitly deleted. Eight cleanup
checks passed. Only reusable account CDK bootstrap resources remain.
