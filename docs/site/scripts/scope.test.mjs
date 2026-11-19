import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import examples from "../tool-examples.json" with { type: "json" };
import models from "../tool-models.json" with { type: "json" };
import { toolReferenceGroups } from "./navigation.mjs";

const root = new URL("../../../", import.meta.url);
const retired =
  /\b(?:OmniHuman|omnihuman_[a-z_]+|vision-cv|openapi\.cv\.bytepluses\.com|cv\.byteplusapi\.com|realman_avatar_picture_omni20_cv|BYTEPLUS_(?:CV_[A-Z_]+|OMNIHUMAN_[A-Z_]+)|ark_job_[a-z_*]+|seed_understand|seed_audio_understand|SEED_UNDERSTANDING_[A-Z_]+|SEED_AUDIO_UNDERSTANDING_[A-Z_]+|FASTMCP_DOCKET_[A-Z_]+|FASTMCP_TASKS_ENCRYPTION_KEY|vod_[a-z_]+|hyper3d_[a-z_]+|hitem3d_[a-z_]+|ark_asset_[a-z_]+|speech_to_text|SEED_SPEECH_ASR_[A-Z_]+|SEED3D_[A-Z_]+|HYPER3D_[A-Z_]+|HITEM3D_[A-Z_]+|SEEDANCE_ASSET_PREFLIGHT|BYTEPLUS_MODELARK_(?:ACCESS_KEY|SECRET_KEY|PRICING_[A-Z_]+|ASSET[A-Z_]*|3D_[A-Z_]+)|BYTEPLUS_VOD_[A-Z_]+)\b/;

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

test("current handbook and shipped skills exclude retired tool and configuration contracts", () => {
  const paths = [
    "README.md",
    "AGENTS.md",
    ".env.example",
    ...markdownFiles("docs"),
    ...markdownFiles("docs/site/tool-notes"),
    ...markdownFiles("specs"),
    ...markdownFiles(".agents/skills/ark-mcp"),
    ...markdownFiles(".agents/skills/ark-mcp-setup"),
  ].filter(
    (path) => !["docs/changelog.md", "docs/migration-0.2.md"].includes(path),
  );
  for (const path of paths) {
    const content = readFileSync(new URL(path, root), "utf8");
    if (path.startsWith("specs/") && /^status: deprecated$/m.test(content)) {
      continue;
    }
    assert.doesNotMatch(content, retired, path);
    assert.doesNotMatch(content, /\bthree_d\b/, path);
  }
});

