import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { EXAMPLES, schemaTable, toolPage } from "./docs.mjs";

const root = new URL("../../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const python =
  process.env.ARK_DOCS_PYTHON ||
  fileURLToPath(
    new URL(
      process.platform === "win32"
        ? ".venv/Scripts/python.exe"
        : ".venv/bin/python",
      root,
    ),
  );

function runScript(path, args = []) {
  const result = spawnSync(
    python,
    ["-I", "-B", fileURLToPath(new URL(path, root)), ...args],
    { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
  );
  assert.equal(result.status, 0, `${path} must succeed offline`);
  return result.stdout;
}

test("discovery docs retain anonymous defaults and a separate HTTP-only check", () => {
  assert.deepEqual(EXAMPLES.ark_list_models, { input: {} });
  const { tools } = JSON.parse(runScript("scripts/export_tool_docs.py"));
  const discovery = tools.find((tool) => tool.name === "ark_list_models");
  const inputRef = discovery.inputSchema.properties.input.$ref
    .split("/")
    .at(-1);
  const input = discovery.inputSchema.$defs[inputRef];
  assert.equal(input.properties.check_connection.default, false);
  assert.equal(discovery.outputSchema.properties.connection.default, null);
  const page = toolPage(discovery);
  assert.match(page, /### HTTP Configuration Check/);
  const check = page.split("### HTTP Configuration Check")[1];
  const call = JSON.parse(check.match(/```json\n([\s\S]*?)\n```/)[1]);
  assert.deepEqual(call, {
    name: "ark_list_models",
    arguments: { input: { check_connection: true } },
  });
  for (const field of [
    "configuration_valid",
    "modelark_key_present",
    "client_secret_present",
    "authentication_verified",
    "provider_calls_made",
  ]) {
    assert.ok(page.includes(field), field);
  }
  assert.match(page, /Other kinds are rejected/);
  assert.equal(discovery.execution, "direct");
  assert.equal(discovery.transports.http.execution, "direct");
  assert.match(page, /not echoed/);
  assert.match(page, /operator.*verif/i);
  const connection = discovery.outputSchema.$defs.HttpConnectionCheck;
  assert.equal(connection.properties.authentication_verified.const, false);
  assert.equal(connection.properties.provider_calls_made.const, false);
  const table = schemaTable(connection);
  assert.match(table, /configuration_valid.*both required headers/);
  assert.match(table, /provider_calls_made.*false.*no provider/);
  const routes = schemaTable(
    discovery.outputSchema.$defs.EndpointSelectionCheck,
  );
  assert.match(routes, /model_id.*null.*unknown.*not echoed/);
  assert.match(routes, /family.*Operator-configured/);
});

for (const [client, language] of [
  ["codex", "toml"],
  ["claude-code", "json"],
]) {
  test(`${client} HTTP docs reproduce the pure generator's default snippet`, () => {
    const generated = runScript("scripts/configure_http_client.py", [
      "--client",
      client,
      "--url",
      "https://mcp.example.com/mcp",
      "--name",
      "ark-seed",
    ]);
    for (const path of [
      `docs/integrations/${client}.md`,
      ".agents/skills/ark-mcp-setup/references/clients.md",
    ]) {
      const http = read(path).split("## HTTP BYOK")[1];
      const snippets = [
        ...http.matchAll(
          new RegExp("```" + language + "\\n([\\s\\S]*?)\\n```", "g"),
        ),
      ].map((match) =>
        match[1].replaceAll(" # pragma: allowlist secret", "").trim(),
      );
      assert.ok(snippets.includes(generated.trim()), path);
    }
    assert.doesNotMatch(generated, /bearer_token_env_var|Authorization/);
  });
}

test("hosted onboarding templates match the generator and deployment record", () => {
  const status = read("docs/hosted-deployment-status.md");
  const endpoint = status.match(
    /Streamable HTTP MCP endpoint:\s*```text\n([^\n]+)\n```/,
  )?.[1];
  assert.ok(endpoint);
  assert.ok(endpoint.startsWith("https://"));
  assert.ok(endpoint.endsWith("/mcp"));
  const install = read("docs/setup/install.md");
  assert.ok(install.includes(`| MCP URL | \`${endpoint}\` |`));
  for (const [client, language] of [
    ["codex", "toml"],
    ["claude-code", "json"],
  ]) {
    const generated = runScript("scripts/configure_http_client.py", [
      "--client",
      client,
      "--url",
      endpoint,
      "--name",
      "ark-seed",
    ]);
    const snippet = install.match(
      new RegExp("```" + language + "\\n([\\s\\S]*?)\\n```"),
    )?.[1];
    assert.equal(
      snippet?.replaceAll(" # pragma: allowlist secret", "").trim(),
      generated.trim(),
      client,
    );
  }
});

test("setup separates supported binding checks from external acceptance", () => {
  const shared = read("docs/setup/shared-server.md");
  for (const text of [
    "--seedance-endpoint-env",
    "--seedream-endpoint-env",
    "missing_modelark_key",
    "missing_client_secret",
    "endpoint_not_configured",
    "configuration_valid",
    "stdout",
  ]) {
    assert.ok(shared.includes(text), text);
  }
  const spec = read("specs/SPEC_HOSTED_BYOK.md");
  assert.match(spec, /get-endpoint-api#authentication/);
  assert.match(spec, /OpenAPI/);
  assert.match(spec, /AK\/SK/);
  assert.match(spec, /model-driven.*Codex.*Claude/);
  assert.match(spec, /paid.*provider.*pending/i);
  for (const path of [
    "README.md",
    "AGENTS.md",
    "docs/setup/shared-server.md",
    "specs/SPEC_HOSTED_BYOK.md",
    ".agents/skills/ark-mcp/SKILL.md",
    ".agents/skills/ark-mcp-setup/SKILL.md",
  ]) {
    assert.match(read(path), /check_connection/, path);
    assert.doesNotMatch(
      read(path),
      /plans\/PLAN_BYOE_CLIENT_WORKFLOW\.md/,
      path,
    );
  }
});
