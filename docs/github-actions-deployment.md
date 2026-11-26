# Deploy VKE From GitHub Actions

`.github/workflows/deploy-vke.yml` provides manual Helm delivery from a private
runner. CI and image publishing remain on GitHub-hosted runners. The application
stays stateless and database-free.

This workflow is **not a live account connection or a one-command infrastructure
bootstrap**. It does not provision VKE, fetch IAM credentials, create IAM/OIDC
trust, obtain kubeconfig, create Secrets, install addons or configure DNS.
Terraform still uses its separate protected operator state. See the
[VKE runbook](byteplus-terraform.md) for those prerequisites.

## Access Model

GitHub schedules the job; the private runner executes Helm against the private
Kubernetes API. Put that runner in the VKE VPC or an explicitly approved private
network. A runner in the same VPC needs neither a laptop VPN nor CEN. Outbound
GitHub access, runner isolation and capacity must be verified. Additional compute
or networking is not free or covered by the application node ceiling.

Kubernetes authorization uses an operator-provisioned token/certificate
kubeconfig. This is **not GitHub-to-BytePlus IAM federation**. VKE IRSA documentation
does not establish acceptance of GitHub-issued OIDC tokens. Do not upload
bytedcli/ArkCLI sessions, temporary IAM triplets, ModelArk keys or Seed Speech
keys to Actions. Namespace delivery does not need generation-provider keys.

## Bootstrap and Isolation

The repository is public. A label alone is not a security boundary. An
organization administrator must configure a dedicated runner group with access
restricted to this repository and this exact workflow:

```text
byteplus-sa/seed-mcp/.github/workflows/deploy-vke.yml@refs/heads/main
```

Use labels `self-hosted`, `linux`, `x64`, `seed-mcp-vke`. Prefer an ephemeral
one-job runner, replenished separately for each `check` and `deploy` job.
Reconcile job completion, deregistration and private scratch teardown before
replacing it. Projected credentials should use kubeconfig `tokenFile`, so
rotation is retained rather than copying a token snapshot.
Do not let PRs, forks, other workflows or arbitrary branches
execute on a runner with deployment credentials or private cluster access.
Verify the organization's runner-group restriction support and authority; do not
silently fall back to an unrestricted repository runner.

Install reviewed Python >=3.12, Helm (source validation uses 4.3.2), OpenSSL and
kubectl compatible with the selected cluster minor. Provision a dedicated
application namespace, existing identity/TLS Secrets and scoped Kubernetes
credentials. Helm needs namespace release-storage/resource permissions; preflight
also needs cluster node and metrics reads plus reads of the selected Secrets.
Review RBAC independently; no blanket cluster-admin policy is supplied.
Both APIG modes also need NetworkPolicy management in the application namespace.

Keep kubeconfig and nonsecret Helm values in same-owner mode-0700 directories
outside the checkout, with mode-0600 regular files and no symlinks. Kubeconfig
must use explicit token/certificate credentials and a CA; exec/auth-provider
plugins, basic credentials, proxies and insecure TLS bypasses are rejected.
Refresh or replace credentials through the operator's approved private process.
Do not put them in logs, artifacts or the repository.

## GitHub Configuration

Create a protected environment named `byteplus-staging`, with an authorized
reviewer, no administrator bypass, and a custom **branch-only `main`** policy.
Manual workflow dispatches from other refs are rejected by both jobs.
For production, pre-create and independently verify a separate protected
`byteplus-production` environment with an authorized reviewer, no administrator
bypass and the same branch-only `main` policy. Do not rely on GitHub implicitly
creating an environment, which would not have those protections.

Repository variables:

| Variable | Meaning |
| --- | --- |
| `VKE_RUNNER_GROUP` | Exact workflow-restricted organization runner group |
| `VKE_RUNNER_READY` | `true` only after authorized runner bootstrap and isolation checks |
| `VKE_PRODUCTION_ENABLED` | Keep absent/false until the documented backend trust decision, production protection and remaining launch prerequisites are approved |
| `VKE_PRODUCTION_RUNNER_GROUP` | Explicit workflow-restricted production runner group; no staging fallback |
| `VKE_PRODUCTION_RUNNER_READY` | Production-only runner-bootstrap acknowledgement; never inferred from staging |

Protected environment variables contain references, not secret values:

