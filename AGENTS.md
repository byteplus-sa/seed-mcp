# AGENTS.md

## Project

Ark Seed Multimodal MCP Server — a Python MCP server (FastMCP on uv)
that exposes BytePlus multimodal generation through a small, typed, safe tool
surface. **One tool per capability**: models, variations, edit modes and
dry runs are parameters validated against the capability registry, not
separate tools. The flow is discovery → create → poll:

- **Discovery** — `ark_list_models` returns the bound models, their limits,
  and the tool that serves each one, from the static tool catalog
  (`tools/_catalog.py`) and the capability registry. Discovery makes no
  provider calls and returns no account pricing. Cost previews use built-in
  estimates, not account-specific quotes. Default discovery is static/anonymous
  with `connection=null`. Opt-in `check_connection=true` requires live HTTP
  and checks ModelArk/client-secret header presence plus exact image/video
  bindings only; omit `kind` for both. Stdio checks are rejected.
  It never proves authentication, live lineage, entitlement or reachability.
- **Seed Audio** — full-scene audio generation through Seed Speech
  (`seed_audio_generate`, including parallel variations).
- **Seed TTS 3.0** — `seed_tts_generate` speaks text or SSML with an
  authorized voice through Seed Speech. Direct call, bounded JSONL collection,
  MP3/PCM/Ogg Opus, pronunciation/delivery controls and optional word alignment.
  Stdio always persists; opt-in HTTP uses private temporary TOS output and returns
  a signed download URL. `MCP_HOSTED_TTS_ENABLED=false` by default; enabling needs
  restricted static TOS credentials and a private versioning-disabled bucket.
  One-day scheduled object expiry, nominal 24-hour URLs (STS may shorten), no
  database/local files/renewal/replay or HTTP Base64 fallback. Hold admission through
  upload; never automatically resynthesize after delivery failure. No provider URL,
  `persist` flag or jobs. Discovery includes configured TTS with `kind="audio"`;
  HTTP preflight remains image/video only. See `docs/seed-tts.md`.
- **Seedream** — image generation and editing through ModelArk with one
  tool, `seedream_generate_image` (generate, edit with point/bbox,
  transparent background, variations, dry run).
  Seedream 5.5 high-resolution output uses explicit `size="3840x2160"` for
  4K UHD on the same model, with a maximum of 8,294,400 pixels. Named tiers
  remain 1K/1.5K/2K; no undocumented `4K` alias. Built-in 5.5 estimates use
  output pixel tiers plus input-image charges per variation, not account quotes.
- **Seedance** — asynchronous video generation through ModelArk with one
  create tool, `seedance_create_task`. Supports two model generations: 2.0
  (legacy, 15s, 4K) and 2.5 (default, 30s, 4K, structured editing, native
  extension). Seedance 2.5 uses `dreamina-seedance-2-5-260628` for all supported
  resolutions, including `resolution="4k"`; no separate model or feature gate.
  Seedance 2.5 Flash (`dreamina-seedance-2-5-flash-261115`, family
  `seedance_2_5_flash`) uses the same tool, supports 480p/720p and 4-30s with
  reference/edit/extend features and 10 images / 5 videos / 5 audios, but no
  Draft mode. Regular 2.5 Drafts have a 14-day window for creation at or after
  2026-10-28 10:00 UTC+8; earlier Drafts retain seven days. HTTP uses provider authorization and does
  not retain ownership or run state pruning. Empty bindings
  add Flash alongside the selected default; explicit binding lists remain
  authoritative. Regular 2.5 remains the default. Retained regular 2.5 4K
  acceptance differs from current model-specific provider docs; see
  `docs/models.md` for the contract caveat.
- **Generation tasks** — `gen_task_get`, `gen_task_list` and
  `gen_task_cancel_or_delete` poll, list and cancel Seedance tasks
  (scopes `gen:read` / `gen:delete`).
- **Local object storage upload** — stdio-only `media_upload` / `media_presign` take lists and
  return presigned URLs for URL-only media workflows (TOS or S3 backend).
- **Temporary HTTP references** — opt-in `media_prepare_upload` signs exact-key
  TOS multipart POST/GET permissions for operator-enrolled client secrets.
  Metadata only; clients upload directly, file last, before using the GET URL.
  Fixed 15-minute upload / 24-hour reference / one-day scheduled object expiry.
  No database, byte inspection, upload receipt, renewal or global storage quota.
