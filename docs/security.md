# Security

This document consolidates the server's security model. See
[configuration.md](configuration.md) for the full env-var reference,
[transports.md](transports.md) for transport setup, and
[deployment.md](deployment.md) for remote-deployment hardening.

## Dependency Security

Use `uv sync --locked` to install the reviewed dependency set. FastMCP is
bounded to `fastmcp>=4.1.8,<4.2`; older 4.0.x environments do not contain
the current upstream security fixes. The framework and MCP SDK
must be upgraded together through the lockfile rather than independently.

On 2026-11-10, `bash scripts/audit_dependencies.sh` reported no known
vulnerabilities for the refreshed lockfile. This is a point-in-time result,
not a guarantee against future disclosures. CI and the commit hook run this
audit without vulnerability exemptions.

Upstream release details:
[FastMCP 4.1.8](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.1.8).
Stage upgrades separately, finish active calls before restarting, and preserve
runtime state, artifact storage and HTTP HMAC identity configuration.

## HTTP BYOK Boundary

`AuthMode` accepts `byok` (default) and explicit stdio-only `local`.
The former `api_key` mode is removed. All HTTP, including loopback, requires
BYOK and the operator's `MCP_IDENTITY_HMAC_KEY` (64 lowercase hex from 32
random bytes), with positive `MCP_IDENTITY_KEY_VERSION` (default `1`).
This key derives identity; it is not a customer credential.

There is no OAuth, signup, server-issued key or bearer-token passthrough.
`Authorization` is rejected with safe guidance. Clients send
`X-MCP-Client-Secret` and the selected `X-ModelArk-Api-Key`
or `X-Seed-Speech-Api-Key`. The client secret must be
client-generated 32 random bytes encoded as 64 lowercase hex.
Only the selected provider key is required, including on dry runs.

Raw ASGI header validation rejects duplicate, empty, non-ASCII, whitespace,
control and oversized values without echoing them. Keys are opaque printable
ASCII of at most 4096 characters. It also rejects a client secret equal to any
supplied provider key with HTTP 400 `CREDENTIAL_REUSE`, before tool execution,
including discovery, dry runs and upload preparation. Constant-time comparisons
are exact; this hygiene check does not establish customer identity or provider
authorization. Generate an independent client secret and update its private
client configuration, keeping provider keys unchanged.
Live credentials are never restored from
task snapshots, persisted in backend/artifact/cache rows, or put in tool inputs.
Request and provider contexts are released on completion/cancellation.
Gateways receive explicit keys and never fall back to environment provider
credentials for HTTP.

## Principal and Tenant

The credential tenant and client-secret digest are ephemeral per-pod admission scopes,
not a durable task authorization boundary. `MCP_IDENTITY_HMAC_KEY` and
`MCP_IDENTITY_KEY_VERSION` never replace provider authorization.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

Task get/list/cancel and Draft lookup are authorized by the supplied provider
key. `X-MCP-Client-Secret` separates per-pod admission scopes, not task access.
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

## Scope Taxonomy

Catalog scope strings remain capability metadata, not customer-selected roles,
OAuth grants or a common team identity. HTTP admission enforces the selected
provider key and client owner. Local stdio trusts its local principal.

All 9 scope strings in the catalog are retained below as metadata, not auth
grants. A label does not register a tool or grant access to provider accounts.

| Catalog scope metadata | Tools |
| --- | --- |
| `artifacts:read` | `seed_media_get_artifact`, `seed_media_export_artifact` (stdio only) |
| `media:upload` | `media_upload`, `seed_media_persist_url` (stdio only); opt-in HTTP `media_prepare_upload` |
| `media:presign` | `media_presign` (stdio only) |
| `seed:audio:generate` | `seed_audio_generate` |
| `seed:tts:generate` | `seed_tts_generate` (stdio or configured hosted output storage) |
| `seedream:generate` | `seedream_generate_image` |
| `seedance:create` | `seedance_create_task` |
| `gen:read` | `gen_task_get`, `gen_task_list` |
| `gen:delete` | `gen_task_cancel_or_delete` |

