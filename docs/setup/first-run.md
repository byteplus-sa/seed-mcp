---
title: Create Media
description: Example prompts for images, video and scene audio.
---

After [connecting](install.md), describe what you want in your client's chat.
The client handles tool calls. **Generation may incur charges**; review the
request before approving it.

## Generate an Image

```text
Use ark-seed to generate one image of a red ceramic cup on a wooden
table beside a window. Warm morning light, realistic product photography,
soft shadows, square composition. Show me the finished image and a
download link.
```

<span id="generate-deliberately"></span>

For transparent PNGs and reference edits, see
[the Seedream tool reference](/seed-mcp/tool-reference/seedream-generate-image/#seedream-5-5).

<span id="video-and-other-provider-tasks"></span>

## Generate a Video

```text
Use ark-seed to generate one 5-second landscape video of a red ceramic
cup on a wooden table beside a window. The camera slowly moves closer
as steam rises in warm morning light. Realistic, cinematic style.
Show me the finished video and a download link.
```

This creates a new video; it does not reuse the image above.
The client should poll the returned task until the video is ready.

## Generate Audio

```text
Use ark-seed to create a short cafe soundscape: quiet conversation,
gentle piano and cups being set on tables. Give me an MP3 download link.
```

Seed Audio generates a complete scene. For exact supplied text or SSML, use
[Seed TTS 3](/seed-mcp/tool-reference/seed-tts-generate/) with an authorized voice.
Hosted TTS returns native audio directly. Save the returned audio block;
playback and saving support depend on your client.

<span id="retrieve-the-job-result"></span>

## If the Agent Pauses

```text
Continue checking my existing request and show me the result when it is
ready. Do not submit a new generation request. If the existing request
cannot be recovered, explain what happened before doing anything else.
```

Keep task/request IDs. A timeout does not cancel provider work, and a repeated
request can create another charge. Download results you want to keep:
image/video links last about 24 hours, audio links about two hours.

## Discover Before Spending

```text
Use ark-seed discovery only to show which media services and models are
configured for me. Do not generate media or upload files.
```

Discovery makes no provider calls and does not prove account access.

## Preview an Image Request

Ask for a non-billable preview and approve only `dry_run: true`.
A request preview is not a generated image. It still needs your private
headers; any estimate is not an account quote.

## Technical Reference

See [available tools](../capabilities.md) or
[direct-call result handling](../integration-guide.md#direct-execution).
