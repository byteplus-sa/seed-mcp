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
| `X-ModelArk-Api-Key` | Images, video, image/video/audio understanding |
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
Arbitrary opaque endpoint lineage is not inferred.

Changing your provider key or client secret changes scope and can make earlier
tasks inaccessible through this server. Changing the operator HMAC key/version
also changes scope. No recovery bridge exists. Two clients sharing a provider
key can still access that provider directly; separate provider keys/projects
are needed for stronger separation.

## Verify

Ask your connected client:

```text
Use the Ark MCP server I just connected. Call only ark_list_models
and report its static services and tools.
Do not generate, understand, transcribe, upload, or submit jobs.
```

HTTP lists 9 tools, or 12 with OmniHuman enabled, independently of operator keys.
Anonymous discovery returns configured model bindings even without environment
provider keys. `services[].enabled` means registered, not entitled.
Discovery does not validate your provider key. Provider tools
are called directly in the foreground, not through jobs/native tasks.
Disable explicit per-call `io.modelcontextprotocol/tasks` opt-in: it is rejected
before provider dispatch, snapshot capture/save or queue creation, even on discovery.

Continue with [Your First Tool Call](first-run.md).

## Local Files and Outputs

A remote server cannot read or write files on your computer using a local
path. HTTP has no storage/artifact tools or resources. Use supported URLs
(small inline references remain subject to the 2 MiB body cap). Persistence
defaults to false globally; HTTP rejects true. Download returned provider
URLs before expiry: audio about 2 hours, image/video 24 hours, OmniHuman 1 hour.
Files API temporary-upload cleanup uses your live ModelArk key; remote file
expiry is distinct from output URL expiry. Do not send private media without approval.

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
Non-dry HTTP Seedance/OmniHuman creates require `idempotency_key`: 16-128 ASCII
letters, digits, `_` or `-`; generate a fresh UUID per intended call, including
one key for all variations. Repeat identical arguments/key only for delivery
recovery, not polling. Only fully successful saved receipts replay after
ownership checks; failed/partial/cancelled attempts need reconciliation, never
a new key to bypass uncertain acceptance. Seedance dry runs need no key or
journal; local stdio rejects supplied keys.
Keep the original provider key/client secret and the operator's same state and
HMAC configuration. Claims never auto-prune; at `STATE_MAX_RECORDS` new keys
fail while existing keys remain readable. See the
[submission contract](../../specs/SPEC_HOSTED_BYOK.md#http-submission-safety).
This remains single-instance SQLite; synchronous product replay and complete
crash recovery are deferred. PostgreSQL/Redis are future scaling choices, not
initial requirements. No migration, multi-replica or public-launch claim.
