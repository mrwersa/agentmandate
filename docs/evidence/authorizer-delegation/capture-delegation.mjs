// Capture a sanitized RFC 8693 delegation chain from Authorizer 2.4.0.
// Derived from authorizerdev/examples/with-agent-delegation at c48e885.
// Node 18+ only; no package dependencies. Raw tokens never leave this process.

import { writeFileSync } from "node:fs";

const BASE = process.env.AUTHORIZER_URL ?? "http://localhost:8080";
const ADMIN_SECRET = process.env.AUTHORIZER_ADMIN_SECRET;
const ORIGIN = process.env.AUTHORIZER_ORIGIN ?? BASE;
const SETTLE_MS = 2100;

const TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token";
const GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange";
const SUBJECT_ALIAS = "subject:demo-user";
const USER_EMAIL = "agentmandate-delegation@example.invalid";
const USER_PASSWORD = "LocalCaptureOnly1!";
const USER_SCOPES = ["openid", "email", "profile", "crm:read", "crm:write", "mail:send"];

const AGENTS = [
  { key: "orchestrator", scopes: USER_SCOPES },
  { key: "research-agent", scopes: ["openid", "crm:read", "crm:write"] },
  { key: "crm-reader", scopes: ["openid", "crm:read"] },
  { key: "export-agent", scopes: ["openid", "crm:read"] },
  { key: "archiver", scopes: ["openid", "crm:read"] },
  { key: "mailer", scopes: ["mail:send"] },
];

function fail(message) {
  throw new Error(message);
}

function requireSafeTarget() {
  const target = new URL(BASE);
  if (
    target.protocol !== "http:" ||
    !["localhost", "127.0.0.1"].includes(target.hostname) ||
    target.port !== "8080"
  ) {
    fail("capture refuses any target except an HTTP loopback server on port 8080");
  }
  if (!ADMIN_SECRET) fail("AUTHORIZER_ADMIN_SECRET is required");
}

function outputPath() {
  const index = process.argv.indexOf("--output");
  if (index === -1 || !process.argv[index + 1] || process.argv.length !== 4) {
    fail("usage: node capture-delegation.mjs --output PATH");
  }
  return process.argv[index + 1];
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function gqlFull(query, variables = undefined, headers = {}) {
  const response = await fetch(`${BASE}/graphql`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: ORIGIN, ...headers },
    body: JSON.stringify({ query, variables }),
  });
  const body = await response.json();
  if (body.errors) fail(body.errors.map((error) => error.message).join("; "));
  return { data: body.data, setCookies: response.headers.getSetCookie() };
}

const gql = (query, variables, headers) =>
  gqlFull(query, variables, headers).then((result) => result.data);
const adminGql = (query, variables) =>
  gql(query, variables, { "x-authorizer-admin-secret": ADMIN_SECRET });

function cookieHeader(setCookies) {
  return setCookies.map((cookie) => cookie.split(";")[0]).join("; ");
}