- **Native asset references** — Seedance accepts existing authorized
  `asset://<id>` references natively with the ModelArk Bearer key. The server
  does not create, verify, administer, resolve or preflight provider assets.
- **Direct execution** — both transports await ordinary tool calls. No MCP
  jobs, native tasks, snapshots or execution claims exist. Provider video
  queues remain asynchronous; retain their task IDs and poll.
- **Local durable artifacts** — stdio-only MCP resources for generated media whose provider URLs
  expire (2h for Seed Audio, 24h for ModelArk image/video).
  Inline provider audio has no store byte cap; input references, URL downloads,
  inline fallback and TTS stream collection retain their separate bounds.
- **Transports** — local stdio retains storage/artifacts.
  HTTP is BYOK: 7 baseline provider/discovery tools,
  direct foreground calls, no jobs/native tasks/local storage/artifact tools/resources.
  Hosted TTS and temporary upload preparation each add one optional tool (up to 9).
  `MCP_AUTH_MODE=byok` is the default; explicit `local` is stdio-only and
  `api_key` is removed. No OAuth/signup/server-issued key. HTTP requires
  operator `MCP_IDENTITY_HMAC_KEY` (64 lowercase hex) and positive
  `MCP_IDENTITY_KEY_VERSION` (default 1), not customer credentials.

Seedance and Seedream share the ModelArk data-plane host and Bearer authentication. Seed Audio and Seed TTS
uses Seed Speech and `X-Api-Key`. These two provider gateways sit behind one normalized domain
layer. See `docs/architecture.md` for current behavior.

The catalog contains **14 definitions**, with **13 local tools** and four always registered on stdio. Enabled
provider/storage tools depend on `modelark`, `seed_audio`, `seed_tts`,
and `object_storage` gates. VOD processing, 3D generation, dedicated ASR, asset
administration and operator-account live pricing are not part of this server.
Local provider keys are startup configuration. HTTP uses only live
`X-ModelArk-Api-Key` or `X-Seed-Speech-Api-Key` for the
selected provider plus required `X-MCP-Client-Secret` (client-generated 32
random bytes, 64 lowercase hex), including dry runs. Discovery is anonymous/static.
Keys are not persisted and never fall back to environment provider keys.
Temporary upload signing and hosted TTS delivery use operator TOS credentials,
never generation keys. `MCP_TEMPORARY_UPLOAD_ENABLED=false` by default; enabling requires HTTP,
TOS configuration and `MCP_UPLOAD_CLIENT_SECRET_SHA256` (1-1000 unique lowercase
SHA-256 digests of exact ASCII client-secret header values, not decoded bytes).
Only enrolled secrets authorize signing; no provider key is required for this
tool. Require a dedicated private versioning-disabled bucket, restricted IAM,
CORS where needed, lifecycle backstop and operator storage/egress controls.
Helm `temporaryUpload.enabled`/`existingSecret` reference a distinct existing
TOS/enrollment Secret. No automatic storage provisioning. See
`docs/temporary-uploads.md` and the hosted contract.

TOS signing defaults to `TOS_CREDENTIAL_MODE=static`. Explicit `irsa` is
HTTP-temporary-upload-only and rejects configured AK/SK/session tokens.
Use exact `TOS_IRSA_ROLE_TRN`, absolute `TOS_IRSA_TOKEN_FILE`, allowlisted
BytePlus STS origin and requested session 3600-43200 seconds (default 3600).
No ambient metadata/environment fallback. Runtime-owned single-flight refresh
is lazy after enrollment/admission, five minutes early with ten-second failure
backoff; never reuse the final sixty seconds. Freeze one triplet for POST/form/
GET. Discovery/readiness do not read tokens or exchange with STS.
Helm `temporaryUpload.credentialsMode=irsa` requires acknowledged prerequisites
and an explicit non-default ServiceAccount. It manually projects audience
`sts.volcengine.com` only into the app, never Caddy, with automatic mounting off.
Cluster OIDC enablement, exact issuer/namespace/ServiceAccount trust, least
privilege and webhook exclusions remain operator-owned; no IAM provisioning.
STS expiry can shorten nominal 24-hour references to an hour or less; refresh
does not renew issued URLs. Live BytePlus OIDC endpoint acceptance and token
rotation remain staging gates, not established by offline tests.

