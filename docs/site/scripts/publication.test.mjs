import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import {
  REPOSITORY_URL,
  SITE_BASE,
  SITE_ORIGIN,
  SITE_TITLE,
} from "../site-config.mjs";
import { SITE_BASE as RENDERER_BASE, SOURCE_BASE, toolPage } from "./docs.mjs";

const root = new URL("../../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

function markdownFiles(directory) {
  return readdirSync(new URL(directory, root), { withFileTypes: true }).flatMap(
    (entry) => {
      if (entry.name === "site") return [];
      const path = `${directory}/${entry.name}`;
      return entry.isDirectory()
        ? markdownFiles(path)
        : /\.mdx?$/.test(entry.name)
          ? [path]
          : [];
    },
  );
}

test("Astro and generated links share the Seed MCP publication identity", () => {
  assert.equal(
    SITE_ORIGIN + SITE_BASE,
    "https://byteplus-sa.github.io/seed-mcp",
  );
  assert.equal(SITE_TITLE, "BytePlus Seed MCP");
  assert.equal(RENDERER_BASE, SITE_BASE);
  assert.equal(SOURCE_BASE, `${REPOSITORY_URL}/blob/main/`);
  const config = read("docs/site/astro.config.mjs");
  for (const property of [
    "site: SITE_ORIGIN",
    "base: SITE_BASE",
    "title: SITE_TITLE",
    "description: SITE_DESCRIPTION",
    "href: REPOSITORY_URL",
  ]) {
    assert.ok(config.includes(property), property);
  }
  assert.match(config, /from "\.\/site-config\.mjs"/);
  assert.match(config, /slug: "seed-tts"/);
  const home = read("docs/index.mdx");
  assert.ok(home.includes(`title: ${SITE_TITLE}`));
  assert.match(home, /__TOOL_COUNT__ tool definitions/);
  assert.match(home, /href="\/seed-mcp\/seed-tts\/"/);
  assert.match(home, /Local stdio only/);
  const notFound = read("docs/404.md");
  assert.match(notFound, /link: \/seed-mcp\/setup\/install\//);
  // Starlight renders this through its dedicated 404 route, not the catch-all.
  assert.match(notFound, /draft: true/);
});

test("current handbook and bundled skills do not send readers to upstream Pages", () => {
  const paths = [
    "README.md",
    "docs/site/tool-models.json",
    ...markdownFiles("docs"),
    ...markdownFiles("docs/site/tool-notes"),
    ...markdownFiles(".agents/skills/ark-mcp"),
    ...markdownFiles(".agents/skills/ark-mcp-setup"),
  ].filter(
    (path) => !["docs/changelog.md", "docs/migration-0.2.md"].includes(path),
  );
  for (const path of paths) {
    const content = read(path);
    assert.doesNotMatch(
      content,
      /https:\/\/byteplus-sa\.github\.io\/ark-mcp(?:\/|["')])/,
      path,
    );
    // Match website links, not unchanged local paths or skill directory names.
    assert.doesNotMatch(
      content,
      /(?:\]\(|(?:href|link)\s*[:=]\s*["']?)\/ark-mcp(?:\/|["'])/,
      path,
    );
    assert.doesNotMatch(
      content,
      /No Seed MCP Pages (?:site|deployment)|no verified Pages deployment|This task publishes no site/,
      path,
    );
  }
});

test("Pages deployment is main-only, fork-restricted and checks repository setup", () => {
  const workflow = read(".github/workflows/docs.yml");
  const deploy = workflow.split("\n  deploy:\n")[1];
  assert.ok(deploy);
  const condition = deploy.match(/^\s+if: (.+)$/m)?.[1];
  assert.ok(condition?.includes("github.repository == 'byteplus-sa/seed-mcp'"));
  assert.ok(condition?.includes("github.event_name != 'pull_request'"));
  assert.ok(condition?.includes("github.ref == 'refs/heads/main'"));
  assert.match(deploy, /pages: write/);
  assert.match(deploy, /id-token: write/);
  assert.match(deploy, /name: github-pages/);
  assert.match(deploy, /gh api "repos\/\$\{GITHUB_REPOSITORY\}\/pages"/);
  assert.match(deploy, /"\$build_type" != "workflow"/);
  assert.match(workflow, /docs\/site\/site-config\.mjs/);
  assert.doesNotMatch(workflow, /pull_request_target/);
});

test("native-asset example uses a direct non-billable Seedance call", () => {
  const assets = read("docs/assets.md");
  const call = JSON.parse(assets.match(/```json\n([\s\S]*?)\n```/)[1]);
  assert.equal(call.name, "seedance_create_task");
  assert.equal(call.arguments.input.dry_run, true);
  assert.deepEqual(call.arguments.input.images, ["asset://asset-EXAMPLE"]);
  assert.doesNotMatch(assets, /job envelope|Ark job ID|"tool_name"/);
});

test("Seed TTS guidance describes always-persisted local audio", () => {
  const page = toolPage({
    name: "seed_tts_generate",
    description: "Speak supplied text.",
    execution: "direct",
    registration_gate: "Requires BYTEPLUS_SEED_SPEECH_API_KEY.",
    transports: { stdio: { execution: "direct" } },
    inputSchema: { properties: {} },
    outputSchema: { properties: {} },
  });
  assert.match(page, /HTTP: unavailable/);
  assert.match(page, /always persists the completed audio/);
  assert.match(page, /no `persist` switch or provider download URL/);
  assert.match(page, /\/seed-mcp\/seed-tts\//);
  assert.doesNotMatch(
    page,
    /Call this tool directly on either supported transport/,
  );
});
