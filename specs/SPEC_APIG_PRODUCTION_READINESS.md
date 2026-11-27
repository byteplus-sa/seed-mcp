---
title: APIG Production Readiness Research and Remediation
type: research
status: proposed
horizon: future
created: 2026-11-24
updated: 2026-11-27
tags: [apig, vke, tls, byok, deployment, research]
related:
  - SPEC_VKE_DEPLOYMENT.md
  - SPEC_HOSTED_BYOK.md
  - SPEC_DIRECT_EXECUTION.md
  - ../docs/hosted-deployment-status.md
---

# APIG Production Readiness

## Subsequent Deployment: 2026-11-27

The scoped deployment is now public after protected delivery, registry recovery,
live APIG/VKE mock drain, real client-side provider testing and explicit launch
approval. Public H1/H2 and private H1 were verified. See the
[deployment record](../docs/hosted-deployment-status.md) for exact scope and
limitations. The dated research/preparation sections below remain historical
snapshots, not current launch blockers or proof of backend identity verification.

## Subsequent Operator Decision: 2026-11-25

After implementation preparation, the operator explicitly selected **"Keep
HTTPS, waive verification"** for the existing deployment. The
[accepted exception](SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception)
defines scope, risk and retained controls. APIG backend certificate verification
and its negative-test matrix are no longer launch blockers for that scope;
they remain deferred hardening. Public TLS verification and private HTTPS
encryption stay in place. No deployment or route enablement occurred.

This supersedes the launch-priority recommendation below, not its factual
findings: backend identity remains unverified. The November 24 research snapshot
must not be used to reimpose the waived gate or to claim that TLS trust passed.
Credential recovery, protected delivery and remaining live acceptance still apply.

## Implementation Follow-Up: 2026-11-25