| Variable | Meaning |
| --- | --- |
| `VKE_KUBECONFIG_PATH` | Absolute private kubeconfig path on the runner |
| `VKE_VALUES_PATH` | Absolute private reviewed Helm values path |
| `VKE_CONTEXT` | Exact operator-verified Kubernetes context |
| `VKE_PRIVATE_API_SERVER` | Exact private HTTPS API origin, including port if used |
| `VKE_NAMESPACE` | Dedicated existing application namespace; default/system namespaces rejected |
| `VKE_PUBLIC_HOST` | Canonical public DNS hostname |
| `VKE_SERVICE_MODE` | Required: `public-clb` or `apig-staging` for staging target; only `apig-production` for production target |
| `VKE_BACKEND_HOST` | Distinct private TLS/SNI hostname for either APIG mode; empty for CLB |
| `VKE_IDENTITY_SECRET` | Existing identity Secret with default HMAC/version key names |
| `VKE_TLS_SECRET` | Distinct existing `kubernetes.io/tls` Secret |
| `VKE_PREREQUISITES_CONFIRMED` | `true` after CCM, addon, capacity, source-range and DNS/TLS checks |
| `VKE_PRODUCTION_APPROVED` | Set only in the protected production environment after independent production-gate approval; absent/false for staging |

Readiness flags are acknowledgements, not proof of network reachability, IAM
authority or capacity. Keep them false until bootstrap checks pass.
The production approval variable must not be defined at repository or
organization scope: it belongs to the pre-existing protected environment.

## Delivery

Run the workflow from `main` with explicit `target=staging` (default) or
`target=production`, `operation=check` first and a reviewed full
`ghcr.io/byteplus-sa/seed-mcp@sha256:<64 lowercase hex>` image reference.
The target-specific readiness gate fails on a GitHub-hosted runner before
queueing unconfigured private work. The target maps only to the fixed
`byteplus-staging` or `byteplus-production` environment; there is no arbitrary
environment-name input. Once configured, the protected job requires approval.
Both targets share one delivery concurrency group because they may address the
same cluster/release. The workflow and helper require an explicit service mode;
neither silently falls back to public CLB.

`scripts/deploy_vke.py` verifies exact context/API matching, RFC1918-only API
resolution, TLS verification, Kubernetes >=1.30 and compatible kubectl, two Ready
schedulable nodes, node metrics, valid identity Secret fields, certificate/key
matching, hostname matching, certificate expiry of at least one day, and strict
Helm lint. It captures command output without forwarding raw diagnostics to
Actions logs. Secret values remain in the live process and private temporary TLS
files, removed on ordinary exit; abrupt host failure requires operator cleanup.
Certificate hostname checks use `VKE_BACKEND_HOST` in either APIG mode and
`VKE_PUBLIC_HOST` in the public CLB mode.

## Private APIG Staging

Set `service.mode=apig-staging`, `backendHost` to the separate private TLS/SNI
hostname, `service.subnetId=""` and `service.sourceRanges` to verified private
source CIDRs. The chart renders a ClusterIP Service on TCP 8443 and an ingress
NetworkPolicy, with no public CLB. CIDRs must be contained entirely in RFC1918.
Establish actual APIG routing/SNAT sources and test allowed/denied paths;
configuration alone is not isolation evidence.

The staging Caddyfile refuses ModelArk, Seed Speech, client-secret and
Authorization headers, including empty values, before proxying. Only `/mcp`
and `/health` are forwarded, with canonical Host/proxy fields. Uploads cannot
be enabled. This is synthetic-only, not a client endpoint or a fix for APIG's
failed backend chain-trust gate. Never send real generation credentials.

Keep public application routes disabled. Temporary diagnostic routes require
an exact operator-held random `X-Seed-Staging-Probe` header matcher at APIG.
Create disabled, inspect the matcher, then verify missing/wrong markers fail
before synthetic acceptance. Disable afterward and confirm public 404.
Without verified operator-only edge controls, use private tests and leave APIG
acceptance pending. Proxy key refusal does not protect the preceding TLS hop.

## Production APIG Preparation

`service.mode=apig-production` is a separate source configuration, not a deployed
endpoint or an APIG trust repair. It retains the private ClusterIP:8443 Service,
entirely RFC1918 ingress ranges, distinct `backendHost`, empty `service.subnetId`
and disabled uploads. The staging proxy and its credential refusals are unchanged.

Production requires `service.productionConfirmed=true`; other modes reject
that value. The delivery helper additionally requires `--production-approved`
only for production and overrides the chart flag from that CLI acknowledgement.
A values file alone cannot supply approval through the helper. The workflow
passes the flag only for the production target and protected environment's
`VKE_PRODUCTION_APPROVED=true`. These are fail-closed acknowledgements, not
automated checks of APIG verification, environment protection or live acceptance.