HTTP endpoint defaults `X-ModelArk-Seedance-Endpoint` and
`X-ModelArk-Seedream-Endpoint` require exact registry bindings; explicit tool
`model` wins. Never infer arbitrary opaque endpoint lineage. HTTP uses fixed
official origins, positive 60 RPM / 2 MiB body / 64 in-flight defaults and
local-only `STATE_MAX_RECORDS=100000`. HTTP readiness is lifespan-only,
with no storage or provider probes; public metrics are unavailable.

Unknown endpoint IDs are not echoed by preflight or endpoint lookup errors;
the operator must verify and bind them. Official GetEndpoint documentation
body and OpenAPI require Access Key V4 (AK/SK), not ModelArk Bearer auth.
No AK/SK custody or arbitrary BYOE self-service is implemented. Keep the
durable contract in `specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority`.
`scripts/configure_http_client.py` emits stdout-only Codex/Claude snippets
with distinct environment-name references; no file/env-secret reads, writes,
client commands or network calls. HTTPS is required except explicit isolated
loopback HTTP. Endpoint env-name options require `modelark`.
Codex uses `env_http_headers`/`tool_timeout_sec`; Claude uses `${VAR}` headers
and `timeout` in milliseconds. Actual model-driven client and paid provider
validation remain pending; isolated config inspection and mocked-network
smoke cannot establish that acceptance.

Hosted HTTP uses `STATE_BACKEND=none` automatically. It never opens SQLite,
PostgreSQL or Redis, stores task IDs, or provides durable replay, deduplication
or a budget ledger. Local stdio retains `STATE_BACKEND=sqlite` for artifacts
and local bookkeeping. Explicit incompatible backends fail startup.
Non-null `idempotency_key` is a rejected legacy input on both transports.
Never automatically resubmit uncertain creates; clients retain task/request IDs.
Task get/list/cancel and Draft lookup rely on provider-key authorization, not
client-secret ownership. Clients sharing a provider key share whatever access
the provider permits. HMAC/client-secret scopes only separate per-pod admission.
Rate and concurrency limits reset at restart and multiply with replicas.
HTTP requires `DAILY_BUDGET_USD=0`; use provider-side spend controls.