HTTP exposes 7 provider/discovery tools, without
requiring operator provider keys. Anonymous `ark_list_models` lists configured
model bindings even without an environment provider key. `services[].enabled`
describes registration, not customer entitlement or key validity. Jobs, native tasks, local storage/artifact tools and all MCP
resources are absent on HTTP. Storage/artifacts remain local stdio capabilities
among the 13 local tools. The catalog has 14 definitions including optional
HTTP upload preparation. No asset administration exists on either transport.

Opt-in `media_prepare_upload` adds one HTTP tool. Operator-enrolled SHA-256
digests of exact ASCII client-secret values authorize it, independently of
generation-provider keys. A self-chosen secret alone grants no upload access.
The tool signs exact-key/size/MIME private POST and GET permissions using
restricted operator TOS credentials; clients upload directly. Signed MIME is
metadata, not content inspection. Returned fields/URLs are sensitive bearer
permissions, potentially including STS; never log or publish them.
Permissions are not guaranteed one-use. Enrollment revocation requires all
pods to reload and does not revoke existing signed permissions.
One-day scheduled object expiry is not precise 24-hour deletion; URL expiry
does not delete objects. Versioning must be disabled. Operator IAM, CORS,
lifecycle and storage/egress abuse controls are separate prerequisites;
per-pod admission is not a global quota. See [temporary uploads](temporary-uploads.md).

TOS signing defaults to explicit static credentials. HTTP-only IRSA mode
rejects static AK/SK/token configuration and performs no ambient environment
or metadata fallback. It lazily exchanges the app-only projected OIDC token
with allowlisted BytePlus STS after enrollment/admission. Redirects and proxy
inheritance are disabled; bounded responses and errors do not echo credentials.
The runtime cache is single-flight, refreshes early and fails closed near expiry.
Automatic API-token mounting remains off, and Caddy has no token/TOS env.
Exact issuer/audience/namespace/ServiceAccount trust, restricted TOS policy,
webhook exclusions and live regional acceptance are operator prerequisites.
STS expiry can shorten references; refreshing credentials never renews issued
URLs. No IAM or cluster OIDC enablement is performed by the server/chart.

## HTTP Admission and Routing

`HardenedFastMCP.http_app()` enforces stateless HTTP, Host/Origin protection
and live credentials on every entry path; stdio-configured HTTP construction
is rejected. Set `MCP_ALLOWED_HOSTS` explicitly for ingress and allow browser
Origins only where needed. Proxy headers are not trusted by default.
`RATE_LIMIT_TRUSTED_PROXY_CIDRS` defaults empty and replaces the removed
boolean trust setting. Only a trusted immediate socket peer can supply
`X-Forwarded-For`; validated bounded chains are walked right-to-left to the
first untrusted address. Malformed/duplicate trusted chains fail without echo.
Catch-all networks are rejected. Uvicorn proxy-header rewriting is disabled.
Rate/body events retain bounded route labels, not raw paths/forwarding headers.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, task-snapshot capture/save or queue creation, including
on discovery. Both transports reject this opt-in and execute directly.

| Setting | Default | Rule |
| --- | --- | --- |
| `RATE_LIMIT_RPM` | `60` | Positive per-IP, per-pod limit with bounded map cardinality; resets at restart |
| `RATE_LIMIT_BURST` | `0` | Uses RPM when zero |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` (2 MiB) | Positive streamed body cap |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Positive per-pod admission limit before body handling, including discovery |
| `STATE_MAX_RECORDS` | `100000` | Local stdio ownership/budget record bound; unused by stateless HTTP |

Backend `/health` and `/ready` are anonymous minimal process/lifespan probes;
HTTP readiness never contacts providers. VKE Caddy exposes only `/mcp` and
`/health`; `/ready` is an internal exec-probe target. `/metrics` is absent
from the main app and proxy. Optional `MCP_METRICS_PORT=0` disables the
HTTP-runtime listener; nonzero 1024-65535 ports bind only 127.0.0.1.
Private metrics require authorized operator access, never a public Service.
`seed-health://status` and artifact resources are stdio-only.

