# Environment, transports, and architecture

Use the selected `byteplus-sa/seed-mcp` checkout and its current schemas.
Upstream Ark MCP pages describe retained tools, not this fork's publication,
inventory or hosted contract. No release or public endpoint is assumed.

## Transport and Auth

| Transport | Tools | Credentials and execution |
| --- | --- | --- |
| Local stdio | 15 conditional entries; four always registered | Private startup provider keys; direct calls; storage/artifacts retained |
| HTTP BYOK | 7, or 10 with OmniHuman enabled | Selected live provider key plus client secret; direct foreground calls only |

HTTP has no ordinary jobs, native tasks, storage/artifact tools, media resources
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
`X-ModelArk-Api-Key`, `X-Seed-Speech-Api-Key`, or `X-OmniHuman-Api-Key`, plus
`X-MCP-Client-Secret` (client-generated 32 random bytes as 64 lowercase hex).
Enter them privately through the client's supported mechanism. Never put
credentials in tool arguments, chat, command-line flags, logs or Git.
No HTTP environment-provider fallback exists; keys are not persisted.

The operator supplies `MCP_AUTH_MODE=byok` (default),
`MCP_IDENTITY_HMAC_KEY` (64 lowercase hex) and positive
`MCP_IDENTITY_KEY_VERSION` (default `1`). The HMAC key is operator identity
configuration, not a customer credential. Explicit `local` is stdio-only.

## Identity and Models

The credential tenant derives from the selected key, provider, fixed official
origin and HMAC version; the owner additionally derives from the client secret.
Unrelated keys do not change ownership. Keep the same credentials and HMAC
configuration to preserve access across restarts. Changing them changes scope
without migration/recovery. Sharing a provider key still permits direct
upstream access; use separate provider keys/projects for stronger isolation.

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
| `BYTEPLUS_CV_BASE_URL` | `https://openapi.cv.bytepluses.com` |

## Limits and State

HTTP defaults: `RATE_LIMIT_RPM=60`, `MCP_HTTP_MAX_BODY_BYTES=2097152` (2 MiB),
`MCP_HTTP_MAX_IN_FLIGHT=64`, `STATE_MAX_RECORDS=100000`; these limits are
positive. `RATE_LIMIT_BURST=0` inherits RPM. Proxy headers are untrusted by
default. Host/Origin protection and stateless HTTP are enforced on every
HTTP entry path, including direct `http_app()`.

Fresh SQLite ownership uses `(provider, tenant_id, task_id)` with immutable
client owner. Capacity and state errors fail closed. No old-schema migration
exists. Retention defaults to 30 days, at least 14 for regular Seedance 2.5 on
HTTP, but submission claims never auto-prune. `STATE_MAX_RECORDS` caps the
journal: new keys fail at capacity while existing keys remain readable.
Do not erase claims to free space; retain state and matching HMAC configuration.
`DAILY_BUDGET_USD=0` records estimates only; a positive value is per owner,
not a provider-account ceiling. Provider/principal concurrency defaults to 5/3.

Backend `/health` and `/ready` return minimal process/state readiness and never
probe providers on HTTP. VKE Caddy exposes only `/mcp` and `/health`.
Public `/metrics` is unavailable. `MCP_METRICS_PORT=0` disables the optional
HTTP-runtime listener; enabled ports 1024-65535 bind only 127.0.0.1.
`seed-health://status`
is local-only. Hosted provider-secret sync is superseded: no provider keys
belong in the hosted deployment.

## Delivery and Retries

Seed Audio/Seedream `persist` and OmniHuman get `persist_output` default to
false globally. HTTP rejects true; local explicit true remains supported.
Local output paths and stored artifact references are rejected on HTTP.
Clients download expiring provider outputs themselves.

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable with safe diagnostics. Mutation 5xx responses are
ambiguous and never automatically retried, even if marked `retryable=true`.
Eligible 429 rejections, demonstrably pre-dispatch failures and reads retain
bounded retries. Never blindly
replay a potentially accepted submission or completion.

Non-dry HTTP Seedance/OmniHuman creates require `idempotency_key` (16-128 ASCII
letters, digits, `_` or `-`; UUID recommended), one per intended whole call.
The root claim is durable before handler entry; key/input fingerprints use
HMAC, without raw prompts, media, credentials or error messages.
Repeat identical arguments/key only for receipt recovery, not polling.
Only saved complete success replays, with ownership checked before upstream
access including Draft lookup. Failed/partial/cancelled attempts remain
unresolved with known IDs, never automatically resumed. Never change keys to
bypass uncertain acceptance. Seedance dry runs need no key/journal; stdio
rejects supplied keys. Keep original provider/client credentials for recovery.

