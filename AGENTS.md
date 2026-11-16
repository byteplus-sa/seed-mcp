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
  estimates, not account-specific quotes.
- **Seed Audio** — full-scene audio generation through Seed Speech
  (`seed_audio_generate`, including parallel variations).
- **Seedream** — image generation and editing through ModelArk with one
  tool, `seedream_generate_image` (generate, edit with point/bbox,
  transparent background, variations, dry run).
- **Seedance** — asynchronous video generation through ModelArk with one
  create tool, `seedance_create_task`. Supports two model generations: 2.0
  (legacy, 15s, 4K) and 2.5 (default, 30s, 4K, structured editing, native
  extension). Seedance 2.5 uses `dreamina-seedance-2-5-260628` for all supported
  resolutions, including `resolution="4k"`; no separate model or feature gate.
  Seedance 2.5 Flash (`dreamina-seedance-2-5-flash-261115`, family
  `seedance_2_5_flash`) uses the same tool, supports 480p/720p and 4-30s with
  reference/edit/extend features and 10 images / 5 videos / 5 audios, but no
  Draft mode. Regular 2.5 Drafts have a 14-day window for creation at or after
  2026-10-28 10:00 UTC+8; earlier Drafts retain seven days. Authenticated HTTP
  with regular 2.5 enabled requires `STATE_PRUNE_MAX_AGE_DAYS >= 14`. Empty bindings
  add Flash alongside the selected default; explicit binding lists remain
  authoritative. Regular 2.5 remains the default. Retained regular 2.5 4K
  acceptance differs from current model-specific provider docs; see
  `docs/models.md` for the contract caveat.
- **Generation tasks** — `gen_task_get`, `gen_task_list` and
  `gen_task_cancel_or_delete` poll, list and cancel Seedance tasks
  (scopes `gen:read` / `gen:delete`).
- **OmniHuman 2.0** — image + audio to talking-avatar video through BytePlus
  Vision AI (`omnihuman_create_task`, `omnihuman_get_task`,
  `omnihuman_cancel_task`). Bearer `BYTEPLUS_CV_API_KEY`; gated by
  `BYTEPLUS_OMNIHUMAN_ENABLED`; disabled by default.
- **Seed 2.1 Understanding** — multimodal video/image understanding and
  reasoning through ModelArk Chat Completions; supports deep-thinking mode.
- **Seed Audio Understanding** — audio understanding and reasoning
  (transcription, translation, analysis, Q&A) through ModelArk Chat Completions
  `input_audio`; model ID set by `SEED_AUDIO_UNDERSTANDING_MODEL`. URL inputs
  can use the Files API for oversized audio and video soundtracks (up to
  512 MB); uploaded files are deleted best-effort after processing.
- **Local object storage upload** — stdio-only `media_upload` / `media_presign` take lists and
  return presigned URLs for URL-only media workflows (TOS or S3 backend).
- **Native asset references** — Seedance accepts existing authorized
  `asset://<id>` references natively with the ModelArk Bearer key. The server
  does not create, verify, administer, resolve or preflight provider assets.
- **Local background jobs** — ordinary `ark_job_*` tools are the stdio-only default route for
  long-running work through the FastMCP worker, since most clients cannot
  negotiate MCP task augmentation; native tasks remain supported for clients
  that can.
- **Local durable artifacts** — stdio-only MCP resources for generated media whose provider URLs
  expire (2h for Seed Audio, 24h for ModelArk image/video, about 1h for OmniHuman).
- **Transports** — local stdio retains jobs/native tasks/storage/artifacts.
  HTTP is forward-only BYOK: 9 provider/discovery tools, or 12 with OmniHuman,
  direct foreground calls, no jobs/native tasks/storage/artifact tools/resources.
  `MCP_AUTH_MODE=byok` is the default; explicit `local` is stdio-only and
  `api_key` is removed. No OAuth/signup/server-issued key. HTTP requires
  operator `MCP_IDENTITY_HMAC_KEY` (64 lowercase hex) and positive
  `MCP_IDENTITY_KEY_VERSION` (default 1), not customer credentials.

Seedance, Seedream, Seed 2.1 Understanding, and Seed Audio Understanding
share the ModelArk data-plane host and Bearer authentication. Seed Audio
uses Seed Speech and `X-Api-Key`; OmniHuman uses Vision AI and its own
Bearer key. These three provider gateways sit behind one normalized domain
layer. See `docs/architecture.md` for current behavior.

The local catalog contains **21 tools**, with eight always registered on stdio. Enabled
tools depend on the four service gates: `modelark`, `seed_audio`, `omnihuman`,
and `object_storage`. VOD processing, 3D generation, dedicated ASR, asset
administration and operator-account live pricing are not part of this server.
Local provider keys are startup configuration. HTTP uses only live
`X-ModelArk-Api-Key`, `X-Seed-Speech-Api-Key` or `X-OmniHuman-Api-Key` for the
selected provider plus required `X-MCP-Client-Secret` (client-generated 32
random bytes, 64 lowercase hex), including dry runs. Discovery is anonymous/static.
Keys are not persisted and never fall back to environment provider keys.

HTTP endpoint defaults `X-ModelArk-Seedance-Endpoint` and
`X-ModelArk-Seedream-Endpoint` require exact registry bindings; explicit tool
`model` wins. Never infer arbitrary opaque endpoint lineage. HTTP uses fixed
official origins, positive 60 RPM / 2 MiB body / 64 in-flight defaults and
`STATE_MAX_RECORDS=100000`. Readiness is minimal state-only, with no provider
probes; public metrics are unavailable.

Fresh SQLite ownership is keyed by `(provider, tenant_id, task_id)` with an
immutable client owner; no compatibility migration. Global persistence defaults
are false for Seed Audio, Seedream and OmniHuman get; HTTP rejects true while
local explicit true remains supported. Files API cleanup uses the live request
key; remote file expiry is separate from output URL expiry.
Uncertain mutation transport failures and malformed 2xx responses are
ambiguous/nonretryable with safe diagnostics. Durable idempotency, crash
recovery, PostgreSQL and multi-replica support remain next phase; no public
launch claim. See `specs/SPEC_HOSTED_BYOK.md`.

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
This is the published handbook: how to install, configure, run, deploy, and
troubleshoot the server.

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
