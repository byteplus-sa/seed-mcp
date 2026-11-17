import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = (path) =>
  readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const source = (path) =>
  readFileSync(new URL(`../../../${path}`, import.meta.url), "utf8");
const normalized = (content) => content.replace(/\s+/g, " ");

test("VKE guide separates source checks from live acceptance", () => {
  const content = normalized(page("byteplus-terraform.md"));
  assert.match(content, /## Validation Status/);
  assert.match(content, /live VKE.*unverified/i);
  assert.match(content, /source.IP.*CSI.*rollout/i);
  assert.match(content, /mock.*not.*capacity certification/i);
  assert.match(content, /real.*client.*provider.*unverified/i);
});

test("VKE setup requires private operator access and safe local checks", () => {
  const content = normalized(page("byteplus-terraform.md"));
  assert.match(content, /## Requirements/);
  assert.match(content, /## Set Up Dependencies/);
  assert.match(content, /## Set Up IAM and Credentials/);
  assert.match(content, /members.*do not need.*IAM/i);
  assert.match(content, /private control plane.*private connectivity/i);
  assert.match(content, /terraform -chdir=deploy\/terraform\/vke validate/);
  assert.match(content, /helm lint deploy\/helm\/seed-mcp/);
  assert.doesNotMatch(
    content,
    /deploy_byteplus\.py|docker compose|terraform apply/,
  );
});

test("VKE addons have one administrator owner and an evidence gate", () => {
  const content = normalized(page("byteplus-terraform.md"));
  for (const addon of ["csi-ebs", "cloud-controller-manager"]) {
    assert.ok(content.includes(addon), addon);
  }
  assert.match(content, /VKE administrator.*outside Terraform and Helm/i);
  assert.match(content, /inspect.*existing.*install.*absent/i);
  assert.match(content, /compatible.*maintained.*VKE addon management/i);
  assert.match(content, /kubectl get csidriver ebs\.csi\.volcengine\.com/);
  assert.match(content, /deployment\/csi-ebs-controller/);
  assert.match(content, /daemonset\/csi-ebs-node/);
  assert.match(content, /nodes.*Ready.*CCM.*Running/i);
  assert.match(
    content,
    /prerequisitesConfirmed=true.*acknowledgement.*not.*proof/i,
  );
});

test("documented VKE network and storage agree with chart sources", () => {
  const guide = normalized(page("byteplus-terraform.md"));
  const pod = source("deploy/helm/seed-mcp/templates/statefulset.yaml");
  const service = source("deploy/helm/seed-mcp/templates/service.yaml");
  const storage = source("deploy/helm/seed-mcp/templates/storageclass.yaml");
  const proxy = source("deploy/helm/seed-mcp/files/Caddyfile");
  assert.match(pod, /replicas: 1/);
  assert.match(pod, /terminationGracePeriodSeconds:.*add \$deadline 60/);
  assert.match(pod, /value: "127\.0\.0\.1\/32"/);
  assert.match(service, /externalTrafficPolicy: Local/);
  assert.match(service, /port: 443/);
  assert.match(service, /protocol: TCP/);
  assert.match(storage, /fsType: ext4/);
  assert.match(storage, /reclaimPolicy: Retain/);
  assert.match(storage, /volumeBindingMode: WaitForFirstConsumer/);
  assert.match(proxy, /@public path \/mcp \/health/);
  assert.match(proxy, /header_up X-Forwarded-For \{http.request.remote.host\}/);
  for (const text of [
    "127.0.0.1:3000",
    "127.0.0.1/32",
    "TCP 443",
    "8443",
    "ReadWriteOnce",
    "ext4",
    "WaitForFirstConsumer",
    "Retain",
    "max(tool, provider) + 30",
    "max(tool, provider) + 60",
  ]) {
    assert.ok(guide.includes(text), text);
  }
  assert.match(guide, /no application HPA/i);
});

test("migration does not confuse source removal with cloud or state retirement", () => {
  const content = normalized(page("byteplus-terraform.md"));
  assert.match(content, /separate fresh VKE.*state/i);
  assert.match(content, /never.*old ECS state/i);
  assert.match(content, /source deletion.*not cloud decommission/i);
  assert.match(content, /reviewed old checkout.*private workspaces.*backups/i);
  assert.match(content, /matching HMAC key\/version/);
  assert.match(content, /no state reset.*blind restore.*requeue/i);
  assert.match(content, /Terraform.*no.*HMAC.*TLS.*kubeconfig.*state/i);
  assert.match(content, /Helm references existing Secrets only/i);
  assert.doesNotMatch(content, /export (?:BYTEPLUS_|CR_PAT)[A-Z_]*=/);
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
    assert.match(content, /idempotency/, path);
    assert.match(content, /crash recovery/, path);
    assert.match(content, /public.launch/, path);
    assert.doesNotMatch(
      content,
      /MCP_API_KEY_SHA256|MCP_AUTH_MODE=api_key/,
      path,
    );
    assert.doesNotMatch(content, /--env BYTEPLUS_.*API_KEY/, path);
  }
});

test("runtime settings and diagnostic commands stay source-linked", () => {
  const content = normalized(page("runtime.md"));
  const environment = source(".env.example");
  const inspector = source("scripts/inspect_runtime_state.py");
  assert.match(content, /runtime\.sqlite3\.lock/);
  assert.match(content, /MCP_METRICS_PORT.*0.*127\.0\.0\.1/);
  assert.match(content, /--database.*--capacity.*--timeout-seconds/);
  assert.match(content, /kubectl -n seed-mcp exec seed-mcp-0 -c app --/);
  assert.ok(
    source("Dockerfile").includes(
      "scripts/inspect_runtime_state.py /app/scripts/inspect_runtime_state.py",
    ),
  );
  for (const flag of ["--database", "--capacity", "--timeout-seconds"]) {
    assert.ok(inspector.includes(`"${flag}"`), flag);
  }
  assert.match(environment, /RATE_LIMIT_TRUSTED_PROXY_CIDRS=\n/);
  assert.match(environment, /MCP_METRICS_PORT=0/);
  assert.doesNotMatch(
    environment,
    /RATE_LIMIT_TRUST_PROXY_HEADERS|deploy\/compose/,
  );
});

test("acceptance instructions describe actual mock-only flags and limits", () => {
  const content = normalized(page("byteplus-terraform.md"));
  const harness = source("scripts/hosted_acceptance.py");
  for (const flag of ["--caddy-bin", "--max-requests", "--concurrency"]) {
    assert.ok(content.includes(flag), flag);
    assert.ok(harness.includes(`"${flag}"`), flag);
  }
  assert.match(content, /synthetic 20 ms.*32 KiB.*2-second tool deadline/);
  assert.match(content, /not production defaults/);
  assert.match(content, /not.*capacity.*certification/i);
});

test("documented Terraform requirement matches the finalized root", () => {
  const versions = source("deploy/terraform/vke/versions.tf");
  assert.match(versions, /required_version = ">= 1\.17\.1, < 2\.0\.0"/);
  assert.match(versions, /version = "= 0\.0\.63"/);
  assert.ok(page("byteplus-terraform.md").includes("`>=1.17.1,<2.0.0`"));
  assert.ok(
    source("specs/SPEC_VKE_DEPLOYMENT.md").includes("`>=1.17.1,<2.0.0`"),
  );
});

test("chart model and runtime docs match explicit allowlisted inputs", () => {
  const guide = normalized(page("byteplus-terraform.md"));
  const schema = JSON.parse(source("deploy/helm/seed-mcp/values.schema.json"));
  const values = source("deploy/helm/seed-mcp/values.yaml");
  const pod = source("deploy/helm/seed-mcp/templates/statefulset.yaml");
  const guards = source("deploy/helm/seed-mcp/templates/validate.yaml");
  for (const product of ["seedream", "seedance"]) {
    const selection = schema.properties.models.properties[product];
    assert.deepEqual(selection.required, ["defaultModel", "bindings"]);
    assert.equal(selection.additionalProperties, false);
    const bindings = selection.properties.bindings;
    assert.equal(bindings.maxItems, 100);
    assert.deepEqual(bindings.items.required, ["model_id", "family"]);
    for (const family of bindings.items.properties.family.enum) {
      assert.ok(guide.includes(`\`${family}\``), family);
    }
    assert.ok(guide.includes(`models.${product}.defaultModel`), product);
    assert.ok(guide.includes(`models.${product}.bindings`), product);
  }
  assert.match(
    guards,
    /model bindings must include the selected product default/,
  );
  assert.match(guide, /alternate default requires explicit bindings/i);
  for (const [name, setting, defaultValue] of [
    ["dailyBudgetUsd", "DAILY_BUDGET_USD", 25],
    ["providerMaxConcurrency", "PROVIDER_MAX_CONCURRENCY", 5],
    ["principalMaxConcurrency", "PRINCIPAL_MAX_CONCURRENCY", 3],
    ["rateLimitBurst", "RATE_LIMIT_BURST", 0],
  ]) {
    assert.ok(schema.properties.app.properties[name], name);
    assert.match(values, new RegExp(`${name}: ${defaultValue}\\n`));
    assert.match(
      pod,
      new RegExp(`name: ${setting}\\s+value:.*\\.Values\\.app\\.${name}`),
    );
    assert.ok(guide.includes(`app.${name}`), name);
    assert.ok(guide.includes(setting), setting);
  }
  assert.equal(schema.additionalProperties, false);
  assert.match(guide, /explicit tool `model` still wins/i);
  assert.match(guide, /used header defaults must match this registry exactly/i);
  assert.doesNotMatch(
    guide,
    /BYOE bindings need a separately reviewed chart configuration change/,
  );
});

test("deployment shell examples parse without executing operations", () => {
  for (const path of ["byteplus-terraform.md", "deployment.md", "runtime.md"]) {
    const blocks = [...page(path).matchAll(/```bash\n([\s\S]*?)\n```/g)];
    assert.ok(blocks.length > 0, path);
    for (const [index, block] of blocks.entries()) {
      const result = spawnSync("bash", ["-n"], {
        input: block[1],
        encoding: "utf8",
      });
      assert.equal(
        result.status,
        0,
        `${path} example ${index + 1}: ${result.stderr}`,
      );
    }
  }
});

test("durable VKE spec retains official plan references and boundaries", () => {
  const spec = source("specs/SPEC_VKE_DEPLOYMENT.md");
  for (const url of [
    "https://registry.terraform.io/providers/byteplus-sdk/bytepluscc/0.0.63/docs/resources/vke_cluster",
    "https://registry.terraform.io/providers/byteplus-sdk/bytepluscc/0.0.63/docs/resources/vke_node_pool",
    "https://docs.byteplus.com/en/docs/vke/Configuring-a-LoadBalancer-Service-using-annotations",
    "https://docs.byteplus.com/docs/vke/Using-dynamic-EBS-Volumes",
    "https://docs.byteplus.com/docs/vke/csi-ebs-add-on",
  ]) {
    assert.ok(spec.includes(url), url);
  }
  assert.match(spec, /status: accepted/);
  assert.match(spec, /horizon: current/);
  assert.match(spec, /unverified/);
});
