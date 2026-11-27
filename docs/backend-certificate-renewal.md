# Backend Certificate Renewal

This is an operator procedure for the private Caddy certificate referenced by
`tlsSecretName`, not certificate automation or authorization to deploy. It
implements the
[certificate lifecycle contract](../specs/SPEC_VKE_DEPLOYMENT.md#certificate-lifecycle).
The [deployment record](hosted-deployment-status.md#renewal-and-follow-ups)
holds the current instance's renewal dates and acceptance evidence.
No issuer, domain, CA, credential or cloud change is selected by this document.

Preserve the existing APIG and generic client URL. APIG terminates public TLS;
the separate `backendHost` identifies Caddy on the private hop. Explicit
`service.mode=apig-production` source support and its approval acknowledgement
do **not** establish deployment, APIG certificate verification or launch approval.
The historical APIG one-way TLS probe accepted an untrusted backend. The
operator has since explicitly accepted that private-hop risk for the
[scoped deployment](../specs/SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception):
keep HTTPS, waive APIG verification. This is not verification success, and
public routes remain blocked until other launch gates and approval pass.
Certificate/key health, expiry and renewal still matter; the waiver does not
remove TLS, alter public/client validation or waive local certificate checks.

## Existing Behavior

The [Deployment template](../deploy/helm/seed-mcp/templates/deployment.yaml)
mounts the existing namespace-local TLS Secret read-only at `/tls` in Caddy,
not the application. `tls.crt` and `tls.key` use mode `0440` with the pod's
nonroot group. Helm neither issues certificates nor creates these Secrets.

Caddy uses explicit certificate files, with automatic HTTPS and its admin API
disabled. There is no issuer, renewal controller or promised automatic reload.
As the [chart notes](../deploy/helm/seed-mcp/templates/NOTES.txt) state, external
Secret changes require a pod rollout. Replacing bytes under the same Secret
name does not change the pod template; filesystem projection or a same-values
Helm upgrade is not proof of renewal.

Prefer a new versioned Secret name. Changing `tlsSecretName` changes the
volume reference and runtime checksum, causing replacement pods. Keep the
normal `maxUnavailable: 0`, `maxSurge: 1`, PDB and topology settings; provide
capacity for active, surge and draining pods. PDB protection is not a substitute
for the Deployment's rolling-update policy. See the
[VKE contract](../specs/SPEC_VKE_DEPLOYMENT.md#network-and-shutdown).

## Ownership and Alerts

Before issuance, record a named primary renewal owner, backup on-call owner,
issuer/CA contact, backend trust decision owner and protected-delivery approver in the
private operations record. Assign responsibility for checking alerts, not
merely configuring them. The repository supplies no expiry monitor.

Inventory the namespace/release, `backendHost`, Secret name/UID, leaf SHA-256
fingerprint, serial, issuer, SANs, UTC validity dates, intermediate-chain
expiry, approved trust anchors and current served fingerprint per replica.
Track the earliest expiry that would invalidate the approved chain, not just
the leaf. Track the APIG public certificate separately; this procedure cannot
renew a provider-owned public identity.

Use these operating windows unless a separately reviewed issuance policy
requires earlier action:

| Remaining validity | Owner action                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| 30 days            | Open renewal work; verify issuer access, trust compatibility, private delivery access and available maintenance capacity. |
| 14 days            | Target completion of issuance, rollout and acceptance; escalate any missing replacement or approval.                      |
| 7 days             | Page primary and backup owners if rotation is incomplete; approve an explicit recovery schedule.                          |
| 72 hours           | Treat unresolved renewal as an availability incident; reconcile before any further write and decide traffic containment.  |
| 24 hours or less   | Do not rely on the helper passing; its one-day expiry check is a rejection boundary, not a renewal target.                |

Check the inventory and served-certificate expiry at least daily, after every
rollout and when replicas are added. A missing observation or fingerprint
mismatch is an alert, not an implicit pass. Test alert delivery to both owners.
For certificates too short-lived for these windows, approve a compressed
schedule **before issuance**, leaving time for issuance failure, separate check
and deploy jobs, acceptance and recovery while still outside the one-day helper
boundary. Historical short-lived self-signed probe certificates are not a
production renewal policy.

## Issuance Prerequisites

1. Have the operator approve the existing backend identity and issuer/CA.
   Under the default verified-backend policy, a private CA or public-CA
   certificate requires supported APIG verification. Under the scoped exception,
   record that APIG identity enforcement is waived; obtaining such a control is
   not an issuance or renewal prerequisite. Continue local checks below. DNS-01 can
   support issuance without public backend ingress, but domain control,
   challenge credentials and issuer choice remain operator-owned. Do not
   request a certificate for the provider-owned generic APIG hostname.
2. Require the expected `backendHost` in a DNS SAN, usable server-auth key
   usage, compatible key/signature algorithms and valid `notBefore`/`notAfter`
   dates on the approved path. Match the private key to the leaf. Check clock
   synchronization. Do not accept a CN-only match as the SAN prerequisite.
3. Supply PEM `tls.crt` as the leaf followed by all required intermediates in
   chain order. Normally omit the root from the served chain; distribute trust
   anchors through the separately approved trust configuration. Do not rely on
   clients fetching missing intermediates. Supply a PEM key loadable without
   an interactive passphrase by Caddy, protected at rest and during transfer.
4. Verify the complete chain for server authentication, expected hostname and
   current validity against the approved CA bundle, independently of the
   deployment helper. Record nonsecret metadata and the chain selected. Local
   verification is a prerequisite, not proof that APIG uses that trust policy.
5. Keep the backend name and trust anchors unchanged for routine leaf renewal.
   A CA, intermediate-path, SAN or algorithm change requires separate review
   of compatibility and overlap. Gateway valid/invalid identity acceptance
   applies to the default verified policy; it is deferred under the exception.
   Never remove an old trust anchor while an approved serving chain needs it;
   never add broad trust or disable verification to make rotation succeed.

## Prepare and Deliver

Every step below requires the operator's separate change authorization.
Use the [protected delivery runbook](github-actions-deployment.md) for runner,
private API, RBAC and approval prerequisites. No command here provisions cloud
resources or creates a Secret.

1. Reconcile the current Helm release, Deployment generation, ReplicaSets,
   pod UIDs/readiness, actual serving certificates and referenced Secret.
   Confirm there is no active or uncertain prior rollout. Record the exact
   reviewed source revision, immutable image digest, service mode, backend and
   public names, ingress ranges and current trust evidence or scoped exception. Keep identity,
   registry credentials, image, routing and other settings unchanged for a
   certificate-only renewal.
2. Privately obtain the approved replacement. Keep key/certificate working
   files in same-owner `0700` directories with `0600` regular files outside the
   checkout, without symlinks. Use the approved secret-management path, not
   chat, shell-history values, Helm values, Terraform state, Actions artifacts
   or diagnostic dumps. Never print raw Secret JSON/YAML or private keys.
3. Through the authorized private provisioning process, create one separately
   named `kubernetes.io/tls` Secret in the exact application namespace with
   `tls.crt` and `tls.key`. Use a unique DNS-label version suffix; do not
   overwrite an existing name. Keep it distinct from identity, image-pull and
   optional upload Secrets. Reconcile uncertain creation by exact name/UID
   and private data comparison before considering another create.
4. Privately read back and validate the new Secret's type, fields, certificate,
   key match and chain. Record its UID and public certificate fingerprint,
   not its data. Confirm the chart's nonroot Caddy can read the projected
   files; do not broaden permissions or give the application a key mount.
5. Review nonsecret inputs changing `tlsSecretName` to that version. The helper
   pins this value from `--tls-secret`, and Actions supplies it from
   `VKE_TLS_SECRET`; updating a values file alone is insufficient. Match those
   references for both check and deploy. Changing an environment variable alone
   does not update existing pods. Preserve explicit APIG mode, `backendHost`,
   private ClusterIP:8443, empty CLB subnet, ingress restrictions and disabled
   uploads. Never allow a missing mode to select the public CLB path.
6. Use a reviewed revision that supports the selected mode. For
   `apig-production`, require the separate production environment/runner and
   launch-gate approval described in the production plan and delivery runbook;
   staging readiness flags do not authorize it. Neither
   `service.productionConfirmed` nor the helper's `--production-approved`
   replaces the recorded trust decision or remaining acceptance evidence.
   Do not promote staging as part of renewal.
7. Run protected `operation=check` first on a fresh workflow-restricted private
   runner. Reconcile its terminal result and teardown. If inputs, certificate
   validity or source change before delivery, obtain a fresh reviewed check.
   After approval, replenish a separate one-job runner and dispatch
   `operation=deploy` once with the same reviewed inputs.
8. Observe the replacement generation and new ReplicaSet, pod readiness,
   endpoint withdrawal and normal termination. The helper runs one
   `helm upgrade --install --wait --timeout=15m --history-max=5`; the workflow
   job limit is 30 minutes. Neither timeout is proof that Kubernetes stopped
   changing resources. Complete the checks below before declaring renewal.

### Helper Limits

[`scripts/deploy_vke.py`](../scripts/deploy_vke.py) checks private API/context,
nodes, metrics, identity fields, TLS Secret type and strict Helm lint. Its TLS
checks load the certificate/key pair, run OpenSSL `x509 -checkhost` against the
selected TLS hostname (`backendHost` for APIG), and `-checkend 86400` on the
certificate. The public-CLB mode uses `publicHost` instead.

These checks do not enforce the operator's SAN-only issuance policy, verify
the issuer/full chain or all validity dates, establish revocation status,
configure APIG trust, monitor expiry, reload Caddy or inspect certificates
actually served by pods. They are not live routing or active-call acceptance.
The helper captures subprocess output and removes temporary TLS files on normal
exit; abrupt runner/host failure needs private cleanup. It does not sync
Secrets, install an issuer, retry Helm or roll back automatically.

## Verify Every Replica

A Ready pod is insufficient: application readiness checks lifespan and Caddy's
probe checks TCP, not the served chain. A successful Service or public URL
request can repeatedly reach one replica and only show APIG's public certificate.

1. Enumerate the release's actual pods and Service EndpointSlices through the
   explicit private kubeconfig/context. Record each pod UID, node, ReplicaSet,
   template Secret reference and readiness/termination state. Include all
   replicas, not only the default two; account for HPA and surge membership.
2. Connect to each selected pod individually with a **fresh TLS connection**.
   Use an authorized private path or an explicitly approved loopback-bound
   pod port-forward. Delivery RBAC is not assumed to grant port-forward or
   exec; obtain separate operator access rather than broadening runner RBAC.
   Never expose a diagnostic port publicly or weaken ingress policy.
3. Send SNI and verify the hostname as `backendHost`, even when connecting by
   pod IP or loopback. Verify the approved CA chain and dates without a TLS
   bypass. Compare the served leaf SHA-256 fingerprint, serial, DNS SAN and
   expiry with the new Secret's approved metadata; inspect the served
   intermediate chain as well.
4. Require every replacement pod to serve the new certificate. An old
   terminating pod may retain the old certificate only within the approved
   drain/overlap window. Wait for old endpoints and pods to finish; check the
   final membership again and verify any new arrivals. A mixed serving fleet
   at completion is a failed renewal, even if Helm reported success.

For an approved per-pod port-forward, the following read-only inspection uses
operator-supplied nonsecret variables. In one terminal, keep the forward bound
only to loopback for the selected `$POD`:

```bash
kubectl --kubeconfig "$KUBECONFIG_FILE" --context "$CONTEXT" \
  --namespace "$NAMESPACE" port-forward --address 127.0.0.1 \
  "pod/$POD" 18443:8443
```

In another terminal with the reviewed `$BACKEND_HOST` and `$CA_BUNDLE`, require
both OpenSSL processes to succeed. Use reviewed OpenSSL tooling supporting
these options; do not silently omit verification flags:

```bash
set -o pipefail
openssl s_client -connect 127.0.0.1:18443 \
  -servername "$BACKEND_HOST" -verify_hostname "$BACKEND_HOST" \
  -CAfile "$CA_BUNDLE" -verify_return_error </dev/null |
  openssl x509 -noout -fingerprint -sha256 -serial -dates -ext subjectAltName
```

This prints leaf metadata, not a complete chain inventory. Inspect the full
served chain separately in protected diagnostics and compare its intermediates.
Bound each inspection to 30 seconds using the approved operator tooling; a
timeout fails the check. Stop each forward before selecting the next pod.
This direct-client check does **not** establish APIG verification.

## Active-Call Acceptance

Record each layer separately as passed, failed or not run. Missing evidence
is not success, and an interrupted accepted call is a failure to reconcile.

### Local Mock Evidence

Use the isolated [hosted acceptance fixture](../scripts/hosted_acceptance.py)
and [bounded drain profiles](../scripts/hosted_drain_acceptance.py) described in
the [delivery runbook](github-actions-deployment.md#local-drain-checks).
Keep a cleared environment, synthetic
credentials, mocked provider dispatch and denial of unmocked network access.
Do not read ambient keys or add a public sleep tool/production mock switch.

Require short app-first, proxy-first and simultaneous TERM cases; stalled and
disconnect-after-dispatch cases must not resubmit. Require an explicit
production-duration case with approximately 590 seconds of accepted mock work,
600-second tool deadline, 630-second app/proxy grace and 660-second pod/client
budget at defaults. Termination must follow an observed dispatch barrier,
not an assumed delay. Record one dispatch, complete receipt, timings and
graceful process exit; an early cleanup kill cannot count as a pass.

Exercise fresh/reused connections and stale keepalive beyond five seconds,
recording actual negotiated protocols. The private production listener is H1
only after a reproduced HTTPX H2 GOAWAY failure; both H1 and H2-capable test
clients must negotiate H1. APIG's public protocol behavior is separate. A short
mock pass is not a ten-minute acceptance result. A drain-profile pass alone
also does **not** prove certificate rotation: require a distinct rehearsal
starting replacement Caddy/app instances with a second synthetic certificate
while the original instance drains an accepted call, then verify new
connections serve the replacement. No harness is assumed to orchestrate a
Kubernetes Secret rollout merely because it tests process termination.

### Separately Approved Live Rehearsal

1. Authorize a bounded, test-only workload/image and versioned synthetic TLS
   Secrets, with verified provider-egress denial and no real provider keys.
   Keep that workload isolated from customer traffic. Use the actual proxy,
   timeout and rollout settings; do not inject a mock mode into production.
2. Identify the pod owning a single accepted synthetic long call from a
   dispatch barrier/receipt. During that call, perform one protected
   Secret-reference rollout. Observe that pod's termination, endpoint
   withdrawal, replacement readiness and receipt completion before grace
   expires. Verify the new certificate on every replacement as above.
3. Require one dispatch and one complete result, no POST retry, forced kill,
   fallback or lost receipt. Include new requests while old work drains.
   Record actual client/proxy protocols and clocks. Test pod rollout and
   node drain separately; idle eviction or HPA scale-in is not equivalent
   active-call evidence. Do not bypass PDB or shorten shutdown grace.
4. For APIG-path acceptance, first record the applicable trust decision:
   a supported verification control by default, or the scoped operator exception.
   Use isolated exact operator-only diagnostic routes, initially disabled,
   with inspected random-marker matching and missing/wrong-marker negatives.
   Keep retries, caching, mirroring and fallback disabled. Without that edge
   boundary, private-only results leave APIG acceptance pending.
5. Under the default verified policy, through APIG require valid old/new approved chains to succeed and untrusted
   issuer, trusted-but-wrong-SAN and trusted-but-expired certificates to fail.
   Establish that the intended backend received no HTTP request for each
   failed handshake. Do not replace a customer backend with negative fixtures.
   Use fresh **APIG-to-backend** connections with a supported, approved method
   and account for TLS session reuse; a fresh client-to-APIG connection alone
   cannot prove a new upstream handshake.
   Under the exception, retain positive old/new HTTPS compatibility and direct
   per-replica certificate checks; gateway certificate-negative tests are
   deferred, not passed. Do not block that rollout on obtaining a native
   verification mechanism or silently broaden the exception.
6. Disable diagnostic routes immediately after the bounded test, including on
   failure. Reconcile disabled-state readback and public 404 without printing
   the marker. Retain sanitized timings, pod UIDs, dispatch counts, receipt
   IDs, fingerprints and outcomes, not traffic bodies or Secret values.

No local test, certificate renewal or private rehearsal proves APIG identity
verification. The scoped waiver removes that prerequisite, not the risk.
Real client/provider acceptance and production route enablement
require separate approval; this procedure performs neither.

## Failure Reconciliation

Stop further writes on a failed preflight, Secret create, rollout, certificate
check or acceptance test. A preflight failure means no Helm dispatch from
that invocation, not that earlier changes did not occur. A failed/cancelled
job or timed-out Helm call can leave live new and old replicas.

Inspect the exact workflow run/runner, Helm release status/history, Deployment
generation, ReplicaSets, pod UIDs/endpoints and referenced Secret UIDs. Compare
served fingerprints on reachable replicas. Coordinate with other operators;
workflow concurrency does not exclude manual Helm or Secret writes. Never
re-run a mutation helper just to discover whether its first attempt succeeded.

After establishing the actual state, have the owner approve one specific
recovery: finish a validated replacement or restore the prior Secret reference
through protected delivery. Restoration is a new rollout, not instantaneous
recovery. Recheck the old certificate's validity, trust and uncompromised key;
an expired, revoked or exposed key is not a rollback option. Do not use
automatic Helm rollback, retry loops, force deletion or shortened grace.

Retain any known request/task IDs. Disconnects and timeouts do not cancel
provider work, and HTTP has no replay journal. Reconcile uncertain acceptance
with the authorized provider before a new create; never automatically resubmit.
See [submission safety](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).

## Bounded Retention

Before rotation, record an explicit UTC rollback-overlap deadline. For routine
renewal, retain at most the current version and one prior rollback version
after acceptance; a candidate may exist only during the recorded change window.
Default overlap ends 24 hours after successful acceptance, or at the prior
certificate's expiry, whichever is earlier. Extend only with a named owner,
reason and new deadline; never retain historical private keys indefinitely.
Compromise requires separate incident containment/revocation, not routine overlap.

Before removing prior material, confirm no running or terminating pod, active
Deployment, other workload or approved rollback procedure still needs it.
Inspect retained ReplicaSet and Helm-history references: the helper retains up
to five revisions, but that does not retain or validate their external Secrets.
Mark revisions referencing retired certificates ineligible for rollback and
reconcile references through approved release management before cleanup.

At the deadline, if dependencies remain, escalate and reconcile rather than
deleting an in-use Secret or silently extending retention. Otherwise retire
the exact old Secret and authorized working copies through the private process,
confirm absence and apply bounded backup retention. Secret deletion is not
issuer revocation or proof that backups disappeared. Clean failed candidate
material and abrupt-runner scratch only after outcome reconciliation.
Keep nonsecret audit evidence under the operator's retention policy; never
commit certificate/key material or session-specific reports to this repository.
