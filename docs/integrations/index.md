---
title: Client Integrations
description: Connect your MCP client to hosted Seed MCP with private headers and non-billable discovery.
---

**Connect to the existing hosted service; do not install or run Seed MCP.**
Start with [the hosted connection guide](../setup/install.md). It provides the
endpoint, private-header requirements and client templates.

## Choose a Client

| Client | Hosted connection |
| --- | --- |
| Codex | [Remote TOML template](../setup/install.md#codex) |
| Claude Code | [Remote JSON template](../setup/install.md#claude-code) |
| TRAE, Cursor, VS Code, OpenCode | [Remote connection requirements](../setup/install.md#other-clients); verify private custom-header support in your edition |
| Claude Desktop | Verify remote custom-header support; the Claude Code JSON is not a Desktop connector template |
| Custom clients | Implement Streamable HTTP with the [documented headers](../setup/shared-server.md#connect) and a 660-second tool timeout |

Use only clients that can supply credentials privately. Unsupported or
unverified remote-header handling is not a reason to inline secrets or
silently switch to a locally installed server.

HTTP has eight tools, anonymous static discovery and direct foreground calls.
The hosted deployment has temporary uploads disabled, no local storage/artifact
tools or resources, and no Seed TTS. No MCP jobs or native tasks are exposed.

Default to user-level registration so Seed MCP is available across projects.
Choose project-only scope when you need it. Your agent should preserve other
MCP entries and ask before replacing an existing connection.

<span id="prepare-the-launch"></span>

## Existing Local Connections

The client-specific pages in the sidebar retain stdio examples for people
who deliberately maintain a separate local installation. Those examples and
[manual installation](../setup/manual-install.md) are not hosted setup steps.
No executable, checkout, local credential-file path or server launch command
belongs in the hosted connection.

## Keep Credentials Private

Enter only the [keys you need](../api-keys.md) and the independent client secret
through the client's protected environment or secret mechanism. Templates
contain variable names, not values. Preserve existing credentials. Never paste
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
It describes the hosted server's configured models and services.
Discovery proves configuration and tool availability, not API-key validity,
account entitlement, or model whitelist access.

There is no need for users to start a server or run a validation script.

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

- **Cannot connect:** check the HTTPS URL including `/mcp`, client transport
  support, network access and service availability.
- **Discovery works but generation fails:** check private header mappings and
  provider account access. Discovery does not verify credentials.
- **A tool is missing:** verify it is available on HTTP. TTS and local artifact
  tools are not; do not substitute a new local installation automatically.
- **A provider task ID is unavailable:** use the original credentials and
  ownership scope; reconcile acceptance instead of recreating it.
- **Edition rejects the configuration:** use that client's guide and official
  source. Do not swap envelope keys blindly or inline keys as a workaround.

## Sources

Official client references and validation limits are listed in the sibling
guides. The [hosted contract](../../specs/SPEC_HOSTED_BYOK.md) defines the server
boundary; the [deployment record](../hosted-deployment-status.md) records dated
live acceptance separately from client-template checks.
