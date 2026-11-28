---
title: Client Integrations
description: Connect local MCP clients to Seed MCP with private credentials and non-billable discovery.
---

Choose the client you want to use. **You configure the connection once; the
client starts Seed MCP automatically.** You do not need to run the launch command
yourself whenever you open a chat.

## Choose a Client

| Client | Easiest starting point |
| --- | --- |
| [Claude Desktop](claude-desktop.md) | Have a coding agent prepare its configuration, then enable it in Desktop |
| [Claude Code](claude-code.md) | Ask Claude Code to perform guided setup |
| [Codex](codex.md) | Ask a terminal-enabled Codex session to perform guided setup |
| [TRAE](trae.md) | Ask its coding agent to prepare setup; confirm any MCP settings UI steps |
| [Cursor](cursor.md) | Use a file/terminal-enabled agent for guided setup |
| [VS Code](vscode.md) | Use an enabled coding agent, then review the MCP connection |
| [OpenCode](opencode.md) | Ask OpenCode to perform guided setup for its installed version |
| [Python](python.md) | Developer example for building your own client |

Use the [guided setup request](../setup/install.md#guided-local-setup) before
opening manual configuration snippets. It requires terminal and file-editing
access; ordinary chat alone cannot install software. For a team-provided
endpoint, [connect over HTTPS](../setup/shared-server.md) instead.

Local launch instructions below are stdio-only. HTTP has 7 tools, plus optional temporary upload preparation, anonymous static discovery and direct foreground calls, with no
jobs/native tasks/local storage/artifact tools/resources. See the private-header
examples for [Codex](codex.md#http-byok) and [Claude Code](claude-code.md#http-byok).

Default to user-level registration so Seed MCP is available across projects.
Choose project-only scope when you need it. Your agent should preserve other
MCP entries and ask before replacing an existing connection.

## Prepare the Launch

Your setup agent resolves the executable, checkout and private credential-file
paths, installs the reviewed locked environment, and prepares the correct
client entry. You only need to approve changes, enter keys privately and
complete any required UI confirmation.

The fallback snippets in each client guide are for manual setup or
troubleshooting, not additional steps after guided setup. Their prerequisites
and exact launch contract are in [Manual Installation](../setup/manual-install.md).
Do not paste unresolved placeholder paths into a client.

## Keep Credentials Private

Enter only the [keys you need](../api-keys.md) in a private local text editor.
The file stays outside your repository and shared folders; client configuration
contains its path, not key values. Preserve existing credentials. Never paste
populated configuration, raw logs or validation errors into chat.

## Verify Without Paid Calls

After saving the entry, review the client's server trust prompt and enable
`ark-seed`. Check active calls before reloading or restarting a client.

Use this request in the client:

Report only static models/tools; discovery does not validate request credentials.
Default discovery returns `connection=null`. For optional HTTP image/video
header-presence and exact-binding diagnostics, use the separate
[`check_connection` request](../setup/shared-server.md#optional-imagevideo-configuration-check).
It does not authenticate or establish live endpoint lineage or entitlement.

```text
Use only the ark-seed server. List its tools, call ark_list_models with
{"input": {}}. Report enabled services, exact model IDs and model limits.
Do not generate or upload.
```

`ark_list_models` is read-only and makes no provider calls.
It describes configured models and services. A connected local server with
empty models may simply have no provider credentials loaded.
Discovery proves configuration and tool availability, not API-key validity,
account entitlement, or model whitelist access.

The setup agent's isolated preflight procedure is in
[Manual Installation](../setup/manual-install.md#verify-without-spending).
There is no need for users to run a separate validation script.

## Long-Running Work

Ask your client to call product tools directly and report the result.
It handles provider polling; there are no MCP jobs or native tasks.
For an optional no-charge check, use the
[request preview](../setup/first-run.md#preview-an-image-request).

Keep the connection open while work runs. Use client timeout 660 seconds for
the default 600-second cooperative deadline; SDK/SQLite cleanup may exceed it.
Retain accepted task/request IDs: never repeat generation just to check progress
or blindly resubmit after a lost response. Technical result handling is in
[Direct Execution](../integration-guide.md#direct-execution).

## Troubleshooting

- **Server does not start:** check the resolved executable, checkout, completed
  locked sync, JSON/TOML syntax, and selected execution host.
- **Connected but expected tools are missing:** check private env-file
  metadata, enabled services, feature flags, and inherited-variable shadowing.
  Never request the populated env file or raw validation exceptions in chat.
- **A provider task ID is unavailable:** use the original credentials and
  ownership scope; reconcile acceptance instead of recreating it.
- **Edition rejects the configuration:** use that client's guide and official
  source. Do not swap envelope keys blindly or inline keys as a workaround.

## Sources

Official client references are listed in each sibling guide. The shared
launch contract follows the current server configuration.
These protocol/runtime references were consulted on
2026-11-10:

- [MCP local-server connections](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [uv project environments and locked execution](https://docs.astral.sh/uv/concepts/projects/sync/)
- [FastMCP client transports](https://gofastmcp.com/clients/transports)
