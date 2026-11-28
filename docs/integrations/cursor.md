---
title: Cursor
description: Connect Cursor to hosted Seed MCP using private HTTP headers, with optional local stdio reference.
---

For **hosted Seed MCP**, follow the [remote connection guide](../setup/install.md#other-clients).
No server installation or startup is needed. Use Cursor's remote HTTP
configuration and verify private custom-header support in your edition.
Preserve existing MCP entries and choose your intended user or project scope.

<details>
<summary>Optional local stdio configuration, not hosted setup</summary>

The following applies only to a deliberately separate
[local installation](../setup/manual-install.md).

## Choose the Scope

- **User/global default:** `~/.cursor/mcp.json`.
- **Project:** `<project>/.cursor/mcp.json`.

Both use `mcpServers`. Merge only the intended `ark-seed` entry and preserve
other entries/comments. Check for another same-name server at a different
scope instead of deleting it. Machine-specific project configuration and
private credentials should not be committed automatically.

## Configure

Complete the [shared prerequisites](index.md#prepare-the-launch), then use
this JSON in the chosen file. Replace the three placeholders with actual
absolute paths on the server host:

```json
{
  "mcpServers": {
    "ark-seed": {
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

The private `.env` is read by Seed MCP, not embedded in Cursor configuration.
Although some Cursor editions support `envFile` and path interpolation,
this template deliberately uses literal absolute paths and only non-secret
`env` settings. Remote workspaces need paths and an installation on the
actual execution host.

</details>

## Verify

Run the [discovery-only check](index.md#verify-without-paid-calls), then
[Your First Tool Call](../setup/first-run.md). UI labels vary by edition;
actual tool results matter more than the connection indicator. Finish active
calls before reconnecting or restarting Cursor.

See [Integrations](index.md), [VS Code](vscode.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Source

- [Cursor MCP configuration and scope](https://cursor.com/docs/context/mcp)

Source consulted 2026-11-10. Runtime verification in the target Cursor
edition remains part of installation, not a promise made by this template.
