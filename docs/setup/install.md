---
title: Connect to Hosted Seed MCP
description: Connect your AI client to the hosted endpoint. No server installation required.
---

**Seed MCP runs on BytePlus. You only connect your AI client.**
No local MCP server or Kubernetes access is needed.

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

Start with **MCP URL + your ModelArk API key**. Generation may incur charges.
Use your client's protected secret settings or environment-backed headers.

| Header | Value you supply privately |
| --- | --- |
| `X-ModelArk-Api-Key` | Your ModelArk API key for images, video and managed Files |
| `X-Seed-Speech-Api-Key` | Your Seed Speech API key for Seed Audio and enabled TTS |
| `X-MCP-Client-Secret` | Optional: separate per-client concurrency admission |

Use the provider key for your chosen service, or both for image/video and audio.
[Get API keys](../api-keys.md).

Omit the client-secret header for the simplest setup. Callers using the same
provider key then share one per-pod principal concurrency allowance.

### Optional Client Secret

To separate client admission, generate **32 random bytes encoded as 64 lowercase hex**
privately (for example, `openssl rand -hex 32`). Keep the value stable and
different from every provider key. Add `X-MCP-Client-Secret` through your
client's private header settings; do not send an empty value.

For Codex/Claude, the snippet generator's `--client-secret-env SEED_MCP_CLIENT_SECRET`
opts in using a private environment variable. No server issues or stores this
secret. It does not change file/task permissions or provide a spend limit.

Never put secrets in chat, shared configuration or Git. Do not use
`Authorization` or OAuth. The server does not persist provider keys.

<span id="clients"></span>

## 3. Configure Your Client

Choose your client below. Environment-backed examples contain **names**, not
secrets; supply values privately to the client process, not just another terminal.
TRAE uses private manual entry instead.

### Codex

<details>
<summary>Configuration</summary>

Add to your Codex configuration, normally `~/.codex/config.toml`
(or your configured `CODEX_HOME` location):

```toml
[mcp_servers."ark-seed"]
url = "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp"
tool_timeout_sec = 660

[mcp_servers."ark-seed".env_http_headers]
"X-ModelArk-Api-Key" = "SEED_MCP_MODELARK_KEY"
```

</details>

### Claude Code

<details>
<summary>Configuration</summary>

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
        "X-ModelArk-Api-Key": "${SEED_MCP_MODELARK_KEY}"
      }
    }
  }
}
```

</details>

### TRAE

<details>
<summary>Configuration</summary>

In TRAE International IDE, open **Settings > MCP > Add > Create Manually**.
Use the HTTP configuration below. Replace the `<enter-...>` placeholder
**privately before confirming**, never in chat or a project file:

```json
{
  "mcpServers": {
    "ark-seed": {
      "url": "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp",
      "headers": {
        "X-ModelArk-Api-Key": "<enter-modelark-key-privately>",
        "RUN_MCP_TIMEOUT_MS": "660000"
      }
    }
  }
}
```

TRAE documents only `${workspaceFolder}` substitution, not environment-backed
headers. Treat saved header values as plaintext credentials: keep the user
configuration private and outside Git/cloud sync. Use another client if your
policy requires secret references. CN/Work editions need their own UI check.
[TRAE reference](https://docs.trae.ai/ide/add-mcp-servers).

</details>

### OpenCode

<details>
<summary>Configuration</summary>

For OpenCode **V2**, merge into user-level
`~/.config/opencode/opencode.json` or `.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "ark-seed": {
        "type": "remote",
        "url": "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp",
        "oauth": false,
        "codemode": false,
        "timeout": { "execution": 660000 },
        "headers": {
          "X-ModelArk-Api-Key": "{env:SEED_MCP_MODELARK_KEY}"
        }
      }
    }
  }
}
```

Use `/mcps` to check the connection. V2 uses `mcp.servers` and milliseconds;
older releases use a different schema. Do not paste this into a classic
configuration unchanged.
[OpenCode reference](https://opencode.ai/docs/mcp-servers/).

</details>

### Cline

<details>
<summary>Configuration</summary>

In the Cline **VS Code extension**, open **MCP Servers > Configure >
Configure MCP Servers** and merge:

```json
{
  "mcpServers": {
    "ark-seed": {
      "type": "streamableHttp",
      "url": "https://st63a28rvt0o3d9htd28d.apigateway-ap-southeast-1.apigw-byteplus.com/mcp",
      "timeout": 660,
      "headers": {
        "X-ModelArk-Api-Key": "${env:SEED_MCP_MODELARK_KEY}"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

`timeout` is seconds. Keep tool approval enabled. Make the environment
variables available to VS Code; missing variables remain literal placeholders.
This example is for the extension, not a claim of Cline CLI compatibility.
[Cline reference](https://docs.cline.bot/mcp/mcp-overview).

</details>

For Seed Audio, replace or supplement the ModelArk header with
`X-Seed-Speech-Api-Key`: enter the Seed Speech key privately in TRAE, or use
`SEED_MCP_SEED_SPEECH_KEY` with your client's reference syntax.

### Other Clients

Cursor, native VS Code MCP and Claude Desktop editions differ.
Use the URL and headers above only if your edition supports **Streamable HTTP
and private custom headers**. Do not copy another client's configuration
format or switch to local installation as a workaround.

These are documentation-checked templates, not live client certification.

<span id="verify"></span>

## 4. Verify Without Spending

Enable `ark-seed` and ask:

```text
Use only the ark-seed server. List its tools and call ark_list_models
with {"input": {}}. Report available services and models.
Do not generate media, upload files, or make paid calls.
```

This source revision exposes twelve tools and `connection=null`. A hosted
deployment may still run an earlier revision; tools/list is authoritative.
Discovery is free and makes no
provider calls; it does not validate your key or account access.
Problems? See [connection checks](shared-server.md).

Then [create your first image, video or audio clip](first-run.md).

### Hosted Availability

Check tools/list for the deployed revision. [Managed Files](../files.md) use
your ModelArk key without a TOS bucket: cloud uploads import HTTPS URLs;
local uploads require installing `seed-mcp-upload` on the client.
[Seed TTS 3](/seed-mcp/tool-reference/seed-tts-generate/) returns native audio without TOS;
playback varies. See [service limits](../service.md).

<span id="guided-local-setup"></span>

The [agent skill](agent-skill.md) is optional; it is not needed to connect.
