import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = (path) =>
  readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

test("primary onboarding connects to hosted MCP without installing a server", () => {
  for (const path of ["setup/install.md", "getting-started.md"]) {
    const content = page(path);
    assert.doesNotMatch(content, /```(?:bash|sh|shell|powershell)\b/);
    assert.doesNotMatch(
      content,
      /git clone|uv sync|ARK_MCP_ENV_FILE|--transport stdio|manual-install\.md|## Running the Server/,
    );
    assert.match(content, /hosted/i);
    assert.match(content, /Streamable HTTP/);
    assert.match(content, /optional client secret/i);
  }
  const install = page("setup/install.md");
  assert.match(install, /You only connect your AI client/);
  assert.match(install, /No local MCP server or Kubernetes access is needed/);
  assert.match(install, /service\.md#privacy/);
  assert.match(page("service.md"), /credential-exposure risk/);
  assert.match(install, /id="guided-local-setup"/);
  assert.match(install, /shared-server\.md/);
  assert.match(page("service.md"), /Managed Files import HTTPS URLs/);
  assert.match(install, /cloud uploads import HTTPS URLs/);
  assert.match(
    install,
    /local uploads require installing `seed-mcp-upload` on the client/,
  );
  assert.match(install, /returns native audio without TOS/);
});

test("first use leads with a generation prompt rather than tool orchestration", () => {
  const content = page("setup/first-run.md");
  const prompts = [...content.matchAll(/```text\n([\s\S]*?)\n```/g)].map(
    (match) => match[1],
  );
  assert.ok(prompts.length >= 2);
  assert.match(prompts[0], /generate one image/i);
  assert.match(prompts[0], /red ceramic cup/i);
  assert.match(prompts[0], /download link/i);
  for (const prompt of prompts) {
    assert.doesNotMatch(
      prompt,
      /ark_job_|ark_list_models|seedream_generate_image|seedance_create_task|gen_task_|dry_run|structured_content|poll_after_ms/,
    );
  }
  assert.doesNotMatch(content, /```(?:json|bash|sh|powershell|toml)\b/);
  assert.match(content, /may incur charges/i);
  assert.match(content, /Do not submit a new generation request/);
  assert.match(content, /preview.*not.*generated image/i);
  assert.match(content, /integration-guide\.md#direct-execution/);
  for (const anchor of [
    "discover-before-spending",
    "preview-an-image-request",
    "retrieve-the-job-result",
    "generate-deliberately",
    "video-and-other-provider-tasks",
  ]) {
    assert.ok(
      content.includes(`id="${anchor}"`) ||
        [...content.matchAll(/^## (.+)$/gm)].some(
          (match) => match[1].toLowerCase().replaceAll(" ", "-") === anchor,
        ),
      anchor,
    );
  }
});

test("client guides put optional manual configuration behind disclosure", () => {
  for (const client of [
    "claude-code",
    "claude-desktop",
    "codex",
    "trae",
    "cursor",
    "vscode",
    "opencode",
  ]) {
    const content = page(`integrations/${client}.md`);
    const start = content.indexOf("<details>");
    const end = content.indexOf("</details>", start);
    assert.ok(start > 0 && end > start, client);
    assert.match(content.slice(0, start), /hosted Seed MCP/i, client);
    assert.match(
      content.slice(0, start),
      /No server installation or startup is needed/,
      client,
    );
    assert.doesNotMatch(
      content.slice(0, start),
      /```(?:bash|json|toml|powershell)\b/,
      client,
    );
    for (const match of content.matchAll(
      /```(?:bash|json|toml|powershell)\b/g,
    )) {
      assert.ok(match.index > start && match.index < end, client);
    }
  }
});

test("manual fallback selects a reviewed release and keeps private launch contract", () => {
  const manual = page("setup/manual-install.md");
  assert.match(manual, /latest published non-draft, non-prerelease/);
  assert.match(
    manual,
    /git clone --no-checkout https:\/\/github\.com\/byteplus-sa\/seed-mcp\.git/,
  );
  assert.match(
    manual,
    /git -C seed-mcp switch --detach "<approved-commit-sha>"/,
  );
  assert.match(manual, /do not silently fall back to main/);
  assert.match(manual, /Record its tag\/ref and SHA/);
  assert.match(manual, /No fork release is assumed/);
  assert.match(manual, /Do not substitute an upstream Ark MCP release/);
  assert.match(manual, /uv sync --locked --no-dev/);
  assert.match(manual, /ARK_MCP_ENV_FILE/);
  assert.match(manual, /--no-sync/);
  assert.match(manual, /v0\.2\.0/);
});

test("hosted setup uses private headers and makes skills optional", () => {
  const install = page("setup/install.md");
  assert.match(
    install,
    /agent skill.*is optional; it is not needed to connect/,
  );
  assert.match(install, /Use the `\/mcp` URL, not this documentation website/);
  assert.match(install, /X-MCP-Client-Secret.*Optional:/);
  assert.match(install, /64 lowercase hex/);
  assert.match(install, /different from every provider key/);
  assert.match(install, /does not validate your key or account access/);
  assert.match(install, /private custom headers/);
  assert.match(install, /Do not use\s+`Authorization` or OAuth/i);
  assert.match(install, /twelve tools and `connection=null`/);
  assert.doesNotMatch(
    page("setup/shared-server.md"),
    /does not provide a public hosted endpoint/,
  );
});

test("hosted client examples preserve each client's header syntax and timeout units", () => {
  const install = page("setup/install.md");
  const sections = Object.fromEntries(
    ["TRAE", "OpenCode", "Cline"].map((client) => [
      client,
      install.split(`### ${client}\n`)[1]?.split(/\n#{2,3} /)[0],
    ]),
  );
  const configs = {};
  for (const client of ["TRAE", "OpenCode", "Cline"]) {
    const section = sections[client];
    assert.ok(section, client);
    assert.match(section, /<details>[\s\S]*<\/details>/);
    configs[client] = JSON.parse(section.match(/```json\n([\s\S]*?)\n```/)[1]);
  }
  const trae = configs.TRAE.mcpServers["ark-seed"];
  const opencode = configs.OpenCode.mcp.servers["ark-seed"];
  const cline = configs.Cline.mcpServers["ark-seed"];
  const url = install.match(/https:\/\/[^`\s]+\/mcp/)[0];
  for (const config of [trae, opencode, cline]) {
    assert.equal(config.url, url);
    assert.equal(config.command, undefined);
    assert.equal(config.headers.Authorization, undefined);
    assert.ok(config.headers["X-ModelArk-Api-Key"]);
    assert.equal(config.headers["X-MCP-Client-Secret"], undefined);
  }
  assert.equal(trae.headers.RUN_MCP_TIMEOUT_MS, "660000");
  assert.equal(
    trae.headers["X-ModelArk-Api-Key"],
    "<enter-modelark-key-privately>",
  );
  assert.match(sections.TRAE, /plaintext credentials/);
  assert.match(sections.TRAE, /not environment-backed/);
  assert.equal(opencode.type, "remote");
  assert.equal(opencode.oauth, false);
  assert.equal(opencode.codemode, false);
  assert.equal(opencode.timeout.execution, 660000);
  assert.equal(
    opencode.headers["X-ModelArk-Api-Key"],
    "{env:SEED_MCP_MODELARK_KEY}",
  );
  assert.equal(cline.type, "streamableHttp");
  assert.equal(cline.timeout, 660);
  assert.equal(cline.disabled, false);
  assert.deepEqual(cline.autoApprove, []);
  assert.equal(
    cline.headers["X-ModelArk-Api-Key"],
    "${env:SEED_MCP_MODELARK_KEY}",
  );
  assert.match(install, /### Optional Client Secret/);
  assert.match(install, /openssl rand -hex 32/);
  assert.match(install, /share one per-pod principal concurrency allowance/);
  assert.match(install, /--client-secret-env SEED_MCP_CLIENT_SECRET/);
  assert.match(install, /do not send an empty value/);
  assert.match(sections.Cline, /VS Code extension/);
  assert.match(install, /not live client certification/);
});

test("legacy onboarding does not advise inline provider keys or new dependency edits", () => {
  const gettingStarted = page("getting-started.md");
  const integrationGuide = page("integration-guide.md");
  const troubleshooting = page("troubleshooting.md");
  assert.doesNotMatch(
    gettingStarted + integrationGuide,
    /Inline in the client config|export BYTEPLUS_.*API_KEY|cp \.env\.example/,
  );
  assert.doesNotMatch(troubleshooting, /uv add truststore|ps -eo/);
});
