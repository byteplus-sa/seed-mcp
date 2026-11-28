# Create-tool reference

Per-product behaviour of the create tools that the tool schemas do not spell out: flows, cross-field rules, gotchas, and recovery. Parameters, ranges and output fields are in each tool's schema (also [API reference](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/api-reference.md)); per-model limits are in [models-and-limits.md](models-and-limits.md); polling, persistence and artifact handling are in [polling-and-artifacts.md](polling-and-artifacts.md); direct execution is in [workflows.md](workflows.md).

**Choose transport first:** HTTP calls provider tools directly in the foreground,
with selected provider key plus client secret headers. It has no jobs/native
tasks/local storage/artifact tools/resources. Optional `media_prepare_upload`
signs temporary TOS references for enrolled clients; the client uploads directly.
Stdio also calls directly;
persistence guidance below is local-only.
**Never resubmit a create tool to poll or bypass an ambiguous failure.**
Take exact model IDs from `ark_list_models`.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

- [Variations and dry runs](#variations-and-dry-runs)
- [Seedance](#seedance)
- [Seedream](#seedream)
- [Seed Audio](#seed-audio)

## Variations and dry runs

**There are no separate variation tools.** Set `variations` on the create tool.

| Tool | `variations` | Seeds | Where results land |
|---|---|---|---|
| `seedance_create_task` | 1-5, each a separate billed task | none | `tasks[]` with `task_id` and/or `error`; overlapping `submitted` / `failed` counts |
| `seedream_generate_image` | 1-10, one provider call each | base `seed` | `summary` (`VariationSummary`) |
| `seed_audio_generate` | 1-5 | none (Seed Audio has no seed) | `summary` (`VariationSummary`) |

- **Partial failure is normal.** Each variation is independent; 4 of 5 can succeed and the call still returns 4 results plus 1 error. Read every `error` before concluding.
  There is no batch replay or automatic resume of missing variations.
  Omit legacy `idempotency_key` on both transports.
- **No separate per-variation timer.** The whole-call cooperative deadline includes all waiting. Provider admission is separately bounded. A batch deadline or storage failure can set `error.phase`: `queued` (`QUEUE_TIMEOUT`, unstarted), `generating` (may have completed, **do not retry blindly**), `persisting` (billed output not stored). Whole-tool expiry instead returns text-only `TOOL_DEADLINE_EXCEEDED` with safe known IDs; reconcile partial acceptance.
- **`variation_prompts`** must have exactly `variations` entries and replaces `prompt` (and satisfies "prompt required").
- **Local export:** image and audio variations need an `output_path` directory ending in `/`. Video variations are polled together with **one** `gen_task_get` call over all non-null `task_id`s.
- **`dry_run: true`** (Seedance and Seedream only) runs local validation and directly returns `preview` (provider request bodies with media URLs reduced to scheme and host, Base64 reduced to its size) plus `estimated_cost_usd`. **Nothing is submitted or billed**; the cost is a built-in estimate, not account billing or a provider quote. It does not check native asset authorization. Remove `dry_run` only for an approved paid operation.
- **Runtime validation reports everything at once.** Per-model limits are checked from the capability registry before any provider call, and all violations come back in one error ending with `Call ark_list_models(kind=...) for per-model limits.` Fix them together.

## Seedance

Needs `BYTEPLUS_MODELARK_API_KEY`. Video is **asynchronous**: `seedance_create_task` returns `tasks[].task_id`; poll with `gen_task_get` ([polling-and-artifacts.md](polling-and-artifacts.md)). States: `queued -> running -> succeeded | failed | cancelled | expired`.

### Model selection

**One tool covers every Seedance model**: 2.0 (Standard, Fast, Mini), regular 2.5, and 2.5 Flash. `ark_list_models(kind='video')` lists the exact `model_id`s, their limits, and which are bound. Omit `model` for the default (`SEEDANCE_DEFAULT_MODEL`, regular Seedance 2.5 unless changed).

- **2.5**: up to 30 s single pass, including 4K through `resolution="4k"` on the same model; richer references, structured editing and native extension (`omni_reference_task_type`), `mov` output, Draft mode, audio-only input. No extra feature flag or model.
- **2.5 Flash**: select `dreamina-seedance-2-5-flash-261115` on the same tool for
  480p/720p reference/edit/extend generation, with the same reference limits
  and formats but no Draft. It is included when bindings are empty; add it
  explicitly to custom binding lists as `seedance_2_5_flash`. Listing it is
  not an account-activation check. Costs use the static 2.5 fallback, not a
  token-based provider quote.
- **2.0 family**: 4K on Standard, Fast/Mini for speed and cost, 15 s maximum, no Draft, no task types, no `output_format`, audio needs an image or video alongside it.

Family limits (resolutions, durations, reference counts, Draft final resolution): [models-and-limits.md](models-and-limits.md).

### Inputs and media rules

- **At least one of `prompt`, `images`, `videos`, `audios`** is required (except with `draft_task_id`). Text-only is valid text-to-video; audio-only works on regular 2.5 and Flash.
- **Media is URL-only for video.** Every video reference must be an HTTPS URL or `asset://<asset_id>`. Images and audio also accept inline Base64 (size- and MIME-checked), but prefer URLs. Local files use stdio `media_upload` or an upload-capable HTTP client with optional `media_prepare_upload` ([media-assets.md](media-assets.md)).
- **Private and link-local hosts are rejected** (SSRF policy); the URL must be publicly fetchable by the provider while the task is queued.
- **`asset://<asset_id>`** passes an existing authorized provider asset natively to Seedance with the ModelArk Bearer key. Establish rights, consent and usability outside this server. The server does not create, resolve or preflight assets; dry runs validate syntax and request limits only.
- **Image roles:** `first_frame`, `last_frame`, `reference_image` (default for bare URLs). Videos and audios have a fixed role.
- **Prompt length:** schema max 32,000 characters; ModelArk recommends staying near 1,000 English words.

### Task types and auto-locked parameters

On regular 2.5 and Flash, `omni_reference_task_type` (`auto`, `reference`, `edit`, `extend`) forces the task type when auto-detection is ambiguous. **Write the prompt to match the type**, otherwise the provider fails the task with `TaskTypeMismatch`.

| Task | Aspect ratio | Duration |
|---|---|---|
| Video editing (`edit`) | Locked to the input video | Locked to the input video (about +/-0.3 s) |
| Video extension (`extend`) | Locked to the input video | Free |
| First or first/last-frame generation | Locked to the first image | Free |
| Text-to-video, standard reference | Free | Free (or `-1` for auto) |

**Server-side rejections** (instead of letting the provider fail with `InvalidParameter.TaskTypeConstraint` after billing a slot):

- `edit` and `extend` need at least one reference video, and `ratio` omitted or `adaptive`.
- `edit` also needs `duration` omitted or `-1`.
- Any request with `first_frame` / `last_frame` images needs `ratio` omitted or `adaptive`.
- 2.0 models reject `omni_reference_task_type` entirely.

### Draft mode (regular 2.5 only)

A cheap 480p preview, then a 1080p final render of the one you like. 4K is supported for ordinary generation, not Draft promotion. Each step is billed separately (the Draft as a normal 480p video). Static video cost previews do not account for resolution or duration.

Poll the Draft to `succeeded`, then promote within 14 days of creation,
or 7 days if created before 2026-10-28 10:00 UTC+8. Keep the ID because listing
only covers seven days. HTTP Draft lookup uses provider-key authorization.

**Reused from the Draft, so omit them (rejected even when identical):** `prompt`, `images`, `videos`, `audios`, `duration`, `ratio`, `generate_audio`, `omni_reference_task_type`. The model is also reused (omit `model`; a different one is rejected), as is the Draft's seed. `resolution` must be omitted or the model's Draft final resolution (the default). Still settable on the final call: `return_last_frame`, `watermark`, `execution_expires_after`, `priority`, `safety_identifier`, `output_format`.

`draft` and `draft_task_id` are mutually exclusive. On a model without Draft support (2.0 or Flash) both are rejected.

These input examples are keyless on both transports. Creation and promotion
are separately billed operations, without saved-response replay.

```json
{ "prompt": "A cinematic 20-second chase through a night market", "duration": 20, "draft": true, "variations": 3 }
```

```json
{ "draft_task_id": "<succeeded draft task_id>" }
```

### Output handling

Retain every non-null task/request ID even alongside an error. Local ownership
recording can fail after acceptance, so `submitted` and `failed` may overlap.
HTTP keeps receipts only in the live call and does not require a local ownership
record for polling. A null ID does not prove that nothing was billed.

## Seedream

Needs local `BYTEPLUS_MODELARK_API_KEY` or HTTP `X-ModelArk-Api-Key` plus the
client secret. **`seedream_generate_image` is the only Seedream tool**:
text-to-image, image-to-image, reference editing, point/box edits, parallel
`variations`, and dry runs with Seedream 5.5 only. Both transports call directly.

### Prompt and edit rules

- **`prompt` is 1-4000 characters including any markup the tool adds**; with `images` it is the edit instruction. Optional only when `variation_prompts` is set.
- **Point and box edits** target the **first** image and require `images`. Pass structured `point` / `bbox`; **do not write the markup into the prompt**. The tool prepends `Image 1<bbox>x1 y1 x2 y2</bbox>` and/or `Image 1<point>x y</point>` (bbox first when both) to **every** variation prompt, which counts against the 4000 characters.
- Coordinates are normalized, top-left `0,0`, bottom-right `999,999`: `normalized = min(999, round(pixel / dimension * 1000))`.
- Reference limits and `size` / `output_format` constraints are in [models-and-limits.md](models-and-limits.md).

### `max_images` versus `variations`

- **`max_images`** accepts only 1 or omission. Provider batches are not supported.
- **`variations`** makes 1-10 separate parallel calls, supports `variation_prompts` and per-variation seeds, and returns `summary` when greater than one (`artifacts` and `usage` stay empty).

### Seeds

Seedream 5.5 does not document this compatibility field; omit it unless provider
acceptance is verified.

A fixed `seed` reproduces request settings, not guaranteed identical pixels. Single-call `-1` or omitted seed remains provider randomness, not a recovered actual seed. With `variations > 1`, `seed` is the **base seed**:

| `seed` | Per-variation seeds |
|---|---|
| omitted | Provider randomizes each; seed **not recorded** in `summary` |
| `-1` | Client picks a random seed per variation; **recorded** |
| `N` | `N, N+1, N+2, ...` wrapped modulo 2147483648; recorded |

### Transparent background

`background="transparent"` requires `output_format` omitted or `png`.
Seedream 5.5 (default) accepts text-only prompts and reference images
without alpha. It defaults to PNG even for ordinary generation.
`prompt_optimization="standard"` is accepted (provider default); `fast` is rejected.
`background="auto"` is the 5.5 default and follows the prompt; JPEG is always opaque.

Use 5.5 size tiers `1K`, `1.5K`, `2K` (default), or positive `WIDTHxHEIGHT`
with 921600-8294400 pixels and width/height ratio 1/16-16, inclusive.
For 4K UHD use `size="3840x2160"` on the same model or bound endpoint.
`"4K"` is not a named tier; `4096x2160` exceeds the pixel limit.
Optional `safety_identifier` must be a stable hashed user ID,
1-64 non-space printable ASCII characters. Previews and logs redact it.
`generations` preserves per-call usage, identifier echo, and provider-reported
image size, format and actual background, with image/variation indices and
matching artifact IDs. Missing values stay null; successful provider metadata
survives partial variation failures. Decomposition/OCR inputs are rejected.

For example, edit a reference into a transparent PNG:

```json
{
  "model": "dola-seedream-5-5-261028",
  "prompt": "Turn the circle into a glossy ceramic button, keep the background transparent",
  "images": [{ "kind": "url", "url": "https://cdn.example.com/circle-rgba.png" }],
  "background": "transparent",
  "output_format": "png"
}
```

### Persistence and local export

- Explicit local `persist=true` stores each image as a durable artifact. Default is false; HTTP rejects true. Storage failures preserve supported provider-URL/inline fallbacks; see [polling-and-artifacts.md](polling-and-artifacts.md).
- `persist=false` returns provider-URL references only.
- Explicit `response_format="b64_json"` with `persist=false` is rejected before
  submission, even for dry runs. Missing output yields `NO_OUTPUT`; unexpected
  Base64-only delivery without persistence yields `NO_DELIVERABLE_OUTPUT`.
- `generations` includes single/variation request IDs, submitted seeds,
  final-prompt hashes and allowlisted options excluding private media and
  identifiers. `images[].inspection` independently measures decoded format,
  dimensions and actual alpha: `verified`, `mismatch`, `invalid`, `unavailable`,
  or null for URL-only delivery. It preserves artifacts, never overwrites
  provider reports, and does not establish visual quality or trigger paid retries.
- Use the bounded [review/edit workflow](workflows.md#seedream-generate-review-edit)
  before accepting text, counts or geometry; publishing previews are a separate check.
- `output_path` (stdio local export) needs `persist=true` and **must be a directory ending in `/`** when `variations > 1`.
- `asset://` references are rejected by Seedream; there is no asset-to-URL resolution fallback.
- Dry-run cost covers `variations` images. 5.5 uses output pixel
  tiers plus $0.008 per input image per variation; a UHD output estimates
  $0.079 before references.

## Seed TTS 3

`seed_tts_generate` uses the Seed Speech key, supplied as a live header on HTTP
or local configuration on stdio. HTTP returns native audio without TOS. It speaks supplied
text/SSML using `dola-seed-tts-3.0`; it does not generate a full audio scene.
Exactly one of `text` or `ssml` is required, plus a compatible authorized
`voice_id` from the [voice list](https://docs.byteplus.com/en/docs/byteplusvoice/voicelist-3-0).
There is no voice enrollment or automatic voice selection.

Call directly with the normal `input` wrapper:

```json
{"input":{"voice_id":"multi_female_skye_v3_uranus_bigtts","text":"Welcome to the demonstration.","language_code":"en","enable_subtitle":true}}
```

- MP3 (default), PCM and Ogg Opus are supported. Output carries the resolved
  encoding, `session_id`, request/log IDs, audio metadata (HTTP) or an artifact (stdio), and optional word alignments.
- `voice_settings` controls speed, volume, pitch, instructions and similarity.
  `pronunciation_dictionary.tone` accepts `term/replacement` rules.
- One bounded JSONL stream becomes complete audio, not live MCP streaming. There is no provider URL, polling, `persist` switch or automatic retry.
- HTTP returns one AudioContent block at content[0], with Base64 data and MIME
  type. structuredContent.audio contains content_index, bytes, mime_type and
  sha256; artifact is null. Save decoded audio client-side. No storage or recovery
  API exists. Client playback/saving support varies; never echo Base64 in chat.
- On stdio, use `output_path` under live MCP roots or `OUTPUT_ROOTS`, or artifact
  export. Local storage fallback is bounded by `ARTIFACT_INLINE_FALLBACK_MAX_BYTES`.
- If fallback is disabled or too small after storage failure, a text-only
  `persist_speech` error retains the request ID and states synthesis completed.
  `retryable=false` means do not resynthesize. `ambiguous_completion=false`
  confirms synthesis completion, not successful delivery or absence of billing.
- Stream output is capped at 30 MiB (40 MiB Base64 before metadata). Text/SSML is capped at 10,000 characters.
  Word times are seconds; `silence_duration` is milliseconds.
- A provider `session_id` is for sequential conversation continuity, not
  idempotency. Disconnects/timeouts can be billed; do not synthesize again blindly.
- Whole-tool deadlines retain the sent TTS `request_id` after dispatch, including
  persistence timeouts. Use it for provider reconciliation, not `gen_task_get`;
  it is not a task ID or proof of acceptance. No request journal is saved.
- Budgeting uses a built-in USD 20 per million characters, including markup,
  not an account quote. See the
  [provider HTTP reference](https://docs.byteplus.com/en/docs/byteplusvoice/seed-tts-3-0-http-streaming).

## Seed Audio

Needs a Seed Speech key, local configuration or HTTP `X-Seed-Speech-Api-Key`.
`seed_audio_generate` produces a full-scene clip from text. Both transports call
directly; HTTP requires persistence false. Default `persist=false` is global;
explicit local true retains outputs. URLs expire after 2 hours.
Missing/unusable URL-only output is a nonretryable per-item
`NO_DELIVERABLE_OUTPUT`, not an empty success or regeneration trigger.

- **References: one kind only.** `audio_references` (up to 3: `speaker` ID, `url`, or `base64`) steer voice or scene; `image_reference` gives visual context. **Passing both is rejected.**
- **Base64 reference audio** is checked against the media limit (30 s by default for WAV) and the audio size cap before submission; prefer a URL for longer material.
- **`asset://` references** are rejected by Seed Audio; only Seedance accepts them natively.
- **`text_prompt` is 1-3000 characters**; a line such as `Max duration: 20 seconds` in the prompt is only used for the cost estimate, not enforced.
- **Output MIME follows `output.format`:** `audio/wav` by default,
  `audio/mpeg` for MP3, `audio/ogg`, or `audio/pcm`. URL references, local
  persistence, variations and fallbacks use the same mapping. This is declared
  format metadata, not byte inspection; raw PCM is not a WAV container.
- **Subtitles** (`output.subtitle`, `subtitle_type` `utterance` or `word`) are
  provider-supplied on the single-call result only; they may be null even when
  requested. Live checks observed missing word/utterance subtitles and OGG
  at 48,000 Hz for a 24,000 Hz request. Controls are forwarded in `audio_config`;
  provider-versus-adapter causes remain unresolved. Verify decoded sample rate,
  raw PCM encoding/channels and subtitles; retain billed output and diagnostics,
  never regenerate automatically to compensate.
- **Variations:** no seed exists, so variations differ only by sampling. With `variations > 1`, `artifact`, `duration_seconds`, `billing_duration_seconds` and `subtitle` are **null**; everything is in `summary` (`total`, `succeeded`, `failed`, per-variation `artifact` or `error`). `output_path` must then be a directory ending in `/`.
- `billing_duration_seconds` can differ from the actual `duration_seconds`.
