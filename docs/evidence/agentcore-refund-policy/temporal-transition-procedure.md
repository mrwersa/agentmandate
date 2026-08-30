# Temporal transition controls

The capture ran on 30 August 2026 against one short-lived AWS IAM-authenticated
AgentCore Gateway in `us-east-1`, one inert Lambda tool, and an ENFORCE-mode
temporal policy. The tool echoed the requested amount and performed no financial
write.

The byte-identical control issued 600, submitted the exact active policy text,
confirmed that the service returned no new revision, and issued a second 600 in
the original session. The semantic no-op cell alternated the two committed
alpha-equivalent policy forms. Every trial first issued 600, required a distinct
ACTIVE revision containing the exact requested form, reused the old session,
then retried in a fresh session. It ran ten times.

The binding cell used the committed `mandate_binding.py` adapter. Each of ten
trials signed a binding for one mandate and the current policy digest, issued
600 through its derived session, alternated the threshold between 1,000 and
1,001, required a distinct exact ACTIVE revision, retried the old binding, then
signed a successor binding for the same mandate and new policy digest. Private
keys, signatures, derived sessions, service timestamps, URLs, ARNs and account
identifiers remained in temporary storage.

Only the sanitized projections are committed. Cleanup deleted the Gateway,
policy engine, policies, Lambda, role and log group; the reusable CDK bootstrap
was retained.
