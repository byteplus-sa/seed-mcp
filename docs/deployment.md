# Deployment

HTTP deployments implement the [BYOK foundation](../specs/SPEC_HOSTED_BYOK.md).
Run one instance with fresh SQLite state. HTTP asynchronous-create idempotency
is implemented; synchronous product replay and complete crash recovery remain
deferred. PostgreSQL/Redis are future scaling choices, not initial requirements.
This is not a multi-replica or public-launch claim. Local stdio retains jobs,
storage and artifacts separately.

## Build the Container

Build a reviewed `byteplus-sa/seed-mcp` revision, or independently verify a
compatible digest-pinned image. No fork image publication is assumed.

```bash
docker build --tag seed-mcp:reviewed .
```

See [releases](releases.md) and the
[breaking capability migration](migration-0.2.md#breaking-capability-migration).
Old database schemas are not migrated. Retain old state separately.

## Run One Instance

Prepare an owner-only runtime env file outside Git with `MCP_AUTH_MODE=byok`,
`MCP_IDENTITY_HMAC_KEY` (operator-generated 32 random bytes, 64 lowercase hex)
and `MCP_IDENTITY_KEY_VERSION=1`. This HMAC key is not a customer credential.
Do not put provider keys, client secrets or task-backend credentials in it.
The defaults enforce 60 RPM, a 2 MiB body limit, 64 in-flight requests and
`STATE_MAX_RECORDS=100000`. See [configuration](configuration.md).

The private file and new volume must be prepared before this example:

```bash
docker run --detach \
  --name seed-mcp \
  --publish 127.0.0.1:3000:3000 \
  --env-file /absolute/private/operator.env \
  --env MCP_TRANSPORT=http \
  --env MCP_HOST=0.0.0.0 \
  --env MCP_AUTH_MODE=byok \
  --env MCP_ALLOWED_HOSTS=mcp.example.com,127.0.0.1 \
  --volume seed-mcp-fresh-state:/app/.artifacts \
  seed-mcp:reviewed
```

Put trusted TLS ingress in front of the loopback port. Preserve Host, reject
untrusted Origins and set proxy/client timeouts for foreground work.
Request headers carry only the selected provider key and
`X-MCP-Client-Secret`; [client setup](setup/shared-server.md) explains them.
Do not configure OAuth, signup or a server-issued connection key.

## Probes and Monitoring

```bash
curl --fail http://127.0.0.1:3000/health
curl --fail http://127.0.0.1:3000/ready
```

These return minimal process/state status; HTTP readiness never probes
providers. `/metrics` is unavailable on HTTP. Application logs and provider
spans use sanitized diagnostics; never enable proxy logging of BYOK headers.
Discovery is anonymous and static, so a successful discovery check does not
prove the caller's provider key works.

## State and Shutdown

Keep the SQLite volume and stable HMAC configuration together. Task records
are credential-tenant and client-owner scoped, not a common team namespace.
`STATE_PRUNE_MAX_AGE_DAYS` defaults to 30 and must be at least 14 for HTTP
regular Seedance 2.5 Draft ownership. Capacity failures deny new work rather
than evict live owners.
Submission claims never auto-prune, even when ownership expires.
`STATE_MAX_RECORDS` caps journal claims; at capacity existing keys remain
readable but new keys fail before dispatch. Do not erase claims to admit work.

HTTP is stateless, with no ordinary jobs, native tasks, storage/artifact tools
or media resources. Do not provision Redis snapshots for hosted requests.
Clients download expiring provider outputs; server persistence is rejected.
Audio Files API temporary uploads are distinct and cleaned up with the request
key, best-effort.

Drain in-flight foreground work before restart. The entrypoint allows up to
`BYTEPLUS_REQUEST_TIMEOUT_MS` for graceful shutdown; orchestrator grace must
cover it plus cleanup. A forced stop or lost submission response can leave
an unknown provider outcome. Reconcile using saved task/request IDs, never
blindly recreate work. Non-dry HTTP Seedance/OmniHuman calls require
`idempotency_key`, one per whole call. Repeat identical arguments/key only for
saved-success delivery recovery, not polling; unresolved attempts never
automatically resume. Seedance dry runs need no key or journal; stdio rejects
supplied keys. See the
[submission contract](../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).

## Deployment Checklist

- Keep one application replica and a fresh private state directory.
- Protect operator HMAC configuration and backups; never distribute it.
- Verify fixed official provider origins and no environment-key fallback.
- Keep positive admission/body/rate/state limits and explicit Host/Origin policy.
- Verify anonymous discovery and denial of missing credentials on provider calls.
- Verify no HTTP job/task/resource surface and no public metrics.
- Validate exact-client headers, TLS, load and restore behavior separately.

The [BytePlus guide](byteplus-terraform.md) describes infrastructure
prerequisites. It is not authorization to provision resources or publish an
endpoint. Public launch remains gated on capacity/recovery procedures,
synchronous product replay, live validation and hardening work.
