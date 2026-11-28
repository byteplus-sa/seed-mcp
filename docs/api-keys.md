# Get API Keys

Use keys from your own [BytePlus account](https://console.byteplus.com).
You only need the provider for the media you want to create.

| Media | Provider key | Header sent to Seed MCP |
| --- | --- | --- |
| Images, video and managed reference files | ModelArk | `X-ModelArk-Api-Key` |
| Scene audio and enabled TTS | Seed Speech | `X-Seed-Speech-Api-Key` |

## ModelArk

1. Open **ModelArk > API Key** in the BytePlus console.
2. Create a key and save it privately when shown.
3. Confirm your account has access to the Seedream or Seedance model you need.

## Seed Speech

1. Open **BytePlus Voice / Seed Speech** in the console.
2. Create a key under API key or application management.
3. Confirm the application has Seed Audio or Seed TTS access; TTS also needs an authorized voice.

This key is separate from your ModelArk key.

## Add the Keys to Your Client

Follow [private-header setup](setup/install.md#enter-credentials-privately).
You also need an independent `X-MCP-Client-Secret`; it is generated privately
by you, not issued by BytePlus.

Never paste keys into chat or send them as tool arguments. Do not use
`Authorization` with Seed MCP. You do not need storage AK/SK or Kubernetes
credentials to use this hosted service.

Discovery does not validate account access. For rejected requests, see
[troubleshooting](troubleshooting.md).