The user approved source preparation after this research. The local checkout
now contains an explicit `apig-production` chart/proxy mode, separate protected
production delivery gates and a
[backend certificate renewal procedure](../docs/backend-certificate-renewal.md).
The [archived execution plan](https://github.com/byteplus-sa/seed-mcp/blob/0b60ea03aa98726b7b71c99abc697ae768504469/plans/PLAN_GATEWAY_DEPLOYMENT.md#production-preparation-implementation-2026-11-25)
tracks mock drain implementation and validation. Current source contracts live
in [VKE deployment](SPEC_VKE_DEPLOYMENT.md) and the
[delivery runbook](../docs/github-actions-deployment.md#production-apig-preparation).
Local validation completed: 3,227 offline tests with 93.00% coverage, plus
short and production-duration mock drain profiles (10/10 cases each, including
six 590-second calls). A reproduced HTTPX/Caddy H2 shutdown failure led to
HTTP/1.1-only negotiation on the new private production listener; APIG public
protocol behavior remains independent and untested. The plan records the
measured timings and independent-review corrections.

The research findings below remain the **November 24 snapshot**, including
statements about then-missing production mode/tests. Source preparation is not
deployment: no APIG trust control, cloud change, credential recovery, certificate
issuance, route enablement or public launch has been performed by this follow-up.
This report remains proposed research, not an accepted replacement for the
current deployment contract.

## Decision Summary

**The server does not need another infrastructure rebuild. It needs a verified
APIG upstream trust mechanism, an explicit production configuration, credential
recovery, and active-request acceptance.**

The preferred design preserves APIG and its current generic client URL.
APIG terminates public TLS, then establishes independently authenticated TLS to
the private Caddy backend. The backend's certificate name can differ from the
public URL. A private CA trusted by APIG, or an owned backend DNS name with a
public-CA certificate, can fit this design **only if APIG actually validates
the chain, validity and expected backend identity**. DNS-01 can issue an
owned-name certificate without exposing the backend publicly. [S09-S14]

**Research did not establish a supported APIG setting that supplies those
checks for the deployed configuration.** Independent Go/Python SDK inspection,
the official upstream/controller guides and the version documentation do not
close that gap. This is a provider-capability dependency, not proof that every
APIG mode is incapable of verification. Do not invent API fields or infer
managed-product support from generic Envoy, Istio or Gateway API features.

We can prepare production-mode code, mock-only drain tests and certificate
renewal procedures independently of that dependency. Registry-token recovery
can also proceed under a separately approved containment procedure. None of
that authorizes opening public BYOK routes before the trust gate passes.

## Scope and Evidence

Research date: **2026-11-24**. Repository revision:
`80d8379a5704bd36391e3187ff7cd03bb9fe4d90`.

Four independent read-only workers investigated native APIG controls,
architecture alternatives, repository promotion/drain gaps, and GHCR
credential rotation. The supervisor independently opened the key cited
sources, inspected the relevant source paths, and assessed Pages and billing
follow-ups. One narrow follow-up worker checked generated-domain usage
restrictions after the initial four tracks completed. Existing uncommitted
deployment notes were preserved.

No cloud resources, credentials, repository settings, public routes or
application source were changed. No application tests or provider calls were
run; no support cases or team messages were sent. Only documentation
metadata/link/secret checks were run locally. Public documentation and public
SDK sources were read. Historical cloud evidence is explicitly historical,
not a fresh availability assertion.

| Evidence class | What is established | What it does not establish |
| --- | --- | --- |
| Historical live staging, November 22-23 | Successful protected delivery; two Ready replicas; synthetic MCP acceptance; burst return to zero; disabled public routes | Current availability, loaded request continuity, production BYOK acceptance |
| Historical gateway probe, November 21 | APIG 4.4.4 with `Protocol=HTTP`, `TlsMode=SIMPLE` and SNI accepted the synthetic self-signed backend | Behavior of every APIG mode; gateway wrong-hostname or expiry rejection |
| Current repository inspection | Staging-only APIG mode, credential refusals, deadline/grace configuration and identified test gaps | A reproduced shutdown outage or measured keepalive failure |
| Current primary documentation | TLS semantics, published SDK fields, supported credential types and lifecycle guidance | Enforcement by the deployed managed gateway or regional feature availability |

Historical evidence is in [the archived deployment plan](https://github.com/byteplus-sa/seed-mcp/blob/0b60ea03aa98726b7b71c99abc697ae768504469/plans/PLAN_GATEWAY_DEPLOYMENT.md#backend-trust-capability-investigation-2026-11-23)
and [the deployment contract](SPEC_VKE_DEPLOYMENT.md).

## What Must Be Completed

| Work | Priority and dependency | Completion evidence |
| --- | --- | --- |
| Establish and configure APIG upstream verification | Hard launch blocker; needs an authoritative supported interface | Valid backend succeeds; untrusted, expired and wrong-host backends fail through APIG |
| Add explicit production APIG mode | Code can be prepared now; deployment follows trust acceptance and approval | Private routing preserved; supported BYOK headers reach the app; unsupported `Authorization` remains rejected |
| Recover the exposed GHCR pull credential | Independent security work; do not postpone indefinitely for TLS | Replacement-only registry and Kubernetes pulls verified; old PAT revoked; obsolete references removed |
| Prove active-call drain and connection behavior | Mock fixture/code can be prepared now; live synthetic acceptance separately approved | Accepted calls complete during planned termination; no hidden create retries; bounded cleanup |
| Establish backend certificate renewal | Design now; issuer/trust selection depends on APIG capability | Expiry ownership and alerts; tested Secret rotation and served-certificate readback on every replica |
| Final target-client and provider acceptance | After trusted routing and approved production delivery | Actual client transport checks; separately approved provider validation, with no blind resubmission |
| Pages publication and full billing reconciliation | Follow-ups, not reasons to rebuild the MCP infrastructure | Correct fork site and publishing settings; complete settled-resource ledger |

Temporary uploads, TOS IRSA activation, a new database, per-key concurrency,
new worker pools, and a public-CLB substitution are not prerequisites for the
selected basic stateless launch.

## APIG Trust: Findings and Options

### Published Controls

The pinned public Go create and update request models contain only `Sni` and
`TlsMode` under `TlsSettings`; Python independently has the same wire fields.
The Go untyped request method is not evidence that arbitrary additional
properties are accepted by APIG. No independently published native OpenAPI
schema establishing a trust control was recovered. [S01-S03]

Important documentation contradictions remain:

- The K8S upstream guide says one-way TLS requires selecting a certificate,
  but does not define its trust/hostname semantics or the missing binding
  observed in the inspected form and SDK. [S04]
- The complete annotations page documents selected NGINX-prefixed annotations,
  not arbitrary NGINX support. It contains no documented upstream CA or
  certificate-verification annotation. [S05]
- The APIG Gateway API guide says "fully compatible", but its supported-resource
  table names GatewayClass, Gateway and HTTPRoute. It marks the feature Beta
  and states a highest compatible CRD version of 1.4.0. Neither statement
  establishes BackendTLSPolicy enforcement. [S06]
- The version-management table stops at 4.0.0 and says self-service version
  upgrades are not supported. That documentation cannot explain the recorded
  4.4.4 console state or supply a corrective upgrade. Release notes direct
  readers to the console for regional availability. [S07-S08]

The existing default domain is documented as stable after service creation.
That does not grant its DNS, certificate-export or private-key authority to
the application operator. [S15]

The historical console's testing-oriented label also needs clarification.
The service-creation guide, domain-stability FAQ, custom-domain guide and Limits
page establish neither an explicit production prohibition nor a complete
production-use/QPS/availability contract for direct use of that hostname.
The Limits introduction explicitly covers only "some constraints"; its table
lists object quotas, not a generated-domain traffic contract. Treat this as a
provider clarification question, **not a newly proven prohibition or evidence
that the hostname is unsuitable**. [S15-S16,S29-S30]

### Option Matrix

| Candidate | Preserves current client URL and ordinary MCP clients? | Assessment |
| --- | --- | --- |
| Supported APIG CA/identity validation on its current upstream connection | Yes, if the existing public service/listener is retained | Preferred, provider support not yet established |
| BackendTLSPolicy enforced by APIG itself | Potentially; existing-service integration also needs proof | Conditional candidate, not an established APIG feature |
| CA-issued backend certificate without changing APIG validation | Yes | Not sufficient; certificate issuance cannot force the client to verify |
| Caddy requires a gateway client certificate | Yes if APIG supports presenting it | Authenticates APIG to Caddy, not Caddy to APIG; insufficient alone |
| Another verifier/proxy behind APIG, including beside backend Caddy | Yes | Leaves APIG's first private-network connection unauthenticated |
| Provider-supported verifier at the APIG end, before the private-network hop | In principle | Hypothesis requiring a protected local handoff and provider-managed integration; not an available operator workaround |
| TLS passthrough to Caddy with an owned domain | Ordinary MCP protocol can remain, endpoint changes | Architecture change, APIG passthrough support unestablished; not authorized |
| Custom client encryption or tunneling | Not ordinary unchanged clients | Protocol/client change, not a drop-in TLS repair |

The TLS checks must be performed by the component initiating the connection.
Envoy explicitly distinguishes trusted-CA chain verification from subject-name
verification. Caddy client authentication checks the client in the opposite
direction. A downstream proxy cannot retroactively authenticate the peer to
which APIG already sent the request. Private networking reduces exposure but
does not supply this missing identity check. [S09-S13]

Passthrough moves public TLS termination to the backend. A certificate for a
different owned domain cannot authenticate the current provider-owned generic
hostname. Provider-authorized delegation of that identity is unknown, not
demonstrated impossible; the reviewed docs do not establish it. [S10-S11,S15-S16]

### Precise Provider Dependency

Request one concrete answer from an identified APIG technical owner:

> For standard APIG 4.4.4 in ap-southeast-1, what supported action/version/field
> or controller policy makes a K8S upstream validate its server certificate
> chain, validity period and expected DNS SAN? How is system/private CA trust
> selected? Does this preserve the existing public service and generic domain?
> If BackendTLSPolicy is the mechanism, which controller version, prerequisites
> and acceptance/status conditions demonstrate enforcement on APIG's connection?
> Separately, does direct production use of the generated hostname have any
> testing-only, QPS, security or availability restrictions?

Request an actual documented configuration, not merely "HTTPS is supported".
If the provider answer depends on another version, require regional
availability and an approved upgrade procedure before attempting it.
If no native control exists, return for an architecture decision. The operator
has selected **Keep APIG**; no endpoint replacement is authorized.

No speculative APIG payload is included in this report.

### Acceptance Before Credential Forwarding

Use an isolated synthetic backend and exact operator-only routes, with no real
provider credentials. For each case, establish that the response came from the
intended backend, not a cached or fallback response.

1. Approved CA, expected SAN and valid dates: success.
2. Untrusted issuer: handshake/forwarding failure.
3. Trusted issuer but wrong SAN: failure.
4. Trusted issuer and correct SAN but expired certificate: failure.
5. Approved replacement certificate: success after deliberate rotation.
6. Missing/wrong operator marker and all unrelated public paths: rejected.
7. Disable test routes and independently verify disabled state and public 404.

For negative cases, confirm the application receives no HTTP request. Use fresh
connections and account for existing connection/session reuse so a successful
old TLS session cannot mask a broken new-certificate check. Keep retries,
fallbacks and mirroring disabled. Positive-only HTTPS or direct-client
verification is not acceptance of APIG's verification.

## Production Configuration

### Proposed Code Boundary

Introduce an explicit proposed `service.mode=apig-production`; do not weaken
`apig-staging` and do not reuse `public-clb` as a hidden fallback.
The mode is a recommendation, not implemented functionality.

| Source area | Proposed work |
| --- | --- |
| `deploy/helm/seed-mcp/values.yaml`, `values.schema.json`, `templates/validate.yaml` | Add the production mode and strict conditions: distinct backend hostname, private Service, approved private source ranges, empty CLB subnet and uploads disabled |
| `templates/_helpers.tpl`, `configmap.yaml`, new `files/Caddyfile.apig-production` | Select a separate reviewed production proxy configuration and include it in the existing checksum mechanism |
| `templates/service.yaml`, `networkpolicy.yaml`, `deployment.yaml`, `NOTES.txt` | Preserve private 8443 exposure, ingress selection, PDB/topology/grace and explicit Secret-rollout requirements in all modes |
| `scripts/deploy_vke.py` | Extend mode/hostname checks and certificate selection; retain private kubeconfig/files, one-shot Helm and captured diagnostics |
| `.github/workflows/deploy-vke.yml` | Explicit production mode and reviewed protected-environment mapping; no inheritance of production approval from staging readiness flags |
| Relevant chart, helper, Caddy tests, docs and skills | Add all-mode coverage and update operator/client-facing contracts in the same implementation unit |

Source anchors: [schema](../deploy/helm/seed-mcp/values.schema.json),
[private-mode validation](../deploy/helm/seed-mcp/templates/validate.yaml),
[proxy selection](../deploy/helm/seed-mcp/templates/_helpers.tpl),
[NetworkPolicy](../deploy/helm/seed-mcp/templates/networkpolicy.yaml),
[delivery helper](../scripts/deploy_vke.py), and
[workflow](../.github/workflows/deploy-vke.yml).

### Credential and Proxy Contract

The current staging Caddyfile rejects ModelArk, Seed Speech, client-secret and
Authorization headers, including empty values. Opening its APIG routes would
not make it a functioning BYOK production endpoint.

The production path must forward the three supported credential headers and
the two ModelArk endpoint-selection headers, without logging or persisting
them. Preserve unsupported `Authorization` rejection at the edge or application;
do not silently strip it to bypass application validation. Maintain canonical
Host, replacement of untrusted forwarded headers, operator-marker stripping,
2 MiB body limits, hidden `/ready` and `/metrics`, and disabled access logs.
Do not add provider keys to server environment or invent customer ownership.

Evidence: [staging proxy](../deploy/helm/seed-mcp/files/Caddyfile.apig-staging),
[credential validation](../src/ark_mcp/security/credentials.py),
[HTTP middleware](../src/ark_mcp/security/http_middleware.py), and
[hosted BYOK contract](SPEC_HOSTED_BYOK.md).

Acceptance should include concurrent mock clients with distinct synthetic
provider identities, selected-provider-only forwarding, no environment-key
fallback, credential-reuse rejection and redacted diagnostics. Client secrets
scope admission, not provider task ownership; different key strings alone do
not prove different provider accounts. Preserve those existing boundaries.

The current proxy supplies its direct APIG peer as X-Forwarded-For. The
application can consequently rate-limit multiple customers in the same
gateway-peer bucket. Decide whether to accept/document that behavior or
separately establish a trustworthy original-client-IP contract. Do not fix it
by trusting arbitrary forwarding headers or adding per-key concurrency.

## Active Calls and Certificate Renewal

### New Acceptance Gaps

The app and Caddy are ordinary containers in the same Pod, without lifecycle
coordination hooks. Kubernetes sends their termination signals in an arbitrary
order and marks terminating endpoints not Ready. The 660-second grace is a
shared budget, including lifecycle hooks; two sequential 630-second drains
would not fit. A native sidecar or sleep alone is not proof of continuity.
[S23; `deployment.yaml`, `runtime.py`]

Current timing semantics:

| Clock | Current source value/meaning |
| --- | --- |
| Tool deadline | 600s default, starts at wrapper entry after HTTP/MCP parsing |
| Uvicorn graceful shutdown | `max(tool deadline, provider timeout) + 30s` |
| Caddy shutdown grace | 630s default |
| Caddy upstream response-header timeout | 630s; not a total response-body deadline |
| Caddy inbound idle keepalive | 5m; not proof a silent active request survives every intermediary |
| Pod termination grace | `max(tool deadline, provider timeout) + 60s`, normally 660s |
| Client timeout guidance | 660s; cooperative draining may overrun a deadline |

The server forces stateless HTTP and JSON responses. Do not assume SSE
heartbeats, session resumption or sticky sessions will protect long silent
calls. Caddy documents that `flush_interval -1` does not cancel its backend
request when the client disconnects early. An interrupted create can therefore
remain uncertain even when the client sees an error. [S13,S24-S26]

There is also a concrete configuration mismatch to test: Caddy's documented
upstream keepalive default is two minutes, while Uvicorn's is five seconds.
The repository does not explicitly align them. Caddy warns this can cause
connection resets/502s for HTTP/1.1 upstreams. Propose a tested explicit
alignment, such as Caddy's upstream idle keepalive shorter than Uvicorn's,
without enabling automatic POST retries. This is a source-grounded risk,
**not a reproduced production failure**. [S13,S24]

Relevant source: [`__main__.py`](../src/ark_mcp/__main__.py),
[`server.py`](../src/ark_mcp/server.py),
[`runtime.py`](../src/ark_mcp/runtime.py),
[`Caddyfile.apig-staging`](../deploy/helm/seed-mcp/files/Caddyfile.apig-staging).

### Bounded Test Design

Extend the existing mock-only hosted acceptance fixture, not the public tool
surface. The current fixture explicitly uses one app/Caddy pair, 20ms mocks,
a 2s tool deadline and short process lifetimes; it is not a ten-minute drain
test. See [`hosted_acceptance.py`](../scripts/hosted_acceptance.py) and
[`hosted_acceptance_support/`](../scripts/hosted_acceptance_support/).

- Add a provider-dispatch barrier, controlled completion, synthetic receipt
  IDs and timestamps. Keep a cleared/allowlisted environment and deny
  unmocked network access; never import ambient generation credentials.
- First exercise short app-first, proxy-first and near-simultaneous TERM
  cases. Then run an explicitly bounded production-duration profile:
  roughly 590s of mock work, termination shortly after dispatch, full response
  completion and process exit within the configured grace.
- Include a stalled call and disconnect-after-dispatch case. Assert one mock
  dispatch, no automatic resubmission, and truthful uncertainty/accepted-ID
  diagnostics when the connection survives.
- Test fresh/reused HTTP/1.1 and HTTP/2 client connections, silent requests over
  300s, stale backend keepalive over 5s, slow response delivery and body limits.
  Account for every intermediary's active-request and idle timeouts.
- Under separate live-test approval, use a test-only workload/image with
  verified egress denial. Identify the pod owning the accepted request before
  PDB-respecting eviction; observe endpoint withdrawal, replacement readiness
  and result completion through the approved gateway path.
- Exercise rollout and node drain separately. HPA/controller replica reduction
  must be assessed on its own behavior, not assumed to use the same voluntary
  eviction protection. Preserve normal grace and capacity controls.

Do not add a public sleep tool, production mock switch, database, replay
journal or retry loop. If a drain test reveals a race, add the smallest
bounded pod-local coordination needed to stop new intake while allowing
accepted work to finish, then repeat the same acceptance matrix.

### Certificate Lifecycle

The chart has no issuer or automatic TLS renewal/reload controller. Caddy has
automatic HTTPS and its admin API disabled. The chart's NOTES explicitly say
to roll pods after external Secret changes. Updating data under the same
Secret name does not change the Pod template; a same-values Helm upgrade is
not a renewal mechanism.

Prefer a privately provisioned, versioned TLS Secret followed by a protected
rollout, or a separately approved explicit rollout after same-name replacement.
Define the issuer/CA, SAN, full-chain requirements, renewal owner, expiry
alerts and lead time. Verify the served certificate on every new replica and
test rotation while a synthetic long call is active. Retain suitable prior
material only through the approved overlap and cleanup procedure.

The helper checks certificate/key loading, selected hostname and at least
one day until expiry. It does not establish APIG trust or monitor future
expiry. Historical short-lived self-signed staging certificates are not a
production issuance plan. [S12,S14; `scripts/deploy_vke.py:211-235`,
`templates/NOTES.txt:32`, `deployment.yaml:27-29`]

## Registry Credential Recovery

For external private GHCR pulls, GitHub documents a classic PAT with
`read:packages`, owned by an account with package Read permission. Required
SSO authorization is separate. A fine-grained PAT is not a documented
replacement for this registry contract. A broadly privileged user's classic
PAT is not limited to one image merely because one Secret uses it. [S17-S18]

Proposed operator sequence, requiring approval before execution:

1. Select incident containment order. Prompt revocation minimizes exposure but
   can interrupt uncached pulls and scale-out. Availability-first overlap keeps
   the exposed token usable and needs explicit, short, time-bounded acceptance;
   it must not become indefinite waiting for the unrelated TLS fix.
2. Create the least-privilege replacement privately, with bounded expiry and
   a renewal owner. Keep pull and publisher identities separate. Do not put
   credentials in chat, command arguments, Helm values, Git or artifacts.
3. Verify the exact immutable private image using only the replacement
   credential in an isolated, empty-auth registry client. Verify the digest
   and a separate unauthenticated negative control. Login alone is insufficient.
4. Provision a separately named namespace-local
   `kubernetes.io/dockerconfigjson` Secret through the approved private path.
   Verify a test Pod referencing only that Secret, using the approved digest
   and `imagePullPolicy: Always`; rule out node/mirror/ServiceAccount fallback.
   Do not delete production caches or drain workers to manufacture a test.
5. Change the chart's pull-Secret reference through reviewed delivery. Confirm
   spare capacity and the existing `maxUnavailable: 0`/`maxSurge: 1` rollout.
   On failure, inspect rather than automatically retrying or restoring an
   exposed credential.
6. Revoke the old PAT within the approved containment window, remove obsolete
   active and rollback references, then retire its old Secret and authorized
   stored copies. Deleting a Kubernetes Secret is not GitHub revocation.
7. Add expiry alerting and a repeatable replacement-only verification process.
   Secret synchronization alone does not mint or renew a PAT. [S17-S22]

The current chart sets `IfNotPresent`. Healthy cached pods or a successful
same-node restart do not prove replacement credentials work. `Always`
requests registry resolution while allowing cached layers; isolate alternate
credential sources as part of the acceptance. [S21;
`deployment.yaml:55-64`]

Near term, a narrowly privileged pull identity and managed renewal are the
documented private-GHCR path. Actions `GITHUB_TOKEN` is job-scoped and not a
durable Kubernetes pull credential. A custom GitHub App token is not an
established drop-in OCI-registry replacement just because Packages REST APIs
support App authentication. [S17-S19]

Longer term, evaluate private-registry promotion and a supported renewable
VKE pull identity. Kubernetes credential-provider plugins need a working
registry integration and node configuration; generic Kubernetes support does
not establish GHCR or managed-VKE integration. Public package visibility is
another option but was not approved. [S21-S22]

## Separate Follow-Ups

### Documentation Publishing

The recorded Pages failure is a publication failure after a successful build,
not a failing MCP deployment. The workflow already has `pages: write`,
`id-token: write`, an uploaded artifact and the `github-pages` environment.
Verify Pages is enabled with **GitHub Actions** as Source and appropriate
default-branch protection. A 404 alone is not a fresh proof of the exact
repository-setting cause. [S27]

The fork's Astro configuration still uses `base: "/ark-mcp"` and a redirect
containing that path. For default project Pages under `byteplus-sa/seed-mcp`,
review `/seed-mcp/` as the publication base, including redirects, generated
links, tests and documentation. Do not repoint users to the upstream site's
URL or blindly broaden workflow permissions. [S28;
`.github/workflows/docs.yml:64-84`, `docs/site/astro.config.mjs:15-22`,
`docs/site-maintenance.md`]

### Billing

The historical USD 2.89 figure was a selected settled-resource subtotal, not
the stack's current bill or a monthly projection. Build a complete resource-ID
ledger covering VKE management, baseline/burst ECS and disks, NAT/EIP, private
API load balancing, APIG nodes and hosted load balancers, public/private
traffic, runner-associated usage and any separately billed dependencies.
Reconcile billing periods, currency, settlement lag and pagination before
summing or forecasting. Do not equate missing rows with free resources.

Two baseline workers and networking still cost money at idle. Worker bounds
and bandwidth ceilings are not spend caps. HTTP has no shared budget ledger;
provider-account spending controls remain separate from operator infrastructure
costs. No new price quote or account bill was retrieved in this research.
See [`gateway.tf`](../deploy/terraform/vke/gateway.tf),
[`main.tf`](../deploy/terraform/vke/main.tf),
[the cost caveats](../docs/byteplus-terraform.md#optional-worker-autoscaling),
and [the BYOK contract](SPEC_HOSTED_BYOK.md).

## Execution Order

1. **Parallel preparation:** obtain the exact native APIG trust contract;
   prepare the explicit production mode and test fixture; plan/authorize
   registry recovery and certificate ownership.
2. **Offline evidence:** run all-mode renders, real pinned-Caddy header tests,
   bounded mock shutdown/timeout tests, Secret-reference rollout tests and
   credential-safe diagnostics checks. Coordinate production-mode and lifecycle
   changes because they touch the same chart/proxy files.
3. **Trusted synthetic gate:** only after a supported APIG mechanism exists,
   configure it through an approved one-shot operation and perform both
   positive and negative certificate tests. Never substitute a new create for
   reconciliation of an uncertain result.
4. **Protected production delivery:** use an explicitly approved environment,
   fresh workflow-restricted runners, verified certificate and pull Secrets,
   immutable image, private preflight and one-shot Helm. Reconcile outcome and
   clean runners before another attempt.
5. **Acceptance and launch:** test clients, active-call continuity, replica
   independence, body/header limits, timeouts, no credential leakage and no
   automatic create retry. Provider-backed tests require their own approval.
   Enable public BYOK routes only after all relevant evidence and launch approval.

Pages and full billing reconciliation can be completed independently. Do not
add unrelated services or make every optional follow-up block useful progress.

## Confidence and Remaining Questions

**High confidence:** current code gaps, published SDK fields, certificate
directionality, registry credential requirements and documented timeout/renewal
semantics were independently checked.

**Conditional:** an APIG-native fix, APIG-side verifier, passthrough or
BackendTLSPolicy enforcement remains unestablished. Documentation absence is
not universal non-support; the current product-owner dependency is real.

**Not tested here:** live provider authorization, active-call drain, keepalive
failure reproduction, current certificate expiry, new registry credentials,
current gateway state or costs. No research claim upgrades historical
synthetic results into production acceptance.

Remaining decisions are the supported APIG control, production approver,
backend certificate/renewal owner, credential containment order, isolated
live-test authorization and desired client-IP rate-limit semantics. Generated
hostname production-use policy remains a clarification, not an established
restriction.

## Sources

All sources below were accessed and their relevant bodies inspected on
**2026-11-24**. Living documentation is not a version-pinned guarantee for the
deployed binaries. Repository links above describe the recorded source revision.

| ID | Primary source | Evidence use |
| --- | --- | --- |
| S01 | [BytePlus Go CreateUpstream, pinned](https://github.com/byteplus-sdk/byteplus-go-sdk-v2/blob/b11e0085af3e9f4d09d690dd0cb804d3bfc6e443/service/apig/api_create_upstream.go#L736-L742) | TLS fields and untyped API distinction |
| S02 | [BytePlus Go UpdateUpstream, pinned](https://github.com/byteplus-sdk/byteplus-go-sdk-v2/blob/b11e0085af3e9f4d09d690dd0cb804d3bfc6e443/service/apig/api_update_upstream.go#L604-L610) | Update TLS fields |
| S03 | [BytePlus Python TLS model, pinned](https://github.com/byteplus-sdk/byteplus-python-sdk-v2/blob/2c97e64db0fb22cf3a126ef0a245f577ec9892aa/byteplussdkapig/models/tls_settings_for_create_upstream_input.py#L35-L45) | Matching wire contract |
| S04 | [APIG K8S upstream guide](https://docs.byteplus.com/en/docs/apig/Creating_a_Vital_Kubernetes_Engine_type_Upstream) | Certificate-selection wording and unresolved semantics |
| S05 | [APIG supported annotations](https://docs.byteplus.com/en/docs/apig/Annotations_Supported_by_the_Gateway) | Documented controller annotation surface |
| S06 | [APIG Gateway API guide](https://docs.byteplus.com/en/docs/apig/Using_Gateway_API_via_APIG) | Beta prerequisites, resources and CRD-version caveat |
| S07 | [APIG version management](https://docs.byteplus.com/en/docs/apig/Version_Management) | Version-table gap and upgrade procedure |
| S08 | [APIG release notes](https://docs.byteplus.com/en/docs/apig/Release_notes) | Regional-availability caveat; updated 2026-11-10 |
| S09 | [Envoy TLS](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/security/ssl) | Chain validation is distinct from identity validation |
| S10 | [RFC 9525](https://www.rfc-editor.org/rfc/rfc9525.html) | TLS service identity and certification-path requirements; November 2023 |
| S11 | [Gateway API TLS guide](https://gateway-api.sigs.k8s.io/guides/tls/) | Backend identity/trust and passthrough semantics, not APIG parity |
| S12 | [Caddy TLS](https://caddyserver.com/docs/caddyfile/directives/tls) | Server certificate and client-authentication direction |
| S13 | [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) | Verification, disconnect, keepalive, retry and timeout semantics |
| S14 | [Let's Encrypt challenges](https://letsencrypt.org/docs/challenge-types/) | DNS-01 for non-public backends; updated 2026-02-12 |
| S15 | [APIG generated-domain stability](https://docs.byteplus.com/en/docs/apig/Will_the_automatically_generated_access_Domain_name_remain_unchanged) | Stable name, not delegated certificate authority |
| S16 | [APIG custom domains](https://docs.byteplus.com/en/docs/apig/Adding_domain_name) | Matching certificate and DNS requirements |
| S17 | [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) | Classic PAT, scopes, SSO and Actions authentication |
| S18 | [GitHub package permissions](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages) | Scope plus account package access |
| S19 | [GitHub GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token) | Job-scoped token lifetime |
| S20 | [GitHub credential security](https://docs.github.com/en/rest/authentication/keeping-your-api-credentials-secure) | Least privilege, storage and compromise remediation |
| S21 | [Kubernetes images](https://kubernetes.io/docs/concepts/containers/images/) | Pull policies, caches and namespace-local pull Secrets |
| S22 | [Kubelet credential providers](https://kubernetes.io/docs/tasks/administer-cluster/kubelet-credential-provider/) | Registry integration and node prerequisites |
| S23 | [Kubernetes Pod termination](https://kubernetes.io/docs/concepts/workloads/pods/pod-termination/) | Signal order, shared grace and endpoint withdrawal |
| S24 | [Uvicorn settings](https://www.uvicorn.org/settings/) | Keepalive and graceful-shutdown meanings |
| S25 | [FastMCP HTTP deployment](https://gofastmcp.com/deployment/http.md) | Transport/lifespan integration guidance |
| S26 | [FastMCP lifespans](https://gofastmcp.com/servers/lifespan.md) | Teardown and cancellation-safe cleanup |
| S27 | [GitHub Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) | Actions publication configuration |
| S28 | [Astro GitHub Pages deployment](https://docs.astro.build/en/guides/deploy/github/) | Correct project base and site settings |
| S29 | [APIG service creation](https://docs.byteplus.com/en/docs/apig/Creating_a_service) | Service scope; no explicit generated-domain production contract |
| S30 | [APIG limits](https://docs.byteplus.com/en/docs/apig/Limits) | Non-exhaustive object quotas, not hostname traffic guarantees |