Direct-call settings: `MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite, positive,
max 30) bounds owner-first then provider-slot waiting;
`MCP_TOOL_TIMEOUT_SECONDS=600.0` (finite, positive, max 3600) starts at wrapper
entry after MCP parsing and before credentials and admission.
Stdio reserves budget after admission. Active/waiting owner limiters remain pinned.
`ADMISSION_TIMEOUT` means this attempt did not dispatch, not the whole batch.
`TOOL_DEADLINE_EXCEEDED` is text-only and preserves mutation uncertainty and
known safe accepted IDs. TTS also retains bounded request-only IDs after
dispatch, including persistence deadlines; these are not tasks or proof of
acceptance and are cleared at invocation exit. External cancellation propagates. SDK/SQLite draining
may exceed the cooperative deadline; timeout is not provider cancellation.
HTTP keeps safe accepted IDs only in the live invocation for deadline diagnostics.
Stdio cancellation drains local bookkeeping; dispatched reservations commit,
undispatched reservations release. No hosted submission journal exists.
Use client timeout 660 seconds and compatible proxy settings. Never blindly
resubmit. Local writes use live MCP roots or `OUTPUT_ROOTS`.
The static exporter uses top-level and per-transport `execution: "direct"`,
with no `background` key. See `specs/SPEC_DIRECT_EXECUTION.md` for the current
contract.

Hosted deployment follows `specs/SPEC_VKE_DEPLOYMENT.md`:
dedicated VKE replaces ECS/Compose.
Terraform root `deploy/terraform/vke` requires dedicated fresh state, separate
from unrelated deployments. No historical database inspection, compatibility
or stateful-release migration tooling is maintained. Source deletion is not
cloud decommissioning. Never automatically requeue uncertain provider work.

The chart uses a stateless Deployment with HPA (default 2-6 pods), PDB and
hostname spreading, without a database or state volume. Kubernetes >=1.30 is
required; verify a maintained regional release. Spread counts each
`pod-template-hash` revision using the default-enabled
`MatchLabelKeysInPodTopologySpread` feature. Verify final worker diversity after
rollout/scale-in; scheduling does not automatically rebalance survivors.
Caddy exposes `/mcp` and
`/health` only; `/ready` is lifespan-only and private. The chart contains no
legacy StatefulSet or StorageClass templates. Local stdio storage remains current
functionality, separate from hosted deployment.

`MCP_METRICS_PORT=0` disables private metrics; HTTP-only nonzero 1024-65535
ports bind 127.0.0.1. Helm enables 9000 only via `app.metricsEnabled`; no public
metrics Service. `scripts/generate_identity_secret.py` remains standalone.
Terraform stores no HMAC/TLS Secret/kubeconfig; Helm references distinct
existing identity and TLS Secrets plus a distinct optional TOS/enrollment Secret.
Private API access requires operator private connectivity.

Manual `.github/workflows/deploy-vke.yml` Helm delivery uses main-only dispatch,
production-only `target=production` and literal protected
`byteplus-production` approval with a workflow-restricted private runner
group. Labels alone are not isolation for this public repository. A same-VPC
runner needs no laptop VPN/CEN. `scripts/deploy_vke.py` checks explicit private
kubeconfig/API, nodes, metrics and existing identity/TLS fields, then optionally
dispatches Helm once (15-minute Helm / 30-minute job limits). No Terraform apply,
IAM federation, secret sync, namespace creation, automatic retry or rollback.
Raw subprocess output is captured, not logged or uploaded. Preserve separate
operator state and addon ownership. GitHub OIDC acceptance is not established by
VKE IRSA docs. See `docs/github-actions-deployment.md`; keep readiness flags false
until private runner isolation and live prerequisites are independently verified.
Production needs a pre-existing verified protected environment, separate
`VKE_PRODUCTION_ENABLED`, runner-ready/group variables and protected
`VKE_PRODUCTION_APPROVED`. The workflow consumes only production readiness/group
variables, defaults to `operation=check` and rejects staging targets and
non-production service modes. Keep the historical `byteplus-staging-delivery`
concurrency key to serialize old and current runs; do not rename the live
`seed-mcp-staging` namespace or `seed-mcp` release. Retain the protected disabled
GitHub staging record and explicit false legacy/prerequisite guards until
pre-cutover rerun windows expire and no old attempts remain active or queued.
Final environment deletion is a separate verified operator action, not cloud
decommissioning. The generic helper/chart retain synthetic and CLB support;
there is no implicit CLB fallback.

Terraform keeps two fixed private on-demand baseline nodes by default.
`burst_node_max_count=0` disables a separate optional burst pool; positive
values start/minimum at zero and cap baseline plus burst at ten nodes.
Only burst `auto_scaling.desired_replicas` is ignored by Terraform.
Cluster Autoscaler discovery, scale-from-zero, automatic scale-in and drain
settings remain VKE-admin owned; HPA does not scale workers. Drain timeout
must exceed configured application pod grace (660 seconds by default).
The chart lists only disposable `app-tmp,proxy-tmp` in
`cluster-autoscaler.kubernetes.io/safe-to-evict-local-volumes`; it does not
bypass PDB, scheduling constraints or shutdown grace, or disable local-volume
protection globally. Verify application rescheduling and scale-in live.
Baseline and networking charges remain at idle; node bounds are not a spend cap.
Live elasticity and capacity require separate evidence.

Terraform `public_gateway_enabled=false` keeps optional dedicated APIG
preparation off. Enabling requires an explicit distinct regional secondary AZ
and adds two gateway subnets/two standard gateway nodes only, no service,
upstream, routes or generic endpoint. Pinned-provider logging configuration
cannot express destination-free disablement; require disabled readback by
postcondition. Native APIG rejects partial disabled `TraceSpec`; omit tracing
input and require disabled tracing readback too. Failure may follow creation:
inspect state/cloud before retries.
Never attach BYOK routes until logging and the approved backend trust decision
are satisfied. Default policy requires verified private HTTPS; the exact
deployment exception below waives backend identity verification only.
The chart defaults to public CLB/Caddy. Opt-in `service.mode=apig-staging`
uses private ClusterIP:8443/ingress policy and separate `backendHost`, refuses
credential headers and forbids uploads. It is synthetic-only, not a BYOK
launch or backend trust fix. Keep public application routes disabled.
`apig-production` is separate private BYOK source support with the same network
boundaries and uploads disabled. It forwards supported credentials/endpoint
headers and rejects Authorization, including empty values. It requires
`service.productionConfirmed=true` and helper `--production-approved`, not
staging readiness; these are acknowledgements, not APIG verification. No native
APIG trust control has been established or deployed. Certificate renewal uses
operator-managed versioned TLS Secrets and protected reference rollouts,
with per-replica served-certificate checks; same-name data has no automatic
rollout/reload guarantee. See `docs/backend-certificate-renewal.md`.
The private production listener is HTTP/1.1-only after a reproduced HTTPX H2
GOAWAY drain failure; public APIG protocol behavior remains a separate live gate.
On 2026-11-25 the operator explicitly selected "Keep HTTPS, waive verification"
for the existing Seed MCP APIG deployment. See
`specs/SPEC_VKE_DEPLOYMENT.md#accepted-backend-verification-exception` for exact
scope and accepted private-hop impersonation/credential-exposure risk. Do not
continue blocking that deployment on a native APIG trust control or certificate-
negative tests; these are deferred hardening, not verified/passed checks.
Keep public TLS verification, private HTTPS encryption, restricted ingress,
certificate preflight/renewal, logging/routing and other launch gates. The
exception does not authorize deployment, route enablement, paid calls, credential
use/rotation, commit or push by itself, and is not a default for other deployments.
Temporary tests require verified operator-only exact header matching at APIG
and immediate disable/404 readback. Replenish ephemeral runners per job.
Explicit operator approval can permit provisioning first and
billing review afterward; real BYOK still requires TLS/logging/stateless routing
and host/proxy-trust acceptance. Quota failure requires verified headroom, not
unapproved unrelated-network reuse or deletion. Exact operator-approved
retirement requires dependency rechecks and confirmed absence; keep its evidence
separate from the new dedicated state. Reconcile tasks/state/inventory before
fresh plans or new create attempts. See `docs/hosted-deployment-status.md`;
do not silently substitute the CLB path for an approved gateway design.

