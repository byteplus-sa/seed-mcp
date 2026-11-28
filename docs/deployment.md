# Deployment

Hosted HTTP is a database-free BYOK proxy with provider-key task authorization.
It supports multiple application pods without durable replay or shared budget
accounting. Local stdio persistence remains available separately.

## Build the Container

Build a reviewed `byteplus-sa/seed-mcp` revision, or independently verify a
compatible digest-pinned image. No fork image publication is assumed.

```bash
docker build --tag seed-mcp:reviewed .
```

See [releases](releases.md) for selecting a reviewed revision.

## Run Shared HTTP

Follow the [staged VKE runbook](byteplus-terraform.md#staged-vke-deployment).
Use dedicated fresh Terraform state, separate from unrelated deployments.

Task get/list/cancel and Draft lookup are authorized by the supplied provider
key. Optional `X-MCP-Client-Secret` separates per-pod admission scopes, not task access.
Without it, callers using the same provider key share one per-pod principal concurrency allowance.
Clients sharing a provider key can access whatever that key authorizes.
Use separate provider credentials when independent authorization is required.

Omit `idempotency_key`; the retained legacy field is rejected when supplied.
An identical create is a new operation and may bill again. Save task/request IDs,
poll existing tasks, and reconcile lost or uncertain create responses through
the provider. Never automatically retry an uncertain mutation.

Rate limits and in-flight/provider/principal concurrency are in-memory per pod;
they multiply with replicas and reset at restart. `DAILY_BUDGET_USD` must be `0`
on HTTP; use provider-side spend controls. Readiness is lifespan-only and makes
no storage or provider probes. No database, migration, distributed lock, shared
volume or sticky session is needed for the hosted deployment.

The chart renders a stateless `Deployment`, HPA (default 2-6 pods, CPU 70%),
`PodDisruptionBudget` with `minAvailable: 1` and hostname topology spread with
`minDomains: 2`. Kubernetes must be >=1.30 and a maintained regional release.
Same-zone nodes are not zone-failure resilience.

Every pod runs FastMCP on `127.0.0.1:3000` and Caddy TLS on 8443. CLB TCP 443 uses
Local traffic policy; Caddy overwrites forwarding headers and Uvicorn does not
rewrite them. Only `/mcp` and `/health` are public. `/ready` is an internal exec
probe. Private metrics remain opt-in on loopback.

Helm references existing identity and TLS Secrets only. `STATE_BACKEND=none` and
`DAILY_BUDGET_USD=0`; database inputs are rejected. No PVC, StorageClass, database
CA, PostgreSQL driver or shared state service is required. Bounded scratch uses
`emptyDir`. Model bindings remain exact and operator-verified. The operator HMAC
key is 32 random bytes encoded as 64 lowercase hex characters; its positive
version defaults to 1. It is not a customer credential. Provider keys and client
secrets must not be configured in the pod environment.

Verify private API access, CCM, two Ready nodes and surge/draining headroom,
DNS/TLS, source restrictions and HPA metrics API before `prerequisitesConfirmed`.
CSI is not an application prerequisite. Addon readiness and lifecycle remain
administrator-owned outside Terraform/Helm.

These commands render synthetic manifests only, without deploying anything:

```bash
helm lint deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
helm template seed-mcp deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
```

CPU HPA is a starting policy, not a capacity guarantee. Measure live rollout,
CLB source-IP preservation, latency, provider quotas and cost before launch.

## Probes and Monitoring

After deployment, an authorized operator with private API access can inspect
the backend using the Python executable already in the app container. The
example assumes namespace/release `seed-mcp`; select the actual pod:

```bash
kubectl -n seed-mcp exec deployment/seed-mcp-seed-mcp -c app -- \
  /app/.venv/bin/python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=2).status)"
kubectl -n seed-mcp exec deployment/seed-mcp-seed-mcp -c app -- \
  /app/.venv/bin/python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/ready', timeout=7).status)"
```

These use the chart's loopback exec probe targets and print HTTP status only.
The routes return minimal process/lifespan status; HTTP readiness never probes
storage or providers. `/ready` is blocked by Caddy; do not use it as a public probe.
`/metrics` is absent from the main app and public proxy. Optional
`MCP_METRICS_PORT` defaults to `0` (off) and otherwise binds only 127.0.0.1;
the chart's `app.metricsEnabled=true` selects port 9000. Use authorized
pod port-forward for [private metrics](observability.md#metrics-endpoint).
Application logs and provider spans use sanitized diagnostics; never enable
proxy logging of BYOK headers.
Discovery is anonymous and static, so a successful discovery check does not
prove the caller's provider key works.

## State and Shutdown

There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a fresh stateless deployment. Historical database compatibility and
stateful-release migration tooling are not part of this repository.

Drain foreground work before restart. Application and Caddy shutdown allow
`max(tool timeout, provider timeout in seconds) + 30`; pod termination grace
uses the same maximum plus 60 (defaults 630/660 seconds). These are cooperative
allowances, not guarantees that accepted provider work stops.

Use a client timeout of 660 seconds with the default 600-second tool deadline.
Admission defaults to 2 seconds. An admission failure applies to that attempt;
other variations may already have been accepted. Save known task/request IDs
and never automatically resubmit an uncertain create.

## Deployment Checklist

- Verify Deployment/HPA/PDB/spread, metrics API and node surge/draining headroom.
- Protect operator HMAC configuration and backups; never distribute it.
- Retain task/request IDs and never requeue uncertain provider work.
  See [recovery](byteplus-terraform.md#restart-and-recovery).
- Verify fixed official provider origins and no environment-key fallback.
- Keep positive admission/body/rate limits and explicit Host/Origin policy.
- Verify anonymous discovery and denial of missing credentials on provider calls.
- Verify no HTTP job/task/resource surface and no public metrics.
- Validate exact-client headers, TLS, load and graceful rollout separately.

The [BytePlus guide](byteplus-terraform.md) describes infrastructure
prerequisites. Source deletion is not cloud decommissioning; infrastructure
retirement requires separate review. No command here authorizes cloud
provisioning or paid generation.
Live VKE apply, source-IP, rollout and real-client/provider acceptance
remain unverified. Mocked TLS/load checks are not capacity certification.