async function oauthToken(parameters) {
  const response = await fetch(`${BASE}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Origin: ORIGIN },
    body: new URLSearchParams(parameters),
  });
  return { status: response.status, body: await response.json() };
}

function decodeJwt(token) {
  const parts = token.split(".");
  if (parts.length !== 3) fail("server returned a non-JWT access token");
  return JSON.parse(Buffer.from(parts[1], "base64url").toString());
}

async function settleMfaOffer(authentication, setCookies) {
  if (authentication?.access_token) return authentication.access_token;
  const { data } = await gqlFull(
    `mutation ($params: SkipMfaSetupRequest!) {
      skip_mfa_setup(params: $params) { access_token }
    }`,
    { params: { email: USER_EMAIL } },
    { Cookie: cookieHeader(setCookies) }
  );
  return data.skip_mfa_setup.access_token;
}

async function getUserToken() {
  const login = async () => {
    const { data, setCookies } = await gqlFull(
      `mutation ($params: LoginRequest!) { login(params: $params) { access_token } }`,
      { params: { email: USER_EMAIL, password: USER_PASSWORD, scope: USER_SCOPES } }
    );
    return settleMfaOffer(data.login, setCookies);
  };
  const signup = async () => {
    const { data, setCookies } = await gqlFull(
      `mutation ($params: SignUpRequest!) { signup(params: $params) { access_token } }`,
      {
        params: {
          email: USER_EMAIL,
          password: USER_PASSWORD,
          confirm_password: USER_PASSWORD,
          scope: USER_SCOPES,
        },
      }
    );
    return settleMfaOffer(data.signup, setCookies);
  };

  try {
    return await login();
  } catch {
    // Continue to a disposable signup.
  }
  try {
    return await signup();
  } catch {
    // A prior interrupted capture may have left the disposable user behind.
  }
  const staleUserId = await findUserId();
  if (!staleUserId) fail("could not recover the disposable capture user");
  await deleteUser(staleUserId);
  return signup();
}

async function findUserId() {
  try {
    const data = await adminGql(
      `query ($params: GetUserRequest!) { _user(params: $params) { id } }`,
      { params: { email: USER_EMAIL } }
    );
    return data._user.id;
  } catch {
    return undefined;
  }
}

async function deleteUser(id) {
  return adminGql(
    `mutation ($params: DeleteUserRequest!) {
      _delete_user(params: $params) { message }
    }`,
    { params: { id } }
  );
}

async function exchange(agent, subjectToken, resource, scope = undefined) {
  // A rapid upstream run hit "Token used before issued" after the host clock
  // stepped backwards by one second. This interval changes no authority fact.
  await sleep(SETTLE_MS);
  return oauthToken({
    grant_type: GRANT_TOKEN_EXCHANGE,
    client_id: agent.clientId,
    client_secret: agent.clientSecret,
    subject_token: subjectToken,
    subject_token_type: TOKEN_TYPE_ACCESS,
    actor_token: agent.machineToken,
    actor_token_type: TOKEN_TYPE_ACCESS,
    resource,
    ...(scope ? { scope } : {}),
  });
}

function requireSuccess(label, result) {
  if (result.status !== 200 || typeof result.body.access_token !== "string") {
    fail(`${label} did not issue an access token`);
  }
  return result.body;
}

function actorChain(act, aliases) {
  const chain = [];
  for (let current = act; current; current = current.act) {
    const alias = aliases.get(current.sub);
    if (!alias) fail("delegated token contains an unknown actor identifier");
    chain.push(`agent:${alias}`);
  }
  return chain;
}

function normalizedHop(hop, actor, expectedSubject, tokenResponse, aliases) {
  const claims = decodeJwt(tokenResponse.access_token);
  if (claims.sub !== expectedSubject) fail(`hop ${hop} changed the subject`);
  if (!Number.isInteger(claims.iat) || !Number.isInteger(claims.exp)) {
    fail(`hop ${hop} lacks integer iat/exp claims`);
  }
  const ttl = claims.exp - claims.iat;
  if (ttl !== tokenResponse.expires_in) fail(`hop ${hop} TTL disagrees with expires_in`);
  const chain = actorChain(claims.act, aliases);
  if (chain[0] !== `agent:${actor}`) fail(`hop ${hop} immediate actor is not the requester`);
  return {
    actor: `agent:${actor}`,
    actor_chain: chain,
    audience: claims.aud,
    grantor: claims.iss,
    hop,
    issued_token_type: tokenResponse.issued_token_type,
    scopes: claims.scope,
    subject: SUBJECT_ALIAS,
    ttl_seconds: ttl,
  };
}

function normalizedRejection(name, result, expectedError) {
  if (result.status === 200 || result.body.error !== expectedError) {
    fail(`${name} did not fail closed with ${expectedError}`);
  }
  return {
    error: result.body.error,
    error_description: result.body.error_description,
    http_status: result.status,
    name,
  };
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonical(child)])
    );
  }
  return value;
}

async function capture() {
  requireSafeTarget();
  const destination = outputPath();
  const aliases = new Map();
  let userId;

  try {
    for (const agent of AGENTS) {
      const data = await adminGql(
        `mutation ($params: CreateClientRequest!) {
          _create_client(params: $params) {
            client { id client_id allowed_scopes }
            client_secret
          }
        }`,
        { params: { name: `${agent.key}-${Date.now()}`, allowed_scopes: agent.scopes } }
      );
      agent.id = data._create_client.client.id;
      agent.clientId = data._create_client.client.client_id;
      agent.clientSecret = data._create_client.client_secret;
      aliases.set(agent.clientId, agent.key);
    }

    const userToken = await getUserToken();
    const userClaims = decodeJwt(userToken);
    userId = userClaims.sub;
    if (userClaims.act !== undefined) fail("initial user token unexpectedly contains act");

    for (const agent of AGENTS) {
      const response = await oauthToken({
        grant_type: "client_credentials",
        client_id: agent.clientId,
        client_secret: agent.clientSecret,
      });
      agent.machineToken = requireSuccess(`${agent.key} client_credentials`, response).access_token;
    }

    const [orchestrator, research, crmReader, exportAgent, archiver, mailer] = AGENTS;
    const hop1 = requireSuccess(
      "hop 1",
      await exchange(orchestrator, userToken, "https://api.internal/orchestrator")
    );
    const hop2 = requireSuccess(
      "hop 2",
      await exchange(research, hop1.access_token, "https://crm.internal/api")
    );
    const hop3 = requireSuccess(
      "hop 3",
      await exchange(
        crmReader,
        hop2.access_token,
        "https://crm.internal/api/read",
        "openid crm:read"
      )
    );
    const hop4 = requireSuccess(
      "hop 4",
      await exchange(exportAgent, hop3.access_token, "https://export.internal/api")
    );

    const hops = [
      normalizedHop(1, "orchestrator", userId, hop1, aliases),
      normalizedHop(2, "research-agent", userId, hop2, aliases),
      normalizedHop(3, "crm-reader", userId, hop3, aliases),
      normalizedHop(4, "export-agent", userId, hop4, aliases),
    ];
    const expectedScopes = [USER_SCOPES, research.scopes, crmReader.scopes, exportAgent.scopes];
    for (const [index, hop] of hops.entries()) {
      if (JSON.stringify(hop.scopes) !== JSON.stringify(expectedScopes[index])) {
        fail(`hop ${index + 1} scope did not match the reviewed attenuation`);
      }
      if (hop.actor_chain.length !== index + 1 || hop.ttl_seconds !== 300) {
        fail(`hop ${index + 1} chain depth or TTL changed`);
      }
    }

    const depth = await exchange(archiver, hop4.access_token, "https://archive.internal/api");
    const rewiden = await exchange(mailer, hop3.access_token, "https://mail.internal/api");
    const substitutedActor = await oauthToken({
      grant_type: GRANT_TOKEN_EXCHANGE,
      client_id: mailer.clientId,
      client_secret: mailer.clientSecret,
      subject_token: userToken,
      subject_token_type: TOKEN_TYPE_ACCESS,
      actor_token: orchestrator.machineToken,
      actor_token_type: TOKEN_TYPE_ACCESS,
      resource: "https://mail.internal/api",
    });

    const result = {
      capture_version: 1,
      deployment: {
        database: "sqlite",
        interactions: ["loopback GraphQL administration", "loopback OAuth token endpoint"],
        profile: "upstream make dev",
      },
      hops,
      implementation: {
        example_commit: "c48e885918da42bf04ce81ab04b061b12f2c70ce",
        example_sha256: "f3d3083a047eb7bbf27b73f7b5292966efaa6e089e2ac93bcf7f9de77018f1da",
        product: "authorizerdev/authorizer",
        release: "2.4.0",
        source_commit: "4ad0758cebf49e65e91ae45047a1f288d1c95a7f",
        token_exchange_sha256: "f32aca8ad291d8822cbc3d7fe92af89e108998b6d5e586dacdefc84b84b99579",
      },
      rejections: [
        normalizedRejection("chain_depth", depth, "invalid_request"),
        normalizedRejection("scope_rewidening", rewiden, "invalid_scope"),
        normalizedRejection("actor_substitution", substitutedActor, "invalid_grant"),
      ],
      subject: {
        alias: SUBJECT_ALIAS,
        initial_scopes: userClaims.scope,
      },
    };
    writeFileSync(destination, `${JSON.stringify(canonical(result), null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o644,
    });
    console.log(`wrote sanitized delegation capture to ${destination}`);
  } finally {
    for (const agent of AGENTS) {
      if (!agent.id) continue;
      await adminGql(
        `mutation ($params: ClientRequest!) {
          _delete_client(params: $params) { message }
        }`,
        { params: { id: agent.id } }
      ).catch(() => {});
    }
    const disposableUserId = userId ?? (await findUserId());
    if (disposableUserId) await deleteUser(disposableUserId).catch(() => {});
  }
}

capture().catch((error) => {
  console.error(`capture failed: ${error.message}`);
  process.exit(1);
});
