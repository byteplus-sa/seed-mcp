# Deploy on BytePlus with Terraform

The supported cloud source is a **dedicated VKE cluster** in
`deploy/terraform/vke` and the application chart in `deploy/helm/seed-mcp`.
It replaces ECS/Compose with database-free FastMCP/Caddy Deployment pods,
default 2-6 pod HPA, PDB and hostname spread. This source support is not live
HA, capacity or public-launch certification. SQLite remains local stdio only, not this chart; Redis is not required.

The durable contract is [VKE Deployment](../specs/SPEC_VKE_DEPLOYMENT.md);
[HTTP BYOK](../specs/SPEC_HOSTED_BYOK.md) remains authoritative for identity
and submission recovery. Commands below are local validation or explicitly
identified operator read-only checks, not authorization for paid execution.

<span id="verify-before-inviting-users"></span>

## Validation Status

Live VKE provisioning remains **unverified**. CLB source-IP preservation,
legacy CSI attach/detach, HPA/spread, rollout/drain behavior, DNS/TLS
and backup recovery require separately authorized evidence. Real target-client
tool execution and provider acceptance remain unverified for this deployment.
Old partial ECS provisioning is not evidence for VKE.

Local mocked Terraform plans, Helm renders and isolated mocked TLS/load
acceptance check source contracts only. A mock benchmark is **not capacity
certification**: it does not measure real provider latency, quotas or regional
network/storage behavior. No universal RPS promise follows from it.

## Requirements

Members connecting to an existing server do not need IAM credentials,
Terraform, Python or a checkout. They need their provider key, a client-generated
isolation secret and a trusted HTTPS endpoint. See
[client setup](setup/shared-server.md).

Operators need:

- A reviewed Seed MCP checkout, Terraform `>=1.17.1,<2.0.0`, locked
  `bytepluscc` 0.0.63, Helm (source validation uses 4.3.2), and a
  Kubernetes-compatible `kubectl`.
- Operator-verified region, zone, maintained Kubernetes >=1.30 and available
  on-demand node type. Regional quotas must cover VKE, nodes, EBS, CLB, NAT
  and EIP. Example values are not inventory or entitlement guarantees.
- Access to the private control plane through approved **private connectivity**
  (such as organizational VPN/private routing or an authorized management host).
  A kubeconfig alone does not provide network reachability. Do not expose the
  API publicly to work around this requirement.
- A reviewed digest-pinned application image compatible with the nodes, a public
  DNS name, a valid matching TLS certificate, and protected existing Kubernetes
  Secrets. No Seed MCP image publication or certificate issuer is assumed.
- Metrics API and node/provider headroom for active/surge/draining pods
  plus maintenance, with a VKE administrator owning addon readiness.

Python/uv are needed for repository checks, not remote client connections.
ArkCLI and bytedcli are not required by this deployment source.

## Set Up Dependencies