Provider origins are fixed to official ModelArk and Seed Speech
URLs listed in [configuration](configuration.md). No arbitrary hosts,
userinfo, query/fragment or path-confused base URLs are accepted.
Endpoint headers select exact registry bindings only; explicit tool `model`
wins and arbitrary opaque `ep-*` lineage is not inferred.

HTTP rejects `persist=true`, `persist_output=true`, local paths and stored
artifact references before dispatch. Seed Audio/Seedream
persistence defaults are false globally. Clients retrieve expiring outputs.

## SSRF-safe downloader (`security/safe_downloader.py`)

Artifact download and persistence below are **local stdio only**. HTTP never
exposes this downloader through artifact or storage tools.

`SafeDownloader` downloads provider media (for `copy_from_trusted_url`) with
two-layer SSRF defense. Constructor defaults: `timeout=120.0s`,
`connect_timeout=30.0s`, `max_attempts=3`, `follow_redirects=False`,
`trust_env=False` (ignores `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`). The runtime
builds it from `ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS`,
`BYTEPLUS_CONNECT_TIMEOUT_MS`, and `ARTIFACT_DOWNLOAD_MAX_ATTEMPTS`.

Retryable failures (timeouts, network errors, 408/429/5xx) are retried with
1s, 2s, 4s, ... backoff. Policy failures (untrusted host, redirect rejection,
oversize, expired source) are never retried, so retries cannot widen what the
downloader accepts.

`download(url, *, trusted_hosts, max_bytes, max_redirects=5)`:

1. `validate_url(current_url)` — full SSRF validation (scheme, host, DNS,
   IP-class denial) returns pinned public IPs.
2. If `not trusted_hosts(hostname)` → `ValueError` (an application host
   allowlist on top of the IP-level check).
3. `_request_pinned(validated, max_bytes=...)` — **IP pinning**: connects to
   `validated.addresses[0]` while preserving the original `Host` header and
   TLS SNI (`sni_hostname`), preventing DNS rebinding between validation and
   connection. The connect URL replaces the netloc with the IP literal
   (IPv6 bracketed).
4. Redirects are handled hop-by-hop: each `Location` is revalidated from
   scratch (DNS + IP + host policy all re-applied). Missing `Location` →
   `ValueError`; too many redirects → `ValueError`.
5. **Streaming size cap:** if `Content-Length > max_bytes` → `ValueError`;
   chunks are accumulated and checked against `max_bytes` after each
   `extend`.

Both artifact backends restrict `copy_from_trusted_url` to provider hosts
via suffix allowlist: `.bytepluses.com`, `.byteplus.com`, `.bytedance.com`,
`.bytednsdoc.com`, `.volces.com`, `.byteplusvod.com`,
`.tos-ap-southeast.bytepluses.com`. This fixed policy has no per-call extensions;
`seed_media_persist_url` uses the same allowlist.

`seed_media_persist_url` accepts a caller-supplied URL, so it relies on the
same controls: the URL goes through `copy_from_trusted_url` with this host
allowlist, full SSRF validation and IP pinning, per-hop redirect
re-validation, and the per-media-type size limits. Any host outside the
allowlist is rejected; the tool cannot be used to fetch arbitrary URLs. It
is available only on trusted local stdio.

For generation tasks, provider completion and artifact persistence are separate
outcomes. A completed provider output URL is preserved for the authorized
caller while requested persistence downloads through this SSRF-safe path.
Outputs above the 200 MiB video limit or failing host/MIME/download/storage
checks do not change provider success into provider failure. Seedance reports
`outputs[].persistence="failed"` with `persistence_issue`. An `ArtifactRef`
fallback instead carries `persistence_error` alongside its temporary URL or
inline bytes. These are distinct output shapes, not interchangeable fields.
Full source URLs and credentials are excluded from logs and safe error messages.

## Local output paths

Tools that write to a caller-chosen local path — `output_path`/`output_dir` on
generation and get tools, and
`destination_path` on `seed_media_export_artifact` — share one policy in
`security/output_paths.py`:

- **stdio only.** The client and server must share a filesystem; the fields
  are rejected on HTTP transport.
