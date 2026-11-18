---
title: Connect to a Shared Server
description: Use an existing administrator-managed Ark MCP server without installing Python, Git or uv locally.
---

**Already have an Ark server URL from your team? Skip local installation.**
Your operator runs the server; your client connects over HTTPS with BYOK.
You do not need Python, Git, uv or a local server checkout.

This repository does not provide a public hosted endpoint. The documentation
website is not an MCP server. Without an existing managed endpoint, use
[guided local setup](install.md).

## What You Need

Ask your administrator for:

- The exact HTTPS MCP endpoint, including its path.
- The supported model bindings and whether OmniHuman is enabled.
- Private custom-header instructions for your client. You supply your own
  provider key and generate your own client isolation secret.

Use only a server you trust: it receives your prompts and media references,
and your live provider credentials. The server does not persist those keys.
Connecting to a server does not mean generation is free.

## Connect

1. Open your client's MCP or connector settings.
2. Choose the supported **remote/HTTP** connection option, not a local command.
3. Enter the operator-provided endpoint and configure BYOK headers
   through the client's supported private credential mechanism.
4. Review the server/tool permissions and enable the connection.

There is no OAuth, signup or server-issued key. `Authorization` is rejected.
Use only the selected provider header plus the client secret:

| Header | Use |
| --- | --- |
| `X-ModelArk-Api-Key` | Images and video |
| `X-Seed-Speech-Api-Key` | Seed Audio generation |
| `X-OmniHuman-Api-Key` | OmniHuman when enabled by the operator |
| `X-MCP-Client-Secret` | Required for every provider call, including dry runs |

Only the selected key is needed; discovery needs none. The client secret must
be **client-generated 32 random bytes encoded as 64 lowercase hex**. Generate
it once using your OS cryptographic RNG or a trusted password/secret manager
in a private local session. For example, privately run `openssl rand -hex 32`,
with terminal sharing, agent capture and shell tracing off. Do not run this
in agent-visible output or reuse an example value. Enter the result directly
into your client's protected secret configuration and keep it stable.
Never paste credentials into chat, tool arguments, screenshots or Git.

