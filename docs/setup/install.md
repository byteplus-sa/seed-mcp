---
title: Connect to Hosted Seed MCP
description: Add the BytePlus-hosted MCP endpoint to your AI client. No server installation or Kubernetes access required.
---

**Seed MCP is already hosted on BytePlus. You only connect your AI client.**
You do not need to clone a repository, install Python, Git, uv or Docker, run
a server, or access Kubernetes. The operator runs and updates the service.

<span id="prerequisites"></span>
<span id="choose-an-installation"></span>
<span id="connect-a-client"></span>

## 1. Add the Hosted Endpoint

Open your client's MCP or connector settings and add a **remote Streamable
HTTP** server:

| Setting | Value |
| --- | --- |
| Connection name | `ark-seed` |
| Transport | Streamable HTTP |
| MCP URL | `https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp` |
| Tool timeout, where supported | 660 seconds (660000 milliseconds) |

Keep the `/mcp` path. The documentation website is not an MCP endpoint.
Do not choose a local command, stdio launcher, or Kubernetes connection.
Preserve other MCP entries and ask before replacing an existing `ark-seed`.

Use this endpoint only when you trust its operator: the service receives
your prompts, media references and live provider credentials. Review the
[deployment and security notes](../hosted-deployment-status.md#connect),
including the accepted private-hop certificate-verification exception.
That record is not an availability SLA.

<span id="enter-credentials-privately"></span>

## 2. Configure Private Headers

Generation uses **your own BytePlus provider key** and may incur charges.
Add headers through your client's protected secret settings or supported
environment-backed configuration, not as tool arguments.

| Header | Value you supply privately |
| --- | --- |
| `X-ModelArk-Api-Key` | Your ModelArk API key for Seedream images and Seedance video |
| `X-Seed-Speech-Api-Key` | Your Seed Speech API key for Seed Audio |
| `X-MCP-Client-Secret` | An independent client-generated secret, required for every provider call |

Supply only the provider key for the capabilities you use. For both image/video
and audio, configure both provider headers. See [Provider Keys](../api-keys.md)
for where to obtain them; you do not need the server's environment-file setup.

Generate the client secret once using a trusted secret manager or your OS
cryptographic random generator: **32 random bytes encoded as 64 lowercase hex
characters**. Keep it stable and different from every provider key.
Generate and enter it privately, outside agent output and shared terminals.
Do not use a sample value, an arbitrary password, or a provider key as this secret.

Never paste credentials into chat, shared JSON/TOML, screenshots or Git.
There is no OAuth login, server-issued key, or `Authorization` header.
The server does not persist provider keys. Discovery alone needs no credentials,
but generation and dry runs require the headers above.

## 3. Configure Your Client

The templates below contain environment **names**, not secret values.
Make those private variables available to the actual client process using its
supported secret/environment mechanism. A variable set in a different terminal
may not be visible to a desktop app.

### Codex

Merge this entry into your chosen Codex configuration scope, preserving other
settings. For user-wide setup, use the user configuration, normally
`~/.codex/config.toml` or the configured `CODEX_HOME` location:

```toml
[mcp_servers."ark-seed"]
url = "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp"
tool_timeout_sec = 660

[mcp_servers."ark-seed".env_http_headers]
"X-ModelArk-Api-Key" = "SEED_MCP_MODELARK_KEY"
"X-MCP-Client-Secret" = "SEED_MCP_CLIENT_SECRET" # pragma: allowlist secret
```

### Claude Code

Merge the remote entry through Claude Code's configuration workflow in the
intended user or project scope. It uses `${VAR}` references and a timeout in
milliseconds; this is not a Claude Desktop connector template:

```json
{
  "mcpServers": {
    "ark-seed": {
      "type": "http",
      "url": "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp",
      "timeout": 660000,
      "headers": {
        "X-ModelArk-Api-Key": "${SEED_MCP_MODELARK_KEY}",
        "X-MCP-Client-Secret": "${SEED_MCP_CLIENT_SECRET}"
      }
    }
  }
}
```

For Seed Audio, replace or supplement the ModelArk header with
`X-Seed-Speech-Api-Key`, using the independent variable
`SEED_MCP_SEED_SPEECH_KEY` (Codex) or `${SEED_MCP_SEED_SPEECH_KEY}` (Claude Code).

### Other Clients

In TRAE, Cursor, VS Code, OpenCode or another client, use its supported remote
MCP configuration with the URL and headers above. Exact fields and secret
handling differ by client and edition. Do not reuse the Claude Code JSON
blindly, including in Claude Desktop.

**Your client must support Streamable HTTP and private custom headers.**
If it does not, use a supported client; do not install a local server or
weaken credential protection to work around it. Template parsing is not proof
of successful tool execution in every edition.

<span id="verify"></span>

## 4. Verify Without Spending

Enable `ark-seed`, approve the connection, and ask your client:

```text
Use only the ark-seed server. List its tools and call ark_list_models
with {"input": {}}. Report available services and models.
Do not generate media, upload files, or make paid calls.
```

Expect seven hosted tools and `connection=null` for ordinary discovery.
Discovery makes no provider calls and does not validate your provider key or
account entitlement. A green connection indicator alone is not sufficient.
The optional [image/video configuration check](shared-server.md#optional-imagevideo-configuration-check)
checks header presence and configured bindings, not provider authentication.

Then continue to [Your First Tool Call](first-run.md). Download generated
results before their URLs expire: about two hours for audio and 24 hours for
images/video. Keep accepted task IDs and never repeat uncertain generation
requests automatically.

### Hosted Availability

The hosted service provides Seedream, Seedance and Seed Audio. Seed TTS 3.0,
local file/artifact tools and MCP resources are not available over HTTP.
Temporary uploads are disabled on this deployment. Use provider-accessible
URLs for reference media; a chat attachment is not automatically uploaded.

<span id="guided-local-setup"></span>

## Optional Agent Assistance

A configuration-capable agent can help connect your client, without installing
or running Seed MCP. Give it this request:

```text
Connect my client to the hosted Seed MCP endpoint in this guide, user-wide.
Use remote Streamable HTTP, not a local command or stdio server.
Preserve existing MCP entries. Set up only private header references;
I will enter my provider key and independent client secret privately.
Do not install or run the server, clone its repository, or access Kubernetes.
Verify using discovery only, with no generation, uploads or paid calls.
```

The [ark-mcp-setup skill](https://github.com/byteplus-sa/seed-mcp/tree/main/.agents/skills/ark-mcp-setup)
contains the HTTP connection workflow. The optional
[Skills CLI usage-skill guide](agent-skill.md) adds agent instructions only.
Neither skill is required to connect.
