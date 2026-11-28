import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const source = (path) =>
  readFileSync(new URL(`../../../${path}`, import.meta.url), "utf8");

test("hosted chart is database-free and preserves bounded pod scaling", () => {
  const pod = source("deploy/helm/seed-mcp/templates/deployment.yaml");
  const values = source("deploy/helm/seed-mcp/values.yaml");
  const schema = JSON.parse(source("deploy/helm/seed-mcp/values.schema.json"));
  assert.match(pod, /kind: Deployment/);
  assert.match(pod, /name: STATE_BACKEND\s+value: none/);
  assert.match(pod, /maxUnavailable: 0/);
  assert.match(pod, /maxSurge: 1/);
  assert.match(pod, /minDomains: 2/);
  assert.match(pod, /terminationGracePeriodSeconds:.*add \$deadline 60/);
  assert.doesNotMatch(
    pod,
    /POSTGRES_|database-ca|persistentVolumeClaim|volumeClaimTemplates/,
  );
  assert.match(values, /dailyBudgetUsd: 0/);
  assert.equal(schema.properties.app.properties.dailyBudgetUsd.const, 0);
  assert.equal(schema.additionalProperties, false);
  for (const key of ["databaseSecret", "databaseCA", "postgres"]) {
    assert.equal(schema.properties[key], undefined);
  }
  assert.match(
    source("deploy/helm/seed-mcp/templates/horizontalpodautoscaler.yaml"),
    /autoscaling\/v2/,
  );
  assert.match(
    source("deploy/helm/seed-mcp/templates/poddisruptionbudget.yaml"),
    /minAvailable: 1/,
  );
  assert.match(source("deploy/helm/seed-mcp/Chart.yaml"), />=1\.30\.0-0/);
});

test("stateless deployment keeps proxy and private-operation boundaries", () => {
  const proxy = source("deploy/helm/seed-mcp/files/Caddyfile");
  const service = source("deploy/helm/seed-mcp/templates/service.yaml");
  assert.match(proxy, /@public path \/mcp \/health/);
  assert.match(proxy, /header_up X-Forwarded-For \{http.request.remote.host\}/);
  assert.match(service, /externalTrafficPolicy: Local/);
  assert.match(
    service,
    /port: \{\{ ternary 443 8443 \(eq \.Values\.service\.mode "public-clb"\) \}\}/,
  );
  assert.match(
    service,
    /if eq \.Values\.service\.mode "public-clb"[\s\S]+type: LoadBalancer[\s\S]+else[\s\S]+type: ClusterIP/,
  );
  const notes = source("deploy/helm/seed-mcp/templates/NOTES.txt");
  assert.match(notes, /fresh stateless deployment/);
  assert.doesNotMatch(notes, /WAL\/database backups|live SQLite release/);
  assert.match(notes, /PER POD/);
  assert.match(notes, /Never repeat uncertain creates/);
  assert.match(notes, /CSI is not a new application prerequisite/);
});

test("hosted guidance explains fresh database-free deployment limits", () => {
  for (const path of [
    "docs/deployment.md",
    "docs/self-hosting.md",
    "specs/SPEC_HOSTED_BYOK.md",
  ]) {
    const text = source(path).replace(/\s+/g, " ");
    assert.match(text, /stateless|database-free/i, path);
    assert.match(text, /provider.key|provider key/i, path);
    assert.match(text, /per.pod/i, path);
    assert.match(text, /uncertain/i, path);
    assert.match(text, /fresh stateless deployment/i, path);
  }
  assert.match(
    source("docs/byteplus-terraform.md"),
    /terraform -chdir=deploy\/terraform\/vke validate/,
  );
  assert.match(
    source("docs/byteplus-terraform.md"),
    /helm lint deploy\/helm\/seed-mcp/,
  );
  assert.match(source("specs/SPEC_VKE_DEPLOYMENT.md"), /Source|source/);
});

