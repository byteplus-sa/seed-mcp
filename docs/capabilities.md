---
title: Tools at a Glance
description: Baseline hosted tools and optional Seed TTS 3 speech synthesis.
---

Usually, you can just [describe what you want in chat](setup/first-run.md).
Your client chooses from these tools. TTS needs operator-enabled output storage.

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
| Speak text or SSML | [seed_tts_generate](/seed-mcp/tool-reference/seed-tts-generate/) | Seed Speech key and authorized voice; available when hosted TTS is enabled |

## Models and Previews

Use discovery for the configured model IDs and limits. It does not prove
account access. Model tables and exact parameters live on each tool's page.
Seedream and Seedance support `dry_run` previews; other generation calls
may incur charges.

<span id="uploads-and-outputs"></span>

## References and Results

Use accessible HTTPS URLs for reference media. Seedance also accepts existing
authorized `asset://` references; it does not create or verify those assets.
Temporary uploads and local artifact tools are not available on this deployment.
Download generated media before its URL expires.

See [service limits](service.md) and [calling tools](calling-tools.md) for
privacy, result handling and recovery.
