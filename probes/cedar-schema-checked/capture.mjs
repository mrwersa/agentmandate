import fs from "node:fs";

import cedar from "@cedar-policy/cedar-wasm/nodejs";

const read = (name) => fs.readFileSync(new URL(name, import.meta.url), "utf8");
const parts = cedar.policySetTextToParts(read("policies.cedar"));
if (parts.type !== "success") {
  throw new Error("the pinned Cedar implementation rejected the synthetic policy set");
}
const policies = {
  staticPolicies: Object.fromEntries(parts.policies.map((policy, index) => [`policy${index}`, policy])),
};
const entities = JSON.parse(read("entities.json"));

const entityUid = (text) => {
  const match = /^([^:]+)::"(.*)"$/.exec(text);
  if (!match) {
    throw new Error("the synthetic request contains a non-canonical entity UID");
  }
  return { type: match[1], id: match[2] };
};

const authorize = (name) => {
  const request = JSON.parse(read(name));
  return cedar.isAuthorized({
    principal: entityUid(request.principal),
    action: entityUid(request.action),
    resource: entityUid(request.resource),
    context: request.context,
    policies,
    entities,
    schema: read("policies.cedarschema"),
    validateRequest: true,
  });
};

const allow = authorize("allow-request.json");
const deny = authorize("deny-request.json");
const output = {
  decisions: {
    allow: { decision: allow.response.decision, reason: allow.response.diagnostics.reason },
    deny: { decision: deny.response.decision, reason: deny.response.diagnostics.reason },
  },
  schema_checked: true,
  validation: { errors: [], status: "success", warnings: [] },
};
process.stdout.write(`${JSON.stringify(output)}\n`);
