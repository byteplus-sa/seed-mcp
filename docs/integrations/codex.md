---
title: Codex
description: Connect Codex to hosted Seed MCP; local stdio configuration is an optional advanced reference.
---

For **hosted Seed MCP**, use the [remote Codex template](../setup/install.md#codex).
No server installation or startup is needed. Configure the private header
variables, review `ark-seed` in `/mcp`, and verify discovery.

<details>
<summary>Advanced configuration, including optional local stdio</summary>

Local launch sections below apply only to a deliberately separate
[local installation](../setup/manual-install.md), not the hosted service.

## Choose the Scope

- **User/global:** `${CODEX_HOME}/config.toml`, normally `~/.codex/config.toml`.
- **Project:** `<project>/.codex/config.toml`, loaded only for trusted projects.

`codex mcp add` writes user/global configuration in the repository's documented
workflow; it is not the project-only registration command. Do not change
project trust automatically or delete a competing same-name entry. Clients
sharing the same Codex configuration do not need duplicate registrations.

Complete the [shared prerequisites](index.md#prepare-the-launch). Registration
scope does not change where Seed MCP's checkout or private credentials live.

## Global CLI Registration

Check `codex mcp add --help`. In a Bash/POSIX shell:

```bash
UV="/absolute/path/to/uv"
CHECKOUT="/absolute/path/to/ark-mcp"
ENV_FILE="/absolute/path/to/private/ark-mcp/.env"

codex mcp add ark-seed \
  --env "ARK_MCP_ENV_FILE=$ENV_FILE" \
  --env MCP_TRANSPORT=stdio \
  --env MCP_AUTH_MODE=local \
  -- "$UV" --directory "$CHECKOUT" run --locked --no-sync python -m ark_mcp
```

All variable values are non-secret absolute paths. Use host-native quoting
on Windows rather than pasting Bash continuations into PowerShell.

## TOML Configuration

For project-only setup, merge this into the trusted project's
`.codex/config.toml`. The same table can instead be placed in the user/global
file; choose one intended scope:

```toml
[mcp_servers.ark-seed]
command = "/absolute/path/to/uv"
args = [
  "--directory",
  "/absolute/path/to/ark-mcp",
  "run",
  "--locked",
  "--no-sync",
  "python",
  "-m",
  "ark_mcp",
]
tool_timeout_sec = 660

[mcp_servers.ark-seed.env]
ARK_MCP_ENV_FILE = "/absolute/path/to/private/ark-mcp/.env"
MCP_TRANSPORT = "stdio"
MCP_AUTH_MODE = "local"
```

Preserve unrelated tables and comments. Never put provider keys in stdio `env`.
Project configuration with machine-specific absolute paths is not a portable
team setup and should not be committed automatically.

## HTTP BYOK

For an existing trusted endpoint, configure a remote entry in the intended
scope, preserving other entries. Load the named variables privately in the
actual Codex launch environment; do not put secret values in flags or chat.
From a reviewed checkout, this optional generator prints the following TOML
without reading files or environment secret values, writing configuration,
contacting servers or invoking a client:

```bash
python scripts/configure_http_client.py --client codex \
  --url https://mcp.example.com/mcp --name ark-seed
```

```toml
[mcp_servers."ark-seed"]
url = "https://mcp.example.com/mcp"
tool_timeout_sec = 660

[mcp_servers."ark-seed".env_http_headers]
"X-ModelArk-Api-Key" = "SEED_MCP_MODELARK_KEY"
```

Use `X-Seed-Speech-Api-Key` with separately named private
environment variables when needed. The generator's repeatable `--provider`
selects `modelark` (default) or `seed-speech`; `--help` lists
variable-name overrides. Selected headers must use independent variable names.
Optionally add `X-MCP-Client-Secret` via `--client-secret-env VAR`.
Generate it privately from 32 random bytes as 64 lowercase hex once per client;
otherwise the same key shares principal concurrency. No `Authorization`, OAuth, signup or server-issued key
is used. Do not use `bearer_token_env_var`. `tool_timeout_sec` is in seconds
(generator default 660, configurable from 1-3600); it does not extend proxy
or provider timeouts.

Default discovery is anonymous/static with `connection=null`. HTTP has 12 tools, direct
foreground calls and no jobs/native tasks/local storage/artifacts/resources.
Managed reference uploads use `ark_file_upload/get/list/delete` with the ModelArk key, without storage enrollment. Hosted local files use `seed-mcp-upload` on the client; retrieve the accepted ID for an active `download_url` before generation. Signed URLs are private and are not renewed by metadata reads.

Use the HTTP-only [configuration check](../setup/shared-server.md#optional-imagevideo-configuration-check)
with `{"input":{"check_connection":true}}` to inspect image/video header
presence and exact bindings, not provider authentication or live lineage.
See [generator options and private setup](../setup/shared-server.md#generate-a-client-snippet).
Validated on 2026-11-17 with **Codex 0.163.0**: `codex mcp get --json` parsed
the generated configuration with isolated `CODEX_HOME`, `HOME` and working
directory. This verifies configuration parsing only. Actual exact-client,
model-driven Codex tool execution remains unverified; provider credentials and
paid provider validation remain pending.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

</details>

## Verify

Run the [discovery-only check](index.md#verify-without-paid-calls) and confirm
the tools you need appear. Continue with [Your First Tool Call](../setup/first-run.md).
Finish active calls before reconnecting; no MCP queue exists. Preserve provider
task IDs and poll them, never recreate work after a lost response.

See [Integrations](index.md), [Claude Code](claude-code.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)

Sources consulted for MCP setup on 2026-11-10. CLI/IDE/app support must still
be checked in the actual target client.
