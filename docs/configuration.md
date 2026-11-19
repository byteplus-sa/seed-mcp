# Configuration

Configuration is loaded from environment variables or `.env` by Pydantic
Settings. For local stdio, copy `.env.example` to a private env file.
Empty values are ignored. Hosted VKE uses [Helm inputs](byteplus-terraform.md#chart-inputs-and-network)
and existing Secret references, not this local provider-key template.

Provider-key environment variables below apply to **local stdio only**.
HTTP uses live request BYOK headers and registers its 7 provider/discovery
tools (10 with OmniHuman) without operator generation keys. No HTTP fallback
to environment provider keys exists. Keep private configuration outside Git.

`.env` is resolved **relative to the server's working directory**. Most MCP
clients set that correctly from their server configuration, so this is rarely
the problem. When a client cannot, it finds no `.env`, and the server starts
with no provider credentials and registers only the always-on discovery and artifact
tools — set `ARK_MCP_ENV_FILE` to an absolute path for that case, or launch the
server with its working directory at the repository root (for example
`uv --directory /path/to/ark-mcp run python -m ark_mcp`). The server logs a
`no_provider_credentials_configured` warning at startup when it happens; if a
client is missing tools and that warning is absent, look at
[troubleshooting](troubleshooting.md) instead.

| Variable | Default | Purpose |
|---|---|---|
| `ARK_MCP_ENV_FILE` | `.env` | Absolute path to the env file, for clients that cannot control the working directory |

## Providers and models

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_MODELARK_API_KEY` | empty | Enables Seedream and Seedance; sent as Bearer auth |
| `BYTEPLUS_SEED_SPEECH_API_KEY` | empty | Enables Seed Audio generation; sent as `X-Api-Key` |
| `BYTEPLUS_CV_API_KEY` | empty | BytePlus Vision AI Bearer key for OmniHuman; tools also need `BYTEPLUS_OMNIHUMAN_ENABLED=true` |
| `BYTEPLUS_MODELARK_BASE_URL` | AP Southeast ModelArk URL | HTTPS data-plane base URL |
| `BYTEPLUS_SEED_AUDIO_BASE_URL` | AP Southeast Seed Speech URL | HTTPS service base URL |
| `SEEDREAM_DEFAULT_MODEL` | `dola-seedream-5-5-261028` | Default image model/endpoint ID (Seedream 5.5; account authorization required) |
| `SEEDREAM_PROMPT_OPTIMIZATION_MODE` | `standard` | Mode 5.0 Pro sends when a caller omits `prompt_optimization`: `standard` (prompt-following quality) or `fast` (lower latency). Both are provider-accepted; an explicit per-call value wins |
| `SEEDANCE_DEFAULT_MODEL` | `dreamina-seedance-2-5-260628` | Default video model/endpoint ID used by `seedance_create_task` when `model` is omitted (Seedance 2.5; was 2.0 before the tool consolidation, see the [upgrade note](#seedance-default-model-upgrade-note)) |
| `SEEDREAM_MODEL_FAMILY` | empty | Family for a custom default: `seedream_5_5`, `pro`, `lite`, or `4x` |
| `SEEDANCE_MODEL_FAMILY` | empty | Family for a custom default: `standard`, `fast`, `mini`, `seedance_2_5` (through 4K), or `seedance_2_5_flash` (480p/720p, no Draft) |
| `SEEDREAM_MODEL_BINDINGS` | empty | JSON list of `{model_id, family}` bindings |
| `SEEDANCE_MODEL_BINDINGS` | empty | JSON list of `{model_id, family}` bindings |
| `BYTEPLUS_OMNIHUMAN_ENABLED` | `false` | Feature flag for OmniHuman 2.0 (`omnihuman_*` tools); requires `BYTEPLUS_CV_API_KEY` |
| `BYTEPLUS_CV_BASE_URL` | `https://openapi.cv.bytepluses.com` | HTTPS Vision AI base URL |
| `BYTEPLUS_OMNIHUMAN_REQ_KEY` | `realman_avatar_picture_omni20_cv` | Service identifier sent as `req_key`; change only if BytePlus issues a new one |

The recognized built-in IDs have known families. A custom ID must be bound
explicitly; the server does not infer capabilities from substrings in an ID.
For example:

```dotenv
SEEDREAM_DEFAULT_MODEL=my-image-endpoint
SEEDREAM_MODEL_BINDINGS=[{"model_id":"my-image-endpoint","family":"pro"}]
```

### Seedream default model upgrade note

The default is now **Seedream 5.5 (`dola-seedream-5-5-261028`)**.
This changes only deployments that omit `SEEDREAM_DEFAULT_MODEL`; existing
explicit defaults stay unchanged. Discovery reflects configured models, not
provider authorization. Accounts without 5.5 access should retain 5.0 Pro:

```dotenv
SEEDREAM_DEFAULT_MODEL=dola-seedream-5-0-pro-260628
```

Both built-in IDs resolve without a family setting. For a custom 5.5 endpoint,
set `SEEDREAM_MODEL_FAMILY=seedream_5_5`. If `SEEDREAM_MODEL_BINDINGS` contains
only older models and no explicit default, startup fails until the default is
set to a bound ID or a 5.5 binding is added. To offer both:

```dotenv
SEEDREAM_DEFAULT_MODEL=dola-seedream-5-5-261028
SEEDREAM_MODEL_BINDINGS=[{"model_id":"dola-seedream-5-5-261028","family":"seedream_5_5"},{"model_id":"dola-seedream-5-0-pro-260628","family":"pro"}]
```

5.5 uses PNG output when omitted and accepts transparent text-to-image.
`SEEDREAM_PROMPT_OPTIMIZATION_MODE` remains specific to 5.0 Pro; explicit
`prompt_optimization="standard"` is accepted on 5.5, while `fast` is rejected
even when the Pro-only operator setting is `fast`. Omitted 5.5 optimization
uses the provider's standard default. Background defaults to `auto` on 5.5.
See [image model limits](models.md#image-capabilities-imagecapabilities).

Read `seed-health://status` to confirm the effective Seedream default model and
binding family. The resource also reports whether local exports
have an absolute `OUTPUT_ROOTS` entry (comma-separated paths). It never reveals
root paths or credentials. These are configuration diagnostics only: they do not
probe provider authorization, check filesystem readiness, or replace the
request's destination preflight. Direct stdio calls can use live client MCP roots.
Seedream dry-run `preview.price_source` is `builtin`: a budgeting estimate,
not an account-specific rate or actual billing.

### Seedance default model upgrade note

**`SEEDANCE_DEFAULT_MODEL` now defaults to Seedance 2.5
(`dreamina-seedance-2-5-260628`) instead of 2.0.** Every Seedance model is
called through the single `seedance_create_task` tool, and the default model
must be one of the bound IDs.

| Your configuration | Result after upgrading |
|---|---|
| No `SEEDANCE_MODEL_BINDINGS`, no `SEEDANCE_DEFAULT_MODEL` | Regular Seedance 2.5 and Flash are bound automatically; regular 2.5 is the default |
| `SEEDANCE_DEFAULT_MODEL` set explicitly, bindings empty | The selected model remains the default; Flash is also bound unless it is the selected default |
| `SEEDANCE_MODEL_BINDINGS` lists only a Seedance 2.0 model and `SEEDANCE_DEFAULT_MODEL` is unset | **Startup fails** with `Seedance default model 'dreamina-seedance-2-5-260628' is missing from its bindings. Set the default model env var to one of the bound IDs: [...]` |

**Fix** for the failing case: set `SEEDANCE_DEFAULT_MODEL` to the bound 2.0 ID
to keep 2.0 as the default, or add a 2.5 binding to use the new default:

```dotenv
# Keep Seedance 2.0 as the default
SEEDANCE_DEFAULT_MODEL=dreamina-seedance-2-0-260128
SEEDANCE_MODEL_BINDINGS=[{"model_id":"dreamina-seedance-2-0-260128","family":"standard"}]

# Or bind both and default to 2.5
SEEDANCE_MODEL_BINDINGS=[{"model_id":"dreamina-seedance-2-0-260128","family":"standard"},{"model_id":"dreamina-seedance-2-5-260628","family":"seedance_2_5"}]
```

Callers then choose a model per request with `model`, taking an exact ID from
`ark_list_models(kind='video')`.

### Seedance 2.5 4K

All resolutions use `dreamina-seedance-2-5-260628` and family `seedance_2_5`.
Select `resolution="4k"` on `seedance_create_task`; no extra feature flag,
model binding, or tool is needed.

The separate Premium model, family, service entry, and configuration settings
have been removed without a compatibility layer. Remove
`BYTEPLUS_MODELARK_SEEDANCE_2_5_PREMIUM_ENABLED` and `SEEDANCE_2_5_PREMIUM_MODEL`
from configuration and replace any `seedance_2_5_premium` binding with the
current 2.5 model and family. There is no automatic alias or rerouting of old
model IDs.

Draft previews remain 480p and Draft-to-final rendering remains 1080p;
4K currently applies to ordinary generation, not Draft promotion. Static
video cost previews do not account for resolution or duration.

### Seedance 2.5 Flash

Flash uses `dreamina-seedance-2-5-flash-261115`, family `seedance_2_5_flash`,
through the same `seedance_create_task` tool, ModelArk key, host, and task
lifecycle. It supports 480p/720p, 4-30 seconds, 10 image / 5 video / 5 audio
references, audio-only input, reference/edit/extend task types, and MP4/MOV.
It does not support 1080p, 4K, `draft`, or `draft_task_id`.

With empty bindings, Flash is added alongside the selected default. Regular
2.5 remains the default for omitted `model`. A non-empty
`SEEDANCE_MODEL_BINDINGS` remains authoritative; add Flash explicitly there:

```dotenv
SEEDANCE_MODEL_BINDINGS=[{"model_id":"dreamina-seedance-2-5-260628","family":"seedance_2_5"},{"model_id":"dreamina-seedance-2-5-flash-261115","family":"seedance_2_5_flash"}]
```

To use a custom Flash endpoint, bind its ID to `seedance_2_5_flash`. Listing
the model does not prove provider activation or account entitlement. No new
feature flag is required. Flash cost previews currently reuse the static
2.5 per-task fallback, not its token-based provider price.

On stdio, missing startup keys omit their tools. On HTTP, only the OmniHuman
enable flag affects provider-tool registration; keys are checked at invocation.
HTTP fixes provider origins to `https://ark.ap-southeast.bytepluses.com/api/v3`,
`https://voice.ap-southeast-1.bytepluses.com` and
`https://openapi.cv.bytepluses.com`. Userinfo, query/fragment, path-confused or
nonofficial origins are rejected. Local overrides require credential-free HTTPS.

Optional HTTP `X-ModelArk-Seedance-Endpoint` and
`X-ModelArk-Seedream-Endpoint` defaults must exactly match a registered binding
for the product. An explicit tool `model` wins. No arbitrary opaque `ep-*`
lineage inference or caller-selected base URL is supported.
The operator must verify an endpoint's model/version before binding it; unknown
endpoint IDs are not echoed by diagnostics. GetEndpoint metadata requires
AK/SK signing, which this server does not accept or hold. See the
[BYOE authority contract](../specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority).

Default discovery remains static/anonymous with `connection=null`. Opt-in
`ark_list_models` input `check_connection=true` is live HTTP only and checks
ModelArk/client-secret header presence plus exact image/video defaults, not
authentication, lineage or entitlement. See the
[preflight check table](setup/shared-server.md#optional-imagevideo-configuration-check)
and [stdout client generator](setup/shared-server.md#generate-a-client-snippet).
The generator's `*-env` options are client variable names, not server settings
or credential values.

## Transport and authentication

| Variable | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or Streamable `http` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_PORT` | `3000` | HTTP listen port |
| `MCP_METRICS_PORT` | `0` | HTTP-runtime-only private metrics listener; 0 disables, otherwise 1024-65535; always binds 127.0.0.1 |
| `MCP_ALLOWED_HOSTS` | loopback hosts | Comma-separated accepted Host headers |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated accepted browser Origins |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` (2 MiB) | Positive maximum streamed HTTP request body |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Positive per-pod admission bound before body handling, including discovery |
| `READINESS_CHECK_PROVIDERS` | `false` | Local diagnostic setting only; HTTP readiness never probes providers |
| `READINESS_PROVIDER_TIMEOUT_SECONDS` | `2.0` | Per-provider timeout for readiness checks |
| `RATE_LIMIT_RPM` | `60` | Max HTTP requests per minute per client IP per pod; positive required on HTTP |
| `RATE_LIMIT_BURST` | `0` | Token bucket burst size; 0 defaults to `RATE_LIMIT_RPM` |
| `RATE_LIMIT_TRUSTED_PROXY_CIDRS` | empty | Comma-separated canonical IPv4/IPv6 networks; trust forwarded addresses only from an immediate peer in these networks; catch-all networks rejected |
| `MCP_AUTH_MODE` | `byok` | HTTP requires `byok`; explicit `local` is stdio-only; `api_key` removed |
| `MCP_IDENTITY_HMAC_KEY` | empty | Required for HTTP: operator random 32-byte secret encoded as 64 lowercase hex; not a customer credential |
| `MCP_IDENTITY_KEY_VERSION` | `1` | Positive HMAC version for ephemeral admission scopes, not task authorization |

`FASTMCP_TRANSPORT`, `FASTMCP_HOST`, and `FASTMCP_PORT` are accepted as
aliases for the corresponding `MCP_*` transport settings.

`RATE_LIMIT_TRUST_PROXY_HEADERS` is removed without a compatibility alias.
Forwarded chains are size/hop bounded and validated, then traversed
right-to-left through trusted hops to the first untrusted address. Untrusted
peers cannot supply a rate-limit identity. Malformed/duplicate trusted chains
fail with fixed text, without header echo. The entrypoint disables Uvicorn
proxy rewriting so middleware receives the actual socket peer.

VKE uses `MCP_HOST=127.0.0.1`, `MCP_PORT=3000` and
`RATE_LIMIT_TRUSTED_PROXY_CIDRS=127.0.0.1/32`, with Caddy in the same pod.
Only the CLB TCP 443 route to Caddy 8443 is public. `app.metricsEnabled=true`
in Helm selects private port 9000; default false leaves it disabled.
Never expose metrics through a Service or trust all networks.

Helm exposes `models.seedream` and `models.seedance` with `defaultModel` and
`bindings` (`{model_id, family}` entries), not an arbitrary environment map.
Nonempty lists must include the default; alternate defaults require explicit
verified bindings. Header overrides still require exact registry matches.
See [model and runtime chart values](byteplus-terraform.md#model-and-runtime-values).
Helm requires `app.dailyBudgetUsd=0`. HTTP has no budget ledger.
`app.providerMaxConcurrency=5`, `app.principalMaxConcurrency=3` and
`app.rateLimitBurst=0` map to per-pod limits.

Clients send `X-MCP-Client-Secret` (client-generated 32 random bytes as
64 lowercase hex) plus only the selected provider header:
`X-ModelArk-Api-Key`, `X-Seed-Speech-Api-Key`, or `X-OmniHuman-Api-Key`.
Provider operations including dry runs require these; discovery is anonymous.
`Authorization` is rejected. There is no OAuth, signup or server-issued key.
The client secret must differ from every supplied provider key; equality
returns HTTP 400 `CREDENTIAL_REUSE` before tool execution. Use a separate
private environment variable and independently generated value for the client
secret. Keep provider keys unchanged when correcting this error.
The provider key authorizes tasks; the client secret scopes admission only.
See [HTTP client setup](setup/shared-server.md) and [security](security.md).

## Object storage (TOS or S3, optional)

The local upload/presign workflows below are stdio-only. HTTP exposes no local
upload, presign renewal or artifact tools. Optional HTTP preparation uses the
TOS signer configuration but not local state.

### Temporary HTTP Upload Preparation

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_TEMPORARY_UPLOAD_ENABLED` | `false` | HTTP-only restricted TOS POST/GET preparation |
| `MCP_UPLOAD_CLIENT_SECRET_SHA256` | empty | Operator enrollment: 1-1000 distinct lowercase SHA-256 digests of exact ASCII client-secret values, comma-separated without whitespace |
| `TOS_CREDENTIAL_MODE` | `static` | Configured AK/SK, or explicit `irsa` for HTTP preparation only; no ambient fallback |
| `TOS_IRSA_ROLE_TRN` | empty | IRSA only: exact `trn:iam::<account>:role/<role>` without wildcards |
| `TOS_IRSA_TOKEN_FILE` | empty | IRSA only: absolute projected OIDC token file path, reread at refresh |
| `TOS_IRSA_STS_ENDPOINT` | `https://sts.byteplusapi.com` | Allowed alternative `https://open.byteplusapi.com`; no other origin/path |
| `TOS_IRSA_DURATION_SECONDS` | `3600` | Requested STS session duration in seconds, 3600-43200; can shorten signed URL validity |

Enabling requires `OBJECT_STORAGE_BACKEND=tos`, complete TOS signing credentials,
valid bucket/region and the exact official `tos-{TOS_REGION}.bytepluses.com`
endpoint (optional HTTPS scheme, no port/path). Lifetimes are fixed at
900-second POST, 86400-second GET and one-day scheduled object expiry;
`TOS_PRESIGN_TTL_SECONDS` does not override them. No generation-provider key
is required to prepare. IRSA rejects configured static AK/SK/session tokens and
requires explicit role/token configuration plus separately approved cluster/
IAM prerequisites. Credentials refresh lazily in runtime memory, not at startup
or readiness. Nominal expiry timestamps do not guarantee 24-hour availability:
one-hour default STS credentials can shorten URLs to an hour or less, and refresh
does not renew issued URLs. Local stdio storage remains static-only.
See [operator prerequisites and client upload flow](temporary-uploads.md)
and [VKE IRSA setup](temporary-uploads.md#vke-iam-roles-for-service-accounts).

The `media_upload` and `media_presign` tools are registered when the selected
object-storage backend is configured. `media_upload` uploads 1-50 files to a
**private** bucket and returns a presigned HTTPS GET URL per file;
`media_presign` generates fresh presigned URLs for 1-100 existing objects
without re-uploading.
Use `OBJECT_STORAGE_BACKEND` to select `tos` (default) or `s3`.

| Variable | Default | Purpose |
|---|---|---|
| `MEDIA_UPLOAD_BATCH_MAX_BYTES` | `524288000` (500 MiB) | Maximum total decoded bytes in one `media_upload` call (all items); checked before any upload starts, and an oversized call fails as a whole |

### TOS backend

| Variable | Default | Purpose |
|---|---|---|
| `TOS_ACCESS_KEY` | empty | TOS access key (AK) |
| `TOS_SECRET_KEY` | empty | TOS secret key (SK) |
| `TOS_SECURITY_TOKEN` | empty | Optional temporary security token |
| `TOS_BUCKET` | empty | Target bucket name |
| `TOS_REGION` | `ap-southeast-1` | TOS region |
| `TOS_ENDPOINT` | `tos-ap-southeast-1.bytepluses.com` | TOS API endpoint |
| `TOS_PRESIGN_TTL_SECONDS` | `1800` | Presigned URL validity in seconds (60–604800) |

### S3 backend

| Variable | Default | Purpose |
|---|---|---|
| `S3_ACCESS_KEY` | empty | S3 access key ID |
| `S3_SECRET_KEY` | empty | S3 secret access key |
| `S3_BUCKET` | empty | Target bucket name |
| `S3_REGION` | `us-east-1` | AWS region |
| `S3_ENDPOINT` | empty | Custom endpoint for S3-compatible storage (MinIO, R2) |
| `S3_PRESIGN_TTL_SECONDS` | `1800` | Presigned URL validity in seconds (60–604800) |
| `OBJECT_STORAGE_BACKEND` | `tos` | Select active backend: `tos` or `s3` |

AK and SK must both be set or both be empty. The bucket must remain private;
presigned URLs grant temporary read access to individual objects. When
`S3_ENDPOINT` is set, path-style addressing is used automatically for
S3-compatible storage.

## Persistence and runtime policy

Artifact, cache and pruning settings below are local stdio only. HTTP uses
no persistence; provider/principal concurrency remains per pod.

| Variable | Default | Purpose |
|---|---|---|
| `STATE_BACKEND` | transport-selected | `none` for HTTP, `sqlite` for stdio; incompatible explicit values reject startup |
| `STATE_MAX_RECORDS` | `100000` | Positive local ownership/budget record capacity; unused on HTTP |
| `ARTIFACT_BACKEND` | `filesystem` | `filesystem` (local disk) or `object_storage` (TOS/S3) |
| `ARTIFACT_DIR` | `~/.seed-mcp/artifacts` | Media, metadata, ownership, and budget state; separate from `ark-mcp` |
| `ARTIFACT_TTL_SECONDS` | `604800` | Artifact retention, in seconds |
| `ARTIFACT_SWEEP_INTERVAL_SECONDS` | `3600` | Interval between background artifact/state expiry sweeps |
| `STATE_PRUNE_MAX_AGE_DAYS` | `30` | Max age for local ownership/budget/cache rows before pruning; minimum 1 day; no HTTP sweep |
| `MCP_INLINE_MEDIA_MAX_BYTES` | `8388608` | Maximum inline MCP media size |
| `ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS` | `120` | Timeout for each attempt to download provider output into artifact storage (filesystem and object-storage backends) |
| `ARTIFACT_DOWNLOAD_MAX_ATTEMPTS` | `3` | Attempts (1-10) for a retryable output download (timeouts, network errors, 408/429/5xx), with 1s, 2s, 4s, ... backoff. Expired, untrusted, or oversized sources are never retried |
| `ARTIFACT_INLINE_FALLBACK_MAX_BYTES` | `8388608` (8 MiB) | When inline Base64 output (Seed Audio, Seedream `b64_json`) cannot be stored, return it inline in `ArtifactRef.fallback_data` up to this decoded size; `0` disables |
| `PROVIDER_MAX_CONCURRENCY` | `5` | Process-wide slots per provider |
| `PRINCIPAL_MAX_CONCURRENCY` | `3` | Per-pod slots per credential/client-derived HTTP owner; skipped for local stdio |
| `DAILY_BUDGET_USD` | `0` | Local UTC daily estimate limit; zero records only on stdio. HTTP requires zero and performs no accounting. Not an account-wide spend guarantee |
| `PERSISTENCE_CACHE_MAX_SIZE` | `10000` | Max cached provider task IDs in artifact-resolution cache |
| `PERSISTENCE_CACHE_TTL_SECONDS` | `86400` | TTL for cached task-to-artifact mappings (seconds) |

HTTP keeps no Draft ownership records and has no state-retention requirement.
Draft eligibility still follows the model/provider creation window.

Seed Audio/Seedream `persist` and OmniHuman get `persist_output` default to
false on every transport. HTTP rejects explicit true and returns temporary
provider URLs; local callers can explicitly opt into persistence.
A local billed output retains fallback delivery when storage fails; see
[Artifacts](artifacts.md#persistence-failures).

The local filesystem backend enforces artifact ownership and is suitable for
one process. Do not use it as shared storage for HTTP replicas.

### PostgreSQL HTTP Settings

Removed. There are no PostgreSQL settings, migrations or operator commands
for the initial hosted phase. HTTP never opens SQLite, PostgreSQL or Redis.
Use `STATE_BACKEND=none` or leave it unset for HTTP.

## Local output paths

| Variable | Default | Purpose |
|---|---|---|
| `OUTPUT_ROOTS` | empty | Comma-separated absolute directories where stdio tools may write files (`output_path`, `output_dir`, `destination_path`) |

The client's MCP roots (`roots/list`) take precedence when the client provides
them; `OUTPUT_ROOTS` is the fallback. With neither, local path writing is
disabled and those fields are rejected. Direct stdio calls retain live MCP
context; no task augmentation is required. Path writing is stdio-only. See
[Security](security.md#local-output-paths).

## Timeouts and logging

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_CONNECT_TIMEOUT_MS` | `10000` | Provider connection timeout |
| `BYTEPLUS_REQUEST_TIMEOUT_MS` | `600000` | Full provider request timeout |
| `MCP_ADMISSION_TIMEOUT_SECONDS` | `2.0` | Finite positive seconds, at most 30; combined wait for owner then provider slots |
| `MCP_TOOL_TIMEOUT_SECONDS` | `600.0` | Finite positive seconds, at most 3600; cooperative whole-tool deadline from wrapper entry |
| `ARK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

Logs are structured JSON on stderr. Provider credentials and sensitive media
fields are redacted.

Both transports call tools directly. The deadline starts after MCP input
parsing and before credential/binding checks, admission and execution.
Local stdio reserves budget after owner-first provider admission. `ADMISSION_TIMEOUT`
means this attempt did not dispatch; other variations may already be accepted.
`TOOL_DEADLINE_EXCEEDED` retains uncertainty and known safe task/request IDs.
External cancellation propagates. Neither timeout nor disconnect guarantees
provider cancellation.

Use a **660-second client timeout** with the default tool deadline: Codex
`tool_timeout_sec=660`, Claude Code `timeout=660000` milliseconds, Python
`Client(..., timeout=660)`. Configure compatible proxy timeouts too.
SQLite/SDK cancellation cleanup may exceed the nominal deadline, so these
allowances are not hard wall-clock guarantees. See
[Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).

HTTP entrypoint and Caddy shutdown grace is
`max(MCP_TOOL_TIMEOUT_SECONDS, BYTEPLUS_REQUEST_TIMEOUT_MS / 1000) + 30`
seconds. Pod termination grace uses the same maximum plus 60 (defaults
630/660 seconds). Align custom process supervisors with these allowances.

### Provider task ownership and recovery

There are no MCP jobs, native tasks, snapshots or execution claims.

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
