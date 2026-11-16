# Environment, transports, and architecture

Use the selected `byteplus-sa/seed-mcp` checkout and its current schemas.
Upstream Ark MCP pages describe retained tools, not this fork's publication,
inventory or hosted contract. No release or public endpoint is assumed.

## Transport and Auth

| Transport | Tools | Credentials and execution |
| --- | --- | --- |
| Local stdio | 21 conditional entries; eight always registered | Private startup provider keys; jobs/native tasks/storage/artifacts retained |
| HTTP BYOK | 9, or 12 with OmniHuman enabled | Selected live provider key plus client secret; direct foreground calls only |

HTTP has no ordinary jobs, native tasks, storage/artifact tools, media resources
or configuration-detail resource. Discovery is anonymous/static and makes no
provider calls. It lists configured bindings without environment provider keys;
`services[].enabled` reports registration, not provider authentication or entitlement.
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
HTTP. `DAILY_BUDGET_USD=0` records estimates only; a positive value is per owner,
not a provider-account ceiling. Provider/principal concurrency defaults to 5/3.

`/health` and `/ready` return minimal process/state readiness and never probe
providers on HTTP. Public `/metrics` is unavailable. `seed-health://status`
is local-only. Hosted provider-secret sync is superseded: no provider keys
belong in the hosted deployment.

## Delivery and Retries

Seed Audio/Seedream `persist` and OmniHuman get `persist_output` default to
false globally. HTTP rejects true; local explicit true remains supported.
Local output paths and stored artifact references are rejected on HTTP.
Clients download expiring provider outputs themselves. Files API cleanup uses
the same live request key; remote temporary-file expiry is distinct from
output URL expiry and local persistence.

Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable with safe diagnostics, including understanding
completions that may already be billed. Chat/mutation 5xx responses are
ambiguous and never automatically retried, even if marked `retryable=true`.
Eligible 429 rejections, demonstrably pre-dispatch failures and reads retain
bounded retries; understanding disables all `TIMEOUT` retries. Never blindly
replay a potentially accepted submission or completion.

## Local Setup

Read the checkout's `docs/setup/install.md`. Use a reviewed locked environment,
private `ARK_MCP_ENV_FILE`, and requested provider keys only. ModelArk enables
image/video/understanding; Seed Speech enables audio; OmniHuman needs its
separate Vision AI key and `BYTEPLUS_OMNIHUMAN_ENABLED=true`.
TOS/S3 storage is optional and stdio-only.

`ark_job_*` uses the local FastMCP worker; `memory://` jobs are process-local.
Local writes inside jobs need `OUTPUT_ROOTS`; explicit persistence does not.
Read [background-job-output.md](background-job-output.md).

## Deployment Limits

Use one instance. PostgreSQL, multi-replica coordination, durable idempotency
and crash recovery remain next phase; no public-launch certification or
exactly-once inference is claimed. Preserve accepted provider IDs for polling.
Exact client/TLS/provider validation requires separate approval.
