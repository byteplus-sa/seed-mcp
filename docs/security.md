# Security

This document consolidates the server's security model. See
[configuration.md](configuration.md) for the full env-var reference,
[transports.md](transports.md) for transport setup, and
[deployment.md](deployment.md) for remote-deployment hardening.

## Dependency Security

Use `uv sync --locked` to install the reviewed dependency set. FastMCP is
bounded to `fastmcp[tasks]>=4.1.8,<4.2`; older 4.0.x environments do not contain
the current upstream security fixes. The framework, task extension and MCP SDK
must be upgraded together through the lockfile rather than independently.

On 2026-11-10, `bash scripts/audit_dependencies.sh` reported no known
vulnerabilities for the refreshed lockfile. This is a point-in-time result,
not a guarantee against future disclosures. CI and the commit hook run this
audit without vulnerability exemptions.

Upstream release details:
[FastMCP 4.1.8](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.1.8).
Stage upgrades separately, finish active jobs before restarting, and preserve
runtime state, artifact storage and any task-snapshot encryption key.

## HTTP BYOK Boundary

`AuthMode` accepts `byok` (default) and explicit stdio-only `local`.
The former `api_key` mode is removed. All HTTP, including loopback, requires
BYOK and the operator's `MCP_IDENTITY_HMAC_KEY` (64 lowercase hex from 32
random bytes), with positive `MCP_IDENTITY_KEY_VERSION` (default `1`).
This key derives identity; it is not a customer credential.

There is no OAuth, signup, server-issued key or bearer-token passthrough.
`Authorization` is rejected with safe guidance. Clients send
`X-MCP-Client-Secret` and the selected `X-ModelArk-Api-Key`,
`X-Seed-Speech-Api-Key`, or `X-OmniHuman-Api-Key`. The client secret must be
client-generated 32 random bytes encoded as 64 lowercase hex.
Only the selected provider key is required, including on dry runs.

Raw ASGI header validation rejects duplicate, empty, non-ASCII, whitespace,
control and oversized values without echoing them. Keys are opaque printable
ASCII of at most 4096 characters. Live credentials are never restored from
task snapshots, persisted in SQLite/artifacts/cache keys, or put in tool inputs.
Request and provider contexts are released on completion/cancellation.
Gateways receive explicit keys and never fall back to environment provider
credentials for HTTP.

## Principal and Tenant

Domain-separated HMAC derives the credential tenant from identity version,
provider, fixed official origin and exact provider key; the client secret
then derives the owner. Unrelated keys do not alter ownership. Same key plus
different client secret means a different owner. This is credential possession,
not verified human or organization identity.

Fresh SQLite ownership uses `(provider, tenant_id, task_id)` as primary key
and stores an immutable `principal_id`. Reads/claims/lists use that namespace;
conflicts cannot transfer ownership. Missing records, database errors or
capacity exhaustion fail closed before upstream access when known.
Post-acceptance recording failure is ambiguous, never an automatic replay.

Keep HMAC configuration and credentials stable to preserve scope across
restarts. Changing a provider key, client secret, HMAC key or version changes
scope; no compatibility migration or recovery bridge exists. Sharing a
provider key still permits direct upstream access outside this boundary.
Use separate provider keys/projects for stronger separation.

## Scope Taxonomy

Catalog scope strings remain capability metadata, not customer-selected roles,
OAuth grants or a common team identity. HTTP admission enforces the selected
provider key and client owner. Local stdio trusts its local principal.

All 12 scope strings in the catalog are retained below as metadata, not auth
grants. A label does not register a tool or grant access to provider accounts.

| Catalog scope metadata | Tools |
| --- | --- |
| `artifacts:read` | `seed_media_get_artifact`, `seed_media_export_artifact` (stdio only) |
| `media:upload` | `media_upload`, `seed_media_persist_url` (stdio only) |
| `media:presign` | `media_presign` (stdio only) |
| `seed:audio:generate` | `seed_audio_generate` |
| `seedream:generate` | `seedream_generate_image` |
| `seedance:create` | `seedance_create_task` |
| `gen:read` | `gen_task_get`, `gen_task_list` |
| `gen:delete` | `gen_task_cancel_or_delete` |
| `understanding:read` | `seed_understand`, `seed_audio_understand` |
| `omnihuman:create` | `omnihuman_create_task` |
| `omnihuman:read` | `omnihuman_get_task` |
| `omnihuman:cancel` | `omnihuman_cancel_task` |

HTTP exposes 9 provider/discovery tools, or 12 with OmniHuman enabled, without
requiring operator provider keys. Anonymous `ark_list_models` lists configured
model bindings even without an environment provider key. `services[].enabled`
describes registration, not customer entitlement or key validity. Jobs, native tasks, storage/artifact tools and all MCP
resources are absent on HTTP. They remain local stdio capabilities within the
21-entry catalog. No asset administration exists on either transport.

