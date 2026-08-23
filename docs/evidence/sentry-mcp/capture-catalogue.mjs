/** Capture a Sentry MCP tools/list payload without contacting Sentry. */

import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";

const options = Object.fromEntries(
  process.argv.slice(2).map((argument) => {
    const [name, ...value] = argument.split("=");
    return [name, value.join("=")];
  }),
);

if (!options["--server"] || !options["--output"]) {
  throw new Error("usage: capture-catalogue.mjs --server=PATH --output=PATH");
}

function shellQuote(value) {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

// A pseudo-terminal keeps the published CLI's stdio lifecycle open on Node 24.
// stty disables request echo so only server messages enter the capture.
const command = [
  "stty -echo; exec",
  shellQuote(options["--server"]),
  "--access-token=inventory-capture-placeholder",
  "--host=localhost",
  "--insecure-http",
  "--skills=inspect,triage,project-management",
  "--sentry-dsn=",
].join(" ");
const childEnv = { ...process.env, NO_COLOR: "1" };
for (const name of [
  "SENTRY_ACCESS_TOKEN",
  "SENTRY_AUTH_TOKEN",
  "SENTRY_DSN",
  "OPENAI_API_KEY",
  "ANTHROPIC_API_KEY",
  "OPENROUTER_API_KEY",
  "EMBEDDED_AGENT_PROVIDER",
]) {
  delete childEnv[name];
}
const child = spawn("/usr/bin/script", ["-qfec", command, "/dev/null"], {
  env: childEnv,
  stdio: ["pipe", "pipe", "pipe"],
});

let stdout = "";
let stderr = "";
let nextId = 1;
const pending = new Map();

child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
child.stderr.on("data", (chunk) => {
  stderr += chunk;
});
child.stdout.on("data", (chunk) => {
  stdout += chunk;
  while (stdout.includes("\n")) {
    const newline = stdout.indexOf("\n");
    const line = stdout.slice(0, newline).trim();
    stdout = stdout.slice(newline + 1);
    if (!line.startsWith("{")) continue;
    const message = JSON.parse(line);
    const resolver = pending.get(message.id);
    if (resolver) {
      pending.delete(message.id);
      resolver(message);
    }
  }
});

function request(method, params = {}) {
  const id = nextId++;
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  return new Promise((resolve) => pending.set(id, resolve));
}

function notify(method) {
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method })}\n`);
}

let timeoutId;
const timeout = new Promise((_, reject) => {
  timeoutId = setTimeout(
    () => reject(new Error(`MCP capture timed out: ${stderr}`)),
    15_000,
  );
});

try {
  await new Promise((resolve) => setTimeout(resolve, 1_000));
  const initialized = await Promise.race([
    request("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "agentmandate-evidence", version: "1.0.0" },
    }),
    timeout,
  ]);
  if (initialized.error) throw new Error(JSON.stringify(initialized.error));
  notify("notifications/initialized");

  const catalogue = await Promise.race([request("tools/list"), timeout]);
  if (catalogue.error) throw new Error(JSON.stringify(catalogue.error));
  await writeFile(options["--output"], `${JSON.stringify(catalogue.result, null, 2)}\n`);
} finally {
  clearTimeout(timeoutId);
  child.kill();
}
