---
title: Hosted BYOK Foundation Contract
type: spec
status: accepted
horizon: current
created: 2026-11-16
updated: 2026-11-16
tags: [byok, http, security, ownership]
related:
  - specs/SPEC_BACKGROUND_JOBS.md
  - docs/security.md
  - docs/setup/shared-server.md
---

# Hosted BYOK Foundation

This is a forward-only, single-instance foundation, not a public-launch or
multi-replica certification. No OAuth, signup, server-issued key, customer
credential database, or compatibility migration is provided.

## Transport Surface

| Transport | Inventory | Execution and storage |
| --- | --- | --- |
| Local stdio | 21 catalog tools, conditionally registered; eight always available | Local provider settings, ordinary jobs/native tasks, optional storage and artifacts |
| HTTP | 9 tools, or 12 with `BYTEPLUS_OMNIHUMAN_ENABLED=true` | Direct foreground calls; provider-managed video tasks; no jobs, native tasks, storage/artifact tools or resources |

HTTP exposes `ark_list_models`, `seed_audio_generate`, `seedream_generate_image`,
`seedance_create_task`, `gen_task_get`, `gen_task_list`,
`gen_task_cancel_or_delete`, `seed_understand`, and `seed_audio_understand`.
The optional tools are `omnihuman_create_task`, `omnihuman_get_task`, and
`omnihuman_cancel_task`. Registration does not depend on operator provider keys.
Discovery is anonymous, static, and makes no provider calls; it does not
establish entitlement or return account pricing.
`ark_list_models` returns the receiving server's configured bindings even
without an environment provider key. `services[].enabled` reports registration,
not customer entitlement, provider-key validity or model activation.
The 12 [catalog scope strings](../docs/security.md#scope-taxonomy) are metadata,
not auth grants or customer-selected roles.

## Request Credentials

| Header | Requirement |
| --- | --- |
| `X-ModelArk-Api-Key` | ModelArk tools, including audio understanding and Files API delivery |
| `X-Seed-Speech-Api-Key` | Seed Audio generation |
| `X-OmniHuman-Api-Key` | Enabled OmniHuman tools |
| `X-MCP-Client-Secret` | Every provider operation, including dry runs; client-generated 32 random bytes encoded as 64 lowercase hex characters |
| `X-ModelArk-Seedance-Endpoint` | Optional exact registered video binding default |
| `X-ModelArk-Seedream-Endpoint` | Optional exact registered image binding default |

Only the selected provider key is required. `Authorization` is rejected,
not interpreted as a provider key or an MCP access token. Raw ASGI header pairs
are validated: duplicate, empty, whitespace-containing, control, non-ASCII
and oversized values are rejected without echoing them. Provider keys are
opaque printable ASCII, 1-4096 characters, never normalized.

An explicit tool `model` wins over its endpoint header default. Used defaults
must exactly match a registry binding for the product. No arbitrary opaque
`ep-*` lineage inference, automatic model activation or caller-selected base URL
is supported. HTTP uses these fixed official origins:

- ModelArk: `https://ark.ap-southeast.bytepluses.com/api/v3`
- Seed Speech: `https://voice.ap-southeast-1.bytepluses.com`
- Vision AI: `https://openapi.cv.bytepluses.com`

## Identity and Ownership

`MCP_AUTH_MODE=byok` is the default. Explicit `local` is stdio-only; the
`api_key` auth mode is removed. HTTP requires the operator's
`MCP_IDENTITY_HMAC_KEY`, a random 32-byte secret encoded as 64 lowercase hex,
and `MCP_IDENTITY_KEY_VERSION`, a positive integer defaulting to `1`.
These are operator identity configuration, not customer credentials.

Domain-separated HMAC derives a credential tenant from the version, selected
provider, fixed base URL and exact provider key. The owner derives from that
tenant and the client secret. Unrelated provider keys do not affect scope.
The same key with a different client secret has a different owner; changing
the provider key, client secret, HMAC key or version changes ownership scope.
Stable settings and credentials preserve identity across restarts, but there
is no recovery bridge or human/organization identity verification.

Fresh SQLite state is required. Task ownership has primary key
`(provider, tenant_id, task_id)` and an immutable `principal_id` owner.
Reads, claims and lists use this namespace. Conflicts cannot reassign owners.
Missing ownership and unavailable/capacity-exhausted state fail closed.
There is no old-schema migration. Retain the original provider IDs and scope
for polling; do not recreate accepted work to bypass an ownership failure.

Sharing a provider key still permits direct upstream access outside this MCP
boundary. Use separate provider keys/projects for stronger separation.
Budgets are per derived owner and approximate, not an account-wide spend ceiling.

## Credential Lifetime

Credentials exist only in a live request context, with a provider-specific
principal around invocation; contexts reset on completion/cancellation.
Explicit request-key gateways have no HTTP environment-key fallback and do
not mutate shared client headers. Credentials are not persisted in arguments,
task snapshots, database rows, artifact metadata, cache keys, logs or spans.
The operator still receives live credentials and must be trusted.

The receiving server's `Settings` is request-scoped and reset on exit.
Capability-registry lookup uses those scoped settings instead of the cached
process-default registry, so concurrent server instances cannot leak model
defaults or bindings into one another. Anonymous discovery uses the same scope.

Every HTTP entry path, including `http_app()`, enforces the boundary.
Constructing HTTP from a stdio-configured server is rejected. Native tasks and
ordinary jobs are not registered. Explicit per-call
`io.modelcontextprotocol/tasks` opt-in, including on discovery, is rejected
before provider dispatch, task-snapshot capture/save or queue creation.
Request headers are never restored from FastMCP task snapshots.
This explicit rejection is the application's stricter boundary, not a promise
that FastMCP's `task=forbidden` mode alone rejects client opt-in.

## Media and Delivery

`seed_audio_generate.persist`, `seedream_generate_image.persist` and
`omnihuman_get_task.persist_output` default to `false` on every transport.
HTTP rejects explicit `true`, local paths and stored artifact references
before dispatch. Explicit local persistence remains supported.
Seedream `b64_json` needs persistence and therefore is not an HTTP output mode.
HTTP returns provider URLs and metadata, not durable MCP media resources.
Missing/unusable URL-only Seed Audio output is a nonretryable per-item
`NO_DELIVERABLE_OUTPUT`, never an empty success or automatic regeneration.

Clients must retrieve outputs before expiry: about 2 hours for Seed Audio,
24 hours for Seedream/Seedance and 1 hour for OmniHuman. Native authorized
Seedance `asset://` references remain supported without asset administration.

Audio-understanding Files API delivery remains supported. Best-effort deletion
uses the same live request ModelArk key. Remote temporary-file expiry (roughly
one day if cleanup cannot complete) is separate from output URL expiry and
does not constitute local persistence. Unknown upload acceptance is not retried.

## Admission and Diagnostics

| Setting | Default | HTTP rule |
| --- | --- | --- |
| `RATE_LIMIT_RPM` | `60` | Positive per-IP rate; bounded limiter map |
| `RATE_LIMIT_BURST` | `0` | Uses RPM when zero |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` (2 MiB) | Positive streamed request limit |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Positive admission bound before body processing, including discovery |
| `STATE_MAX_RECORDS` | `100000` | Positive retained-state bound; no eviction of live owners |
| `STATE_PRUNE_MAX_AGE_DAYS` | `30` | At least 14 when regular Seedance 2.5 is bound on HTTP |

Stateless HTTP forces Host/Origin protection. Proxy headers are untrusted by
default. `/health` and `/ready` return minimal liveness/state readiness without
provider probes or configuration disclosure. Public HTTP has no `/metrics`
endpoint or configuration-detail resource.

Uncertain mutation transport failures and malformed 2xx responses are
nonretryable/ambiguous with sanitized diagnostics. Billable understanding
completions use this same policy: response loss, read/write/protocol errors and
malformed provider 2xx responses do not permit automatic replay.
Chat/mutation 5xx errors remain `retryable=true` in HTTP normalization but are
ambiguous and never retried automatically. Eligible 429 rejections,
demonstrably pre-dispatch connection/pool failures and reads retain bounded
retries; understanding's `retry_timeouts=False` excludes all `TIMEOUT` retries.
Errors retain safe codes/request IDs, not raw exception text or credential URLs.
Clients must reconcile instead of blindly retrying.

Budget reservation before dispatch still fails closed. In `billed_provider_slot`,
commit/release exceptions log `ERROR` event `budget_finalization_failed` with
safe `provider`, `action` and `reservation_id` fields, never raw exception text.
They do not replace the provider result/error, raise `AcceptedTaskError`, or
add to Seedance's `failed` count. Failed finalization leaves conservative
reserved allowance. Cancellation cleanup is shielded best effort, not a
guarantee that no reserved rows remain.

Seedance proceeds to the shared `record_accepted_task` helper even after a
budget-finalization log event; OmniHuman uses the same ownership helper.
Only accepted ownership-record failures become outward `AcceptedTaskError`
(`OWNERSHIP_RECORD_FAILED`), retaining accepted task IDs and available request
IDs. These failures are ambiguous/nonretryable and never cause internal
resubmission. In Seedance variation results, `task_id` and `error` can coexist:
`submitted` counts known accepted IDs, while `failed` counts entries with
errors, so accepted ownership-record errors can count in both. Single-call
failures remain error `ToolResult` text carrying known IDs, not structured
success output. HTTP polling requires recorded ownership; otherwise use
task/request IDs for provider-side reconciliation. Trusted stdio permits
unrecorded IDs, but still rejects a recorded owner mismatch.

Understanding JSON Schema validation is offline. `$ref`, `$dynamicRef` and
`$recursiveRef` must be fragment-only (`#...`); external schemas are never
retrieved. Internal tool metrics use catalog names or a fixed `unknown` label,
not arbitrary caller-supplied tool names; unknown background targets are skipped.

```mermaid
flowchart TD
    Client["Client request"] --> Limit["Admission, rate and body limits"]
    Limit --> Headers["Validate live headers"]
    Headers --> Discovery{"Discovery?"}
    Discovery -->|Yes| Static["Static bindings; no provider call"]
    Discovery -->|No| Identity["Selected key and client secret; derive owner"]
    Identity --> Validate["Validate binding, media and ownership"]
    Validate --> Gateway["Explicit request-key gateway"]
    Gateway --> Provider["Official provider"]
    Provider --> Result["URL, task ID or safe error"]
    Result --> Release["Release live credential context"]
```

## Next Phase

PostgreSQL, multi-replica coordination, durable pre-dispatch records,
idempotency and crash recovery are not implemented. Loss of an accepted
submission response can still require manual provider reconciliation.
Exactly-once inference is not promised. Public multi-user launch requires
those follow-ups, load/security validation and exact-client interoperability
checks. Offline protocol tests are not live provider or desktop-client evidence.

## Sources

- Current implementation: `server.py`, `security/http_middleware.py`,
  `config/env.py`, `config/model_capabilities.py`, `tools/ark_list_models.py`,
  `tools/_seedance_shared.py`, and ModelArk gateway/understanding adapters.
- [FastMCP background tasks](https://gofastmcp.com/servers/tasks), accessed
  2026-11-16: per-call extension opt-in and execution modes. The application
  boundary above is verified against this checkout, not inferred from framework defaults.