The separate production Caddyfile forwards `X-ModelArk-Api-Key`,
`X-Seed-Speech-Api-Key`, `X-MCP-Client-Secret`,
`X-ModelArk-Seedance-Endpoint` and `X-ModelArk-Seedream-Endpoint` unchanged to
the application. The application still selects the provider and rejects malformed
or reused credentials; no server key fallback is introduced. Incoming
`Authorization`, including empty values, is rejected with HTTP 400.
Only `/mcp` and `/health` are forwarded, with canonical Host and replacement
forwarded fields. The operator marker is stripped and logs remain disabled.
APIG's direct peer is the rate-limit source; several clients may share that
bucket. This does not establish original-client IP or add per-key concurrency.

The new private production listener advertises HTTP/1.1 only. With Caddy 2.11.9,
the mock drain test reproduced HTTPX 0.28.1 aborting accepted HTTP/2 calls on
shutdown GOAWAY; this source configuration avoids that combination rather than
retrying interrupted creates. HTTP/2-capable clients must negotiate HTTP/1.1
on this listener. Existing staging/CLB listeners are unchanged. APIG terminates
public TLS independently: verify its private-hop HTTP/1.1 compatibility and
public client behavior live; this local result is not APIG acceptance.

The default backend policy requires APIG chain/validity/DNS-SAN verification
with positive and negative tests. The existing Seed MCP deployment has an
explicit [operator-accepted exception](../specs/SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception):
keep HTTPS, waive APIG backend verification. For that exact scope, obtaining
the verification control and proving certificate rejection no longer block
launch. Do not describe the private hop as identity-verified or extend the
exception to another deployment automatically.

Before enabling production acknowledgements, retain the applicable trust
evidence or scoped exception plus evidence of disabled logging/tracing,
no caching/mirroring/automatic POST retries, compatible timeouts, ingress
enforcement, registry-credential recovery, certificate renewal ownership and
active-call/client acceptance. Public launch approval is separate. Keep routes
blocked until these remaining gates pass; the waiver alone enables nothing.
Public HTTPS verification, private HTTPS encryption and certificate preflight
remain unchanged. See the [historical research](../specs/SPEC_APIG_PRODUCTION_READINESS.md).

Use [backend certificate renewal](backend-certificate-renewal.md) for versioned
Secret references, expiry ownership and per-replica verification. The helper's
one-day expiry/hostname checks do not validate a CA chain or reload Caddy.

### Local Drain Checks

After `uv sync --locked`, run the isolated short profile (also required in CI):

```bash
uv run python scripts/hosted_drain_acceptance.py --caddy-bin /path/to/caddy --profile short
```

Use explicit `--profile production` for six parallel 590-second mock calls
with 600-second tool, 630-second process-grace and 660-second observation/client
budgets. Both profiles test app-first, proxy-first and simultaneous TERM,
single dispatch, complete synthetic task/request receipts, graceful exits,
connection reuse and idle reconnection beyond five seconds. HTTP/1.1 and
HTTP/2-capable client offers must both negotiate the production listener's
HTTP/1.1 policy. Stalled/disconnected controls always use short clocks and
verify uncertainty without resubmission. Any failed case returns nonzero.

The worker has no real provider credentials and denies unmocked outbound socket
operations. These tests do not exercise APIG, Kubernetes endpoint withdrawal,
new traffic during rollout, certificate rotation, node drain or actual provider
SDK cleanup. Those remain separately approved acceptance work; the harness
adds no production test tool or mock switch.

## One-Shot Delivery

After the read-only check and prerequisites pass, dispatch `operation=deploy`
and approve it. This executes one `helm upgrade --install --wait`, with a
15-minute Helm timeout and 30-minute job limit. It does not create namespaces,
regenerate Secrets, automatically retry or automatically roll back. No secret
values or manifests are uploaded as workflow artifacts.

A timeout/failure may leave a partial installation and billable CLB resources.
Inspect the release before another dispatch. Job cancellation is not a rollback.
Coordinate external operator writes; workflow concurrency does not lock out
manual Helm operations. Verify public HTTPS, BYOK boundaries, CCM/source-range
enforcement, actual capacity and autoscaler behavior separately before launch.
Node counts and these checks do not establish a USD 200/400 monthly spend cap.

## References

- [VKE deployment contract](../specs/SPEC_VKE_DEPLOYMENT.md)
- [Using self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow)
- [Runner group API](https://docs.github.com/en/rest/actions/self-hosted-runner-groups)
