---
title: OpenCode
description: Connect OpenCode to hosted Seed MCP using private HTTP headers, with optional local stdio reference.
---

For **hosted Seed MCP**, follow the [OpenCode connection guide](../setup/install.md#opencode).
No server installation or startup is needed. Use your edition's remote MCP
schema and verify private custom-header support. Classic and V2 configuration
shapes differ; do not use the local launcher examples for the hosted service.

<details>
<summary>Optional local stdio configuration, not hosted setup</summary>

The following applies only to a deliberately separate
[local installation](../setup/manual-install.md).

## Choose the Scope

- **User/global default:** `~/.config/opencode/opencode.json` or
  `opencode.jsonc`, subject to the selected profile/configuration overrides.
- **Project:** project-root `opencode.json` or `opencode.jsonc`. V2 docs also
  describe `.opencode/opencode.json(c)` and hierarchical merging.

Complete the [shared prerequisites](index.md#prepare-the-launch). Preserve
existing entries and JSONC comments. Check precedence and same-name entries:
V2 project overrides replace a whole server object, so partial overrides
can drop required fields. Never automatically commit machine-specific paths.

## Classic Repository Template

Use this only when your installed OpenCode schema puts server names directly
under `mcp`. `command` is an array, and environment settings use
`environment`, not `env`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ark-seed": {
      "type": "local",
      "command": [
        "/absolute/path/to/uv",
        "--directory",
        "/absolute/path/to/ark-mcp",
        "run",
        "--locked",
        "--no-sync",
        "python",
        "-m",
        "ark_mcp"
      ],
      "enabled": true,
      "environment": {
        "ARK_MCP_ENV_FILE": "/absolute/path/to/private/ark-mcp/.env",
        "MCP_TRANSPORT": "stdio",
        "MCP_AUTH_MODE": "local"
      }
    }
  }
}
```

## V2 Official-Docs Variant

Use this only when the installed schema requires `mcp.servers` and uses
`disabled` rather than classic `enabled`. Here `disabled: false` permits
connection, and `codemode: false` requests directly exposed tools:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "ark-seed": {
        "type": "local",
        "command": [
          "/absolute/path/to/uv",
          "--directory",
          "/absolute/path/to/ark-mcp",
          "run",
          "--locked",
          "--no-sync",
          "python",
          "-m",
          "ark_mcp"
        ],
        "disabled": false,
        "codemode": false,
        "environment": {
          "ARK_MCP_ENV_FILE": "/absolute/path/to/private/ark-mcp/.env",
          "MCP_TRANSPORT": "stdio",
          "MCP_AUTH_MODE": "local"
        }
      }
    }
  }
}
```

Replace all absolute-path placeholders on the actual execution host.
`type: "local"` means subprocess transport, not project scope. Both variants
contain only non-secret environment settings; Seed MCP reads credentials from the
private file. OpenCode may inherit other environment variables that override
that file, so check presence/names without printing values.

</details>

## Verify

Run the [discovery-only check](index.md#verify-without-paid-calls), then
[Your First Tool Call](../setup/first-run.md). Finish active calls before
reloading the connection. If you need troubleshooting commands, ask the
agent to use the help for your installed OpenCode version.

See [Integrations](index.md), [Python](python.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/)
- [OpenCode configuration and precedence](https://opencode.ai/docs/config/)

Sources consulted 2026-11-10 describe V2. The classic shape follows this
repository's integration/setup references; check the installed edition
before selecting either template.
