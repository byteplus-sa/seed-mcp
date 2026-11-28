---
title: Claude Code
description: Choose user, private-project, or shared-project scope for Seed MCP in Claude Code.
---

Use Claude Code's terminal-enabled agent to prepare Seed MCP for you. This guide is
for the coding client, not [Claude Desktop](claude-desktop.md).

## Recommended Setup

1. Send the [guided setup request](../setup/install.md#guided-local-setup)
   to Claude Code, naming **Claude Code** as the target.
2. Approve setup changes and enter provider keys in the private editor.
3. Open `/mcp`, review the connection and enable `ark-seed`.

Claude Code starts the server automatically. You do not need to run the
registration command below yourself if your setup agent has completed it.

<details>
<summary>Manual configuration and scope options</summary>

## Choose the Scope

| CLI scope | Visibility | Storage |
| --- | --- | --- |
| `user` | All your projects; recommended default | User configuration, normally `~/.claude.json` |
| `local` | Private to the current project | Project-specific entry in user configuration |
| `project` | Shareable configuration for this project | Project-root `.mcp.json` |

Claude Code's default `local` scope is **not global**. `CLAUDE_CONFIG_DIR`
can change user configuration locations; prefer the CLI over editing that
file manually. For either project scope, run registration from the intended
project, which need not be the Seed MCP checkout.

## Register

Complete the [shared prerequisites](index.md#prepare-the-launch). Check
`claude mcp add --help` for the installed CLI before using these Bash/POSIX
commands. The variables contain only absolute paths, never credential values:

```bash
UV="/absolute/path/to/uv"
CHECKOUT="/absolute/path/to/ark-mcp"
ENV_FILE="/absolute/path/to/private/ark-mcp/.env"

claude mcp add ark-seed --transport stdio --scope user \
  --env "ARK_MCP_ENV_FILE=$ENV_FILE" \
  --env MCP_TRANSPORT=stdio \
  --env MCP_AUTH_MODE=local \
  -- "$UV" --directory "$CHECKOUT" run --locked --no-sync python -m ark_mcp
```

Put the server name before `--env`, since that option may consume multiple
values. `--` separates Claude's options from the server command.
Replace `--scope user` with `--scope local` for a private project entry, or
`--scope project` for the shareable file. Do not blindly re-add or remove an
existing `ark-seed` entry to resolve shadowing.

For manual project configuration, merge this entry into `.mcp.json`:

```json
{
  "mcpServers": {
    "ark-seed": {
      "type": "stdio",
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory",
        "/absolute/path/to/ark-mcp",
        "run",
        "--locked",
        "--no-sync",
        "python",
        "-m",
        "ark_mcp"
      ],
      "env": {
        "ARK_MCP_ENV_FILE": "/absolute/path/to/private/ark-mcp/.env",
        "MCP_TRANSPORT": "stdio",
        "MCP_AUTH_MODE": "local"
      }
    }
  }
}
```

These machine-specific paths are not portable team defaults. Each teammate
needs their own private env file and installation. Do not commit populated
credential files or automatically commit this configuration.

## HTTP BYOK

For an existing trusted endpoint, use a remote entry in the intended scope,
preserving other entries. Inject the named variables privately into the actual
Claude Code launch environment. From a reviewed checkout, this optional
generator prints the following JSON without reading files or environment
secret values, writing configuration, contacting servers or invoking a client:

```bash
python scripts/configure_http_client.py --client claude-code \
  --url https://mcp.example.com/mcp --name ark-seed
```

```json
{
  "mcpServers": {
    "ark-seed": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "timeout": 660000,
      "headers": {
        "X-ModelArk-Api-Key": "${SEED_MCP_MODELARK_KEY}",
        "X-MCP-Client-Secret": "${SEED_MCP_CLIENT_SECRET}"
      }
    }
  }
}
```

Only the selected key is needed: use `X-Seed-Speech-Api-Key` for Seed Audio
with `--provider seed-speech`; omitted means `modelark`.
The generator's `--help` lists variable-name overrides, never credential-value
flags. Selected headers must use independent variable names.
The client secret is privately
generated once from 32 random bytes, encoded as 64 lowercase hex.
There is no OAuth, signup, server-issued key or `Authorization` header.
Do not put real keys in CLI flags, chat or committed JSON.

HTTP exposes 7 tools, default anonymous static discovery
with `connection=null`, and direct
foreground calls. Jobs/native tasks/local storage/artifact tools/resources are absent.
Optional [temporary TOS preparation](../temporary-uploads.md) adds one tool for
enrolled clients; it requires a separate multipart-capable client integration.
`timeout` is milliseconds: `--tool-timeout-seconds` accepts 1-3600 seconds
and defaults to 660 (660000 ms). It does not extend proxy/provider timeouts.
Keep persistence false and retrieve expiring URLs yourself.

Optional `--seedance-endpoint-env SEED_MCP_SEEDANCE_ENDPOINT` and/or
`--seedream-endpoint-env SEED_MCP_SEEDREAM_ENDPOINT` add `${VAR}` references
and require selected provider `modelark`. They take names, not endpoint values.
Endpoint headers select operator-verified exact registry defaults; explicit
create-tool `model` wins. Unknown IDs are not echoed; the operator must verify
and bind them, not supply AK/SK to this server.

Follow [private setup and generator options](../setup/shared-server.md#generate-a-client-snippet),
then the HTTP-only [configuration check](../setup/shared-server.md#optional-imagevideo-configuration-check)
with `{"input":{"check_connection":true}}`. It checks image/video header
presence and bindings, not provider authentication, live lineage or entitlement.
Validated on 2026-11-17 with **Claude Code 2.1.292**: `claude mcp get`
recognized the generated project `.mcp.json` with isolated `CLAUDE_CONFIG_DIR`,
`HOME` and working directory. It remained **Pending approval**, with no network
access. This verifies configuration parsing only, not a working connection.
Actual exact-client, model-driven Claude tool execution remains unverified;
provider credentials and paid provider validation remain pending.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

</details>

## Verify

Use the [discovery-only check](index.md#verify-without-paid-calls), then try
[Your First Tool Call](../setup/first-run.md). Confirm actual tool results,
not just an entry in `/mcp`. Finish active calls before restarting the connection.

See [Integrations](index.md), [Getting Started](../getting-started.md),
[Tools](../tools.md), and [Configuration](../configuration.md).

## Official Source

- [Claude Code MCP connections and scopes](https://code.claude.com/docs/en/mcp)

Source consulted 2026-11-10. Check local help and the installed edition
before registration.
