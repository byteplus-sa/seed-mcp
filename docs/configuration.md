# Configuration

Configuration is loaded from environment variables or `.env` by Pydantic
Settings. Copy `.env.example` to `.env`. Empty values are ignored.

Provider-key environment variables below apply to **local stdio only**.
HTTP uses live request BYOK headers and registers its 9 provider/discovery
tools (12 with OmniHuman) without operator generation keys. No HTTP fallback
to environment provider keys exists. Keep private configuration outside Git.

`.env` is resolved **relative to the server's working directory**. Most MCP
clients set that correctly from their server configuration, so this is rarely
the problem. When a client cannot, it finds no `.env`, and the server starts
with no provider credentials and registers only the always-on job and artifact
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
| `BYTEPLUS_MODELARK_API_KEY` | empty | Enables Seedream, Seedance, and Seed 2.1 understanding; sent as Bearer auth |
| `BYTEPLUS_SEED_SPEECH_API_KEY` | empty | Enables Seed Audio generation; sent as `X-Api-Key` |
| `BYTEPLUS_CV_API_KEY` | empty | BytePlus Vision AI Bearer key for OmniHuman; tools also need `BYTEPLUS_OMNIHUMAN_ENABLED=true` |
| `BYTEPLUS_MODELARK_BASE_URL` | AP Southeast ModelArk URL | HTTPS data-plane base URL |
| `BYTEPLUS_SEED_AUDIO_BASE_URL` | AP Southeast Seed Speech URL | HTTPS service base URL |
| `SEEDREAM_DEFAULT_MODEL` | `dola-seedream-5-5-261028` | Default image model/endpoint ID (Seedream 5.5; account authorization required) |
| `SEEDREAM_PROMPT_OPTIMIZATION_MODE` | `standard` | Mode 5.0 Pro sends when a caller omits `prompt_optimization`: `standard` (prompt-following quality) or `fast` (lower latency). Both are provider-accepted; an explicit per-call value wins |
| `SEEDANCE_DEFAULT_MODEL` | `dreamina-seedance-2-5-260628` | Default video model/endpoint ID used by `seedance_create_task` when `model` is omitted (Seedance 2.5; was 2.0 before the tool consolidation, see the [upgrade note](#seedance-default-model-upgrade-note)) |
| `SEED_UNDERSTANDING_DEFAULT_MODEL` | `dola-seed-2-1-turbo-260628` | Default understanding model/endpoint ID. Set to `dola-seed-evolving` to use the latest Pro-tier model (auto-resolves to family `pro`, no `SEED_UNDERSTANDING_MODEL_FAMILY` needed) |
| `SEEDREAM_MODEL_FAMILY` | empty | Family for a custom default: `seedream_5_5`, `pro`, `lite`, or `4x` |
| `SEEDANCE_MODEL_FAMILY` | empty | Family for a custom default: `standard`, `fast`, `mini`, `seedance_2_5` (through 4K), or `seedance_2_5_flash` (480p/720p, no Draft) |
| `SEED_UNDERSTANDING_MODEL_FAMILY` | empty | Family for a custom default: `pro` or `turbo` |
| `SEEDREAM_MODEL_BINDINGS` | empty | JSON list of `{model_id, family}` bindings |
| `SEEDANCE_MODEL_BINDINGS` | empty | JSON list of `{model_id, family}` bindings |
| `SEED_UNDERSTANDING_MODEL_BINDINGS` | empty | JSON list of `{model_id, family}` bindings |
| `SEED_AUDIO_UNDERSTANDING_MODEL` | `seed-2-0-lite-260428` | Model/endpoint ID used by `seed_audio_understand`. Any ModelArk model that accepts Chat Completions `input_audio` parts with deep thinking works; change it when a newer audio-capable model ships |
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
binding family. The resource also reports whether background-job local exports
have an absolute `OUTPUT_ROOTS` entry (comma-separated paths). It never reveals
root paths or credentials. These are configuration diagnostics only: they do not
probe provider authorization, check filesystem readiness, or replace the
request's destination preflight. Client MCP roots are unavailable inside jobs.
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

## Transport and authentication

| Variable | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or Streamable `http` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_PORT` | `3000` | HTTP listen port |
| `MCP_ALLOWED_HOSTS` | loopback hosts | Comma-separated accepted Host headers |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated accepted browser Origins |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` (2 MiB) | Positive maximum streamed HTTP request body |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Positive admission bound before body handling, including discovery |
| `READINESS_CHECK_PROVIDERS` | `false` | Local diagnostic setting only; HTTP readiness never probes providers |
| `READINESS_PROVIDER_TIMEOUT_SECONDS` | `2.0` | Per-provider timeout for readiness checks |
| `RATE_LIMIT_RPM` | `60` | Max HTTP requests per minute per client IP; positive required on HTTP |
| `RATE_LIMIT_BURST` | `0` | Token bucket burst size; 0 defaults to `RATE_LIMIT_RPM` |
| `RATE_LIMIT_TRUST_PROXY_HEADERS` | `false` | Trust the first `X-Forwarded-For` entry for rate-limit keys; enable only behind a trusted proxy |
| `MCP_AUTH_MODE` | `byok` | HTTP requires `byok`; explicit `local` is stdio-only; `api_key` removed |
| `MCP_IDENTITY_HMAC_KEY` | empty | Required for HTTP: operator random 32-byte secret encoded as 64 lowercase hex; not a customer credential |
| `MCP_IDENTITY_KEY_VERSION` | `1` | Positive HMAC identity version; changes ownership namespace when changed |

`FASTMCP_TRANSPORT`, `FASTMCP_HOST`, and `FASTMCP_PORT` are accepted as
aliases for the corresponding `MCP_*` transport settings.

Clients send `X-MCP-Client-Secret` (client-generated 32 random bytes as
64 lowercase hex) plus only the selected provider header:
`X-ModelArk-Api-Key`, `X-Seed-Speech-Api-Key`, or `X-OmniHuman-Api-Key`.
Provider operations including dry runs require these; discovery is anonymous.
`Authorization` is rejected. There is no OAuth, signup or server-issued key.
Keep HMAC configuration and client credentials stable for ownership continuity.
Fresh SQLite is required, with no old-schema migration or scope recovery bridge.
See [HTTP client setup](setup/shared-server.md) and [security](security.md).

## Object storage (TOS or S3, optional)

This section is stdio-only. HTTP exposes no upload, presign or artifact tools.

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

| Variable | Default | Purpose |
|---|---|---|
| `ARTIFACT_BACKEND` | `filesystem` | `filesystem` (local disk) or `object_storage` (TOS/S3) |
| `STATE_BACKEND` | `sqlite` | Task ownership/budget/cache backend; only `sqlite` (single instance) is implemented |
| `STATE_MAX_RECORDS` | `100000` | Positive ownership/budget retained-state capacity; exhaustion fails closed |
| `ARTIFACT_DIR` | `~/.seed-mcp/artifacts` | Media, metadata, ownership, and budget state; separate from `ark-mcp` |
| `ARTIFACT_TTL_SECONDS` | `604800` | Artifact retention, in seconds |
| `ARTIFACT_SWEEP_INTERVAL_SECONDS` | `3600` | Interval between background artifact/state expiry sweeps |
| `STATE_PRUNE_MAX_AGE_DAYS` | `30` | Max age for ownership/budget/cache rows before pruning; at least 14 for authenticated HTTP with regular Seedance 2.5 enabled |
| `MCP_INLINE_MEDIA_MAX_BYTES` | `8388608` | Maximum inline MCP media size |
| `ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS` | `120` | Timeout for each attempt to download provider output into artifact storage (filesystem and object-storage backends) |
| `ARTIFACT_DOWNLOAD_MAX_ATTEMPTS` | `3` | Attempts (1-10) for a retryable output download (timeouts, network errors, 408/429/5xx), with 1s, 2s, 4s, ... backoff. Expired, untrusted, or oversized sources are never retried |
| `ARTIFACT_INLINE_FALLBACK_MAX_BYTES` | `8388608` (8 MiB) | When inline Base64 output (Seed Audio, Seedream `b64_json`) cannot be stored, return it inline in `ArtifactRef.fallback_data` up to this decoded size; `0` disables |
| `PROVIDER_MAX_CONCURRENCY` | `5` | Process-wide slots per provider |
| `PRINCIPAL_MAX_CONCURRENCY` | `3` | Slots per credential/client-derived HTTP owner; skipped for local stdio |
| `DAILY_BUDGET_USD` | `0` | Per-owner UTC daily estimate limit; zero records only, not an account-wide spend guarantee |
| `PERSISTENCE_CACHE_MAX_SIZE` | `10000` | Max cached provider task IDs in artifact-resolution cache |
| `PERSISTENCE_CACHE_TTL_SECONDS` | `86400` | TTL for cached task-to-artifact mappings (seconds) |

HTTP servers with any regular
`seedance_2_5` binding (including custom or non-default models) require
`STATE_PRUNE_MAX_AGE_DAYS >= 14` to retain Draft ownership throughout the
promotion window. Shorter values fail at startup; increase existing overrides
or keep the 30-day default. Flash-only, legacy-only, local, and disabled
ModelArk configurations retain the one-day minimum. Increasing retention does
not recover already-pruned ownership rows; missing ownership remains denied.

Seed Audio/Seedream `persist` and OmniHuman get `persist_output` default to
false on every transport. HTTP rejects explicit true and returns temporary
provider URLs; local callers can explicitly opt into persistence.
A local billed output retains fallback delivery when storage fails; see
[Artifacts](artifacts.md#persistence-failures).

The filesystem backend enforces principal and tenant ownership. It is suitable
for one process. Multiple replicas require shared artifact, task-ownership,
budget, cache, and limiter implementations before horizontal scaling is safe.

## Local output paths

| Variable | Default | Purpose |
|---|---|---|
| `OUTPUT_ROOTS` | empty | Comma-separated absolute directories where stdio tools may write files (`output_path`, `output_dir`, `save_to`, `destination_path`) |

The client's MCP roots (`roots/list`) take precedence when the client provides
them; `OUTPUT_ROOTS` is the fallback. With neither, local path writing is
disabled and those fields are rejected. **Background jobs
(`ark_job_submit`) run in a worker with no MCP session and therefore no MCP
roots, so local writes from a job always use `OUTPUT_ROOTS`; set it whenever
jobs should write files.** Path writing is stdio-only. See
[Security](security.md#local-output-paths).

## Timeouts and logging

| Variable | Default | Purpose |
|---|---|---|
| `BYTEPLUS_CONNECT_TIMEOUT_MS` | `10000` | Provider connection timeout |
| `BYTEPLUS_REQUEST_TIMEOUT_MS` | `600000` | Full provider request timeout |
| `SEED_UNDERSTANDING_TIMEOUT_MS` | unset (uses `BYTEPLUS_REQUEST_TIMEOUT_MS`) | Request timeout for `seed_understand` and `seed_audio_understand` chat completions. Deep thinking is always on, so long analyses may need more than the general request timeout |
| `FASTMCP_DOCKET_URL` | `memory://` | FastMCP background-task backend used by generation, upload, provider submission, understanding (including audio transcription), and optional media-persistence calls; Redis can retain task state across restarts of the same single-replica deployment; it does not make SQLite state horizontally scalable |
| `FASTMCP_TASKS_ENCRYPTION_KEY` | unset | Local task snapshot protection only; HTTP has no task backend or snapshots |
| `FASTMCP_DOCKET_CONCURRENCY` | `10` | Maximum active background tasks per worker; provider/principal limits still apply |
| `ARK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

Logs are structured JSON on stderr. Provider credentials and sensitive media
fields are redacted. The default in-memory task backend is process-local; a
server restart discards active and retained task state.


### Background task ownership and recovery

**Local stdio only.** Keep the runtime database with any retained local queue.
HTTP exposes no `ark_job_*`, native task augmentation or task snapshots.
Do not use HTTP as a shared local-job server. See [transports.md](transports.md).

Before a required-task handler starts, it atomically records an execution claim
in the same database. If that MCP task is delivered again, the handler returns
an error without repeating provider work. This favors avoiding duplicate charges
over automatic recovery: after an interrupted submission, reconcile its provider
outcome before creating a new operation. Optional output-retrieval tasks can be
retried because they do not submit paid generation work.

The default local in-memory queue loses task results at process exit. Local
Redis retention does not distribute SQLite or make replicas safe. Restrict
access to retained arguments/results and protect configured snapshot keys.
HTTP retains only minimal scoped state, never customer credentials.
Durable HTTP submission records, idempotency and crash recovery remain next phase.
