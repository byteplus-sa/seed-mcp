---
title: Connect to Hosted Seed MCP
description: Connect your AI client to the hosted endpoint. No server installation required.
---

**Seed MCP runs on BytePlus. You only connect your AI client.**
No local server, software installation or Kubernetes access is needed.

<span id="prerequisites"></span>
<span id="choose-an-installation"></span>
<span id="connect-a-client"></span>

## 1. Add the Hosted Endpoint

Add a **remote Streamable HTTP** connection in your client's MCP settings:

| Setting | Value |
| --- | --- |
| Connection name | `ark-seed` |
| Transport | Streamable HTTP |
| MCP URL | `https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp` |
| Tool timeout, where supported | 660 seconds (660000 milliseconds) |

Use the `/mcp` URL, not this documentation website. Preserve existing MCP
entries. Review [service privacy and trust](../service.md#privacy) before
sending credentials.

<span id="enter-credentials-privately"></span>

## 2. Configure Private Headers

Generation uses **your own provider key** and may incur charges.
Use your client's protected secret settings or environment-backed headers.

| Header | Value you supply privately |
| --- | --- |
| `X-ModelArk-Api-Key` | Your ModelArk API key for Seedream images and Seedance video |
| `X-Seed-Speech-Api-Key` | Your Seed Speech API key for Seed Audio |
| `X-MCP-Client-Secret` | An independent client-generated secret, required for every provider call |

Use the provider key for your chosen service, or both for image/video and audio.
[Get API keys](../api-keys.md).

Generate the client secret privately with a trusted secret manager or OS
cryptographic random generator: **32 random bytes encoded as 64 lowercase hex
characters**. Keep it stable and different from every provider key.

Never put secrets in chat, shared configuration or Git. Do not use
`Authorization` or OAuth. The server does not persist provider keys.

<span id="clients"></span>

## 3. Configure Your Client

These templates contain environment **names**, not secrets. Supply their values
privately to the actual client process; a desktop app may not inherit your terminal.

### Codex

Add to your Codex configuration, normally `~/.codex/config.toml`
(or your configured `CODEX_HOME` location):

```toml
[mcp_servers."ark-seed"]
url = "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp"
tool_timeout_sec = 660

[mcp_servers."ark-seed".env_http_headers]
"X-ModelArk-Api-Key" = "SEED_MCP_MODELARK_KEY"
"X-MCP-Client-Secret" = "SEED_MCP_CLIENT_SECRET" # pragma: allowlist secret
```

### Claude Code

Merge this entry through Claude Code's configuration workflow in your chosen
scope. This template is not for Claude Desktop:

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

TRAE, Cursor, VS Code, OpenCode and Claude Desktop editions differ.
Use the URL and headers above only if your edition supports **Streamable HTTP
and private custom headers**. Do not copy another client's configuration
format or switch to local installation as a workaround.

<span id="verify"></span>

## 4. Verify Without Spending

Enable `ark-seed` and ask:

```text
Use only the ark-seed server. List its tools and call ark_list_models
with {"input": {}}. Report available services and models.
Do not generate media, upload files, or make paid calls.
```

Expect seven tools and `connection=null`. Discovery is free and makes no
provider calls; it does not validate your key or account access.
Problems? See [connection checks](shared-server.md).

Then [create your first image, video or audio clip](first-run.md).

### Hosted Availability

Seedream, Seedance and Seed Audio are available. TTS and local file tools are
not hosted. See [service limits](../service.md).

<span id="guided-local-setup"></span>

The [agent skill](agent-skill.md) is optional; it is not needed to connect.