- **Allowed roots.** The client's MCP roots (`roots/list`, `file://` URIs
  only, 2-second timeout) are used when available; otherwise `OUTPUT_ROOTS`
  (comma-separated absolute directories). With neither, path writing is
  disabled and every such field is rejected. Direct stdio calls retain live
  MCP roots; no worker snapshot or task extension is required.
- **Containment.** The path must be absolute and resolve inside a root. A file
  target cannot be a directory or a root itself.
- **Pre-flight.** Paths are validated before any billable provider call, so a
  rejected path never produces paid output.
- **TOCTOU-safe writes.** Missing parent directories are created one level at
  a time with containment re-checked. The final directory is opened with
  `O_NOFOLLOW`, its real location is re-checked against the roots, and the
  file is published atomically through the directory descriptor. A symlink
  swapped in after validation cannot redirect the write.
- **No silent overwrite.** Publishing is exclusive unless `overwrite=true`; a
  destination that already holds identical bytes (same SHA-256) is a success.

Breaking change for `seed_media_export_artifact`: `destination_path` must now
be absolute and inside an allowed root, and an existing file is no longer
silently overwritten (pass `overwrite=true`).

## URL policy (`security/url_policy.py`)

Exception: `UrlValidationError(ValueError)`.

- **Blocked hostnames (literal):** `169.254.169.254` (AWS metadata),
  `metadata.google.internal` (GCP), `100.100.100.200` (Alibaba),
  `fd00:ec2::254` (AWS IPv6 metadata).
- **Allowed schemes:** `https` always; `http` only when the caller passes
  `allow_http=True`. `file://` is never allowed.
- **No credentials in URLs** (`userinfo` rejected).
- **Hostname** is IDNA-encoded → ASCII → lowercased.
- **Ports:** only `443` (https) and `80` (http) are allowed; any other
  explicit port is rejected. Default is 443 (https) / 80 (http).
- **DNS + IP denial:** `resolve_public_addresses` resolves the hostname
  (or uses a literal IP directly), then denies any address that is not
  globally reachable — `is_private`, `is_loopback`, `is_link_local`,
  `is_multicast`, `is_reserved`, `is_unspecified`, or `not is_global` (which
  additionally covers CGNAT shared space `100.64.0.0/10`). For IPv6, embedded
  IPv4 transition formats (`ipv4_mapped`, `sixtofour`, `teredo[1]`) are
  recursively checked.

`validate_url` combines syntax validation + DNS resolution and returns a
`ValidatedUrl(url, parsed, hostname, port, addresses)`.

## Media policy (`security/media_policy.py`)

Exception: `MediaValidationError(ValueError)`.

`MediaLimits` (returned by `get_media_limits()`, no env override in this
module) cap **provider-bound** media:

| Limit | Default |
|---|---|
| `audio_max_bytes` | 10 MiB |
| `audio_max_seconds` | 30 |
| `image_max_bytes` | 10 MiB |
| `video_max_bytes` | 200 MiB |

Allowed MIME types:

| Category | MIME types |
|---|---|
| Audio | `audio/wav`, `audio/x-wav`, `audio/wave`, `audio/mpeg`, `audio/mp3`, `audio/pcm`, `audio/x-pcm`, `audio/ogg`, `audio/ogg;codecs=opus`, `audio/webm` |
| Image | `image/jpeg`, `image/jpg`, `image/png`, `image/webp` |
| Video | `video/mp4`, `video/quicktime` |

`check_base64_size` estimates decoded size as `(len(stripped) * 3) // 4`
(without full decode); `decode_base64_safely` validates then decodes.
`check_audio_duration_from_base64` decodes WAV (RIFF) headers and enforces
`audio_max_seconds` for Base64 audio references; non-WAV formats (MP3, PCM,
OGG) cannot be measured without a full decoder and are skipped — the
provider enforces the limit server-side for those. This preflight is
best-effort: it trusts the declared `data` chunk size, so a crafted header
with an under-reported size could bypass it. The provider enforces the
30-second limit server-side regardless.

