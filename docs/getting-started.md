# Getting Started

Connect your AI client to the existing BytePlus-hosted Seed MCP service.
There is no server to install or run on your computer and no Kubernetes
access to configure.

## Connect

Follow [Connect to Hosted Seed MCP](setup/install.md):

1. Add the hosted URL as a remote Streamable HTTP MCP connection.
2. Configure your selected provider API key
   through private custom headers.
3. Enable `ark-seed` and verify with discovery only.

## Configuration

Use the [Codex](setup/install.md#codex), [Claude Code](setup/install.md#claude-code)
or [other-client](setup/install.md#other-clients) instructions.
You do not need Git, Python, uv, Docker or a local checkout.
ModelArk keys cover images, video and Files; Seed Speech keys cover Seed Audio and TTS.
The [optional client secret](setup/install.md#optional-client-secret) separates
per-client admission. Without it, callers using the same provider key share
principal concurrency. Never paste credentials into chat.

## Verifying Your Setup

Ask your connected client:

```text
Use only ark-seed. List its tools and call ark_list_models with {"input": {}}.
Report the available services and models. Do not generate or upload.
```

Ordinary discovery returns `connection=null` and makes no provider calls.
It does not validate provider credentials or account entitlement.
See [HTTP connection details](setup/shared-server.md) for optional
header-presence checks and troubleshooting.

## Create Media

Try [Your First Tool Call](setup/first-run.md). Describe the image or video
you want; your client handles tool calls and video polling.
Generation may incur provider charges. Save returned task IDs and download
results before provider URLs expire; do not repeat uncertain creates.
The hosted service has twelve tools for discovery, images, video, scene
audio and Seed TTS. TTS returns audio directly without output storage. Local storage/artifact
tools remain unavailable over HTTP.

The [optional ark-mcp usage skill](setup/agent-skill.md) provides workflow
instructions. It is not required to connect and does not run the server.

<span id="prerequisites"></span>
<span id="stdio-default-for-local-mcp-clients"></span>
<span id="streamable-http-loopback-development"></span>
<span id="dev-mode-with-auto-reload"></span>
<span id="claude-desktop"></span>
<span id="mcp-inspector"></span>

## Next Steps

- [Choose a Tool](capabilities.md) for images, video and audio.
- [Client Integrations](integrations/index.md) for connection compatibility.
- [Direct Execution](integration-guide.md#direct-execution) for developers.
