import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { EXAMPLES, hostedToolPage, resolveDocLink } from "./docs.mjs";
import {
  collectSources,
  documentTarget,
  HOSTED_TOOLS,
  PUBLIC_PAGES,
  selectHostedTools,
  siteRedirects,
  SOURCE_BASE,
  sourceRoute,
} from "./publication.mjs";

const root = new URL("../../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

test("the public site is a small explicit hosted guide, not the whole handbook", () => {
  assert.equal(PUBLIC_PAGES.length, 11);
  assert.equal(new Set(PUBLIC_PAGES).size, PUBLIC_PAGES.length);
  for (const source of PUBLIC_PAGES) {
    assert.ok(existsSync(new URL(`docs/${source}`, root)), source);
    const text = read(`docs/${source}`);
    // Connection setup includes five client-specific, collapsible templates.
    const limit = source === "setup/install.md" ? 900 : 450;
    assert.ok(
      text.split(/\s+/).length <= limit,
      `${source}: keep the guide concise`,
    );
    assert.doesNotMatch(
      text,
      /git clone|uv sync|python -m ark_mcp|make inspect/,
    );
  }
  for (const source of [
    "getting-started.md",
    "integrations/codex.md",
    "setup/manual-install.md",
    "byteplus-terraform.md",
    "configuration.md",
    "api-reference.md",
    "tools.md",
    "seed-tts.md",
    "hosted-deployment-status.md",
  ]) {
    assert.equal(PUBLIC_PAGES.includes(source), false, source);
    assert.ok(existsSync(new URL(`docs/${source}`, root)), source);
  }
});

test("old routes redirect to the consolidated guide or retained repository source", () => {
  const sources = collectSources();
  assert.equal(new Set(sources.map(sourceRoute)).size, sources.length);
  const redirects = siteRedirects(sources, [{ name: "seed_tts_generate" }]);
  for (const source of sources) {
    if (PUBLIC_PAGES.includes(source)) {
      assert.equal(redirects[sourceRoute(source)], undefined);
    } else {
      assert.equal(redirects[sourceRoute(source)], documentTarget(source));
    }
  }
  assert.equal(redirects["/getting-started/"], "/seed-mcp/setup/install/");
  assert.equal(
    redirects["/integrations/codex/"],
    "/seed-mcp/setup/install/#codex",
  );
  for (const client of ["trae", "opencode"]) {
    assert.equal(
      redirects[`/integrations/${client}/`],
      `/seed-mcp/setup/install/#${client}`,
    );
  }
  assert.equal(redirects["/troubleshooting/"], "/seed-mcp/help/");
  assert.equal(
    redirects["/byteplus-terraform/"],
    "https://github.com/byteplus-sa/seed-mcp/blob/main/docs/byteplus-terraform.md",
  );
  assert.equal(redirects["/tool-reference/seed-tts-generate/"], undefined);
  assert.equal(
    redirects["/seed-tts/"],
    "/seed-mcp/tool-reference/seed-tts-generate/",
  );
});

test("rewritten links retain fragments without sending readers through redirects", () => {
  assert.equal(
    resolveDocLink("setup/install.md", "../service.md#privacy"),
    "/seed-mcp/service/#privacy",
  );
  assert.equal(
    resolveDocLink(
      "index.mdx",
      "/seed-mcp/models/#video-capabilities-videocapabilities",
    ),
    "https://github.com/byteplus-sa/seed-mcp/blob/main/docs/models.md#video-capabilities-videocapabilities",
  );
  assert.equal(
    resolveDocLink("tools.md", "integrations/codex.md?view=1#http-byok"),
    "/seed-mcp/setup/install/?view=1#codex",
  );
  assert.equal(
    resolveDocLink(
      "index.mdx",
      "/seed-mcp/integration-guide/#direct-execution",
    ),
    "/seed-mcp/calling-tools/#direct-execution",
  );
  assert.equal(
    resolveDocLink("index.mdx", "/seed-mcp/not-a-real-page/"),
    "/seed-mcp/not-a-real-page/",
    "Unknown links must reach the build validator, not become guessed GitHub links",
  );
});

test("public tool pages retain exact schemas and one unchanged example", () => {
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
  const result = spawnSync(
    python,
    ["-I", "-B", fileURLToPath(new URL("scripts/export_tool_docs.py", root))],
    {
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
    },
  );
  assert.equal(result.status, 0, "Offline export must succeed");
  const { tools } = JSON.parse(result.stdout);
  const before = JSON.stringify(tools);
  const selected = selectHostedTools(tools);
  assert.equal(
    tools.length,
    14,
    "Publication cannot narrow the runtime catalog",
  );
  assert.deepEqual(
    selected.map((tool) => tool.name),
    HOSTED_TOOLS,
  );
  assert.equal(selected.length, 8);
  for (const tool of selected) {
    const page = hostedToolPage(tool);
    for (const [, target] of page
      .split("## Inputs")[0]
      .matchAll(/\]\(([^)\s]+)\)/g)) {
      const resolved = resolveDocLink(
        `tool-reference/${tool.name.replaceAll("_", "-")}.md`,
        target,
      );
      if (resolved.startsWith(SOURCE_BASE)) {
        assert.ok(
          existsSync(
            new URL(resolved.slice(SOURCE_BASE.length).split(/[?#]/)[0], root),
          ),
          resolved,
        );
      }
    }
    const example = JSON.parse(
      page
        .split('<span id="http-call"></span>')[1]
        .match(/```json\n([\s\S]*?)\n```/)[1],
    );
    assert.deepEqual(example, {
      name: tool.name,
      arguments: EXAMPLES[tool.name],
    });
    for (const [heading, schema] of [
      ["Input Schema", tool.inputSchema],
      ["Output Schema", tool.outputSchema],
    ]) {
      const rendered = page
        .split(`### ${heading}\n`)[1]
        .match(/```json\n([\s\S]*?)\n```/)[1];
      assert.deepEqual(JSON.parse(rendered), schema, tool.name);
    }
    assert.match(page, /<details data-pagefind-ignore>/);
    if (tool.name === "gen_task_cancel_or_delete") {
      assert.match(page, /destructive call, not a preview/);
    }
    if (tool.name === "seed_tts_generate") {
      assert.match(page, /native MCP AudioContent/);
      assert.match(page, /generates audio and may incur charges/);
      assert.match(page, /no persist switch/);
    }
    assert.doesNotMatch(
      page,
      /Local stdio registration \||Exact MCP call \(for developers\)/,
    );
  }
  assert.equal(JSON.stringify(tools), before);
  const local = tools.find((tool) => tool.name === "media_upload");
  assert.throws(() => hostedToolPage(local), /Not a hosted reference tool/);
  assert.throws(
    () => hostedToolPage({ ...selected[0], execution: "background" }),
    /Invalid direct execution/,
  );
  assert.throws(
    () =>
      selectHostedTools(tools.filter((tool) => tool.name !== HOSTED_TOOLS[0])),
    /Missing direct HTTP contract/,
  );
  assert.throws(
    () => selectHostedTools([...tools, tools[0]]),
    /Duplicate tool/,
  );
});

test("short guides preserve the essential billing, privacy and recovery boundaries", () => {
  const service = read("docs/service.md");
  assert.match(service, /keys are not persisted/);
  assert.match(service, /credential-exposure risk/);
  assert.match(service, /not a promise about provider retention/);
  assert.match(service, /Temporary uploads are disabled/);
  assert.match(service, /built-in estimates, not account quotes/);
  const calls = read("docs/calling-tools.md");
  for (const text of [
    "isError",
    "structuredContent",
    "600-second",
    "660-second",
    "ADMISSION_TIMEOUT",
    "TOOL_DEADLINE_EXCEEDED",
    "idempotency_key",
  ]) {
    assert.ok(calls.includes(text), text);
  }
  assert.match(calls, /Never blindly retry/);
  const checks = read("docs/connection-checks.md");
  for (const text of [
    "check_connection",
    "missing_modelark_key",
    "missing_client_secret",
    "endpoint_not_configured",
    "configuration_valid",
    "authentication_verified=false",
    "provider_calls_made=false",
  ]) {
    assert.ok(checks.includes(text), text);
  }
});
