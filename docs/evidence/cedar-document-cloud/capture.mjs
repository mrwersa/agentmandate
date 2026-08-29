import fs from "node:fs";
import process from "node:process";

import cedar from "@cedar-policy/cedar-wasm/nodejs";

const read = (name) => fs.readFileSync(new URL(name, import.meta.url), "utf8");
const policyText = read("policies.cedar");
const schema = read("policies.cedarschema");
const entities = JSON.parse(read("entities.json"));
const parts = cedar.policySetTextToParts(policyText);
if (parts.type !== "success") {
  throw new Error("the pinned Cedar implementation rejected the policy set");
}
const policies = {
  staticPolicies: Object.fromEntries(parts.policies.map((policy, index) => [`policy${index}`, policy])),
};

const entityUid = (text) => {
  const match = /^([^:]+)::"(.*)"$/.exec(text);
  if (!match) {
    throw new Error("the request contains a non-canonical entity UID");
  }
  return { type: match[1], id: match[2] };
};

const authorize = (name, useSchema) => {
  const request = JSON.parse(read(name));
  const call = {
    principal: entityUid(request.principal),
    action: entityUid(request.action),
    resource: entityUid(request.resource),
    context: request.context,
    policies,
    entities,
  };
  if (useSchema) {
    call.schema = schema;
    call.validateRequest = true;
  }
  return cedar.isAuthorized(call);
};

const output = {
  cedar: {
    language_version: cedar.getCedarLangVersion(),
    sdk_version: cedar.getCedarSDKVersion(),
  },
  decisions: {
    allow: authorize("allow-request.json", false),
    deny: authorize("deny-request.json", false),
  },
  schema_checked_probe: authorize("allow-request.json", true),
  validation: cedar.validate({ schema, policies }),
};

process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
