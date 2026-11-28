# Transports

The default transport is local stdio. Streamable HTTP is a separate
BYOK surface, including on loopback.

| Transport | Tools | Execution |
| --- | --- | --- |
| stdio | 13 catalog tools, conditional on local credentials/flags; four always available | Direct calls; storage and artifacts retained |
| HTTP | 8 baseline; temporary upload optionally adds one | Direct foreground calls; no jobs, native tasks, local storage/artifact tools or resources |

## stdio

The client starts a subprocess with `MCP_TRANSPORT=stdio`. Provider credentials
come from private local configuration referenced by `ARK_MCP_ENV_FILE`.
`MCP_AUTH_MODE=local` remains an explicit stdio-only choice; the default
`byok` setting does not require an HMAC key for stdio.

```bash
uv run --locked --no-sync python -m ark_mcp
```

Call the original tool directly, without native task opt-in. Local SQLite
supports storage/artifacts and bookkeeping, not saved-response replay.
Seedance calls must omit the unsupported legacy `idempotency_key`.
Seed TTS 3 always persists its completed audio stream on stdio. HTTP returns
native MCP audio directly without storage. See [Seed TTS](seed-tts.md).

## Streamable HTTP

HTTP requires `MCP_AUTH_MODE=byok` (default) and the operator's private
`MCP_IDENTITY_HMAC_KEY`: 32 random bytes encoded as 64 lowercase hex.
`MCP_IDENTITY_KEY_VERSION` defaults to `1`. Neither is a customer credential.
Local-auth HTTP and the former shared-key auth mode are not supported.

After securely loading operator configuration, launch an isolated loopback
server with no database and no hosted budget ledger:

```bash
STATE_BACKEND=none DAILY_BUDGET_USD=0 MCP_TRANSPORT=http MCP_HOST=127.0.0.1 \
  uv run --locked --no-sync python -m ark_mcp
```

For non-loopback access use trusted TLS ingress and explicit
`MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS`. Stateless HTTP and Host/Origin
protection are enforced by `HardenedFastMCP.http_app()` and the normal CLI.
Building an HTTP app from stdio-configured settings is rejected.

Clients supply `X-MCP-Client-Secret` and only the selected provider header:
`X-ModelArk-Api-Key` or `X-Seed-Speech-Api-Key`.
The client secret is client-generated 32 random bytes as 64 lowercase hex.
`Authorization` is rejected. There is no OAuth, signup or server-issued key.
[Client setup](setup/shared-server.md) includes private entry and examples.

Discovery is anonymous/static and lists configured bindings without environment
provider keys; `services[].enabled` reports registration, not entitlement.
Provider calls, including dry runs, need live
headers on every request. No server provider-key fallback exists. Model
endpoint defaults are exact registered IDs; explicit tool `model` wins.
Default discovery returns `connection=null`. Opt-in `check_connection=true`
requires live HTTP and checks only ModelArk/client-secret header presence and
exact image/video defaults. It does not authenticate, query endpoint lineage
or verify entitlement. Unknown IDs are not echoed; the operator must verify
and bind them. See the [configuration check](setup/shared-server.md#optional-imagevideo-configuration-check).
Use client timeout 660 seconds with the default 600-second cooperative tool
deadline and compatible proxy settings on both transports. SDK/SQLite cleanup
may exceed the nominal deadline. Owner-first provider admission defaults to
2 seconds (max 30); the tool deadline max is 3600 seconds. Both settings
require finite positive values. Local stdio reserves budget after admission;
HTTP has no budget ledger.
`ADMISSION_TIMEOUT` means this attempt did not dispatch, not the whole batch.
`TOOL_DEADLINE_EXCEEDED` preserves uncertainty and safe accepted IDs; never
blindly resubmit or assume timeout cancelled upstream work.
Keep returned provider task IDs and poll
with `gen_task_get`. Never resubmit to poll.

### Create Delivery Recovery

There is no durable replay or deduplication. Omit `idempotency_key`; supplied
legacy keys are rejected on both transports, including dry runs. Repeated
creates are independent operations and may bill again. Reconcile uncertain
or lost create responses with the provider instead of automatically retrying.

Task get/list/cancel and Draft lookup use the supplied provider credential.
Client secrets separate admission scopes only; they do not filter task access.

Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, task-snapshot capture/save or queue creation, including
discovery. Omit task opt-in; ordinary jobs are unavailable on HTTP.

## HTTP Limits and Routes

HTTP defaults to 60 requests/minute per IP per pod, a 2 MiB body cap and
64 in-flight requests per pod. Positive limits are enforced and include
anonymous discovery. Rate/concurrency limits reset on restart and multiply
with replicas. `STATE_MAX_RECORDS` applies only to local stdio.
Proxy headers are untrusted by default.
See [configuration](configuration.md#transport-and-authentication).

| Route | Backend access | Meaning |
| --- | --- | --- |
| `/mcp` | Anonymous discovery; request BYOK for provider tools | Stateless Streamable HTTP |
| `/health` | Anonymous | Minimal process liveness |
| `/ready` | Anonymous on backend; blocked by VKE Caddy | Minimal lifespan readiness; no storage or provider probes |
| `/metrics` | Absent from main app and public proxy | Optional separate loopback-only operator listener |

`RATE_LIMIT_TRUSTED_PROXY_CIDRS` replaces the removed boolean trust setting;
empty means ignore forwarded identities. Only trusted immediate peers can
supply a bounded validated chain; walk right-to-left to the first untrusted
address. Uvicorn proxy rewriting is disabled.
VKE uses same-pod Caddy, application bind `127.0.0.1:3000`, trusted
`127.0.0.1/32` and CLB TCP 443 to Caddy 8443. Only `/mcp` and `/health` are
public. `MCP_METRICS_PORT=0` disables private metrics by default; enabled ports
1024-65535 bind only 127.0.0.1. See [private monitoring](observability.md#metrics-endpoint).

`seed-health://status` and `seed-media://` resources are stdio-only.
No HTTP local file access, persistence or artifact downloads are offered.
Optional `media_prepare_upload` gives enrolled clients restricted TOS POST/GET
permissions; the client uploads bytes directly, not through MCP.
See [temporary references](temporary-uploads.md). Output URLs expire;
clients retrieve media themselves.

## Deployment Boundary

HTTP uses `STATE_BACKEND=none` automatically and rejects explicit database
backends. `DAILY_BUDGET_USD` must be zero; use provider-side spend controls.
The VKE chart supports stateless Deployment/HPA/PDB/hostname spread without
a state volume or sticky sessions. Local stdio remains single-process SQLite.

Preserve previous stateful releases, databases, volumes, identity and accepted
IDs for separately reviewed reconciliation. Source removal is not cloud
decommissioning, and Helm upgrades may delete removed resources. Live routing,
scaling, capacity and client/provider validation remain separate gates.
See [deployment](deployment.md) and the [BYOK contract](../specs/SPEC_HOSTED_BYOK.md).

## MCP Inspector

```bash
make inspect
```

For HTTP, use a trusted existing endpoint and private header configuration.
Do not enter keys into tool arguments, shared inspector logs or screenshots.
