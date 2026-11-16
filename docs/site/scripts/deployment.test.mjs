import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = (path) =>
  readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

test("deployment guide distinguishes partial live provisioning from end-to-end validation", () => {
  const content = page("byteplus-terraform.md").replace(/\s+/g, " ");
  assert.match(content, /## Validation Status/);
  assert.match(content, /2026-11-13/);
  assert.match(content, /EIP quota.*before application activation/i);
  assert.match(content, /Partial Terraform state was preserved/);
  assert.match(
    content,
    /temporary VM, both disks,? and security group.*removed/i,
  );
  assert.match(content, /does not validate the new BYOK application/i);
  assert.match(content, /HTTPS.*resume.*updates.*not yet.*live/i);
});

test("deployment guide separates operator tools from member access", () => {
  const content = page("byteplus-terraform.md").replace(/\s+/g, " ");
  assert.match(content, /## Requirements/);
  assert.match(content, /## Set Up Dependencies/);
  assert.match(content, /## Set Up IAM and Credentials/);
  assert.match(content, /members.*do not need.*IAM/i);
  assert.match(content, /ArkCLI.*bytedcli.*not required/i);
  assert.match(content, /Docker.*installed.*VM/i);
  assert.match(content, /Windows.*not established/i);
  assert.match(content, /Git.*archive/i);
  assert.match(content, /uv python install 3\.12/);
  assert.match(content, /uv sync --locked --no-dev --python 3\.12/);
  assert.match(content, /Terraform `>=1\.9,<2\.0`/);
  assert.match(content, /terraform version/);
  assert.match(content, /deploy_byteplus\.py --help/);
});

test("deployment credentials retain explicit safety and permission boundaries", () => {
  const content = page("byteplus-terraform.md").replace(/\s+/g, " ");
  for (const name of [
    "BYTEPLUS_ACCESS_KEY",
    "BYTEPLUS_SECRET_KEY",
    "BYTEPLUS_SESSION_TOKEN",
    "DescribeImages",
    "DescribeKeyPairs",
    "RunCommand",
    "DescribeInvocationResults",
    "read:packages",
  ]) {
    assert.ok(content.includes(name), name);
  }
  assert.match(content, /not a validated least-privilege IAM policy/i);
  assert.match(content, /Guest commands run as root/i);
  assert.match(content, /CLI.*does not create.*IAM/i);
  assert.match(content, /STS.*requires a new plan/);
  assert.match(content, /mode `0600`/);
  assert.match(content, /Do not mix raw `terraform apply`, manual disk/);
  assert.doesNotMatch(content, /export (?:BYTEPLUS_|CR_PAT)[A-Z_]*=/);
});

test("deployment shell examples parse without running installations or cloud actions", () => {
  const blocks = [
    ...page("byteplus-terraform.md").matchAll(/```bash\n([\s\S]*?)\n```/g),
  ];
  assert.ok(blocks.length > 0);
  for (const [index, block] of blocks.entries()) {
    const result = spawnSync("bash", ["-n"], {
      input: block[1],
      encoding: "utf8",
    });
    assert.equal(
      result.status,
      0,
      `Bash example ${index + 1}: ${result.stderr}`,
    );
  }
});

test("dependency and account setup links use official documentation", () => {
  const content = page("byteplus-terraform.md");
  for (const url of [
    "https://docs.astral.sh/uv/getting-started/installation/",
    "https://docs.astral.sh/uv/guides/install-python/",
    "https://developer.hashicorp.com/terraform/install",
    "https://docs.byteplus.com/en/docs/IAM/creating-an-access-key",
    "https://docs.byteplus.com/en/docs/IAM/about-roles",
    "https://docs.byteplus.com/en/docs/byteplus-platform/reference-assumerole",
    "https://docs.byteplus.com/en/docs/ecs/Creating-key-pairs",
    "https://docs.byteplus.com/en/docs/ecs/Install-the-Cloud-Assistant-client",
    "https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry",
  ]) {
    assert.ok(content.includes(url), url);
  }
  assert.match(
    page("setup/shared-server.md"),
    /\.\.\/byteplus-terraform\.md#requirements/,
  );
});

test("hosted provider-secret sync is superseded without replacement key custody", () => {
  const content = page("secret-manager.md").replace(/\s+/g, " ");
  assert.match(content, /provider-secret sync is superseded/i);
  assert.match(content, /must not fetch one from Secret Manager/);
  assert.match(content, /not a customer credential/);
  assert.match(content, /MCP_IDENTITY_HMAC_KEY/);
  assert.match(content, /MCP_IDENTITY_KEY_VERSION/);
  assert.match(content, /SPEC_PROVIDER_SECRET_SYNC\.md/);
  assert.doesNotMatch(content, /config (?:plan|apply)|--secret-reference-file/);
  assert.ok(page("byteplus-terraform.md").includes("(secret-manager.md)"));
  assert.ok(page("setup/shared-server.md").includes("(../secret-manager.md)"));
});

test("hosted deployment keeps fresh state and future launch limits explicit", () => {
  for (const path of [
    "deployment.md",
    "self-hosting.md",
    "byteplus-terraform.md",
  ]) {
    const content = page(path).replace(/\s+/g, " ");
    assert.match(content, /MCP_IDENTITY_HMAC_KEY/, path);
    assert.match(content, /64 lowercase hex/, path);
    assert.match(content, /fresh.*SQLite|SQLite.*fresh/i, path);
    assert.match(content, /idempotency.*crash recovery/, path);
    assert.match(content, /public.launch/, path);
    assert.doesNotMatch(
      content,
      /MCP_API_KEY_SHA256|MCP_AUTH_MODE=api_key/,
      path,
    );
    assert.doesNotMatch(content, /--env BYTEPLUS_.*API_KEY/, path);
  }
});