Helm `models.seedream`/`models.seedance` expose `defaultModel` and
`bindings: [{model_id, family}]`, with strict product families, unique IDs
and selected-default inclusion. Alternate defaults require explicit verified
bindings; used request headers still need exact registry matches and explicit
tool `model` wins. No endpoint authority change or arbitrary env map.
Chart runtime defaults are `app.dailyBudgetUsd=0` (HTTP requires zero),
`providerMaxConcurrency=5`, `principalMaxConcurrency=3`, `rateLimitBurst=0`.
These are explicit per-pod env mappings, not account spend caps.

`scripts/hosted_acceptance.py --caddy-bin PATH` runs isolated mock-only TLS/load
checks without a database or live provider calls. Live VKE routing, rollout,
capacity and client/provider validation remain separate approved gates.
`scripts/hosted_drain_acceptance.py --caddy-bin PATH --profile short|production`
tests accepted mock work through TERM with no retries; production uses six
parallel 590s calls and 600/630/660s clocks. Both H1 and H2-capable client offers
must negotiate H1 on the private production listener. Only short runs in CI.
These process checks do not prove APIG trust, new-intake withdrawal, certificate
rotation or live node drain. Test-only h2 is a dev dependency, not a runtime feature.

## Repository Layout

```text
ark-mcp/
├── AGENTS.md          # project conventions for agents (this file)
├── CLAUDE.md          # redirects to AGENTS.md
├── README.md          # project overview and quickstart
├── Makefile           # task runner (wraps uv + fastmcp CLI)
├── pyproject.toml     # project metadata and dependencies (uv)
├── uv.lock            # locked dependencies for reproducible installs
├── fastmcp.json       # declarative FastMCP server configuration
├── .agents/skills/    # canonical project skills (source of truth)
├── .claude/skills/    # per-skill symlinks mirroring .agents/skills/
├── plans/             # implementation plans for features
├── specs/             # future-looking specs and design docs
├── docs/              # project documentation
├── scripts/           # live smoke tests and utility scripts
├── src/ark_mcp/  # server source (Python package)
└── tests/             # tests (pytest)
```

## Skills and Agent Configuration

Agent skills and the agent rule files must stay aligned across the tools
that read this repository:

