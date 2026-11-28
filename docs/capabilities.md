---
title: Tools at a Glance
description: Hosted generation, managed reference files, discovery and speech synthesis.
---

Usually, you can just [describe what you want in chat](setup/first-run.md).
Your client chooses from these tools. TTS returns native audio directly; client playback support varies.

<span id="images-and-video"></span>
<span id="audio"></span>

| Task | Tool | What to know |
| --- | --- | --- |
| Discover models | [ark_list_models](/seed-mcp/tool-reference/ark-list-models/) | No credentials or provider calls for ordinary discovery |
| Generate or edit images | [seedream_generate_image](/seed-mcp/tool-reference/seedream-generate-image/) | Seedream; ModelArk key |
| Create video | [seedance_create_task](/seed-mcp/tool-reference/seedance-create-task/) | Seedance; ModelArk key; returns task IDs |
| Check video progress | [gen_task_get](/seed-mcp/tool-reference/gen-task-get/) | Poll saved IDs; do not create again |
| List videos | [gen_task_list](/seed-mcp/tool-reference/gen-task-list/) | Tasks authorized by your provider key |
| Cancel or delete a video task | [gen_task_cancel_or_delete](/seed-mcp/tool-reference/gen-task-cancel-or-delete/) | Confirm the task and its current status first |
| Generate scene audio | [seed_audio_generate](/seed-mcp/tool-reference/seed-audio-generate/) | Seed Speech key |
| Speak text or SSML | [seed_tts_generate](/seed-mcp/tool-reference/seed-tts-generate/) | Seed Speech key and authorized voice; native audio output without TOS |
| Upload a reference | [ark_file_upload](/seed-mcp/tool-reference/ark-file-upload/) | ModelArk-managed storage; HTTP imports an HTTPS URL |
| Retrieve a reference | [ark_file_get](/seed-mcp/tool-reference/ark-file-get/) | Wait for active with a download URL; no renewal |
| List files | [ark_file_list](/seed-mcp/tool-reference/ark-file-list/) | One page authorized by your ModelArk key |
| Delete a file | [ark_file_delete](/seed-mcp/tool-reference/ark-file-delete/) | Permanent; confirm and wait for dependent tasks first |

## Models and Previews

Use discovery for the configured model IDs and limits. It does not prove
account access. Model tables and exact parameters live on each tool's page.
Seedream and Seedance support `dry_run` previews; other generation calls
may incur charges.

<span id="uploads-and-outputs"></span>

## References and Results

Use accessible HTTPS URLs for reference media. Seedance also accepts existing
authorized `asset://` references; it does not create or verify those assets.
For local media, use the [managed Files workflow](files.md); no bucket setup
is needed. A hosted MCP server cannot read client paths; the client-side helper
streams local files directly to ModelArk. This source revision includes Files;
check the connected deployment's tools/list before use.
Download generated media before its URL expires.

See [service limits](service.md) and [calling tools](calling-tools.md) for
privacy, result handling and recovery.
