---
title: TRAE
description: Connect TRAE to hosted Seed MCP when its edition supports private HTTP headers.
---

For **hosted Seed MCP**, follow the [TRAE connection guide](../setup/install.md#trae).
No server installation or startup is needed. Choose remote Streamable HTTP
and private custom headers in your edition's MCP settings. Verify support
for **IDE or Work** and **International or CN**; do not assume their fields match.

<details>
<summary>Optional local stdio configuration, not hosted setup</summary>

The following applies only to a deliberately separate
[local installation](../setup/manual-install.md).

## Scope and Runtime

- **User/global default:** use the selected edition's MCP settings UI.
  In IDE, look for **Settings > MCP > Add > Manual configuration**.
  In Work, look for **Settings > MCP > Create > Manual configuration**.
  Confirm the selected scope in the actual UI.
- **Project:** the repository's IDE template uses `<project>/.trae/mcp.json`
  with project-level MCP enabled in settings. Verify support in your edition.
  Do not claim global setup by writing a project file.
- **Execution host:** select local runtime for this guide. Work editions may
  offer local/cloud selection. Cloud requires a checkout, `uv`, and private
  credentials accessible on that cloud host; local paths will not work.
  Do not transfer credentials to another host without explicit approval.

Do not guess a global `~/.trae/mcp.json` path from the existence of that
directory. If the edition only offers a UI for user-level setup, use the UI.

## Configure

Complete the [shared prerequisites](index.md#prepare-the-launch). Paste this
JSON into the supported manual configuration UI, or merge the entry into
the supported project file. Replace each placeholder with an absolute
path on the selected server host:

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

The `env` contains no key values. The Seed MCP checkout does not need to be the
project being edited; do not substitute `${workspaceFolder}` for its path
unless that folder actually contains the prepared server checkout.
Preserve existing servers and any same-name entry at a different scope.

</details>

## Verify

Choose a tool-enabled chat mode and run the
[discovery-only check](index.md#verify-without-paid-calls). A pending UI
step is not a completed installation. Once your tools appear, try
[Your First Tool Call](../setup/first-run.md). Finish active calls before
reloading the connection.

See [Integrations](index.md), [Codex](codex.md) for an embedded Codex agent,
[Getting Started](../getting-started.md), [Tools](../tools.md), and
[Configuration](../configuration.md).

## Official Sources

- [TRAE International IDE MCP overview](https://docs.trae.ai/ide/model-context-protocol)
- [TRAE Work MCP and runtime guide](https://docs.trae.cn/work/remote-mcp-server)

The IDE overview was consulted on 2026-11-10. The Work page could not be
retrieved during this documentation pass; Work UI/runtime instructions
follow the repository's setup references and must be checked in the app.