- **`.agents/skills/` is the canonical source of truth** for project
  skills. Add and edit skills here. `skills-lock.json` pins externally
  sourced skills (e.g. `mcp-builder` from `anthropics/skills`); locally
  authored skills (`fastmcp`, `fastmcp-docs`) are committed directly.
- **`.claude/skills/` mirrors `.agents/skills/`** through one relative
  symlink per skill (e.g. `.claude/skills/mcp-builder` →
  `../../.agents/skills/mcp-builder`). When you add a skill under
  `.agents/skills/<name>/`, also create the matching
  `.claude/skills/<name>` symlink so Claude Code discovers the same skill.
  Never edit files through the `.claude/skills/` symlinks — change
  `.agents/skills/` and both trees update.
- **Keep project skills current with the MCP server.** When a code change
  adds, removes, renames, or materially changes MCP tools, resources,
  configuration, auth scopes, transport behavior, or output schemas, update
  the affected skill docs in `.agents/skills/` in the same unit of work.
  Treat agent-facing skills as shipped documentation for the current server,
  not as optional follow-up polish.
- **`CLAUDE.md` imports `AGENTS.md`.** `CLAUDE.md` contains a single
  `@AGENTS.md` import so Claude Code loads the same rules. Edit `AGENTS.md`
  only; never duplicate content into `CLAUDE.md`, so the two stay in sync.

## Documentation Standard

All non-code documentation lives in one of three top-level directories. Keep
their purposes distinct and do not mix them.

### `plans/` — Plans for features

Concrete, actionable implementation plans for a specific feature or unit of
work. A plan describes **how** to build something, with enough detail (code
structures, API signatures, data models, file organization, phases) that an
engineer or agent can execute it without re-deriving the design.

- Naming convention: `PLAN_<FEATURE_OR_SCOPE>.md`.
- Include frontmatter (`title`, `type: plan`, `status`, `created`, `updated`,
  `tags`, `source`, `related`) when the plan draws on external research.
- `status` is one of `draft`, `proposed`, `accepted`, `in-progress`,
  `shipped`, `superseded`, or `deprecated`.
- A plan is a living document: update `status` and `updated` as work
  progresses. Once shipped, the durable decisions should move to `specs/` or
  `docs/` and the plan can be archived or marked `status: shipped`.
- Reference the plan by path when writing code that implements it.

### `specs/` — Future-looking specs and design docs

