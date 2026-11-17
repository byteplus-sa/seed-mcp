---
title: Choose a Tool
description: Find the right Ark MCP capability and learn its credentials, execution mode and result lifecycle.
---

Ark MCP has one tool per capability. Models, variations, edits and previews
are parameters, not separate tool names. Start with `ark_list_models`.
HTTP has 7 tools, or 10 with OmniHuman enabled, anonymous static discovery
and direct foreground provider calls. Local stdio has a 15-tool conditional
catalog, four always registered. It also calls directly, with local
storage/artifacts retained. Neither transport exposes MCP jobs/native tasks.

The sidebar's **Tool Reference** contains one generated page per catalog tool,
with exact input/output schemas, nested types, registration requirements and
execution guidance. The tables below help you choose a starting point.

## Images and Video

| Task | Tool | What to know |
| --- | --- | --- |
| Generate or edit images | [seedream_generate_image](/ark-mcp/tool-reference/seedream-generate-image/) | ModelArk key; reference edits, point/bbox edits, variations and `dry_run` |
| Create video | [seedance_create_task](/ark-mcp/tool-reference/seedance-create-task/) | ModelArk key; select an enabled Seedance model, then poll the provider task |
| Poll Seedance tasks | [gen_task_get](/ark-mcp/tool-reference/gen-task-get/) | Batch status checks; lightweight calls can skip output persistence |
| List or cancel/delete tasks | [gen_task_list](/ark-mcp/tool-reference/gen-task-list/), [gen_task_cancel_or_delete](/ark-mcp/tool-reference/gen-task-cancel-or-delete/) | Owned-task lifecycle; cancellation/deletion has provider-specific semantics |

[Seedream 5.5](/ark-mcp/tool-reference/seedream-generate-image/#seedream-5-5) is the built-in image default
(`dola-seedream-5-5-261028`). It supports text-to-image, reference and point/bbox
editing, and transparent PNG generation without an already-transparent input.
Explicit operator defaults remain unchanged. Layer decomposition and native OCR
are not supported by the MCP integration.

Regular Seedance 2.5 is the default and supports `resolution="4k"` on the
same model, with no separate model or feature gate. Flash uses the same create
tool at 480p/720p without Draft. Empty bindings add Flash alongside the selected
default; explicit lists remain authoritative. Discovery does not prove account
entitlement. The models enabled on the ComfyUI node pack are not automatically
available in Ark MCP.


## Audio

| Task | Tool | Credential |
| --- | --- | --- |
| Generate full-scene audio | [seed_audio_generate](/ark-mcp/tool-reference/seed-audio-generate/) | Seed Speech key |

## Avatars

| Task | Tool | Requirements |
| --- | --- | --- |
| Image + audio to avatar video | [omnihuman_create_task](/ark-mcp/tool-reference/omnihuman-create-task/) | Vision AI key and `BYTEPLUS_OMNIHUMAN_ENABLED=true` |
| Poll/cancel avatars | [omnihuman_get_task](/ark-mcp/tool-reference/omnihuman-get-task/), [omnihuman_cancel_task](/ark-mcp/tool-reference/omnihuman-cancel-task/) | Vision AI credentials and gate |

OmniHuman has its own poller and cancel tool. Avatars are disabled by default.

## Uploads and Outputs

These tools are stdio-only. HTTP has no storage/artifact tools or resources;
clients host references externally and retrieve expiring provider URLs.
Persistence defaults to false globally; HTTP rejects true.

| Task | Tool |
| --- | --- |
| Upload local/Base64 references to TOS/S3 | [media_upload](/ark-mcp/tool-reference/media-upload/) |
| Renew object URLs | [media_presign](/ark-mcp/tool-reference/media-presign/) |
| Read stored artifacts inline | [seed_media_get_artifact](/ark-mcp/tool-reference/seed-media-get-artifact/) |
| Export stored artifacts to a local path | [seed_media_export_artifact](/ark-mcp/tool-reference/seed-media-export-artifact/) |
| Recover a provider URL after persistence failed | [seed_media_persist_url](/ark-mcp/tool-reference/seed-media-persist-url/) |

Video references need public HTTPS URLs. `media_upload` requires configured
object storage and accepts local paths only over stdio. Private-network URLs
are rejected. Store results promptly because provider links expire; consult
[Artifacts](artifacts.md) for durable resource access.
