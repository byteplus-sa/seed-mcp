# Understanding, object storage, and native assets

Behaviour and gotchas for `seed_understand`, `seed_audio_understand`,
`media_upload`, `media_presign`, and native Seedance asset references.
For parameters see the tool schema and
[API reference](https://byteplus-sa.github.io/ark-mcp/api-reference/). Per-model limits:
[models-and-limits.md](models-and-limits.md); env vars:
[environment.md](environment.md); submitting and polling background work:
[workflows.md](workflows.md), [polling-and-artifacts.md](polling-and-artifacts.md).

## Execution mode at a glance

| Tool | Mode | Needs |
|---|---|---|
| `seed_understand`, `seed_audio_understand` | background required (`ark_job_submit`) | `BYTEPLUS_MODELARK_API_KEY` |
| `media_upload` | background required | object storage (TOS or S3) |
| `media_presign` | foreground | object storage |

**Never work around a client timeout by shortening the prompt or calling a
background-required tool in the foreground**: submit with `ark_job_submit` and
poll `ark_job_get`. `save_to` inside a job needs `OUTPUT_ROOTS` on the server
(a worker has no MCP roots) and is otherwise rejected before billing; see
[background-job-output.md](background-job-output.md).

## Understanding (`seed_understand`, `seed_audio_understand`)

Both tools use ModelArk Chat Completions with **deep thinking always on** and
return **only the final answer** (the trace is never returned or saved). Depth is `reasoning_effort`: `low` for simple OCR or lookups,
`medium` default, `high` for deep reviews; cost shows in `usage.reasoning_tokens`.
Do not pass `thinking` (ignored).

### Choosing the model

- **`seed_understand`**: pick the model from `ark_list_models(kind='understanding')`
  (exact IDs; omit for the default). Per-model limits are in
  [models-and-limits.md](models-and-limits.md); a request outside them fails
  locally before billing.
- **`seed_audio_understand` has no `model` argument.** The server fixes the
  model (`SEED_AUDIO_UNDERSTANDING_MODEL`); `ark_list_models` shows which.

### Media inputs

- **Videos are HTTPS URLs only** (no Base64). Page or platform links (YouTube,
  TikTok, Instagram), auth-gated URLs, and anything that is not a directly
  fetchable video file fail: download locally, `media_upload`, and pass the
  returned URL. Do not substitute transcripts when the task is about visuals.
- **Images**: URL or Base64; upload local files with `media_upload` first.
- **Audio**: 1-8 clips in order; URL preferred. Base64 must be raw (no `data:`
  prefix), at most 10 MB decoded, with `mime_type` one of `audio/wav`,
  `audio/mpeg`, `audio/flac`, `audio/aac`, `audio/mp4`. **Base64 Ogg/Opus/PCM is
  rejected: upload and pass a URL.**
- **Large audio / video soundtracks:** `seed_audio_understand.delivery` is
  `auto` (default), `direct`, or `files_api`. Automatic delivery retries one
  audio-related 400 rejection through Files API; explicit delivery uploads
  first. Files API supports up to 512 MB versus the default model's 25 MiB
  direct URL limit. Base64 stays inline. Video uses its soundtrack plus
  frames sampled at 0.2 fps, which also consume tokens. Outputs report
  `audio_delivery` per input and `delivery_fallback_reason`. Uploads are
  deleted best-effort after the call and otherwise expire after roughly a day.
  Malformed upload successes return `INVALID_RESPONSE` with
  `ambiguous_completion=true`, not a safe retry. Cleanup uses a recoverable,
  validated file ID; without one, the upload must expire.

### Shaping and saving the answer

- **Enforce structure with `response_format`, not prompt wording.** Pass a
  template's JSON Schema verbatim as `type: "json_schema"`; the parsed value is
  in `choices[0].parsed` and is returned even when `return_content` is
  `summary` or `none`. **Always check `choices[0].schema_violation` before
  trusting `parsed`.**
- **`json_retry` (0-2) costs extra billed attempts** and is skipped when
  `finish_reason="length"`: raise `max_tokens` instead (it includes thinking
  tokens). If a retry call itself fails, the earlier billed answer is kept.
- **Keep large answers out of context** with `save_to` plus
  `return_content="none"` (or `"summary"`: first 2,000 characters). `save_to` is
  an absolute path inside an allowed output root (stdio only), validated before
  billing; replacing a different existing file needs `overwrite=true`. If the
  write fails after billing the call still succeeds with `saved_path=null` and
  the full answer inline.
- Ask for timestamps when referencing video moments; name the languages for OCR.

### Timeouts and cost

A chat timeout returns `TIMEOUT` (`retryable=true`) but the server **does not
retry it**: a second full thinking run doubles the cost (429 and 5xx are
retried). Raise `SEED_UNDERSTANDING_TIMEOUT_MS` for long video analysis and size
the job TTL to match. Output is text only.

### Audio transcription and analysis

- **`seed_audio_understand`** answers questions about audio: translation,
  speaker count/gender/emotion, summaries and minutes, music and sound events.
  It can also produce transcripts and speaker labels, but there is no dedicated
  ASR alignment tool. Verify timestamps against the original recording.
- **Structured output:** the default audio model enforces `json_schema` but not
  `json_object`; use `json_schema` when you need JSON.

## Object storage (`media_upload`, `media_presign`)

Needed whenever a tool takes media as a URL only (Seedance video/audio
references, understanding videos, OmniHuman inputs). TOS or S3 makes no difference
to tool behaviour.

### `media_upload`

Uploads 1-50 items (Base64 `data` or stdio-only `file_path`) and returns a
presigned GET `url` and an `object_key` per item, in request order.

- **Items fail independently** and the call still succeeds: **always check
  `failed` and each `items[].error`**; re-upload only `retryable=true` items and
  fix the input of the rest.
- **Only an over-size request fails the whole call.** The total decoded size is
  checked before anything uploads against `MEDIA_UPLOAD_BATCH_MAX_BYTES`
  (default 500 MiB): split into smaller calls. Per-item size limits (video
  200 MiB) fail just that item.
- **`mime_type`** is required for `data` items and inferred from the extension
  for `file_path` items; if inference fails that item errors, so set it for
  unusual extensions.
- **`expires_in_seconds`:** use a sufficiently long TTL (e.g. 3600) when a provider
  fetches asynchronously and a default-TTL URL can expire first. It applies to
  every item in the call.
- **Keep each returned `object_key`** for `media_presign` reuse without
  re-uploading. It is not a provider asset ID.

### `media_presign`

Mints fresh URLs for 1-100 `object_keys` without re-uploading. Read-only,
foreground. Authenticated HTTP requires keys owned by the calling principal;
all shared-key members share that owner and can presign team uploads. Each
key fails on its own, so check `failed` and per-key `code`:

| `code` | Meaning and fix |
|---|---|
| `INVALID_KEY` | Malformed key; use it exactly as `media_upload` returned it |
| `NOT_OWNED` | Not uploaded by this caller; re-upload |
| `INTERNAL` | Unexpected server error; retry |
| provider code | TOS/S3 rejected it (object missing, credentials); see `error`, `request_id` |

### Presign-reuse pattern

Presigned URLs expire (default 30 minutes; `TOS_PRESIGN_TTL_SECONDS` /
`S3_PRESIGN_TTL_SECONDS`). When the same references (character sheets, a music
bed) feed many shots, **upload once, then presign per shot**:

1. Upload all references in one `media_upload` call, check `failed`, and store
   each `object_key` in the project's reference registry.
2. Right before each submission, `media_presign` the keys that shot needs, check
   per-key `code`, and submit immediately while the URLs are valid.

## Native Seedance assets

Existing authorized `asset://<id>` references are passed to Seedance without
downloading or resolving them. Use them in `images`, `videos` or `audios`,
and refer to inputs by position in the prompt. Both transports require only
the normal ModelArk key for generation.

Asset creation, verification, status checks and administration happen outside
this server. A dry run does not prove an asset is active or authorized. Other
products do not support native asset references, and an ordinary object-storage
upload does not create a provider asset.
