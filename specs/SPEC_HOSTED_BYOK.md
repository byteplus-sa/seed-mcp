---
title: Hosted BYOK Foundation Contract
type: spec
status: accepted
horizon: current
created: 2026-11-16
updated: 2026-11-28
tags: [byok, http, security, ownership]
related:
  - specs/SPEC_DIRECT_EXECUTION.md
  - specs/SPEC_VKE_DEPLOYMENT.md
  - docs/security.md
  - docs/setup/shared-server.md
---

# Hosted BYOK Foundation

Hosted HTTP is a database-free BYOK proxy with provider-key task authorization.
It provides no durable replay, deduplication or shared budget accounting.
Local stdio persistence remains available. Source support for multiple pods
is not public-launch or deployed-capacity certification.

## Transport Surface

| Transport | Inventory | Execution and storage |
| --- | --- | --- |
| Local stdio | 17 catalog tools, conditionally registered; four always available | Direct calls, local provider settings, storage and artifacts; TTS always persists |
| HTTP | 12 provider/discovery tools | Direct calls; provider-managed video tasks; no jobs, native tasks, local storage/artifact tools or resources |

HTTP exposes `ark_list_models`, `seed_audio_generate`, `seedream_generate_image`,
`seedance_create_task`, `gen_task_get`, `gen_task_list`,
`gen_task_cancel_or_delete`, `seed_tts_generate`, and the four `ark_file_*` tools.
Registration does not depend on operator provider keys.
Discovery is anonymous, static, and makes no provider calls; it does not
establish entitlement or return account pricing.
Default `check_connection=false` returns `connection=null` without inspecting
request credentials in discovery. An opt-in HTTP configuration check is
described below; it is not a provider-authentication check.
`ark_list_models` returns the receiving server's configured bindings even
without an environment provider key. `services[].enabled` reports registration,
not customer entitlement, provider-key validity or model activation.
The 12 [catalog scope strings](../docs/security.md#scope-taxonomy) are metadata,
not auth grants or customer-selected roles.

## Request Credentials

| Header | Requirement |
| --- | --- |
| `X-ModelArk-Api-Key` | Seedream, Seedance and Files tools |
| `X-Seed-Speech-Api-Key` | Seed Audio and Seed TTS generation |
| `X-MCP-Client-Secret` | Optional separate client admission; when supplied, client-generated 32 random bytes encoded as 64 lowercase hex characters |
| `X-ModelArk-Seedance-Endpoint` | Optional exact registered video binding default |
| `X-ModelArk-Seedream-Endpoint` | Optional exact registered image binding default |

Only the selected provider key is required. `Authorization` is rejected,
not interpreted as a provider key or an MCP access token. Raw ASGI header pairs
are validated: duplicate, empty, whitespace-containing, control, non-ASCII
and oversized values are rejected without echoing them. Provider keys are
opaque printable ASCII, 1-4096 characters, never normalized.

Omit `X-MCP-Client-Secret` for URL-plus-provider-key setup. Absence selects
shared provider-key admission; empty, malformed, duplicate or reused values
are still errors, not fallback requests. This applies to both provider
gateways and every provider operation, including Files, task reads and dry runs.

After syntax validation and before binding a request context, exact
constant-time comparisons reject `X-MCP-Client-Secret` matching any supplied
provider API key, including an unselected provider. Header order and casing
do not affect this check. The response is HTTP 400 plain text with the stable
prefix `CREDENTIAL_REUSE:` and guidance to generate an independent 32-random-byte,
64-lowercase-hex client secret, update its private client configuration and
keep provider keys unchanged. It echoes no credential values and precedes tool
execution, provider dispatch, including on discovery and dry runs.
Provider keys are not required to differ from one another; omission of headers
for anonymous discovery remains supported. This is configuration hygiene, not
authentication, customer identity or provider-task authorization.

An explicit tool `model` wins over its endpoint header default. Used defaults
must exactly match a registry binding for the product. No arbitrary opaque
`ep-*` lineage inference, automatic model activation or caller-selected base URL
is supported. HTTP uses these fixed official origins:

- ModelArk: `https://ark.ap-southeast.bytepluses.com/api/v3`
- Seed Speech: `https://voice.ap-southeast-1.bytepluses.com`

## Managed Files API

Managed reference files use `ark_file_upload`, `ark_file_get`,
`ark_file_list`, and `ark_file_delete` with the ModelArk API key. Default
`purpose="agent"` uses provider-managed storage without bucket setup. Retrieve
the accepted file ID until active with a `download_url`, then pass that URL
to generation. The client-side `seed-mcp-upload` streams local files directly
to ModelArk; HTTP MCP accepts HTTPS source URLs, not local paths or Base64.
Reads do not renew the documented 24-hour/100-download URL limit. No upload
enrollment, TOS signer, IRSA, application file database or cleanup worker remains.
Never automatically retry an uncertain upload/delete; keep file/request IDs.

All four tools are provider-authorized on both transports. HTTP requires
the live ModelArk key; the optional client secret scopes per-pod admission,
not file ownership. Shared provider keys share provider-authorized file access.
Scopes are `files:read`, `files:write`, and `files:delete`, metadata only.
Get/list return bounded typed metadata, with at most 100 files and 2 MiB
provider response bytes. They do not download content or renew URLs.
Delete requires explicit boolean `confirm=true` and is permanent.

Stdio upload additionally accepts an absolute regular-file path. Local
uploads use a no-follow, nonblocking descriptor, a 512,000,000-byte cap and
64 KiB streamed reads. File changes are rejected without resubmission.
HTTP local paths, Base64, arbitrary origins, TOS options and legacy idempotency
inputs are rejected. URL import checks public HTTPS syntax/DNS before the
provider fetch; provider-side redirect behavior is not certified by that check.
Large client files go directly to ModelArk through `seed-mcp-upload`, using
only an explicitly named key environment variable and `--confirm-upload`.
The helper reads no env files, never changes client configuration, and emits
metadata without signed URLs. It has a 600-second cooperative bound.
On deadline, the helper reports whether dispatch began and preserves at most
two safe invocation-local sent/observed request IDs for reconciliation.
These IDs are not proof of acceptance. No automatic retry or provider
cancellation is implied; no diagnostics are persisted.

File retention is provider-managed: default seven days, optionally 1-30 days
through Unix `expire_at`. Documented managed quota is 20 GB per account.
No account pricing, global quota enforcement or malware-scan claim is added.
Known safe accepted file IDs survive in live-call deadline diagnostics.
The TOS backend and all signer/IRSA/enrollment configuration are removed
without compatibility aliases. Local S3 artifacts remain independent.
See [Files workflows and sources](../docs/files.md).

## BYOE Endpoint Authority

Bring-your-own-endpoint (BYOE) support means selecting an **operator-verified
exact binding**, not self-service verification of an arbitrary customer ID.
The official [GetEndpoint authentication contract](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/get-endpoint-api#authentication),
verified against the documentation body and OpenAPI schema on 2026-11-17,
requires Access Key V4 signing (AK/SK), not a ModelArk Bearer API key.
Its `ModelReference.FoundationModel.Name` and `ModelVersion` describe lineage;
an opaque endpoint ID or a caller-declared family does not establish it.

An authorized operator must verify the endpoint's model/version outside this
server, then configure the exact ID and supported family in
`SEEDANCE_MODEL_BINDINGS` or `SEEDREAM_MODEL_BINDINGS`. Retain an entry for the
configured product default. These bindings are visible in anonymous discovery,
so do not treat endpoint IDs in them as secrets. This server does not collect,
store or use customer AK/SK, fetch endpoint metadata, infer lineage, or activate
models. Automatic arbitrary-endpoint onboarding remains unimplemented and
requires a separately approved authority/credential design.

Seedream bindings accept only `seedream_5_5`. Seedream 5.0 Pro and lower
are not supported on either transport; legacy families fail startup and
unconfigured model selections fail before dispatch. Custom image endpoints
must be independently verified as 5.5, not relabeled from an older version.
The built-in default is `dola-seedream-5-5-261028`, with no older-model fallback.

Unknown image/video `ep-*` selections fail with `ENDPOINT_NOT_CONFIGURED`
guidance before provider dispatch, without echoing the unknown ID. The operator
must verify and bind it; do not guess a family or bypass the check.

## HTTP Configuration Preflight

Call `ark_list_models` with `{"input":{"check_connection":true}}` only through
a live HTTP request. Omitted/null `kind` checks both video and image routes;
`kind="video"` or `"image"` checks just that route. Other kinds, stdio calls,
and calls without a live HTTP request context are rejected.
Seed Speech is not checked.

No provider key or client secret is required to request diagnostics: a missing
ModelArk key becomes an issue; an omitted client secret does not.
The HTTP boundary still rejects malformed headers.
Preflight uses header presence and this server's registry only, with no HMAC
identity derivation, provider or metadata requests, credential persistence,
state writes or changes to server settings.

`connection: HttpConnectionCheck | null` is null unless opted in:

| Field | Type | Meaning |
| --- | --- | --- |
| `configuration_valid` | boolean | The ModelArk key header is present and every checked route is configured |
| `modelark_key_present` | boolean | Live `X-ModelArk-Api-Key` header is present |
| `client_secret_present` | boolean | Optional independent `X-MCP-Client-Secret` header is present; false is valid |
| `authentication_verified` | literal `false` | No upstream authentication, entitlement or balance verification |
| `provider_calls_made` | literal `false` | No provider or endpoint-metadata requests |
| `issues` | list of strings | `missing_modelark_key` if the key is absent; otherwise empty. No missing-secret issue |
| `routes` | list of `EndpointSelectionCheck` | Checked defaults, video then image when both are requested |

Each `EndpointSelectionCheck` contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool` | `seedance_create_task` or `seedream_generate_image` | Product route checked |
| `source` | `request_header` or `server_default` | Endpoint header when present, otherwise the operator default |
| `configured` | boolean | Exact selected ID is registered for that product |
| `model_id` | string or null | Registered model/endpoint ID; null for unknown selections, which are never echoed |
| `family` | string or null | Operator-configured family, not verified live lineage; null for unknown selections |
| `issue` | `endpoint_not_configured` or null | Operator verification/binding required, otherwise null |

`configuration_valid=true` does not prove key validity, endpoint existence,
current lineage, activation, permissions, balance or reachability. The check
describes route defaults, not a prospective create payload: an explicit
create-tool `model` still wins over an endpoint header. `models[].is_default`
continues to describe the server default, not the request-header override.
Neither a valid preflight nor a dry run is authorization to spend.

## Client Snippet Generator

`scripts/configure_http_client.py` is a standalone stdlib-only formatter:
`python scripts/configure_http_client.py --client codex|claude-code --url URL`.
It emits one TOML/JSON snippet to stdout. It reads no files or environment
secret values, writes no files, makes no network calls, and never invokes or
changes a client. Applying a snippet and private credential entry are separate
user-authorized setup steps.

- `--name`: defaults to `seed-mcp`, 1-64 ASCII letters/digits/underscore/hyphen.
- Repeated `--provider`: `modelark`, `seed-speech`; defaults to
  `modelark` when omitted. Only selected providers get headers.
- Provider environment-name defaults: `SEED_MCP_MODELARK_KEY` and
  `SEED_MCP_SEED_SPEECH_KEY`. Override with `--modelark-key-env` and
  `--seed-speech-key-env`. Client-secret headers are omitted by default;
  explicitly pass `--client-secret-env VAR` to add one. No secret is generated.
- Optional `--seedance-endpoint-env` and `--seedream-endpoint-env` add endpoint
  headers and require selected provider `modelark`; values must resolve to
  exact registered bindings when the client sends them.
- Variable names match `[A-Za-z_][A-Za-z0-9_]{0,127}`. Selected headers must use
  distinct names, including an independent client-secret variable. The
  generator does not inspect values or prove they are distinct.
- URLs require absolute HTTPS with a valid host/port and no userinfo, query,
  fragment, whitespace, controls or backslashes. `--allow-loopback-http` permits
  HTTP only on literal `localhost`, `127.0.0.1` or `::1` for isolated tests,
  not remote plaintext access or disabled TLS verification.
- `--tool-timeout-seconds`: integer 1-3600, default 660. Codex receives
  `mcp_servers.<name>`, `env_http_headers` and `tool_timeout_sec`; no
  `bearer_token_env_var`. Claude Code receives `mcpServers.<name>`,
  `type="http"`, `${VAR}` header references and `timeout` in milliseconds
  (660000 by default). These settings do not extend provider/proxy timeouts.

Invalid input exits with a safe generic error rather than echoing supplied
values. No credential-value or authentication flags are accepted. The
[shared-server guide](../docs/setup/shared-server.md) covers help, examples
and private client environment setup.

## Identity and Ownership

`MCP_AUTH_MODE=byok` is the default; explicit `local` is stdio-only and the
`api_key` mode is removed. HTTP requires operator `MCP_IDENTITY_HMAC_KEY`
(32 random bytes, 64 lowercase hex characters) and positive
`MCP_IDENTITY_KEY_VERSION` (default 1). These are operator configuration,
not customer credentials. No OAuth, signup or server-issued key is added.

Domain-separated HMAC derives an ephemeral admission tenant from the version,
selected provider, fixed base URL and exact provider key. With a client secret,
the existing `seed-mcp:owner` HMAC over tenant and secret is unchanged.
Without one, `seed-mcp:owner:provider-key` over the tenant derives a stable
principal shared by callers of that key. This separate domain cannot collide
with an explicit-secret principal through a chosen placeholder. Never use raw
keys, an empty secret, a public constant secret or a random per-request secret
as the identity fallback. No new persistence or enrollment is introduced.
Unrelated provider keys do not change the scope. Changes affect admission,
not provider task/file authorization. Optional secrets are self-selected and
are not an anti-abuse identity, extra authorization factor or spend control.
Global per-pod provider concurrency, HTTP in-flight and IP rate limits remain
unchanged; limits reset at restart and multiply across replicas.

Task get/list/cancel and Draft lookup are authorized by the supplied provider
key. Optional `X-MCP-Client-Secret` separates per-pod admission scopes, not task access.
Without it, callers using the same provider key share one per-pod principal concurrency allowance.
Clients sharing a provider key can access whatever that key authorizes.
Use separate provider credentials when independent authorization is required.

There is no local task-ID ledger or client-secret ownership filtering on HTTP.
Authorization remains the provider's responsibility; the server does not
assert authorization before the provider response.

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

`seed_audio_generate.persist` and `seedream_generate_image.persist` default to `false` on every transport.
HTTP rejects explicit `true`, local paths and stored artifact references
before dispatch. Explicit local persistence remains supported.
Seedream `b64_json` needs persistence and therefore is not an HTTP output mode.
Seed TTS collects up to 30 MiB of streamed provider audio and returns a native
MCP audio block without storage. Stdio still
persists locally. No `persist` flag exists; local output paths are rejected on HTTP.
HTTP returns provider download URLs or native TTS audio, not durable MCP media resources.
Missing/unusable URL-only Seed Audio output is a nonretryable per-item
`NO_DELIVERABLE_OUTPUT`, never an empty success or automatic regeneration.

Clients must retrieve outputs before expiry: about 2 hours for Seed Audio,
24 hours for Seedream/Seedance. Native authorized
Seedance `asset://` references remain supported without asset administration.

### Hosted TTS Audio

`seed_tts_generate` is part of the baseline HTTP inventory, independent of
operator storage/provider configuration. Invocation requires the live Seed Speech
key; the client secret is optional. No TTS storage flag, bucket or operator storage
credential is required.

One call collects at most 30 MiB of decoded audio and returns one native
`AudioContent` block at `content[0]`, with Base64 `data` and wire `mimeType`.
`structuredContent.audio` describes its content index, MIME type, byte count
and SHA-256. `artifact` is null. The metadata also retains output format,
session/request/log IDs and optional word alignment; no Base64 is duplicated
in structured or text metadata. Stdio retains artifact persistence.

Encoding occurs under Seed Speech admission. The existing 8 MiB per-event and
8 MiB metadata limits remain; total wire collection is bounded relative to the
audio cap. At the audio cap the response contains 40 MiB Base64 plus metadata
and protocol overhead. Client/proxy response capacity must be validated; this
does not change the inbound 2 MiB request cap.

No output upload, database, local file, artifact resource, replay or recovery
API exists. Return audio only after successful final completion; failures are
text-only. Cancellation propagates and deadlines retain known dispatched
request IDs. A lost response may mean billed audio is lost; never resynthesize
automatically. Client playback/saving behavior is not implied by protocol-level
tests. See [TTS delivery](../docs/seed-tts.md#direct-audio-delivery).

## Admission and Diagnostics

| Setting | Default | Meaning |
| --- | --- | --- |
| `MCP_IDENTITY_KEY_VERSION` | `1` | HMAC version for ephemeral admission scopes |
| `RATE_LIMIT_RPM` | `60` | Requests per IP per pod |
| `RATE_LIMIT_BURST` | `0` | Uses RPM when zero |
| `MCP_HTTP_MAX_BODY_BYTES` | `2097152` | Streamed request body cap |
| `MCP_HTTP_MAX_IN_FLIGHT` | `64` | Per-pod in-flight requests |
| `MCP_ADMISSION_TIMEOUT_SECONDS` | `2.0` | Finite positive seconds, max 30; owner-first/provider-slot wait |
| `MCP_TOOL_TIMEOUT_SECONDS` | `600.0` | Finite positive seconds, max 3600; cooperative whole-tool deadline |
| `DAILY_BUDGET_USD` | `0` | Required zero on HTTP; no budget ledger |

Rate limits and in-flight/provider/principal concurrency are in-memory per pod;
they multiply with replicas and reset at restart. `DAILY_BUDGET_USD` must be `0`
on HTTP; use provider-side spend controls. Readiness is lifespan-only and makes
no storage or provider probes. No database, migration, distributed lock, shared
volume or sticky session is needed for the hosted deployment.

The whole-tool timer starts at wrapper entry after MCP parsing, before
credentials, binding and admission. Active/waiting principal limiters stay
pinned; partial acquisitions release on failure. `ADMISSION_TIMEOUT` means
this attempt did not dispatch, not that other variations were unsubmitted.
No automatic admission retry is added.

Use client timeout 660 seconds with the default 600-second tool and provider
timeouts and compatible proxy settings. SDK drain may exceed the cooperative
deadline. `TOOL_DEADLINE_EXCEEDED` is text-only and preserves mutation
uncertainty and known safe accepted IDs. External cancellation propagates;
neither expiry nor disconnect guarantees provider cancellation.

Mutation read/write/protocol transport failures and malformed mutation 2xx
responses are ambiguous/nonretryable. Mutation 5xx responses remain marked
retryable by normalization but are ambiguous and never automatically retried.
Eligible 429 rejections, demonstrably pre-dispatch connection/pool failures
and reads retain bounded retries. Diagnostics exclude raw exceptions,
credentials and credential-bearing URLs. Tool metrics use catalog names or a
fixed `unknown` label, not arbitrary caller-supplied names.

## Trusted Proxy and Private Operations

`RATE_LIMIT_TRUSTED_PROXY_CIDRS` defaults empty and replaces the removed
boolean `RATE_LIMIT_TRUST_PROXY_HEADERS` without an alias. It accepts explicit
canonical IPv4/IPv6 CIDRs; host bits, empty entries and catch-all networks
(including combined catch-all coverage) are rejected. Uvicorn proxy-header
rewriting is disabled so the middleware sees the immediate socket peer.

Untrusted peers' forwarding headers are ignored. Trusted peers' single
`X-Forwarded-For` header has bounded size/hops and canonical address parsing.
Walk right-to-left through trusted hops to the first untrusted address.
Malformed or duplicate chains fail with fixed text and no header echo.
Rate/body events use bounded route labels, not arbitrary paths or raw headers.

VKE runs Caddy in each pod alongside the loopback-bound application
(`127.0.0.1:3000`), trusting only `127.0.0.1/32`. Caddy overwrites forwarded
addresses and host/proto, removes `Forwarded`, and exposes only `/mcp` and
`/health` behind CLB TCP 443. Actual VKE source-IP preservation is unverified.
Do not add broad trusted networks to bypass this acceptance gate.

`MCP_METRICS_PORT` defaults to `0` (disabled); nonzero ports must be
1024-65535. The listener is HTTP-runtime-only and binds only 127.0.0.1,
separate from the main app, with thread shutdown/drain owned by the runtime.
It exposes the existing Prometheus registry without per-owner labels.
Admission rejections and tool deadlines use fixed aggregate labels.
Helm can enable port 9000, but creates no metrics Service; only authorized
loopback-bound pod port-forward/exec is supported for access.

## HTTP State Ownership

`STATE_BACKEND` resolves to `none` for HTTP and `sqlite` for local stdio.
Incompatible explicit backends reject startup. HTTP never opens SQLite,
PostgreSQL, Redis, local artifact/cache stores, a submission journal or a
filesystem lease. Local stdio retains its artifact and bookkeeping features.
The chart uses a stateless Deployment with HPA/PDB/hostname spread and no
application state volume. See [VKE Deployment](SPEC_VKE_DEPLOYMENT.md).

There is no hosted state to restore or replay. Restarting a pod does not
cancel provider work; clients must retain IDs and poll with authorized provider
credentials. A lost create response may hide billed work and must be reconciled,
not resubmitted automatically.

This is a fresh stateless deployment. Historical database compatibility and
stateful-release migration tooling are not part of this repository.

Shutdown allows `max(tool timeout, provider timeout in seconds) + 30`;
pod termination grace uses the same maximum plus 60 (defaults 630/660 seconds).
Draining is cooperative, not a guarantee that upstream work stops.

## HTTP Submission Safety

The Seedance input schema retains nullable legacy
`idempotency_key` fields so old clients receive an explicit rejection.
Non-null values are rejected before dispatch on both transports, including
Seedance dry runs. Omit the field.

Identical creates are independent operations and may bill again. No root claim,
saved-success replay, failed-batch resume or exactly-once billing is provided.
Do not repeat a create for delivery recovery or polling. Retain known
task/request IDs, poll through the provider-authorized task tools, and reconcile
uncertain or lost responses with the provider.

Safe accepted IDs are captured only in the live invocation, before the next
await, for partial/deadline diagnostics. HTTP task/request IDs must match
`[A-Za-z0-9._:-]{1,256}` and must not echo request/operator secrets. Unsafe
receipts fail with ambiguous, nonretryable `UNSAFE_TASK_RECEIPT` without echo.
A crash or lost response can lose an accepted ID; the server cannot recover it.
No raw prompts, media, credentials or error messages are journaled.

## Remaining Acceptance

Actual model-driven Codex/Claude tool execution and paid provider validation remain pending.
Isolated `codex mcp get --json` / `claude mcp get` configuration inspection
can establish parsing only, not tool use or upstream authorization. An
unapproved Claude project entry remains unapproved. A loopback network smoke
with synthetic headers and mocked providers establishes only the tested
transport path, not live provider access, deployed TLS or customer endpoint
lineage. Neither check authorizes changing real client configuration,
credentials or trust settings.

The maintained `scripts/hosted_acceptance.py --caddy-bin PATH` checks isolated
real HTTP/Caddy TLS with mocked providers and bounded synthetic load.
Mock measurements are not capacity certification. Live VKE apply, source IP,
rollout/drain and real-client/provider acceptance remain unverified.
Terraform uses dedicated fresh state. Source deletion is not cloud
decommissioning; any infrastructure retirement requires separate approval.

## Sources

- Current implementation: `server.py`, `security/http_middleware.py`,
  `config/env.py`, `config/model_capabilities.py`, `tools/ark_list_models.py`,
  `tools/_seedance_shared.py`, `domain/submissions.py`, `state/stateless.py`,
  `runtime.py`, `execution.py`, and provider gateway adapters.
- [FastMCP background tasks](https://gofastmcp.com/servers/tasks), accessed
  2026-11-16: per-call extension opt-in and execution modes. The application
  boundary above is verified against this checkout, not inferred from framework defaults.
- [GetEndpoint](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/get-endpoint-api#authentication),
  documentation body and linked OpenAPI schema verified 2026-11-17: Access Key
  V4 authentication and foundation-model lineage fields, not Bearer metadata access.
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
  and [Claude Code MCP](https://code.claude.com/docs/en/mcp): client header and
  timeout configuration. Snippet generation is not model-driven client certification.
