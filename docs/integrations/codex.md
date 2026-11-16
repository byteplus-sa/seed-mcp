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

[mcp_servers.ark-seed.env]
ARK_MCP_ENV_FILE = "/absolute/path/to/private/ark-mcp/.env"
MCP_TRANSPORT = "stdio"
MCP_AUTH_MODE = "local"
```

Preserve unrelated tables and comments. Never put provider keys in stdio `env`.
Project configuration with machine-specific absolute paths is not a portable
team setup and should not be committed automatically.

## HTTP BYOK

For an existing trusted endpoint, replace the local entry with a remote one.
Replace the angle-bracket placeholders with private environment variable names,
not secret values. Load those variables privately in the actual Codex launch environment;
do not put them in command-line flags or chat.

```toml
[mcp_servers.ark-seed]
url = "https://mcp.example.com/mcp"
tool_timeout_sec = 660

[mcp_servers.ark-seed.env_http_headers]
X-ModelArk-Api-Key = "<MODELARK_KEY_ENV_VAR>"
X-MCP-Client-Secret = "<CLIENT_SECRET_ENV_VAR>"
```

Use `X-Seed-Speech-Api-Key` or `X-OmniHuman-Api-Key` with separately named private
environment variables when needed. Only the selected provider key is required.
Generate the client secret privately from 32 random bytes as 64 lowercase hex,
once per intended owner. No `Authorization`, OAuth, signup or server-issued key
is used. Do not use `bearer_token_env_var`.

Discovery is anonymous/static. HTTP has 9 tools (12 with OmniHuman), direct
foreground calls and no jobs/native tasks/storage/artifacts/resources.
Keep persistence false and retrieve expiring URLs yourself. Optional endpoint
headers need exact registered bindings; explicit tool `model` wins.
See [private setup and ownership](../setup/shared-server.md).
This is a configuration template, not an exact-client live verification claim.

</details>

## Verify

Run the [discovery-only check](index.md#verify-without-paid-calls) and confirm
the tools you need appear. Continue with [Your First Tool Call](../setup/first-run.md).
Finish active jobs before reconnecting; a new local process does not inherit
the previous process's in-memory queue.

See [Integrations](index.md), [Claude Code](claude-code.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)

Sources consulted for MCP setup on 2026-11-10. CLI/IDE/app support must still
be checked in the actual target client.
