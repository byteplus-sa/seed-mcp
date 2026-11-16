import assert from "node:assert/strict";
import { test } from "node:test";
import {
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
    "/ark-mcp/migration-02/",
  );
  assert.equal(
    resolveDocLink("integrations/codex.md", "../configuration.md#providers"),
    "/ark-mcp/configuration/#providers",
  );
  assert.equal(
    resolveDocLink("setup/install.md", "../integrations/index.md"),
    "/ark-mcp/integrations/",
  );
  assert.equal(
    resolveDocLink(
      "getting-started.md",
      "integration-guide.md?view=1#background-execution",
    ),
    "/ark-mcp/integration-guide/?view=1#background-execution",
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

test("required background tools show the complete ordinary job wrapper", () => {
  const page = toolPage({
    name: "seedream_generate_image",
    description: "Generate an image.",
    background: "required",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    scope: "seed:image:generate",
    inputSchema: {
      properties: { input: { $ref: "#/$defs/Input" } },
      $defs: { Input: { properties: { prompt: { type: "string" } } } },
    },
    outputSchema: { properties: { images: { type: "array" } } },
  });
  assert.match(page, /ark_job_submit/);
  assert.match(page, /"arguments": \{\s*"input":/);
  assert.match(page, /"dry_run": true/);
  assert.match(page, /result\.structured_content/);
  assert.match(page, /seed:image:generate/);
  assert.match(page, /Requires BYTEPLUS_MODELARK_API_KEY/);
  assert.match(page, /Ask your connected AI client/);
  assert.match(
    page,
    /<details>\s*<summary>Exact MCP call \(for developers\)<\/summary>/,
  );
});

test("foreground tools do not advise submission through background jobs", () => {
  const page = toolPage({
    name: "ark_job_capabilities",
    description: "Discover jobs.",
    background: null,
    registration_gate: "Always registered.",
    scope: null,
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /Foreground/);
  assert.match(page, /"arguments": \{\}/);
  assert.doesNotMatch(page, /"tool_name": "ark_job_capabilities"/);
  assert.doesNotMatch(page, /An Ark job ID is not a provider task ID/);
  assert.match(page, /HTTP: unavailable/);
});

test("HTTP generation uses a direct envelope and request-only credentials", () => {
  const page = toolPage({
    name: "seedream_generate_image",
    description: "Generate an image.",
    background: "required",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    scope: "seedream:generate",
    transports: {
      http: {
        background: null,
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
  assert.match(
    page,
    /before provider dispatch, snapshot capture\/save or queue creation/,
  );
  assert.match(page, /Catalog capability labels are metadata, not auth grants/);
});

test("HTTP discovery has no credential requirement", () => {
  const page = toolPage({
    name: "ark_list_models",
    description: "Discover models.",
    background: null,
    registration_gate: "Always registered.",
    scope: null,
    transports: {
      http: {
        background: null,
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

test("Seedance generated guidance preserves accepted IDs on errors", () => {
  const page = toolPage({
    name: "seedance_create_task",
    description: "Create video tasks.",
    background: "required",
    registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /`task_id` and `error` can coexist/);
  assert.match(page, /`submitted` counts known accepted IDs/);
  assert.match(page, /`failed` counts entries with errors/);
  assert.match(page, /single-call failure remains error `ToolResult` text/);
  assert.match(page, /MCP polling requires recorded ownership/);
});

for (const name of ["seed_understand", "seed_audio_understand"]) {
  test(`${name} generated guidance treats uncertain completion as billed`, () => {
    const page = toolPage({
      name,
      description: "Understand media.",
      background: "required",
      registration_gate: "Requires BYTEPLUS_MODELARK_API_KEY.",
      inputSchema: { properties: {} },
      outputSchema: { properties: {} },
    });
    assert.match(page, /`retryable=false` and `ambiguous_completion=true`/);
    assert.match(page, /read\/write\/protocol failures/);
    assert.match(page, /malformed provider 2xx responses/);
    assert.match(page, /5xx responses are ambiguous/);
    assert.match(page, /never automatically retried/);
  });
}
