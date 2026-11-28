---
title: VS Code
description: Connect VS Code to hosted Seed MCP using private HTTP headers, with optional local stdio reference.
---

For **hosted Seed MCP**, follow the [remote connection guide](../setup/install.md#other-clients).
No server installation or startup is needed. Use **MCP: Add Server** or your
edition's MCP settings to select remote HTTP and private custom headers.
VS Code and portable Copilot formats differ; verify the selected harness's
supported schema rather than copying another client's JSON.

<details>
<summary>Optional local stdio configuration, not hosted setup</summary>

The following applies only to a deliberately separate
[local installation](../setup/manual-install.md).

## Choose Scope and Format

| Destination | Scope | Envelope |
| --- | --- | --- |
| `.vscode/mcp.json` | Workspace, VS Code compatibility format | `servers` |
| Selected user profile's `mcp.json` | User/profile, compatibility format | `servers` |
| Workspace-root `.mcp.json`, where supported | Project, portable Copilot format | `mcpServers` |
| Copilot user configuration | User/global for that harness | `mcpServers` |

For user/global setup, use **MCP: Add Server** and select the supported
user/profile or harness destination. Do not guess the profile's storage path.
Current official docs place portable Copilot user configuration at
`$COPILOT_HOME/mcp-config.json`, falling back to `~/.copilot/mcp-config.json`;
confirm this in your installed edition. Older editions may offer only the
VS Code profile/workspace format.

Complete the [shared prerequisites](index.md#prepare-the-launch). A remote
or Dev Container session needs the installation and paths on its execution
host, not automatically on the local desktop.

## VS Code Format

Merge this into workspace `.vscode/mcp.json`, or the profile file opened by
the supported configuration command. Use `servers`, not `mcpServers`:

```json
{
  "servers": {
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

Replace all placeholder paths. Optional `inputs` belongs at the top level,
not inside `servers`; this example needs no interactive credential inputs.
Do not use `envFile` to distribute provider keys. Seed MCP reads its private file
through the non-secret `ARK_MCP_ENV_FILE` path.

## Portable Copilot Format

Only use this variant when your installed harness supports the corresponding
portable destination. Merge it into that destination, not `.vscode/mcp.json`:

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

Portable configuration does not need `envFile` or VS Code `${input:...}`
support because the server loads its private credentials itself.
Preserve existing entries, avoid duplicate same-name definitions, and do
not automatically commit machine-specific project configuration.

</details>

## Verify

Use **MCP: List Servers**, or the MCP/customizations panel available in your
edition, and run the [discovery-only check](index.md#verify-without-paid-calls).
Continue with [Your First Tool Call](../setup/first-run.md). Finish active
calls before restarting the connection.

See [Integrations](index.md), [Cursor](cursor.md),
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [Add MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [VS Code MCP configuration formats](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration)

Sources consulted 2026-11-10. The compatibility and portable variants still
require verification against the actual installed edition and harness.