test("all 13 exported tools retain direct metadata and exclude retired contracts", () => {
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
  const exported = spawnSync(
    python,
    ["-I", "-B", fileURLToPath(new URL("scripts/export_tool_docs.py", root))],
    { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
  );
  assert.equal(exported.status, 0, "Isolated catalog export must succeed");
  const { tools } = JSON.parse(exported.stdout);
  assert.equal(tools.length, 13);
  const groups = toolReferenceGroups(tools);
  assert.equal(groups.flatMap((group) => group.items).length, 13);
  for (const tool of tools) {
    assert.equal(tool.execution, "direct", tool.name);
    assert.equal("background" in tool, false, tool.name);
    for (const transport of Object.values(tool.transports)) {
      if (!transport) continue;
      assert.equal(transport.execution, "direct", tool.name);
      assert.equal("background" in transport, false, tool.name);
    }
  }
  const http = tools.filter((tool) => tool.transports.http);
  assert.equal(http.length, 8);
  assert.doesNotMatch(JSON.stringify(tools), retired);
  assert.doesNotMatch(JSON.stringify(tools), /\bthree_d\b/);
  const seedream = tools.find(
    (tool) => tool.name === "seedream_generate_image",
  );
  const preview = seedream.outputSchema.$defs.SeedreamGeneratePreview;
  assert.equal(preview.properties.price_source.const, "builtin");
  assert.match(preview.properties.estimated_cost_usd.description, /built-in/i);
  assert.doesNotMatch(JSON.stringify(seedream), /cached account|HTTP\/HTTPS/i);
  const names = new Set(tools.map((tool) => tool.name));
  for (const name of [...Object.keys(examples), ...Object.keys(models)]) {
    assert.doesNotMatch(name, retired);
    assert.ok(names.has(name), name);
  }
});

test("project-local setup selects the narrowed fork without assuming publication", () => {
  const setup = readFileSync(
    new URL(".agents/skills/ark-mcp-setup/SKILL.md", root),
    "utf8",
  );
  assert.match(
    setup,
    /Default upstream: `https:\/\/github\.com\/byteplus-sa\/seed-mcp\.git`/,
  );
  const releases = readFileSync(
    new URL(".agents/skills/ark-mcp-setup/references/releases.md", root),
    "utf8",
  );
  assert.match(releases, /repos\/byteplus-sa\/seed-mcp\/releases\/latest/);
  assert.match(
    releases,
    /Clone `https:\/\/github\.com\/byteplus-sa\/seed-mcp\.git`/,
  );
  assert.doesNotMatch(releases, /gh api .*repos\/byteplus-sa\/ark-mcp/);
  assert.match(setup, /No Seed MCP Pages deployment/);
});

test("retained skills document bindings services hosts and accurate persistence", () => {
  const limits = readFileSync(
    new URL(".agents/skills/ark-mcp/references/models-and-limits.md", root),
    "utf8",
  );
  assert.match(limits, /`services\[\]`/);
  for (const service of ["modelark", "seed_audio", "object_storage"]) {
    assert.ok(limits.includes(`\`${service}\``), service);
  }
  for (const setting of [
    "SEEDREAM_MODEL_BINDINGS",
    "SEEDANCE_MODEL_BINDINGS",
  ]) {
    assert.ok(limits.includes(`\`${setting}\``), setting);
  }
  const environment = readFileSync(
    new URL(".agents/skills/ark-mcp/references/environment.md", root),
    "utf8",
  );
  assert.match(environment, /BYTEPLUS_SEED_AUDIO_BASE_URL/);
  assert.match(environment, /malformed 2xx responses/);
  assert.match(environment, /ambiguous\/nonretryable/);
  assert.doesNotMatch(
    environment,
    /existing Seedance adapter.*not.*ambiguous/s,
  );
  const observability = readFileSync(
    new URL("docs/observability.md", root),
    "utf8",
  );
  assert.match(observability, /ArtifactRef\.persistence_error/);
  assert.match(observability, /outputs\[\]\.persistence_issue/);
  const jobs = readFileSync(
    new URL("specs/SPEC_BACKGROUND_JOBS.md", root),
    "utf8",
  );
  assert.match(jobs, /^status: deprecated$/m);
  assert.match(jobs, /SPEC_DIRECT_EXECUTION\.md/);
  const direct = readFileSync(
    new URL("specs/SPEC_DIRECT_EXECUTION.md", root),
    "utf8",
  );
  for (const required of [
    "MCP_ADMISSION_TIMEOUT_SECONDS",
    "MCP_TOOL_TIMEOUT_SECONDS",
    "ADMISSION_TIMEOUT",
    "TOOL_DEADLINE_EXCEEDED",
    "660",
    "SDK",
    "SQLite",
    "owner slot first",
    "stateless",
  ]) {
    assert.ok(direct.includes(required), required);
  }
});

test("native references and current BYOK ownership remain explicit", () => {
  const assets = readFileSync(new URL("docs/assets.md", root), "utf8");
  assert.match(assets, /asset:\/\//);
  assert.match(assets, /does not look up asset status/i);
  assert.match(assets, /no asset-to-URL resolution fallback/i);
  const security = readFileSync(new URL("docs/security.md", root), "utf8");
  assert.match(security, /credential tenant/);
  assert.match(security, /MCP_IDENTITY_HMAC_KEY/);
  assert.match(security, /X-MCP-Client-Secret/);
  assert.doesNotMatch(security, /MCP_API_KEY_SHA256/);
  assert.doesNotMatch(
    security,
    /catalog retains `assets:|Trusted local administration/,
  );
  const runtime = readFileSync(new URL("docs/runtime.md", root), "utf8");
  assert.match(runtime, /`modelark`/);
  assert.match(runtime, /`seed-speech`/);
  assert.doesNotMatch(
    readFileSync(new URL("docs/architecture.md", root), "utf8"),
    /generation, transcription|calls, transcription|generation, transcription/i,
  );
  assert.match(readFileSync(new URL("README.md", root), "utf8"), /HTTP BYOK/);
});

test("current docs and skills cannot restore shared-key HTTP instructions", () => {
  const paths = [
    "README.md",
    "AGENTS.md",
    ...markdownFiles("docs"),
    ...markdownFiles("specs"),
    ...markdownFiles(".agents/skills/ark-mcp"),
    ...markdownFiles(".agents/skills/ark-mcp-setup"),
  ].filter((path) => path !== "docs/changelog.md");
  for (const path of paths) {
    const content = readFileSync(new URL(path, root), "utf8");
    assert.doesNotMatch(
      content,
      /MCP_API_KEY_SHA256|MCP_AUTH_MODE=api_key|make shared-http|Per-user BYOK is not implemented|shared-team/,
      path,
    );
  }
});

test("breaking capability migration requires old-server export before upgrading", () => {
  const migration = readFileSync(
    new URL("docs/migration-0.2.md", root),
    "utf8",
  );
  assert.match(migration, /Historical migration guide/);
  assert.match(migration, /Old saved 3D artifacts are no longer served/);
  assert.match(migration, /old server \*\*before upgrading\*\*/);
  assert.match(migration, /No compatibility layer or automatic migration/);
  for (const path of ["README.md", "docs/artifacts.md", "docs/releases.md"]) {
    assert.match(
      readFileSync(new URL(path, root), "utf8"),
      /breaking-capability-migration/,
      path,
    );
  }
});
