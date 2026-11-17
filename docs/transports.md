# Transports

The default transport is local stdio. Streamable HTTP is a separate
forward-only BYOK surface, including on loopback.

| Transport | Tools | Execution |
| --- | --- | --- |
| stdio | 21 catalog tools, conditional on local credentials/flags; eight always available | Local jobs/native tasks, storage and artifacts retained |
| HTTP | 9, or 12 with OmniHuman enabled | Direct foreground provider calls; no jobs, native tasks, storage/artifact tools or resources |

## stdio

The client starts a subprocess with `MCP_TRANSPORT=stdio`. Provider credentials
come from private local configuration referenced by `ARK_MCP_ENV_FILE`.
`MCP_AUTH_MODE=local` remains an explicit stdio-only choice; the default
`byok` setting does not require an HMAC key for stdio.

```bash
uv run --locked --no-sync python -m ark_mcp
```

Use `ark_job_submit`/`ark_job_get` for required long operations. Native MCP
tasks remain available to capable clients. Local jobs are process-local with
the default memory backend. Separate stdio processes do not share jobs.
See [background execution](integration-guide.md#background-execution).
Local Seedance/OmniHuman calls must omit `idempotency_key`; supplied keys are
rejected, including on Seedance dry runs.

## Streamable HTTP

HTTP requires `MCP_AUTH_MODE=byok` (default) and the operator's private
`MCP_IDENTITY_HMAC_KEY`: 32 random bytes encoded as 64 lowercase hex.
`MCP_IDENTITY_KEY_VERSION` defaults to `1`. Neither is a customer credential.
Local-auth HTTP and the former shared-key auth mode are not supported.

After securely loading operator configuration, a developer can launch:

```bash
MCP_TRANSPORT=http MCP_HOST=127.0.0.1 \
  uv run --locked --no-sync python -m ark_mcp
```

For non-loopback access use trusted TLS ingress and explicit
`MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS`. Stateless HTTP and Host/Origin
protection are enforced by `HardenedFastMCP.http_app()` as well as the normal
CLI route. Building an HTTP app from stdio-configured settings is rejected.

Clients supply `X-MCP-Client-Secret` and only the selected provider header:
`X-ModelArk-Api-Key`, `X-Seed-Speech-Api-Key`, or `X-OmniHuman-Api-Key`.
The client secret is client-generated 32 random bytes as 64 lowercase hex.
`Authorization` is rejected. There is no OAuth, signup or server-issued key.
[Client setup](setup/shared-server.md) includes private entry and examples.

Discovery is anonymous/static and lists configured bindings without environment
provider keys; `services[].enabled` reports registration, not entitlement.
Provider calls, including dry runs, need live
headers on every request. No server provider-key fallback exists. Model
endpoint defaults are exact registered IDs; explicit tool `model` wins.
HTTP generation and understanding run in the foreground, so configure the
client/proxy timeout for long calls. Keep returned provider task IDs and poll
with `gen_task_get` or `omnihuman_get_task`. Never resubmit to poll.

### Create Delivery Recovery

Non-dry HTTP `seedance_create_task` and `omnihuman_create_task` require
`idempotency_key`: 16-128 ASCII letters, digits, `_` or `-`; use a fresh UUID
per intended operation, including one key for a whole variation batch.
Seedance dry runs need no key and do not consume a journal claim.
Repeat identical arguments and the original key only to recover delivery of a
saved successful receipt, not to poll. Replay checks existing ownership before
any upstream call, including Draft lookup. Failed, partial or cancelled
attempts remain unresolved with known IDs; no automatic resume occurs.
Never change keys to bypass uncertain acceptance. See the
[submission contract](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).

Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected before
provider dispatch, task-snapshot capture/save or queue creation, including
discovery. Omit task opt-in; ordinary jobs are unavailable on HTTP.

## HTTP Limits and Routes

HTTP defaults to 60 requests/minute per IP, a 2 MiB body cap, 64 in-flight
requests and `STATE_MAX_RECORDS=100000`. Positive limits are enforced; global
admission includes anonymous discovery. Proxy headers are untrusted by default.
See [configuration](configuration.md#transport-and-authentication).

| Route | Access | Meaning |
| --- | --- | --- |
| `/mcp` | Anonymous discovery; request BYOK for provider tools | Stateless Streamable HTTP |
| `/health` | Anonymous | Minimal process liveness |
| `/ready` | Anonymous | Minimal local state readiness; no provider probes |
| `/metrics` | Unavailable on HTTP | Not a public monitoring endpoint |

`seed-health://status` and `seed-media://` resources are stdio-only.
No HTTP local file access, persistence, artifact downloads or uploads are
offered. Output URLs expire; clients retrieve media themselves.

## Deployment Boundary

Use fresh SQLite state for one application instance. Preserve the same state,
HMAC key/version and original provider/client credentials for replay.
Journal claims never auto-prune: at `STATE_MAX_RECORDS`, new keys fail but
existing keys remain readable. There is no old-schema migration or
multi-replica coordination. Synchronous product replay and complete crash
recovery remain deferred; PostgreSQL/Redis are future scaling choices, not
initial requirements. This foundation is not public-launch certification.
See [self-hosting](self-hosting.md), [security](security.md), and the
[BYOK contract](../specs/SPEC_HOSTED_BYOK.md).

## MCP Inspector

```bash
make inspect
```

For HTTP, use a trusted existing endpoint and private header configuration.
Do not enter keys into tool arguments, shared inspector logs or screenshots.
