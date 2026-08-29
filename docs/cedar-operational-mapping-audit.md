# Cedar operational mapping audit

Research cutoff: 29 August 2026. This audit selects a candidate for Cedar
import gate 4; it does not claim that AgentMandate reproduced a managed-policy
decision or that the gate is complete.

## Decision

Use AWS's
[`sample-agentcore-gateway-fgac`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/tree/3e0d462c679c4cddfdea1bfc9176256628c7d699)
at commit `3e0d462c679c4cddfdea1bfc9176256628c7d699` as the operational-mapping
candidate. It clears the source-side screen because a real MCP Gateway target,
finite OpenAPI tool domain, Cedar policies, identity construction, and
ENFORCE-mode attachment are joined in one deployable repository. It does not
yet clear the decision-evidence screen: no AgentCore native validation or
decision record has been captured in this repository.

No deployment was performed during this audit. Deploying the sample would
create billable AWS and Okta resources and requires authority beyond a
read-only evidence review.

## Why the mapping is mechanically testable

The pinned Gateway module registers one `openApiSchema` target named
`ecommerce-tools`, attaches OAuth token exchange, and provisions a policy
engine. Policy attachment is an explicit CLI step because the pinned Terraform
provider does not expose it
([Gateway module](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/infra/modules/agentcore/main.tf),
[attachment script](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/scripts/attach_policy_engine.sh)).

The application's explicit OpenAPI operation IDs define a finite six-tool
domain:

| Operation/tool | Customer | Admin | Source |
|---|---:|---:|---|
| `list_products` | allow | allow | [`products.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/products.py) |
| `add_to_cart` | allow | allow | [`cart.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/cart.py) |
| `checkout` | allow | allow | [`checkout.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/checkout.py) |
| `add_product` | deny | allow | [`products.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/products.py) |
| `update_price` | deny | allow | [`products.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/products.py) |
| `update_stock` | deny | allow | [`products.py`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/app/src/ecommerce/api/products.py) |

The deployment guide creates a customer policy over the first three exact
`ecommerce-tools___<operation>` actions and an admin policy over the target,
then instructs users to observe denial of the three administrative tools in
ENFORCE mode
([deployment and controls](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/README.md)).
The authorization design documents how the verified JWT `role` claim becomes
the Cedar principal tag and how the Gateway constructs and enforces the
request before forwarding it
([authentication chain](https://github.com/aws-samples/sample-agentcore-gateway-fgac/blob/3e0d462c679c4cddfdea1bfc9176256628c7d699/docs/auth.md)).
This matches AWS's documented AgentCore mapping of JWT claims, MCP tool names,
Gateway resources, and tool arguments into Cedar requests
([AgentCore Policy guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html)).

## Why the gate remains open

Source inspection proves how the deployment is intended to construct and
enforce requests; it does not prove a deployed policy engine evaluated them.
README expectations are not native decisions, and a local Cedar replay would
not prove that AgentCore attached the same engine in `ENFORCE` mode. The admin
policy's wildcard is valid Cedar behavior but cannot substitute for an
explicit six-entry AgentMandate mapping.

Issue [#112](https://github.com/mrwersa/agentmandate/issues/112) therefore
requires digest-pinned source capture, set equality across the OpenAPI,
Gateway, Cedar, and mapping domains, and sanitized native controls for:

- customer allow: `list_products`;
- customer deny: `add_product`; and
- admin allow for both calls.

Any absent native output, `LOG_ONLY` attachment, incomplete mapping, or
sanitization that changes decision inputs keeps the bundle ineligible. No
account, tenant, credential, ARN, or trace identifier may enter the fixture.

## Rejected shortcuts

- Do not infer enforcement from deployable source or documentation alone.
- Do not treat a generated OpenAPI document as proof that the Gateway exposed
  or evaluated every operation.
- Do not convert the admin wildcard into an implicit complete tool mapping.
- Do not deploy billable infrastructure without separate authorization.
- Do not present a local Cedar control as an AgentCore decision record.
