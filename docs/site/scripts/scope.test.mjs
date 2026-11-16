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
  /\b(?:vod_[a-z_]+|hyper3d_[a-z_]+|hitem3d_[a-z_]+|ark_asset_[a-z_]+|speech_to_text|SEED_SPEECH_ASR_[A-Z_]+|SEED3D_[A-Z_]+|HYPER3D_[A-Z_]+|HITEM3D_[A-Z_]+|SEEDANCE_ASSET_PREFLIGHT|BYTEPLUS_MODELARK_(?:ACCESS_KEY|SECRET_KEY|PRICING_[A-Z_]+|ASSET[A-Z_]*|3D_[A-Z_]+)|BYTEPLUS_VOD_[A-Z_]+)\b/;

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
    ...markdownFiles("docs"),
    ...markdownFiles("specs"),
    ...markdownFiles(".agents/skills/ark-mcp"),
    ...markdownFiles(".agents/skills/ark-mcp-setup"),
  ].filter(
    (path) => !["docs/changelog.md", "docs/migration-0.2.md"].includes(path),
  );
  for (const path of paths) {
    const content = readFileSync(new URL(path, root), "utf8");
    assert.doesNotMatch(content, retired, path);
    assert.doesNotMatch(content, /\bthree_d\b/, path);
  }
});

test("all 21 exported tools retain stable routes and exclude retired contracts", () => {
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
  assert.equal(tools.length, 21);
  const groups = toolReferenceGroups(tools);
  assert.equal(groups.flatMap((group) => group.items).length, 21);
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
  for (const service of [
    "modelark",
    "seed_audio",
    "omnihuman",
    "object_storage",
  ]) {
    assert.ok(limits.includes(`\`${service}\``), service);
  }
  for (const setting of [
    "SEEDREAM_MODEL_BINDINGS",
    "SEEDANCE_MODEL_BINDINGS",
    "SEED_UNDERSTANDING_MODEL_BINDINGS",
  ]) {
    assert.ok(limits.includes(`\`${setting}\``), setting);
  }
  const environment = readFileSync(
    new URL(".agents/skills/ark-mcp/references/environment.md", root),
    "utf8",
  );
  assert.match(environment, /BYTEPLUS_SEED_AUDIO_BASE_URL/);
  assert.match(environment, /raw connection\/transport failures/);
  const observability = readFileSync(
    new URL("docs/observability.md", root),
    "utf8",
  );
  assert.match(observability, /ArtifactRef\.persistence_error/);
  assert.match(observability, /outputs\[\]\.persistence_issue/);
  assert.match(observability, /top-level `persistence_issue`/);
  const jobs = readFileSync(
    new URL("specs/SPEC_BACKGROUND_JOBS.md", root),
    "utf8",
  );
  assert.match(jobs, /persist-URL always downloads and stores/);
  assert.doesNotMatch(jobs, /Runs synchronously when persistence is disabled/);
});

test("native references and current shared-team auth remain explicit", () => {
  const assets = readFileSync(new URL("docs/assets.md", root), "utf8");
  assert.match(assets, /asset:\/\//);
  assert.match(assets, /does not look up asset status/i);
  assert.match(assets, /no asset-to-URL resolution fallback/i);
  const security = readFileSync(new URL("docs/security.md", root), "utf8");
  assert.match(security, /shared-team/);
  assert.match(security, /MCP_API_KEY_SHA256/);
  assert.doesNotMatch(
    security,
    /catalog retains `assets:|Trusted local administration/,
  );
  const runtime = readFileSync(new URL("docs/runtime.md", root), "utf8");
  assert.match(runtime, /`byteplus-vision-cv`/);
  assert.match(runtime, /"vision-cv"/);
  assert.doesNotMatch(
    readFileSync(new URL("docs/architecture.md", root), "utf8"),
    /generation, transcription|calls, transcription|generation, transcription/i,
  );
  assert.match(
    readFileSync(new URL("README.md", root), "utf8"),
    /Per-user BYOK is not implemented/,
  );
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
