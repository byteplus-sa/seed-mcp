# Environment, transports, and architecture

Use the selected `byteplus-sa/seed-mcp` checkout and its current schemas.
The [Seed MCP handbook](https://byteplus-sa.github.io/seed-mcp/) follows its
build revision, not necessarily the connected server. Documentation publication
does not establish a stable release or provide a trusted MCP endpoint.

## Transport and Auth

| Transport | Tools | Credentials and execution |
| --- | --- | --- |
| Local stdio | 13 conditional entries; four always registered | Private startup provider keys; direct calls; storage/artifacts retained |
| HTTP BYOK | 7; opt-in upload adds one | Selected live provider key plus client secret for generation; enrolled secret alone for preparation; direct foreground calls |

HTTP has no ordinary jobs, native tasks, local storage/artifact tools, media resources
or configuration-detail resource. Discovery is anonymous/static and makes no
provider calls. It lists configured bindings without environment provider keys;
`services[].enabled` reports registration, not provider authentication or entitlement.
Default discovery returns `connection=null`. Optional live HTTP
`check_connection=true` checks only ModelArk/client-secret presence and exact
image/video defaults. Omit `kind` for both routes; stdio checks
are rejected. `authentication_verified` and `provider_calls_made` remain false.
See [preflight results](models-and-limits.md#optional-http-preflight).
There is no OAuth, signup or server-issued key; `Authorization` is rejected.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, snapshot capture/save or queue creation, including discovery.

HTTP provider calls, including dry runs, require only the selected header:
`X-ModelArk-Api-Key` or `X-Seed-Speech-Api-Key`, plus
`X-MCP-Client-Secret` (client-generated 32 random bytes as 64 lowercase hex).
Enter them privately through the client's supported mechanism. Never put
credentials in tool arguments, chat, command-line flags, logs or Git.
No HTTP environment-provider fallback exists; keys are not persisted.

Local `BYTEPLUS_SEED_SPEECH_API_KEY` also enables `seed_tts_generate`.
TTS shares `BYTEPLUS_SEED_AUDIO_BASE_URL` and persists its completed stream on
stdio. HTTP returns native audio directly with live Seed Speech/client-secret
headers. No TTS storage flag, TOS credentials, Helm Secret or upload enrollment
is required. Clients must handle up to 40 MiB Base64 plus response metadata.

Optional `media_prepare_upload` uses operator TOS signing configuration with
`MCP_TEMPORARY_UPLOAD_ENABLED=true` and `MCP_UPLOAD_CLIENT_SECRET_SHA256`
(1-1000 unique lowercase SHA-256 digests of exact ASCII client-secret values).
No generation-provider key is needed for preparation. It signs restricted
POST/GET permissions only; no bytes, upload receipt, DB or global quota.
Helm `temporaryUpload.enabled`/`existingSecret` reference a distinct existing
TOS/enrollment Secret. Bucket/IAM/CORS/versioning/lifecycle setup and live
acceptance are separate operator gates. See [media-assets.md](media-assets.md#temporary-http-references).

`TOS_CREDENTIAL_MODE=static` retains configured AK/SK and optional matching STS
token. Explicit `irsa` is HTTP-preparation-only: exact `TOS_IRSA_ROLE_TRN`,
absolute `TOS_IRSA_TOKEN_FILE`, allowlisted BytePlus STS endpoint and session
3600-43200 seconds (default 3600). No static/metadata fallback. Refresh is lazy
after enrollment/admission, single-flight and runtime-memory-only, not a
discovery/readiness probe. Helm `temporaryUpload.credentialsMode=irsa`
requires acknowledged prerequisites and an explicit non-default ServiceAccount;
manual audience `sts.volcengine.com` token projection is app-only, not Caddy.
The existing upload Secret holds bucket/region/endpoint/enrollment, not AK/SK.
Cluster OIDC/IAM trust, least privilege, webhook exclusion and live STS/token
rotation acceptance require separate approved operator setup. Default one-hour
credentials can shorten signed references to an hour or less; refresh never
renews already issued URLs. See `docs/temporary-uploads.md` in the checkout.

The operator supplies `MCP_AUTH_MODE=byok` (default),
`MCP_IDENTITY_HMAC_KEY` (64 lowercase hex) and positive
`MCP_IDENTITY_KEY_VERSION` (default `1`). The HMAC key is operator identity
configuration, not a customer credential. Explicit `local` is stdio-only.

## Identity and Models

The admission tenant derives from the selected key, provider, fixed official
origin and HMAC version; the principal additionally derives from the client
secret. These scopes are ephemeral per-pod limits, not task ownership.
HTTP task access follows the selected provider credential. Clients sharing a
provider key share whatever access the provider permits; use separate provider
credentials when independent authorization is required.

Optional `X-ModelArk-Seedance-Endpoint` and
`X-ModelArk-Seedream-Endpoint` defaults must exactly match registered product
bindings. Explicit tool `model` wins. Never infer arbitrary opaque endpoint
lineage. [Model bindings](models-and-limits.md) remain authoritative.
Unknown endpoint IDs are not echoed; the operator must verify and bind them.
GetEndpoint metadata is AK/SK-only, not ModelArk Bearer-authenticated. This
server does not collect AK/SK or offer arbitrary BYOE self-service.
See `specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority` in the selected checkout.
Request-scoped settings and capability lookup use the receiving server's
configuration, isolated from other server instances' defaults.

| Setting | Fixed HTTP value |
| --- | --- |
| `BYTEPLUS_MODELARK_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `BYTEPLUS_SEED_AUDIO_BASE_URL` | `https://voice.ap-southeast-1.bytepluses.com` |

## Limits and State

HTTP defaults: `RATE_LIMIT_RPM=60`, `MCP_HTTP_MAX_BODY_BYTES=2097152` (2 MiB),
`MCP_HTTP_MAX_IN_FLIGHT=64`; these limits are positive and per pod.
`RATE_LIMIT_BURST=0` inherits RPM. Proxy headers are untrusted by
default. Host/Origin protection and stateless HTTP are enforced on every
HTTP entry path, including direct `http_app()`.

HTTP automatically selects `STATE_BACKEND=none`; explicit database backends
reject startup. There is no durable replay, deduplication or shared budget
accounting. `DAILY_BUDGET_USD` must be zero; use provider-side spend controls.
Local stdio selects SQLite and retains `STATE_MAX_RECORDS=100000` for local
bookkeeping. Rate and concurrency limits reset on restart.

Backend `/health` and `/ready` return minimal process/lifespan status and never
probe storage or providers on HTTP. VKE Caddy exposes only `/mcp` and `/health`.
Public `/metrics` is unavailable. `MCP_METRICS_PORT=0` disables the optional
HTTP-runtime listener; enabled ports 1024-65535 bind only 127.0.0.1.
`seed-health://status`
is local-only. Hosted provider-secret sync is superseded: no provider keys
belong in the hosted deployment.

## Delivery and Retries

Seed Audio/Seedream `persist` default to
false globally. HTTP rejects true; local explicit true remains supported.
Local output paths and stored artifact references are rejected on HTTP.
Clients download expiring provider outputs themselves.

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable with safe diagnostics. Mutation 5xx responses are
ambiguous and never automatically retried, even if marked `retryable=true`.
Eligible 429 rejections, demonstrably pre-dispatch failures and reads retain
bounded retries. Never blindly
replay a potentially accepted submission or completion.

Omit `idempotency_key`; non-null legacy keys are rejected on both transports,
including dry runs. Identical creates may bill again. Retain task/request IDs
and reconcile uncertain creates with the provider instead of repeating them.

## Local Setup

Read the checkout's `docs/setup/install.md`. Use a reviewed locked environment,
private `ARK_MCP_ENV_FILE`, and requested provider keys only. ModelArk enables
image/video; Seed Speech enables audio.
TOS/S3 storage is optional and stdio-only.

Both transports execute directly with no MCP jobs, worker, snapshots or
execution claims. Local writes use live MCP roots or `OUTPUT_ROOTS`;
explicit persistence into the artifact store does not need output roots.
Read [local-output.md](local-output.md).

## Execution Limits

`MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite positive, max 30) bounds total
waiting for owner then provider slots. Active/waiting owners remain pinned;
local stdio budget reservation happens after admission. `ADMISSION_TIMEOUT` is retryable
and nonambiguous for this attempt only, not the whole variation batch.

`MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite positive, max 3600) starts at wrapper
entry after MCP parsing, before credentials and admission. Use
client timeout 660 seconds and compatible proxy settings. SDK/SQLite draining
may exceed the cooperative deadline. `TOOL_DEADLINE_EXCEEDED` preserves
mutation uncertainty and known safe IDs. External cancellation propagates;
timeout does not cancel accepted provider work. Never blindly resubmit.
Poll known IDs or reconcile; local creates have no submission journal.

## Deployment Limits

Dedicated VKE replaces ECS/Compose with stateless Deployment/HPA/PDB/spread,
default 2-6 pods on maintained Kubernetes >=1.30, no state PVC/StorageClass/
headless Service. Same-pod Caddy proxies the backend bound to
`127.0.0.1:3000`; CLB TCP443 reaches Caddy8443 with Local traffic policy.
`RATE_LIMIT_TRUSTED_PROXY_CIDRS` replaces the removed boolean, defaults empty,
and is `127.0.0.1/32` in the chart. Caddy overwrites forwarding headers;
Uvicorn proxy rewriting is disabled. Never trust all proxies.

HTTP/Caddy shutdown uses `max(tool, provider seconds) + 30`; pod grace uses
the maximum plus 60 (default 630/660 seconds). Historical database inspection
and stateful-release migration tooling are not supported.

Terraform uses dedicated fresh VKE state and stores no
HMAC/TLS Secret/kubeconfig. Helm references existing Secrets only. Private
control-plane access requires operator private connectivity.
`scripts/prepare_vke_terraform.py prepare` makes a new private source copy,
refuses existing destinations and leaves regional inputs/fresh-state approval
unset. Its `validate` command runs isolated mock-only Terraform checks with no
inherited credentials or backend initialization. Registry downloads may occur;
no live plan, apply, IAM changes or Helm installation is performed. Live
planning/provisioning requires separate approval; use the operator runbook,
not media generation or client setup, for those operations.
Chart `models.seedream` and `models.seedance` accept `defaultModel` and
`bindings: [{model_id, family}]` with strict families and unique IDs.
Nonempty lists must include their default; alternate defaults need explicit
verified bindings. Used endpoint headers still require exact registry matches;
explicit tool `model` wins. This adds no endpoint-authority verification.
Only explicit env mappings exist, not arbitrary env or secret maps.
`app.dailyBudgetUsd=0` is required; HTTP has no budget ledger;
`app.providerMaxConcurrency=10`, `app.principalMaxConcurrency=10` and
`app.rateLimitBurst=0` retain their defaults. These limits are per pod, not account-wide spend protection.
Provider slots are shared across clients, not reserved per client. Pod resources
and CPU-only HPA are unchanged; validate representative load and maximum-size
TTS memory use before rollout.

`cloud-controller-manager` and addon lifecycle are VKE-admin owned outside
Terraform/Helm. Inspect existing addons; install absent compatible maintained
versions via VKE addon management. Require CCM Running and Ready nodes with capacity before
`prerequisitesConfirmed=true`. This acknowledgement is not readiness proof.
CSI is not a stateless app prerequisite; the chart has no persistent volumes.

Verify two eligible Ready nodes with surge/draining capacity, identity/TLS
Secrets, DNS/TLS and HPA metrics API before deployment.

Source deletion is not cloud decommissioning; infrastructure retirement
requires separate approval. Retain task/request IDs and never automatically
requeue uncertain provider work.
Keep deployment operations out of media generation and client setup.
See `docs/byteplus-terraform.md` and `specs/SPEC_VKE_DEPLOYMENT.md` in the
selected checkout for the complete operator runbook.

`scripts/hosted_acceptance.py --caddy-bin PATH` runs isolated mock-only TLS/load
checks, not deployed-capacity certification. Live VKE routing, scaling, rollout
and actual client/provider acceptance remain separately approved gates.