Use private environment-backed header configuration where supported:
[Codex](../integrations/codex.md#http-byok) and
[Claude Code](../integrations/claude-code.md#http-byok) have placeholder-only
examples. Client versions differ; exact-client verification is still required.
If custom headers cannot be supplied privately, that client is not supported
for this workflow. Do not disable the boundary.

Optional `X-ModelArk-Seedance-Endpoint` and `X-ModelArk-Seedream-Endpoint`
headers select only exact registered bindings. Explicit tool `model` wins.
An unknown endpoint is not echoed by diagnostics; the operator must verify its
model/version and bind it before use. Arbitrary BYOE self-service is not
implemented. The official GetEndpoint API needs AK/SK signing, not your
ModelArk Bearer key; do not send AK/SK to this server. See the
[endpoint authority contract](../../specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority).

Task access depends on provider authorization. Changing the client secret or
operator HMAC changes only per-pod admission scope, not access to existing tasks.
Clients sharing a provider key can access tasks that key authorizes through
this server. Use separate provider keys/projects for separate authorization.
There is no database or saved-response replay. Retain task IDs and never
automatically repeat uncertain creates. Do not request operator secrets for
a customer connection.

## Generate a Client Snippet

This optional helper needs Python and a reviewed checkout containing
`scripts/configure_http_client.py`; connecting with the manual client
templates above does not. From that checkout:

```bash
python scripts/configure_http_client.py --help
python scripts/configure_http_client.py --client codex --url https://mcp.example.com/mcp
python scripts/configure_http_client.py --client claude-code --url https://mcp.example.com/mcp
```

Replace the URL with your trusted server's HTTPS address. The helper prints
one snippet to **stdout only**: it reads no files or environment secret values,
writes no client files, makes no network requests, and runs no client commands.
Review and merge only the intended entry through your client's supported
configuration workflow, preserving unrelated entries. Private variable values
must be available to the actual client process, not just the setup terminal.

| Option | Use |
| --- | --- |
| `--name` | Server name; default `seed-mcp`. Use `--name ark-seed` to match the client guides |
| `--provider` | Repeat for `modelark`, `seed-speech`, `vision-cv`; omitted means `modelark` |
| `--modelark-key-env`, `--seed-speech-key-env`, `--omnihuman-key-env` | Variable names, defaulting to `SEED_MCP_MODELARK_KEY`, `SEED_MCP_SEED_SPEECH_KEY`, `SEED_MCP_OMNIHUMAN_KEY` |
| `--client-secret-env` | Independent variable name, default `SEED_MCP_CLIENT_SECRET` |
| `--seedance-endpoint-env`, `--seedream-endpoint-env` | Optional endpoint variable names; require `modelark` among selected providers |
| `--tool-timeout-seconds` | 1-3600 seconds; default 660. Codex `tool_timeout_sec`; Claude `timeout` in milliseconds |

For operator-verified image/video bindings, generate their optional header
references without reading the endpoint values:

```bash
python scripts/configure_http_client.py --client codex \
  --url https://mcp.example.com/mcp --name ark-seed \
  --provider modelark \
  --seedance-endpoint-env SEED_MCP_SEEDANCE_ENDPOINT \
  --seedream-endpoint-env SEED_MCP_SEEDREAM_ENDPOINT
```

Use `--client claude-code` for JSON with `${VAR}` references; Codex TOML uses
`env_http_headers`. All `*-env` flags take names, never keys or endpoint values.
Names must match `[A-Za-z_][A-Za-z0-9_]{0,127}` and be distinct across selected
headers. Keep the actual client secret independent of all provider keys too;
the helper cannot inspect that. Omit unused endpoint flags instead of mapping
them to empty values.

URLs cannot contain credentials, queries, fragments, whitespace, controls or
backslashes. The explicit `--allow-loopback-http` exception is only for
isolated tests on literal `localhost`, `127.0.0.1` or `::1`, not a remote
plaintext or TLS-verification bypass. Invalid arguments return a generic
error; inspect names/options privately rather than printing secret values.

## Verify

Ask your connected client:

```text
Use the Ark MCP server I just connected. List its tools and call
ark_list_models with {"input": {}}. Report its static models and services
and confirm connection is null.
Do not generate or upload.
```

HTTP lists 7 tools, or 10 with OmniHuman enabled, independently of operator keys.
Optional temporary upload preparation adds one (8/11); its presence in
tools/list does not prove that your client secret is enrolled.
Anonymous discovery returns configured model bindings even without environment
provider keys. `services[].enabled` means registered, not entitled.
Default discovery is static/anonymous: `check_connection=false` returns
`connection=null` without inspecting credentials in the discovery handler.
Discovery does not validate your provider key. Provider tools
are called directly in the foreground, not through jobs/native tasks.
Disable explicit per-call `io.modelcontextprotocol/tasks` opt-in: it is rejected
before provider dispatch, snapshot capture/save or queue creation, even on discovery.

### Optional Image/Video Configuration Check

After private headers are configured, ask the connected HTTP client:

```text
Call only ark_list_models with {"input":{"check_connection":true}}.
Report header presence, route source and configured bindings, and any issues.
Do not claim authentication, entitlement or live lineage was verified.
Do not generate or upload.
```

Omit `kind` to check both image and video, or use `"kind":"image"` /
`"kind":"video"` for just that route. This needs a live HTTP request context;
stdio checks and other kinds are rejected. It checks no
Seed Speech or OmniHuman credentials.

| Result | Meaning / action |
| --- | --- |
| `connection=null` | Check was not requested; normal anonymous discovery |
| `issues` includes `missing_modelark_key` | ModelArk header absent; check the client's private variable mapping |
| `issues` includes `missing_client_secret` | Client-secret header absent; supply the independent private variable |
| `routes[].issue="endpoint_not_configured"` | Exact product binding missing; operator must verify and bind it. Unknown ID/family are null, not echoed |
| `routes[].source="request_header"` | The product's endpoint header selected the checked default |
| `routes[].source="server_default"` | No endpoint header; the operator default was checked |
| `configuration_valid=true` | Both required headers present and every checked route configured, not proof of upstream access |
| `authentication_verified=false`, `provider_calls_made=false` | Always false; no provider authentication, lineage or entitlement check took place |

Malformed headers can fail HTTP validation before diagnostics. A valid result
does not prove endpoint existence, current model/version, activation, balance
or reachability. The check describes defaults, not a create payload:
explicit create-tool `model` wins even when an endpoint header is present.
`models[].is_default` still describes the server default.

### Validation Boundary

Verified on 2026-11-17:

- Real loopback HTTP preflight, image generation, video creation and polling
  passed with strict provider `respx` mocks installed in the server child.
  Duplicate video submission produced one video POST; no key or prompt
  persistence was observed. No live provider was contacted.
- [Codex 0.163.0](../integrations/codex.md#http-byok) parsed the generated
  configuration through `mcp get --json` in isolated client directories.
- [Claude Code 2.1.292](../integrations/claude-code.md#http-byok) recognized
  the isolated project configuration through `mcp get`, with no network
  access; it remained **Pending approval**.

Actual model-driven Codex/Claude tool execution and paid provider validation
remain pending. Isolated config inspections demonstrate parsing only;
mocked-network loopback smoke demonstrates only the tested transport path.
Neither establishes deployed TLS, live credentials or endpoint lineage.
An unapproved Claude project entry is not a connected-client success.

Continue with [Your First Tool Call](first-run.md).

## Local Files and Outputs

A remote server cannot read or write files on your computer using a local
file attachment. Optional [temporary TOS upload preparation](../temporary-uploads.md)
requires an operator-enrolled client secret and a multipart-capable client:
prepare metadata, upload bytes directly to TOS, wait for success, then use
the GET URL with normal generation headers. No generation key is needed
for preparation itself. A chat attachment does not upload automatically.

A remote server cannot read or write files on your computer using a local
path. HTTP has no local storage/artifact tools or resources. Use supported URLs
(small inline references remain subject to the 2 MiB body cap). Persistence
defaults to false globally; HTTP rejects true. Download returned provider
URLs before expiry: audio about 2 hours, image/video 24 hours, OmniHuman 1 hour.
Do not send private media without approval.

## For Administrators

Deploying a server is separate from connecting to one. See
[Self-Hosting](../self-hosting.md) for the protected deployment kit and
[Transports](../transports.md) for BYOK, TLS, ownership and Host/Origin guards.
For BytePlus infrastructure, start with
[deployment requirements](../byteplus-terraform.md#requirements),
[dependency installation](../byteplus-terraform.md#set-up-dependencies), and
[IAM and credential setup](../byteplus-terraform.md#set-up-iam-and-credentials).
Hosted [provider-secret sync is superseded](../secret-manager.md).
Operators supply a stable `MCP_IDENTITY_HMAC_KEY` and version, not provider keys.
These are operator requirements, not customer credentials.
Dedicated VKE replaces the old ECS/Compose path. Operators need private
control-plane connectivity, CCM/node readiness, metrics API and distinct existing
identity and TLS Secrets; customers do not. No database or database CA is required.
The chart uses Deployment/HPA/PDB/spread, default 2-6 pods on maintained
Kubernetes >=1.30, no state PVC/StorageClass/headless Service. CSI remains
admin-owned but is not a new stateless app prerequisite; preserve legacy safeguards.
Public routes are `/mcp` and
`/health`; readiness and optional metrics remain private.
Source deletion does not decommission old cloud resources. Preserve old
reviewed checkouts, private workspaces, state/backups and matching HMAC
configuration for separately approved retirement. No reset, blind restore
or requeue is a supported repair.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.