Use your organization's approved installation process or the official
[uv installation guide](https://docs.astral.sh/uv/getting-started/installation/),
[Python setup](https://docs.astral.sh/uv/guides/install-python/) and
[Terraform installation guide](https://developer.hashicorp.com/terraform/install).
Review downloaded code before executing it. With dependencies already installed,
these checks use no cloud account:

```bash
terraform version
helm version
kubectl version --client
terraform -chdir=deploy/terraform/vke fmt -check
terraform -chdir=deploy/terraform/vke init -backend=false -lockfile=readonly
terraform -chdir=deploy/terraform/vke validate
terraform -chdir=deploy/terraform/vke test
helm lint deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
helm template seed-mcp deploy/helm/seed-mcp -f deploy/helm/seed-mcp/values.ci.yaml
python scripts/generate_identity_secret.py --help
python scripts/inspect_runtime_state.py --help
```

Provider initialization may download the locked provider; never bypass checksum
checks. Terraform tests use mocks. `values.ci.yaml` contains synthetic inputs
for rendering, **not deployment approvals** or usable credentials. Do not install
it into a cluster. Default/example values intentionally fail until required
inputs and the prerequisite acknowledgement are supplied.

## Set Up IAM and Credentials

Infrastructure credentials (`BYTEPLUS_ACCESS_KEY`, `BYTEPLUS_SECRET_KEY`,
and matching `BYTEPLUS_SESSION_TOKEN` for STS) belong only in the operator's
approved secure injector. Never put values in HCL, tfvars, CLI arguments,
shell history or logs. ArkCLI sign-in does not automatically configure them.

Review Cloud Control and VKE/node/VPC/NAT/EIP permissions separately from
VKE administrator addon privileges and namespace-level application access.
This is not a validated least-privilege IAM policy. Do not grant blanket admin
access as a shortcut. Protect kubeconfig and private files with mode `0600`
in a private `0700` directory; never print raw kubeconfig or Secret data.
Refreshing STS or changing inputs invalidates a previously reviewed plan.

Official account setup references:

- [Create IAM access keys](https://docs.byteplus.com/en/docs/IAM/creating-an-access-key)
- [IAM roles](https://docs.byteplus.com/en/docs/IAM/about-roles)
- [Temporary STS credentials](https://docs.byteplus.com/en/docs/byteplus-platform/reference-assumerole)
- [GHCR pull authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

Terraform stores no HMAC key, TLS Secret or kubeconfig in state or outputs and
does not retrieve them. Helm references existing Secrets only; it does not
create Secret resources or accept secret values. A protected operator workflow
must create them in the intended namespace before installation:

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

The retained standalone `scripts/generate_identity_secret.py` is for private
operator generation, not a customer connection token. Do not invoke generation
in agent-visible output or regenerate an identity for existing state.
[Provider-secret sync is superseded](secret-manager.md); no hosted provider
key bundle or client secret belongs in Terraform, Helm or pod environment.

<span id="guided-deployment-cli"></span>

## Staged VKE Deployment

1. Select a **separate fresh VKE Terraform state** and independently reviewed
   backend/workspace. Never apply this root over old ECS state or migrate that
   state into this stack. `fresh_state_confirmed=true` acknowledges separation;
   it does not inspect or prove the backend is safe.
2. Review `variables.tf` and `terraform.tfvars.example`. Verify `zone_id`,
   `kubernetes_version`, `node_instance_type`, private network ranges and
   regional quotas. Defaults select `ap-southeast-1`, two fixed on-demand nodes
   and no node autoscaling. Hostname spreading needs two schedulable nodes;
   same-zone nodes are not AZ resilience. NAT/EIP/SNAT supply egress without public
   node IPs. Infrastructure creation is a separate approved, billable step.
3. Establish authenticated private management access. Inspect the actual VKE
   cluster and its addons before preparing Helm values.
4. Complete prerequisites, privately provision database/TLS/roles/schema/contract,
   identity/database/TLS Secrets and CA ConfigMap, then review actual nonsecret inputs.
5. Obtain separate approval for Helm installation. It creates a public CLB
   and can incur charges. Verify DNS/TLS and all live gates
   before inviting clients. No one-command cloud deployment is provided.

## Addon and Node Gate

The **VKE administrator owns both `csi-ebs` and `cloud-controller-manager`,
outside Terraform and Helm**. Inspect existing installations first; retain
healthy compatible versions, and install only absent addons using compatible,
maintained versions through **VKE addon management**. Do not assume automatic
installation, create a duplicate controller, import them into this root, or
silently upgrade/delete them.

After approved cluster creation, an authorized operator with private connectivity
can run these read-only checks against the deliberately selected context:

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl wait --for=condition=Ready nodes --all --timeout=300s
kubectl get csidriver ebs.csi.volcengine.com
kubectl -n kube-system rollout status deployment/csi-ebs-controller --timeout=300s
kubectl -n kube-system rollout status daemonset/csi-ebs-node --timeout=300s
```

CSI commands above apply to retained legacy storage, not a new stateless
application prerequisite. Preserve existing addon/volume safeguards.
Check nodes are Ready with adequate allocatable CPU/memory; check CCM is
Running on its VKE addon card even if its workload is outside the tenant
namespace. Existing addon versions/lifecycle remain administrator-owned. Record versions
and readiness evidence privately. Verify private API access, existing HMAC
Secret keys, database CA/schema/contract/runtime-role access, metrics API,
node/connection headroom, failover fencing, TLS and hostname without displaying data.

Only then set `prerequisitesConfirmed=true`. This is an **acknowledgement,
not programmatic proof** of addon, node, TLS, identity or network readiness.
Failure of a prerequisite blocks deployment even when rendering succeeds.

<span id="state-and-activation"></span>

## Chart Inputs and Network

Start from `values.example.yaml`, not the synthetic CI file. Required inputs:
`image` (digest pinned), `publicHost`, `identitySecret.name`, `tlsSecretName`,
`service.subnetId` and
`service.sourceRanges`. Match actual network references;
review `values.schema.json`. No storage-zone pin is accepted.
Do not guess zone availability, Kubernetes versions, image digests or subnet IDs.

Custom BYOE endpoints require operator-verified exact model/family bindings.
A request header cannot make an unknown endpoint usable or establish lineage;
the [authority contract](../specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority)
is unchanged. Do not bypass validation, infer endpoint lineage or supply an
arbitrary environment map or provider secrets.

### Model and Runtime Values

The chart passes only explicit allowlisted environment settings. Model IDs and
families are nonsecret configuration visible in anonymous discovery, not
evidence of customer entitlement.

| Helm value | Chart default | Application setting / meaning |
| --- | --- | --- |
| `models.seedream.defaultModel` | `dola-seedream-5-5-261028` | `SEEDREAM_DEFAULT_MODEL` |
| `models.seedance.defaultModel` | `dreamina-seedance-2-5-260628` | `SEEDANCE_DEFAULT_MODEL` |
| `models.seedream.bindings` | `[]` | JSON `SEEDREAM_MODEL_BINDINGS`; entries `{model_id, family}` |
| `models.seedance.bindings` | `[]` | JSON `SEEDANCE_MODEL_BINDINGS`; entries `{model_id, family}` |
| `app.dailyBudgetUsd` | `0` | HTTP requires zero; no budget ledger. Use provider spend controls. |
| `app.providerMaxConcurrency` | `5` | `PROVIDER_MAX_CONCURRENCY`; per-pod slots per provider bucket |
| `app.principalMaxConcurrency` | `3` | `PRINCIPAL_MAX_CONCURRENCY`; per-pod slots per derived HTTP owner |
| `app.rateLimitBurst` | `0` | `RATE_LIMIT_BURST`; zero inherits RPM, default 60 |

Seedream families are `seedream_5_5`, `pro`, `lite`, `4x`; Seedance families
are `standard`, `fast`, `mini`, `seedance_2_5`, `seedance_2_5_flash`.
Each product accepts at most 100 bindings with unique IDs. A nonempty list
must include its selected `defaultModel`. **Any alternate default requires
explicit bindings**, including another built-in model. Empty lists are allowed
only with the chart's shipped defaults; the runtime then adds Seedance Flash
alongside regular 2.5. Explicit lists replace, not append to, those bindings:
include Flash yourself when it should remain available.

An operator must verify each custom endpoint's model/version outside this
server before adding its exact ID/family. Explicit tool `model` still wins
over a request endpoint header; used header defaults must match this registry
exactly. No AK/SK custody, automatic metadata lookup or arbitrary BYOE
self-service is added.

The chart requires `DAILY_BUDGET_USD=0`: no hosted budget ledger exists. Concurrency values remain bounded to1-256 and burst to0-10000, per pod. Use provider-console spend controls and measured capacity.

### Network and Scaling

```mermaid
flowchart LR
    Client["Client BYOK headers"] -->|TLS over TCP 443| CLB["Public CLB; Local traffic policy"]
    subgraph Pod["Deployment pods; default HPA 2-6"]
        Caddy["Caddy TLS on 8443"] -->|"127.0.0.1:3000"| App["Direct FastMCP"]
        Metrics["Optional loopback metrics"]
    end
    CLB -->|TCP 8443| Caddy
    App -.->|Runtime-owned| Metrics
    App -->|Private node and pod egress via NAT| Provider["Fixed provider origins"]
    Operator["Private API access and authorized port-forward"] --> Metrics
```

The chart exposes **TCP 443** to Caddy **8443** with
`externalTrafficPolicy: Local`; TLS terminates in Caddy, not the CLB. The
backend binds **127.0.0.1:3000** and trusts only **127.0.0.1/32** through
`RATE_LIMIT_TRUSTED_PROXY_CIDRS`. Caddy overwrites `X-Forwarded-For` with the
socket source, removes `Forwarded` and replaces forwarded host/proto.
Uvicorn proxy-header rewriting is disabled. Real source-IP behavior still
needs VKE acceptance; never widen trusted CIDRs to hide failed preservation.
`service.sourceRanges` requests a Kubernetes source restriction; it is not
proof of CLB ACL enforcement. Verify both source preservation and restriction
from allowed/disallowed networks during authorized live acceptance.

Only `/mcp` and `/health` pass the proxy. `/ready`, `/metrics` and unknown paths
return 404 publicly. Application readiness is a loopback exec probe, not a
provider probe. Admin API and proxy access logs are disabled; responses stream
without buffering. Both layers default to a 2 MiB request body limit.

The pod runs nonroot UID/GID 1001, read-only root filesystems, dropped
capabilities and RuntimeDefault seccomp, without a service-account token.
CPU/memory and temporary volumes are bounded. `app.metricsEnabled=false`
keeps the optional loopback listener off; enabling it selects port 9000,
never a public Service. See [private operations](observability.md#metrics-endpoint).

See the database-free HTTP contract above; local stdio persistence is unchanged.

The HTTP process and Caddy use `max(tool, provider) + 30` seconds for graceful
shutdown; the chart uses `max(tool, provider) + 60` for pod termination
(630/660 seconds with default 600-second deadlines). Use client timeout 660
seconds by default. Cooperative SDK/SQLite draining can exceed nominal
deadlines; forced termination is not provider cancellation.

## Backup, Upgrade and Recovery


There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a deliberate contract change, not an automatic migration. Existing
stateful installations must preserve their old release, database/WAL backups,
identity and accepted IDs for reconciliation. Never delete retained data to
make the new version start. A Helm upgrade can delete removed resources; use
separately reviewed transition steps. No cloud resources are changed by source
removal.

## Local TLS and Load Acceptance


Run `uv run python scripts/hosted_acceptance.py --caddy-bin PATH`. This uses isolated loopback TLS and mocked providers, not a database or live credentials. It checks seven/ten tools, BYOK isolation, repeated-create behavior, polling after restart, proxy controls, bounded load and absence of local state. Live VKE/client/provider and capacity validation remain separately authorized gates.

## Decommissioning

**Source deletion is not cloud decommissioning.** Preserve a reviewed old
checkout, private workspaces, old Terraform state and backups for separately
approved ECS retirement. Do not reconstruct old state with this VKE root or
assume removed automation deleted cloud resources.

For VKE retirement, reconcile active provider work, archive state and HMAC
configuration, then separately review application, cluster and retained-disk
disposition. Both addons remain VKE-admin owned. Retained PVC/PV/EBS,
StorageClass, snapshots, CLB, NAT and EIP resources can continue to cost money.
Verify actual cloud absence and billing after approved retirement; empty
Terraform state or a Helm uninstall alone is not proof.

## Official References

The [durable spec sources](../specs/SPEC_VKE_DEPLOYMENT.md#sources) retain the
official VKE, CLB and EBS URLs recorded during plan research on 2026-11-17.
Use those manuals to verify regional prerequisites; source rendering cannot
replace the operator's live evidence.