Specifications describing what the system **is or will be**, independent of any
single implementation effort. Specs are the source of truth for contracts,
interfaces, and intended behavior. A spec may describe current reality ("what
it is today") or a future state ("what it will become"); label the horizon
explicitly when it matters.

- Naming convention: `SPEC_<DOMAIN_OR_CAPABILITY>.md`, or a short descriptive
  filename for cross-cutting specs (e.g. `security.md`, `error-model.md`).
- Include frontmatter with `status: draft | proposed | accepted | deprecated`
  and a `horizon: current | future` field when the spec is forward-looking.
- Specs hold: API contracts, tool schemas, data models, security models, error
  taxonomies, capability registries, and architecture decisions that outlive a
  single plan.
- Prefer updating an existing spec over creating a new one. When a spec is
  superseded, mark it `deprecated` and point to the successor rather than
  deleting it.

### `docs/` — Project documentation

User- and contributor-facing documentation for the project as it exists today.
This is the project handbook: how to connect, configure, run, deploy, and
troubleshoot the server. GitHub Pages publishes only the curated hosted guide
and hosted tool pages (seven baseline plus optional TTS) selected in `docs/site/scripts/publication.mjs`.
Operator/local material remains in the repository, outside site search and
navigation. Keep old public URLs redirected when consolidating pages.

- Examples: `getting-started.md`, `configuration.md`, `transports.md`,
  `tools.md`, `deployment.md`, `troubleshooting.md`.
- Documentation describes **current** behavior. When something is planned but
  not yet built, link to the relevant entry in `plans/` or `specs/` instead of
  documenting it as if it already works.
- Keep docs in sync with the shipped code. If the code and docs disagree, the
  code is correct until the docs are updated; open a follow-up if they cannot
  be reconciled immediately.

## Working Conventions

- **Read before writing.** Before implementing, read the relevant plan in
  `plans/`, the applicable specs in `specs/`, and any existing docs in `docs/`.
- **Plans reference specs.** A plan may quote or link to a spec, but the spec
  remains the long-lived source of truth. Do not duplicate a contract into a
  plan and then let the two drift; link instead.
- **Docs reflect shipped work.** Do not document a feature in `docs/` until it
  is built. Use `plans/` and `specs/` for not-yet-shipped work.
- **Keep docs and skills in lockstep with shipped MCP changes.** If a server
  change affects tool inventory, resources, schemas, env vars, or user-facing
  workflows, update the relevant files in `docs/`, `README.md`, and
  `.agents/skills/` before considering the work complete. If full reconciliation
  is too large for the current task, document the remaining drift explicitly.
- **Frontmatter.** Plans and specs use YAML frontmatter. Docs may use
  frontmatter for title and weight/order but are not required to.
- **Diagrams.** Use Mermaid for architecture, sequence, and flow diagrams. Keep
  diagrams in the relevant plan or spec and update them when the design
  changes.
- **Sources.** When a plan or spec draws on external documentation, record the
  URLs in a `source:` frontmatter field or a `## Sources` section with access
  dates. Prefer official BytePlus and Model Context Protocol sources.
- **Secrets.** Never commit credentials, API keys, or provider response
  fixtures containing real media. Redact before saving examples.

## Repository Hygiene

The repository should contain only source code, tests, configuration,
documentation, plans, specs, and skills — **not** generated media, scratch
reports, or transient review artifacts. The following must never be committed:

- **Generated media at the repository root.** This includes `*.mp4`, `*.wav`,
  `*.mp3`, `*.jpeg`, `*.png`, `*.mov` files produced by the MCP tools, smoke
  tests, or manual experiments (e.g. `ppop-*.wav`, `output_*.mp4`,
  `seedance_*_test_*.mp4`). Move them to `.artifacts/` or `out/` (both
  gitignored) or delete them.
- **Generated output directories.** `output/`, `assets/`, and `sample/` are
  scratch containers for demo or experiment output. Do not commit them.
- **PR review scratch files.** `pr-reviews/` holds transient review reports
  produced during PR cycles. Delete them after the PR is merged or closed.
- **One-off reports and handovers.** Files like `CODE_REVIEW_REPORT.md` and
  `HANDOVER.md` are session-scoped artifacts. If their content has lasting
  value, distill it into `docs/` or `specs/`; otherwise delete them.
- **Shipped, superseded, or deprecated plans.** Once a plan reaches
  `status: shipped`, `status: superseded`, or `status: deprecated`, remove it
  from `plans/`. Move durable decisions into `specs/` or `docs/` first.
- **Build artifacts and runtime state.** `.artifacts/`, `out/`, and `dist/`
  are gitignored. Never force-commit them.

When in doubt about whether a file is scratch, treat it as scratch and delete
it. Practice CLAYGO — clean as you go, not just at the end of a task.

## Tool Contract Rules

Every MCP tool must be self-describing for MCP clients (Claude Desktop,
Cursor, TRAE, etc.) without requiring external documentation. These rules are
mandatory for all new and modified tools:

- **Function docstring required.** Every tool handler function MUST have a
  docstring. FastMCP uses this as the tool's `description` field in the MCP
  schema. A tool with no docstring appears as an empty description to clients.
- **Every field needs a description.** Every field on every Pydantic model
  that appears in a tool's input or output — including nested and shared
  domain models — MUST have a `Field(description=...)`. Bare declarations like
  `task_id: str` are not acceptable. This includes `Literal` fields with
  defaults (e.g. `provider: Literal["x"] = Field("x", description=...)`).
- **Descriptions must be accurate.** Field descriptions must match what the
  code actually produces. Reference units (seconds, milliseconds, bytes),
  enumerations, ranges, and mutual exclusivity where applicable.
- **Output models are client-facing.** MCP clients use JSON schema field
  descriptions to interpret tool results. Treat output model descriptions as
  shipped user documentation, not internal comments.
- **Shared domain models are client-facing.** Models in `domain/models.py`,
  `domain/media.py`, `domain/artifacts.py`, and `domain/transcription.py`
  appear in tool output schemas. All their fields need descriptions too.
- **Internal-only models are exempt.** Provider DTOs, config models, and
  security models that never appear in an MCP tool's `inputSchema` or
  `outputSchema` do not need descriptions (though they benefit from them).
