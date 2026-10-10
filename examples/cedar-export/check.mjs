// Verify generated policies with the pinned native engine, never Python policy evaluation.
import fs from 'node:fs';
import path from 'node:path';
import cedar from '@cedar-policy/cedar-wasm/nodejs';

const directory = process.argv[2] || 'generated';
const read = (name) => fs.readFileSync(path.join(directory, name), 'utf8');
const receipt = JSON.parse(read('export.json'));
if (receipt.target.sdk_version !== '4.12.0' || receipt.native_validation !== 'not_run') {
  throw new Error('unexpected compiler target or native-validation claim');
}
const parsed = cedar.policySetTextToParts(read('policies.cedar'));
if (parsed.type !== 'success') throw new Error(JSON.stringify(parsed));
const policies = {staticPolicies: Object.fromEntries(parsed.policies.map((p, i) => [`p${i}`, p]))};
const schema = JSON.parse(read('schema.json'));
const entities = JSON.parse(read('entities.json'));
const validation = cedar.validate({policies, schema});
if (validation.type !== 'success' || validation.validationErrors.length) {
  throw new Error(JSON.stringify(validation));
}
const cases = JSON.parse(read('tests.json'));
const decisions = [];
for (const test of cases) {
  const answer = cedar.isAuthorized({...test.request, policies, schema, entities, validateRequest: true});
  if (answer.type !== 'success' || answer.response.decision !== test.expected
      || answer.response.diagnostics.errors.length) {
    throw new Error(`${test.name}: ${JSON.stringify(answer)}`);
  }
  decisions.push({name: test.name, decision: answer.response.decision});
}
const allowed = cases.find(test => test.expected === 'allow');
const child = {...allowed.request.principal, id: '__child_principal__'};
const inherited = cedar.isAuthorized({...allowed.request, principal: child, policies,
  entities: [...entities, {uid: child, attrs: {}, parents: [allowed.request.principal]}],
  validateRequest: false});
if (inherited.type !== 'success' || inherited.response.decision !== 'deny') {
  throw new Error('the export incorrectly grants permission to a descendant principal');
}
process.stdout.write(JSON.stringify({sdk: '4.12.0', validation, decisions,
  descendant_principal: 'deny', scope: receipt.scope, losses: receipt.losses}) + '\n');
