---
title: Codex
description: Connect Codex to Ark using global or trusted-project MCP configuration and private env-file paths.
---

Use a Codex session with terminal and file-editing access to prepare Ark.
Ordinary chat without those permissions cannot perform local installation.

## Recommended Setup

1. Send the [guided setup request](../setup/install.md#guided-local-setup),
   naming **Codex** and your actual execution host.
2. Approve setup changes and enter keys privately when prompted.
3. Review `ark-seed` in `/mcp` or your edition's MCP settings.

The agent resolves paths and uses the installed client's registration
mechanism. Once configured, Codex starts Ark automatically.

<details>
<summary>Manual configuration and scope options</summary>

## Choose the Scope

- **User/global:** `${CODEX_HOME}/config.toml`, normally `~/.codex/config.toml`.
- **Project:** `<project>/.codex/config.toml`, loaded only for trusted projects.

`codex mcp add` writes user/global configuration in the repository's documented
workflow; it is not the project-only registration command. Do not change
project trust automatically or delete a competing same-name entry. Clients
sharing the same Codex configuration do not need duplicate registrations.

Complete the [shared prerequisites](index.md#prepare-the-launch). Registration
scope does not change where Ark's checkout or private credentials live.

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
"X-MCP-Client-Secret" = "SEED_MCP_CLIENT_SECRET" # pragma: allowlist secret
```

Use `X-Seed-Speech-Api-Key` or `X-OmniHuman-Api-Key` with separately named private
environment variables when needed. The generator's repeatable `--provider`
selects `modelark` (default), `seed-speech` or `vision-cv`; `--help` lists
variable-name overrides. Selected headers must use independent variable names.
Generate the client secret privately from 32 random bytes as 64 lowercase hex,
once per intended owner. No `Authorization`, OAuth, signup or server-issued key
is used. Do not use `bearer_token_env_var`. `tool_timeout_sec` is in seconds
(generator default 660, configurable from 1-3600); it does not extend proxy
or provider timeouts.

Default discovery is anonymous/static with `connection=null`. HTTP has 7 tools (10 with OmniHuman), direct
foreground calls and no jobs/native tasks/local storage/artifacts/resources.
Optional [temporary TOS preparation](../temporary-uploads.md) adds one tool
for enrolled clients; it requires a separate multipart-capable client integration.
Keep persistence false and retrieve expiring URLs yourself. Optional endpoint
headers need operator-verified exact bindings; explicit create-tool `model` wins.
Add `--seedance-endpoint-env SEED_MCP_SEEDANCE_ENDPOINT` and/or
`--seedream-endpoint-env SEED_MCP_SEEDREAM_ENDPOINT` only for bindings you use;
these options require `modelark` and take variable names, not endpoint values.
An unknown endpoint is not echoed; ask the operator to verify and bind it.

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