> `MCP_INLINE_MEDIA_MAX_BYTES` (default 8 MiB) lives in `config/env.py`, not
> here. It caps **inline MCP media returned to the client**; the per-type
> `MediaLimits` above cap **provider-bound** media. The two are independent.

## TLS and provider URLs

- `truststore.inject_into_ssl()` runs at module import in `server.py` and
  `__main__.py`, so Python uses the macOS Keychain for TLS verification.
- Provider base URLs (`BYTEPLUS_MODELARK_BASE_URL`,
  `BYTEPLUS_SEED_AUDIO_BASE_URL`) are
  validated at settings load: local overrides require HTTPS with a hostname
  and no embedded credentials; HTTP accepts only the fixed official origins.
- ModelArk uses Bearer authentication; Seed Speech uses
  `X-Api-Key`. Keys are never logged, returned or accepted as tool arguments.
- Prompt, subtitle, media URL, and credential fields are treated as sensitive
  content and redacted from structured logs.

## Failure and Launch Limits

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable.
Mutation 5xx responses are ambiguous and never automatically retried,
even when `retryable=true`. Eligible 429 rejections, demonstrably pre-dispatch
failures and reads can retain bounded retries. Diagnostics retain safe codes/request IDs, never
raw exceptions or echoed secrets. Reconcile accepted work before resubmission.

Owner-first provider admission is bounded to 2 seconds by default (maximum
30); it precedes local stdio budget reservation and pins active/waiting owner entries.
The whole-tool deadline defaults to 600 seconds (maximum 3600), starting at
wrapper entry before credentials and admission. Both settings require
finite positive values. `ADMISSION_TIMEOUT` means this attempt did not dispatch,
not that the entire variation batch did not. `TOOL_DEADLINE_EXCEEDED` preserves
uncertainty and validated accepted IDs. SDK/SQLite draining can exceed the
cooperative deadline. Use client timeout 660 seconds and never blindly
resubmit or assume timeout cancelled upstream work. See
[Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).

See the database-free HTTP contract above; local stdio persistence is unchanged.

## VKE Operations

The chart renders a stateless `Deployment`, HPA (default 2-6 pods, CPU 70%),
`PodDisruptionBudget` with `minAvailable: 1` and hostname topology spread with
`minDomains: 2`. Kubernetes must be >=1.30 and a maintained regional release.
Same-zone nodes are not zone-failure resilience.

Every pod runs FastMCP on `127.0.0.1:3000` and Caddy TLS on 8443. CLB TCP 443 uses
Local traffic policy; Caddy overwrites forwarding headers and Uvicorn does not
rewrite them. Only `/mcp` and `/health` are public. `/ready` is an internal exec
probe. Private metrics remain opt-in on loopback.

Helm references existing identity and TLS Secrets, plus a distinct optional
TOS/enrollment Secret for temporary upload preparation. `STATE_BACKEND=none` and
`DAILY_BUDGET_USD=0`; database inputs are rejected. No PVC, StorageClass, database
CA, PostgreSQL driver or shared state service is required. Bounded scratch uses
emptyDir. Model bindings remain exact and operator-verified.

Verify private API access, CCM, two Ready nodes and surge/draining headroom,
DNS/TLS, source restrictions and HPA metrics API before `prerequisitesConfirmed`.
CSI is not an application prerequisite. Addon readiness and lifecycle remain
administrator-owned outside Terraform/Helm.

Shutdown allows max(tool, provider seconds)+30; pod grace uses+60. CPU HPA is a
starting policy, not a capacity guarantee. Measure live rollout, CLB source-IP,
latency, provider quotas and cost before launch. No paid/live acceptance is
implied by source checks.

There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a fresh stateless deployment. Historical database compatibility and
stateful-release migration tooling are not part of this repository.

## Shared Database Boundary

See the database-free HTTP contract above; local stdio persistence is unchanged.

Task get/list/cancel and Draft lookup are authorized by the supplied provider
key. `X-MCP-Client-Secret` separates per-pod admission scopes, not task access.
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

There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a fresh stateless deployment. Historical database compatibility and
stateful-release migration tooling are not part of this repository.
