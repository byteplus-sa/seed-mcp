# Deployment

HTTP deployments implement the [BYOK foundation](../specs/SPEC_HOSTED_BYOK.md).
The cloud path is dedicated VKE, replacing ECS/Compose: Terraform provisions
infrastructure; Helm runs one StatefulSet pod with Caddy and retained ext4
ReadWriteOnce EBS. No application HPA is supported. Start new installations
with fresh SQLite state. HTTP asynchronous-create idempotency
is implemented; synchronous product replay and complete crash recovery remain
deferred. PostgreSQL/Redis are future scaling choices, not initial requirements.
This is not a multi-replica or public-launch claim. Local stdio retains
storage and artifacts separately.

## Build the Container

Build a reviewed `byteplus-sa/seed-mcp` revision, or independently verify a
compatible digest-pinned image. No fork image publication is assumed.

```bash
docker build --tag seed-mcp:reviewed .
```

See [releases](releases.md) and the
[breaking capability migration](migration-0.2.md#breaking-capability-migration).
Old database schemas are not migrated. Retain old state separately.

## Run One Instance

Follow the [staged VKE runbook](byteplus-terraform.md#staged-vke-deployment).
Use a separate fresh Terraform state, never old ECS state. The private control
plane needs operator private connectivity. Both `csi-ebs` and
`cloud-controller-manager` are VKE-admin owned outside Terraform/Helm:
inspect existing installations, install only absent compatible maintained
versions through VKE, and verify CSI readiness, Ready nodes and CCM Running.
`prerequisitesConfirmed=true` acknowledges checks, not proof of their success.

Helm references existing Secrets only: operator `MCP_IDENTITY_HMAC_KEY`
(random 32 bytes, 64 lowercase hex) and positive `MCP_IDENTITY_KEY_VERSION`,
plus a distinct TLS Secret. Terraform never retrieves or stores these or a
kubeconfig. No provider keys or client secrets belong in the pod environment.
The HMAC key is not a customer credential. Keep the same state and matching
identity across updates.

These local commands render synthetic manifests only; they do not install
anything or prove live readiness:

```bash
helm lint deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
helm template seed-mcp deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
```

The CLB forwards TCP 443 to Caddy 8443 in the same pod; only `/mcp` and
`/health` are public. FastMCP binds `127.0.0.1:3000`, trusts
`RATE_LIMIT_TRUSTED_PROXY_CIDRS=127.0.0.1/32`, and disables Uvicorn proxy
rewriting. Caddy overwrites forwarding headers. The old boolean trust setting
is removed. Default limits remain 60 RPM, 2 MiB bodies, 64 in-flight requests
and `STATE_MAX_RECORDS=100000`. See [configuration](configuration.md).

Use client timeout 660 seconds with `MCP_TOOL_TIMEOUT_SECONDS=600.0`
(finite positive, max 3600). Provider admission defaults to 2 seconds
(`MCP_ADMISSION_TIMEOUT_SECONDS`, finite positive, max 30), owner-first before
budget reservation. SDK/SQLite draining may exceed the cooperative deadline.
Do not treat an admission error for one attempt as proof that a whole batch
was unsubmitted; preserve known accepted IDs and never blindly resubmit.
Request headers carry only the selected provider key and
`X-MCP-Client-Secret`; [client setup](setup/shared-server.md) explains them.
Do not configure OAuth, signup or a server-issued connection key.

## Probes and Monitoring

After deployment, an authorized operator with private API access can inspect
the backend using the Python executable already in the app container. The
example assumes namespace/release `seed-mcp`; select the actual pod:

```bash
kubectl -n seed-mcp exec seed-mcp-seed-mcp-0 -c app -- \
  /app/.venv/bin/python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=2).status)"
kubectl -n seed-mcp exec seed-mcp-seed-mcp-0 -c app -- \
  /app/.venv/bin/python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/ready', timeout=2).status)"
```

These use the chart's loopback exec probe targets and print HTTP status only.
The routes return minimal process/state status; HTTP readiness never probes
providers. `/ready` is blocked by Caddy; do not use it as a public probe.
`/metrics` is absent from the main app and public proxy. Optional
`MCP_METRICS_PORT` defaults to `0` (off) and otherwise binds only 127.0.0.1;
the chart's `app.metricsEnabled=true` selects port 9000. Use authorized
pod port-forward for [private metrics](observability.md#metrics-endpoint).
Application logs and provider spans use sanitized diagnostics; never enable
proxy logging of BYOK headers.
Discovery is anonymous and static, so a successful discovery check does not
prove the caller's provider key works.

## State and Shutdown

Keep the SQLite volume and stable HMAC configuration together. Task records
are credential-tenant and client-owner scoped, not a common team namespace.
`STATE_PRUNE_MAX_AGE_DAYS` defaults to 30 and must be at least 14 for HTTP
regular Seedance 2.5 Draft ownership. Capacity failures deny new work rather
than evict live owners.
Submission claims never auto-prune, even when ownership expires.
`STATE_MAX_RECORDS` caps journal claims; at capacity existing keys remain
readable but new keys fail before dispatch. Do not erase claims to admit work.

HTTP transport sessions are stateless, but ownership/budgets/journal are durable.
There are no ordinary jobs, native tasks, storage/artifact tools
or media resources. Do not provision Redis snapshots for hosted requests.
Clients download expiring provider outputs; server persistence is rejected.

The HTTP runtime holds an exclusive `runtime.sqlite3.lock` from before stores/
recovery until all state users close. Contention fails startup closed; never
unlink an active lock or share SQLite over a network filesystem. This lease
is not distributed fencing or permission to run multiple pods.

Drain in-flight foreground work before restart. The entrypoint grace is
`max(MCP_TOOL_TIMEOUT_SECONDS, BYTEPLUS_REQUEST_TIMEOUT_MS / 1000) + 30`
seconds; Caddy uses the same allowance and the chart adds 60 instead of 30
for pod termination. Defaults are 630/660 seconds, not a hard cleanup bound.
A forced stop or lost submission response can leave
an unknown provider outcome. Reconcile using saved task/request IDs, never
blindly recreate work. Non-dry HTTP Seedance/OmniHuman calls require
`idempotency_key`, one per whole call. Repeat identical arguments/key only for
saved-success delivery recovery, not polling; unresolved attempts never
automatically resume. Seedance dry runs need no key or journal; stdio rejects
supplied keys. See the
[submission contract](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).

## Deployment Checklist

- Keep one application replica and a fresh private state directory.
- Protect operator HMAC configuration and backups; never distribute it.
- Preserve consistent SQLite/WAL state and matching HMAC; no blind restore,
  reset, claim deletion or requeue. See [recovery](byteplus-terraform.md#backup-upgrade-and-recovery).
- Verify fixed official provider origins and no environment-key fallback.
- Keep positive admission/body/rate/state limits and explicit Host/Origin policy.
- Verify anonymous discovery and denial of missing credentials on provider calls.
- Verify no HTTP job/task/resource surface and no public metrics.
- Validate exact-client headers, TLS, load and restore behavior separately.

The [BytePlus guide](byteplus-terraform.md) describes infrastructure
prerequisites. Source deletion is not cloud decommissioning: retain the
reviewed old checkout, private workspaces, old state and backups for explicit
retirement. No command here authorizes cloud provisioning or paid generation.
Live VKE apply, source-IP, CSI, rollout and real-client/provider acceptance
remain unverified. Mocked TLS/load checks are not capacity certification.
