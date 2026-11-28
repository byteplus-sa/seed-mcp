import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EXAMPLES,
  handbookPage,
  resolveDocLink,
  schemaTable,
  toolPage,
} from "./docs.mjs";

test("handbook metadata links to canonical sources and preserves explicit overrides", () => {
  const page = handbookPage(
    "integrations/codex.md",
    "---\ntitle: Codex\n---\n\n__TOOL_COUNT__ tools",
    39,
  );
  assert.match(page, /edit\/main\/docs\/integrations\/codex.md/);
  assert.match(page, /39 tools/);
  assert.equal(
    handbookPage("integrations/codex.md", page.replaceAll("\n", "\r\n"), 39),
    page,
  );
  const error = "---\ntitle: Not Found\neditUrl: false\n---";
  assert.equal(handbookPage("404.md", error, 39), error);
  const plain = handbookPage("tools.md", "# Tools\n\nUse tools.", 39);
  assert.match(plain, /title: "Tools"/);
  assert.doesNotMatch(plain, /# Tools/);
});

test("documentation links retain the project base and section fragments", () => {
  assert.equal(
    resolveDocLink("setup/updating.md", "../migration-0.2.md"),
    "https://github.com/byteplus-sa/seed-mcp/blob/main/docs/migration-0.2.md",
  );
  assert.equal(
    resolveDocLink("integrations/codex.md", "../configuration.md#providers"),
    "https://github.com/byteplus-sa/seed-mcp/blob/main/docs/configuration.md#providers",
  );
  assert.equal(
    resolveDocLink("setup/install.md", "../integrations/index.md"),
    "/seed-mcp/setup/install/#clients",
  );
  assert.equal(
    resolveDocLink(
      "getting-started.md",
      "integration-guide.md?view=1#direct-execution",
    ),
    "/seed-mcp/calling-tools/?view=1#direct-execution",
  );
});

test("external URLs, fragment links and source references are preserved correctly", () => {
  assert.equal(
    resolveDocLink("tools.md", "https://example.com/reference.md"),
    "https://example.com/reference.md",
  );
  assert.equal(resolveDocLink("tools.md", "#output"), "#output");
  assert.equal(
    resolveDocLink("getting-started.md", "../.agents/skills/ark-mcp/SKILL.md"),
    "https://github.com/byteplus-sa/seed-mcp/blob/main/.agents/skills/ark-mcp/SKILL.md",
  );
  assert.throws(
    () => resolveDocLink("tools.md", "../../../private.md"),
    /outside repository/,
  );
});

test("field tables describe required fields, choices, constraints and defaults", () => {
  const table = schemaTable({
    type: "object",
    required: ["prompt"],
    properties: {
      prompt: {
        type: "string",
        minLength: 1,
        description: "Text | instruction",
      },
      mode: {
        type: "string",
        enum: ["a", "b"],
        default: "a",
        description: "Mode",
      },
      detail: { $ref: "#/$defs/Detail" },
    },
  });
  assert.match(table, /prompt.*Yes.*Text \\?\| instruction.*minLength: 1/);
  assert.match(table, /mode.*a.*b.*No.*Default/);
  assert.match(table, /Detail/);
  assert.equal(
    schemaTable({ type: "object", properties: {} }),
    "No fields. Pass `{}`.\n",
  );
});

test("nullable operation keys retain string constraints in field tables", () => {
  const table = schemaTable({
    properties: {
      idempotency_key: {
        anyOf: [
          {
            type: "string",
            minLength: 16,
            maxLength: 128,
            pattern: "^[A-Za-z0-9_-]+$",
          },
          { type: "null" },
        ],
        default: null,
        description: "Required for HTTP creation, except Seedance dry runs.",
      },
    },
  });
  assert.match(table, /idempotency_key.*string or null.*No.*Required for HTTP/);
  assert.match(table, /minLength: 16/);
  assert.match(table, /maxLength: 128/);
  assert.ok(table.includes('pattern: "^[A-Za-z0-9_-]+$"'));
  assert.match(table, /Default: null/);
});

for (const name of ["seedance_create_task"]) {
  test(`${name} HTTP example separates receipt recovery from polling and local calls`, () => {
    const original = JSON.stringify(EXAMPLES);
    const page = toolPage({
      name,
      description: "Create provider tasks.",
      execution: "direct",
      registration_gate: "Local provider configuration.",
      transports: {
        http: {
          execution: "direct",
          credential_header: "X-ModelArk-Api-Key",
          registration_gate: "HTTP provider tool.",
        },
      },
      inputSchema: { properties: {} },
      outputSchema: { properties: {} },
    });
    const http = page.split("### HTTP Call")[1].split("<details>")[0];
    const call = JSON.parse(http.match(/```json\n([\s\S]*?)\n```/)[1]);
    assert.equal(call.name, name);
    assert.doesNotMatch(http, /ark_job_submit/);
    assert.equal(call.arguments.input.dry_run, true);
    assert.equal(call.arguments.input.idempotency_key, undefined);
    const local = page.split("Exact MCP call (for developers)</summary>")[1];
    const localCall = JSON.parse(local.match(/```json\n([\s\S]*?)\n```/)[1]);
    assert.equal(localCall.name, name);
    assert.deepEqual(localCall.arguments, EXAMPLES[name]);
    assert.equal(localCall.arguments.input.idempotency_key, undefined);
    assert.equal(JSON.stringify(EXAMPLES), original);
    assert.match(page, /stateless/);
    assert.match(page, /legacy keys are rejected/);
    assert.match(page, /bill again/);
    assert.match(page, /uncertain acceptance/);
  });
}

test("generation tools show a direct input wrapper without jobs", () => {
  const page = toolPage({
    name: "seedream_generate_image",
    description: "Generate an image.",
    execution: "direct",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    scope: "seed:image:generate",
    inputSchema: {
      properties: { input: { $ref: "#/$defs/Input" } },
      $defs: { Input: { properties: { prompt: { type: "string" } } } },
    },
    outputSchema: { properties: { images: { type: "array" } } },
  });
  assert.doesNotMatch(page, /ark_job_submit/);
  assert.match(page, /"arguments": \{\s*"input":/);
  assert.match(page, /"dry_run": true/);
  assert.match(page, /structured_content/);
  assert.match(page, /seed:image:generate/);
  assert.match(page, /Requires BYTEPLUS_MODELARK_API_KEY/);
  assert.match(page, /Ask your connected AI client/);
  assert.match(
    page,
    /<details>\s*<summary>Exact MCP call \(for developers\)<\/summary>/,
  );
});

test("local artifact tools use direct calls and remain unavailable on HTTP", () => {
  const page = toolPage({
    name: "seed_media_get_artifact",
    description: "Retrieve an artifact.",
    execution: "direct",
    registration_gate: "Always registered.",
    scope: null,
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /Direct/);
  assert.doesNotMatch(page, /ark_job_submit/);
  assert.doesNotMatch(page, /An Ark job ID is not a provider task ID/);
  assert.match(page, /HTTP: unavailable/);
});

test("HTTP generation uses a direct envelope and request-only credentials", () => {
  const page = toolPage({
    name: "seedream_generate_image",
    description: "Generate an image.",
    execution: "direct",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    scope: "seedream:generate",
    transports: {
      http: {
        execution: "direct",
        credential_header: "X-ModelArk-Api-Key",
        registration_gate: "Always registered on HTTP.",
      },
    },
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  const http = page.split("### HTTP Call")[1].split("<details>")[0];
  const call = JSON.parse(http.match(/```json\n([\s\S]*?)\n```/)[1]);
  assert.equal(call.name, "seedream_generate_image");
  assert.equal(call.arguments.input.dry_run, true);
  assert.equal(call.arguments.input.persist, undefined);
  assert.doesNotMatch(http, /ark_job_submit/);
  assert.match(page, /X-MCP-Client-Secret/);
  assert.match(page, /client-generated 32 random bytes/);
  assert.match(page, /HTTP rejects true/);
  assert.match(page, /per-call `io\.modelcontextprotocol\/tasks` opt-in/);
  assert.match(page, /before provider dispatch/);
  assert.match(page, /Catalog capability labels are metadata, not auth grants/);
});

test("HTTP discovery has no credential requirement", () => {
  const page = toolPage({
    name: "ark_list_models",
    description: "Discover models.",
    execution: "direct",
    registration_gate: "Always registered.",
    scope: null,
    transports: {
      http: {
        execution: "direct",
        credential_header: null,
        registration_gate: "Anonymous static discovery.",
      },
    },
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /No provider key or client secret is required/);
  assert.doesNotMatch(page, /Supply `X-/);
  assert.match(
    page,
    /configured model bindings even without environment provider keys/,
  );
  assert.match(
    page,
    /`services\[\]\.enabled` reports registration, not entitlement/,
  );
  assert.match(page, /per-call `io\.modelcontextprotocol\/tasks` opt-in/);
});

test("managed Files document both transports and direct client upload without enrollment", () => {
  const page = toolPage({
    name: "ark_file_upload",
    description: "Upload to ModelArk-managed storage.",
    execution: "direct",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    transports: {
      stdio: { execution: "direct" },
      http: {
        execution: "direct",
        credential_header: "X-ModelArk-Api-Key",
        registration_gate: "Always registered on HTTP.",
      },
    },
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /Local stdio execution \| Direct/);
  assert.match(page, /ModelArk-managed files/);
  assert.match(page, /seed-mcp-upload/);
  assert.match(page, /No bucket setup or URL renewal/);
  assert.doesNotMatch(page, /operator-enrolled|MCP_TEMPORARY_UPLOAD_ENABLED/);
  const http = page.split("### HTTP Call")[1].split("<details>")[0];
  assert.equal(
    JSON.parse(http.match(/```json\n([\s\S]*?)\n```/)[1]).name,
    "ark_file_upload",
  );
});

test("Seedance generated guidance preserves accepted IDs on errors", () => {
  const page = toolPage({
    name: "seedance_create_task",
    description: "Create video tasks.",
    execution: "direct",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /`task_id` and `error` can coexist/);
  assert.match(page, /`submitted` counts known accepted IDs/);
  assert.match(page, /`failed` counts entries with errors/);
  assert.match(page, /single-call failure remains error `ToolResult` text/);
  assert.match(page, /HTTP polling uses provider-key authorization/);
  assert.doesNotMatch(page, /MCP polling requires recorded ownership/);
  assert.match(
    page,
    /There is no durable replay or automatic partial-batch resume/,
  );
});

test("renderer rejects obsolete or missing execution metadata", () => {
  const tool = {
    name: "ark_list_models",
    execution: "direct",
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  };
  for (const override of [
    { execution: undefined },
    { execution: "background" },
    { background: null },
    { transports: { http: { execution: "direct", background: null } } },
    { transports: { stdio: {} } },
  ]) {
    assert.throws(
      () => toolPage({ ...tool, ...override }),
      /execution metadata/,
    );
  }
  const page = toolPage(tool);
  assert.match(page, /660-second client timeout/);
  assert.match(page, /600-second cooperative tool deadline/);
  assert.match(page, /SQLite\/SDK cleanup may exceed/);
  assert.match(page, /ADMISSION_TIMEOUT/);
  assert.match(page, /TOOL_DEADLINE_EXCEEDED/);
  assert.match(page, /never blindly resubmit/);
});