## HTTP Admission and Routing

`HardenedFastMCP.http_app()` enforces stateless HTTP, Host/Origin protection
and live credentials on every entry path; stdio-configured HTTP construction
is rejected. Set `MCP_ALLOWED_HOSTS` explicitly for ingress and allow browser
Origins only where needed. Proxy headers are not trusted by default.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, task-snapshot capture/save or queue creation, including
on discovery. Omit the opt-in and call HTTP tools directly.

| Setting | Default | Rule |
| --- | --- | --- |
| `RATE_LIMIT_RPM` | `60` | Positive per-IP limit with bounded map cardinality |
| `RATE_LIMIT_BURST` | `0` | Uses RPM when zero |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` (2 MiB) | Positive streamed body cap |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Positive global admission limit before body handling, including discovery |
| `STATE_MAX_RECORDS` | `100000` | Positive state bound; never evict live owners to admit work |

`/health` and `/ready` are anonymous minimal process/state probes; HTTP
readiness never contacts providers. `/metrics` is unavailable on HTTP.
`seed-health://status` and artifact resources are stdio-only.

Provider origins are fixed to official ModelArk, Seed Speech and Vision AI
URLs listed in [configuration](configuration.md). No arbitrary hosts,
userinfo, query/fragment or path-confused base URLs are accepted.
Endpoint headers select exact registry bindings only; explicit tool `model`
wins and arbitrary opaque `ep-*` lineage is not inferred.

HTTP rejects `persist=true`, `persist_output=true`, local paths and stored
artifact references before dispatch. Seed Audio/Seedream/OmniHuman get
persistence defaults are false globally. Clients retrieve expiring outputs.
Files API temporary uploads are cleaned up using the same request key;
remote file expiry is distinct from output URL expiry/local persistence.

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

`FilesystemArtifactStore` restricts `copy_from_trusted_url` to provider hosts
via suffix allowlist: `.bytepluses.com`, `.byteplus.com`, `.bytedance.com`,
`.bytednsdoc.com`, `.volces.com`, `.byteplusvod.com`,
`.tos-ap-southeast.bytepluses.com`. A caller may extend the list for one download
only: `omnihuman_get_task` additionally trusts `.tiktokcdn.com`, where OmniHuman
output videos are served, so `seed_media_persist_url` still
reject that host.

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
`outputs[].persistence="failed"` with `persistence_issue`; OmniHuman reports
top-level `persistence="failed"` with `persistence_issue`. An `ArtifactRef`
fallback instead carries `persistence_error` alongside its temporary URL or
inline bytes. These are distinct output shapes, not interchangeable fields.
Full source URLs and credentials are excluded from logs and safe error messages.

## Local output paths

Tools that write to a caller-chosen local path — `output_path`/`output_dir` on
generation and get tools, `save_to` on `seed_understand` and
`seed_audio_understand`, and
`destination_path` on `seed_media_export_artifact` — share one policy in
`security/output_paths.py`:

- **stdio only.** The client and server must share a filesystem; the fields
  are rejected on HTTP transport.
- **Allowed roots.** The client's MCP roots (`roots/list`, `file://` URIs
  only, 2-second timeout) are used when available; otherwise `OUTPUT_ROOTS`
  (comma-separated absolute directories). With neither, path writing is
  disabled and every such field is rejected. A background worker has no MCP
  session and so no MCP roots: local writes inside `ark_job_submit` are
  checked against `OUTPUT_ROOTS` only.
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
  `BYTEPLUS_SEED_AUDIO_BASE_URL`, `BYTEPLUS_CV_BASE_URL`) are
  validated at settings load: local overrides require HTTPS with a hostname
  and no embedded credentials; HTTP accepts only the fixed official origins.
- ModelArk and Vision AI use separate Bearer keys; Seed Speech uses
  `X-Api-Key`. Keys are never logged, returned or accepted as tool arguments.
- Prompt, subtitle, media URL, and credential fields are treated as sensitive
  content and redacted from structured logs.

## Failure and Launch Limits

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable, including billable understanding completions.
Mutation 5xx responses are ambiguous and never automatically retried,
even when `retryable=true`. Eligible 429 rejections, demonstrably pre-dispatch
failures and reads can retain bounded retries; understanding disables all
automatic `TIMEOUT` retries. Diagnostics retain safe codes/request IDs, never
raw exceptions or echoed secrets. Reconcile accepted work before resubmission.

Single-instance SQLite is the only state backend. PostgreSQL, multi-replica
coordination, durable idempotency and crash recovery are next phase.
No exactly-once inference or public-launch readiness is claimed.
See [SPEC_HOSTED_BYOK.md](../specs/SPEC_HOSTED_BYOK.md).