test("fresh stateless deployment has no database provisioning or credential gates", () => {
  for (const path of ["docs/byteplus-terraform.md", "docs/self-hosting.md"]) {
    const text = source(path).replace(/\s+/g, " ");
    assert.match(text, /identity and TLS Secrets/, path);
    assert.match(text, /TOS\/enrollment Secret/, path);
    assert.match(
      text,
      /No database Secret or database CA ConfigMap is required/,
      path,
    );
    assert.doesNotMatch(
      text,
      /privately provision database|identity\/database\/TLS|database CA\/schema\/contract\/runtime-role|node\/connection headroom|failover fencing|A positive daily budget is useful|stateful installations must preserve|database\/WAL backups|inspect_runtime_state|kubectl get csidriver/,
      path,
    );
  }
  assert.match(
    source("docs/self-hosting.md").replace(/\s+/g, " "),
    /HTTP has no budget ledger and rejects nonzero values/,
  );
});

test("fresh repo ships no historical inspector or legacy storage templates", () => {
  for (const path of [
    "scripts/inspect_runtime_state.py",
    "tests/unit/test_inspect_runtime_state.py",
    "deploy/helm/seed-mcp/templates/statefulset.yaml",
    "deploy/helm/seed-mcp/templates/storageclass.yaml",
  ]) {
    assert.equal(
      existsSync(new URL(`../../../${path}`, import.meta.url)),
      false,
      path,
    );
  }
  for (const path of [
    "Dockerfile",
    "Makefile",
    "AGENTS.md",
    "README.md",
    "docs/runtime.md",
    "docs/byteplus-terraform.md",
    "specs/SPEC_VKE_DEPLOYMENT.md",
    ".agents/skills/ark-mcp/SKILL.md",
    ".agents/skills/ark-mcp-setup/SKILL.md",
    ".agents/skills/ark-mcp/references/environment.md",
  ]) {
    assert.doesNotMatch(
      source(path),
      /inspect_runtime_state\.py|database\/WAL backups|preserve legacy volume/i,
      path,
    );
  }
});

test("launch examples and landing page do not restore retired hosted guarantees", () => {
  const transport = source("docs/transports.md");
  assert.match(
    transport,
    /STATE_BACKEND=none DAILY_BUDGET_USD=0 MCP_TRANSPORT=http/,
  );
  assert.doesNotMatch(transport, /STATE_BACKEND=sqlite MCP_TRANSPORT=http/);
  assert.match(source("docs/index.mdx"), /\/seed-mcp\/service\//);
  assert.match(source("docs/calling-tools.md"), /Omit `idempotency_key`/);
  assert.doesNotMatch(
    source("docs/index.mdx"),
    /single-instance foundation|saved-success receipt recovery/,
  );
  assert.doesNotMatch(source("docs/deployment.md"), /DB connection headroom/);
  assert.doesNotMatch(
    source("docs/configuration.md"),
    /at least 14 for authenticated HTTP/,
  );
  assert.doesNotMatch(
    source("specs/SPEC_DIRECT_EXECUTION.md"),
    /durable root claim|Journal IDs/,
  );
});

test("task and skill guidance delegates HTTP authorization to the provider", () => {
  for (const path of [
    "docs/api-reference.md",
    "docs/integration-guide.md",
    "docs/multi-generation.md",
    "docs/troubleshooting.md",
    "docs/site/tool-notes/seedance-create-task.md",
    ".agents/skills/ark-mcp/SKILL.md",
    ".agents/skills/ark-mcp/references/tool-reference.md",
    ".agents/skills/ark-mcp/references/workflows.md",
    ".agents/skills/ark-mcp/references/polling-and-artifacts.md",
    ".agents/skills/ark-mcp-setup/references/credentials.md",
  ]) {
    const text = source(path).replace(/\s+/g, " ");
    assert.doesNotMatch(
      text,
      /HTTP polling (?:requires|needs) recorded ownership/,
      path,
    );
    assert.doesNotMatch(text, /HTTP.*safe accepted IDs are journaled/, path);
    assert.doesNotMatch(
      text,
      /HTTP.*key covers the whole (?:variation |Seedance )?batch/,
      path,
    );
    assert.doesNotMatch(text, /recover an HTTP create receipt/, path);
    assert.doesNotMatch(text, /SUBMISSION_UNAVAILABLE/, path);
  }
});