## Local Setup

Read the checkout's `docs/setup/install.md`. Use a reviewed locked environment,
private `ARK_MCP_ENV_FILE`, and requested provider keys only. ModelArk enables
image/video; Seed Speech enables audio; OmniHuman needs its
separate Vision AI key and `BYTEPLUS_OMNIHUMAN_ENABLED=true`.
TOS/S3 storage is optional and stdio-only.

Both transports execute directly with no MCP jobs, worker, snapshots or
execution claims. Local writes use live MCP roots or `OUTPUT_ROOTS`;
explicit persistence into the artifact store does not need output roots.
Read [local-output.md](local-output.md).

## Execution Limits

`MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite positive, max 30) bounds total
waiting for owner then provider slots. Active/waiting owners remain pinned;
budget reservation happens after admission. `ADMISSION_TIMEOUT` is retryable
and nonambiguous for this attempt only, not the whole variation batch.

`MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite positive, max 3600) starts at wrapper
entry after MCP parsing, before credentials, journal and admission. Use
client timeout 660 seconds and compatible proxy settings. SDK/SQLite draining
may exceed the cooperative deadline. `TOOL_DEADLINE_EXCEEDED` preserves
mutation uncertainty and known safe IDs. External cancellation propagates;
timeout does not cancel accepted provider work. Never blindly resubmit.
Poll known IDs or reconcile; local creates have no submission journal.

## Deployment Limits

Dedicated VKE replaces ECS/Compose. Use one StatefulSet with retained RWO
ext4 EBS and same-pod Caddy, no application HPA. The backend binds
`127.0.0.1:3000`; CLB TCP443 reaches Caddy8443 with Local traffic policy.
`RATE_LIMIT_TRUSTED_PROXY_CIDRS` replaces the removed boolean, defaults empty,
and is `127.0.0.1/32` in the chart. Caddy overwrites forwarding headers;
Uvicorn proxy rewriting is disabled. Never trust all proxies.

HTTP acquires `runtime.sqlite3.lock` before stores/recovery and holds it
until close. Never unlink an active lock or use network-filesystem SQLite.
This is not distributed fencing. HTTP/Caddy shutdown uses max(tool, provider
seconds) + 30; pod grace uses max + 60, default 630/660 seconds.
The read-only aggregate inspector takes `--database`, `--capacity` and
`--timeout-seconds`. It does not repair, reset, restore or requeue state.

Terraform uses separate fresh VKE state, never old ECS state, and stores no
HMAC/TLS Secret/kubeconfig. Helm references existing Secrets only. Private
control-plane access requires operator private connectivity.
Chart `models.seedream` and `models.seedance` accept `defaultModel` and
`bindings: [{model_id, family}]` with strict families and unique IDs.
Nonempty lists must include their default; alternate defaults need explicit
verified bindings. Used endpoint headers still require exact registry matches;
explicit tool `model` wins. This adds no endpoint-authority verification.
Only explicit env mappings exist, not arbitrary env or secret maps.
`app.dailyBudgetUsd=25` overrides the standalone application's zero default;
`app.providerMaxConcurrency=5`, `app.principalMaxConcurrency=3` and
`app.rateLimitBurst=0` retain their defaults. Budgets are per-owner estimates,
not an account-wide spending ceiling.

Both `csi-ebs` and `cloud-controller-manager` are VKE-admin owned outside
Terraform/Helm. Inspect existing addons; install absent compatible maintained
versions via VKE addon management. Require Running addon cards, CSI
driver/controller/node readiness and Ready nodes with capacity before
`prerequisitesConfirmed=true`. This acknowledgement is not readiness proof.

Source deletion is not cloud decommissioning. Retain reviewed old checkouts,
private workspaces, backups and matching HMAC key/version for separately
approved retirement/recovery. No state reset, blind restore or requeue.
Keep deployment operations out of media generation and client setup.
See `docs/byteplus-terraform.md` and `specs/SPEC_VKE_DEPLOYMENT.md` in the
selected checkout for the complete operator runbook.

Synchronous product replay and complete crash recovery
remain deferred. PostgreSQL/Redis are future scaling choices, not initial
requirements; no multi-replica, public-launch certification or exactly-once
inference is claimed. Preserve accepted provider IDs for polling.
See `specs/SPEC_HOSTED_BYOK.md#http-submission-safety` in the selected checkout.
`scripts/hosted_acceptance.py --caddy-bin PATH` performs isolated mocked
TLS/load checks, not capacity certification. Live VKE apply, source-IP, CSI,
rollout and real-client/provider acceptance remain unverified without separate
approval and evidence.
