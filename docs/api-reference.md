# API Reference

Complete schemas, inputs, outputs, and examples for the conditional MCP tool
surface.

The static catalog has 21 local stdio tools, eight always registered locally.
HTTP exposes only tools 1-9 below, plus 10-12 when OmniHuman is enabled.
HTTP registration does not require operator keys; discovery is anonymous/static.
Provider calls run directly in the foreground with selected BYOK headers and
required client secret. No jobs/native tasks/storage/artifact tools/resources
exist on HTTP. No OAuth, signup, server-issued key or provider-key fallback.
See [HTTP setup](setup/shared-server.md). Catalog scope strings below are
metadata, not customer-selected roles.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected on HTTP,
including discovery, before provider dispatch, snapshot capture/save or queue
creation. Omit task opt-in; ordinary jobs are not an HTTP fallback.

**Background, artifact and startup-key guidance below is stdio-only.**
Seed Audio/Seedream `persist` and OmniHuman get `persist_output` default to
false globally. HTTP rejects true, local paths and stored artifact references;
local explicit true remains supported. HTTP clients download expiring URLs.
Generated per-tool pages show both transports and exact current schemas.

## Tool Inventory

| # | Tool | Product | Type | Auth |
|---|---|---|---|---|
| 1 | `ark_list_models` | Discovery | Read-only | No extra tool scope |
| 2 | `seed_audio_generate` | Seed Audio | Required background task | Seed Speech |
| 3 | `seedream_generate_image` | Seedream | Required background task | ModelArk |
| 4 | `seedance_create_task` | Seedance (every configured model; 2.5 supports 4K) | Required background submission | ModelArk |
| 5 | `seed_understand` | Seed 2.1 (optional) | Required background task | ModelArk |
| 6 | `seed_audio_understand` | Seed audio understanding (optional) | Required background task | ModelArk |
| 7 | `gen_task_get` | Seedance tasks | Optional background retrieval | ModelArk |
| 8 | `gen_task_list` | Seedance tasks | Read-only | ModelArk |
| 9 | `gen_task_cancel_or_delete` | Seedance tasks | Destructive | ModelArk |
| 10 | `omnihuman_create_task` | OmniHuman 2.0 (flag-gated) | Required background submission | Vision AI Bearer |
| 11 | `omnihuman_get_task` | OmniHuman 2.0 (flag-gated) | Optional background retrieval | Vision AI Bearer |
| 12 | `omnihuman_cancel_task` | OmniHuman 2.0 (flag-gated) | Destructive | Vision AI Bearer |
| 13 | `seed_media_get_artifact` | Artifacts | Read-only | Local stdio only |
| 14 | `seed_media_export_artifact` | Artifacts | Locate (read-only) or copy (stdio only) | Local stdio |
| 15 | `seed_media_persist_url` | Artifacts | Optional background task | Local stdio only |
| 16 | `media_upload` | Object storage (optional) | Required background task (1-50 files) | TOS / S3 |
| 17 | `media_presign` | Object storage (optional) | Read-only (1-100 keys) | TOS / S3 |
| 18 | `ark_job_capabilities` | Background jobs | Read-only ordinary tool | Local stdio only |
| 19 | `ark_job_submit` | Background jobs | Default background submission path | Dynamic target scope |
| 20 | `ark_job_get` | Background jobs | Read-only ordinary tool | Owner only |
| 21 | `ark_job_cancel` | Background jobs | Destructive ordinary tool | Owner only |

Read the [breaking-capability migration](migration-0.2.md#breaking-capability-migration)
before upgrading; the 0.2 consolidation tables on that page are historical.

**`seedream_generate_image` is the only Seedream tool**: registered whenever
`BYTEPLUS_MODELARK_API_KEY` is set on stdio; its catalog label is `seedream:generate`.
**`seed_audio_generate` covers single and parallel audio**, with catalog label
`seed:audio:generate`.

`seedance_create_task` serves every configured
Seedance model (pick one from `ark_list_models(kind='video')`), is registered
whenever `BYTEPLUS_MODELARK_API_KEY` is set on stdio, with catalog label
`seedance:create`. Seedance 2.5 supports 4K through `resolution="4k"` on the same model;
no additional tool, model, or feature flag is needed.

The three `gen_task_*` tools poll, list, and cancel or delete Seedance tasks.
They register whenever ModelArk is configured on stdio and always on HTTP.
Catalog labels are `gen:read` (`gen_task_get`, `gen_task_list`) and `gen:delete`
(`gen_task_cancel_or_delete`).
**`media_upload` takes a list of files** (`media:upload`)
and **`media_presign` takes a list of keys** (`media:presign`); both are
registered when object storage is configured.
See [security.md](security.md) for the full scope list.

## Tool Annotations

| Tool | readOnly | destructive | idempotent | openWorld |
|---|---|---|---|---|
| `ark_list_models` | true | false | true | false |
| `seed_audio_generate` | false | false | false | true |
| `seedream_generate_image` | false | false | false | true |
| `seedance_create_task` | false | false | false | true |
| `gen_task_get` | false | false | true | false |
| `gen_task_list` | true | false | true | false |
| `gen_task_cancel_or_delete` | false | true | false | true |
| `media_upload` | false | false | false | true |
| `media_presign` | true | false | true | false |
| `seed_understand` | false | false | false | true |
| `seed_audio_understand` | false | false | false | true |
| `seed_media_get_artifact` | true | false | true | false |
| `seed_media_export_artifact` | false | false | true | false |
| `omnihuman_create_task` | false | false | false | true |
| `omnihuman_get_task` | false | false | true | true |
| `omnihuman_cancel_task` | false | true | false | true |
| `ark_job_capabilities` | true | false | true | false |
| `ark_job_submit` | false | false | false | true |
| `ark_job_get` | true | false | true | false |
| `ark_job_cancel` | false | true | false | true |
| `seed_media_persist_url` | false | false | false | true |

`seed_understand` and `seed_audio_understand` perform billable completions and
can write local files with `save_to`; the task pollers (`gen_task_get` and `omnihuman_get_task`) are
not read-only because `output_dir`/`output_path` write local files.

## Background Execution

On stdio only, seven tools declare `execution.taskSupport="required"`:
`seed_audio_generate`, `seedream_generate_image`, `seedance_create_task`,
`omnihuman_create_task`, `media_upload`, `seed_understand`, and
`seed_audio_understand`, including supported variations and dry runs.
By default, discover them
with `ark_job_capabilities`, submit them through `ark_job_submit`, and poll
`ark_job_get` at the advertised two-second interval until terminal. A
task-capable client may instead invoke them with MCP task metadata and read the
result from the `tasks/get` response. Foreground direct calls to those target
tools fail before the provider is contacted.

In this reference, **background result** means the original tool result under
terminal `ark_job_get.result`, or the terminal `tasks/get` response on the
native path.

The task pollers `gen_task_get` (Seedance) and `omnihuman_get_task` declare
`execution.taskSupport="optional"` because a processing-status check is short,
but a successful response with `persist_output=true` may download a large
artifact. Use foreground execution with persistence disabled for quick polling,
then background execution to retrieve and persist completed output.
`gen_task_get` and OmniHuman both default to `persist_output=false`. Pass
`persist_output=true` through `ark_job_submit` or native task augmentation.
`seed_media_persist_url` also supports optional background execution, but
always downloads and stores; it has no persistence-disable status-only mode.
List, presign, artifact-read and cancel/delete tools remain foreground.

The ordinary background-job tools, usable on any MCP client:

1. `ark_job_capabilities()` returns the configured, scope-filtered targets and
   each target's original input schema.
2. `ark_job_submit({"tool_name": name, "arguments": original_arguments})`
   enqueues the same registered task-enabled tool and returns a
   server-generated Ark `job_id`.
3. `ark_job_get({"job_id": id})` returns `working` or a terminal snapshot. On
   completion, `result` preserves the original MCP tool result. Check
   `result.is_error` and read `result.structured_content`; job completion is
   not proof that provider generation succeeded.
4. `ark_job_cancel({"job_id": id})` cooperatively cancels the local job.

The ordinary path uses the same worker, target schema validation,
target-scope check, tenant/principal ownership, replay claim, budget, concurrency,
metrics, and provider adapter as native task augmentation. Ark job IDs and
provider task IDs are separate identifiers.

## Local Output Paths

On stdio transport, these fields write output straight to a local file:
`output_path` on `seedream_generate_image`, `seed_audio_generate`, and
`omnihuman_get_task`; `output_dir` on `gen_task_get`; `save_to` on `seed_understand`
and `seed_audio_understand`; and `destination_path` on
`seed_media_export_artifact`. Each comes with an `overwrite` boolean (default
`false`).

| Rule | Behavior |
|---|---|
| Transport | stdio only; rejected on HTTP |
| Path form | Absolute. `output_path` names a file, or a directory when it ends with `/` (files named `<artifact_id>.<ext>`) |
| Allowed roots | Client MCP roots (`roots/list`) first, otherwise `OUTPUT_ROOTS`; with neither, path writing is disabled. Inside `ark_job_submit` there are no MCP roots, so `OUTPUT_ROOTS` is required |
| Timing | Validated before any provider call |
| Preconditions | Media-output paths require `persist=true` or `persist_output=true`; image/audio `output_path` must be a directory ending `/` for `variations > 1` or image `max_images > 1`; answer paths use `save_to` |
| Existing files | Replaced only with `overwrite=true`; identical content is success |
| Failure | A failed local write never fails the call; see `ArtifactRef.local_path` / `export_error` |

`gen_task_get` writes each persisted video and last-frame output into
`output_dir` as `<artifact_id>.<ext>`.
`seedream_generate_image` and `seed_audio_generate` with `variations > 1` write
**every** succeeded variation into the `output_path` directory (see
`summary.variations[].artifact.local_path`).

---

## Shared Types

### MediaSource

A media reference by URL or Base64.

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | `"url"` \| `"base64"` | Yes | Source type |
| `url` | string | If kind=url | HTTPS URL |
| `data` | string | If kind=base64 | Base64-encoded data |
| `mime_type` | string | No | MIME type |

Seedance image/audio inputs also accept `url: "asset://<asset_id>"`;
video inputs accept the native URI directly. Seedance passes existing
authorized assets through without a lookup. Seedream, Seed Audio and
understanding do not support native assets. See [assets.md](assets.md).

### AudioReference

An audio reference for voice cloning.

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | `"speaker"` \| `"url"` \| `"base64"` | Yes | Reference mode |
| `speaker_id` | string | If kind=speaker | Preset speaker ID |
| `url` | string | If kind=url | HTTPS reference audio URL |
| `data` | string | If kind=base64 | Base64 audio data (WAV preflight-checked against 30s limit) |
| `mime_type` | string | No | MIME type |

### ArtifactRef

A durable reference to persisted media.

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique artifact ID, or `provider-url` / `inline-fallback` when the output could not be stored |
| `uri` | string | `seed-media://artifacts/{id}`, or the temporary provider URL when `id="provider-url"` |
| `media_type` | `"image"` \| `"audio"` \| `"video"` | Logical type |
| `mime_type` | string | e.g. `image/png`, `audio/wav`, `video/mp4` |
| `bytes` | integer | Size in bytes |
| `sha256` | string | SHA-256 hex digest |
| `created_at` | string | ISO-8601 timestamp |
| `expires_at` | string | Local artifact expiry |
| `source_expires_at` | string | Provider URL expiry (2h audio, 24h ModelArk image/video; about 1h OmniHuman) |
| `persistence_error` | ArtifactPersistenceIssue \| null | Set when the output was generated (and billed) but could not be stored durably |
| `fallback_data` | string \| null | Base64 output bytes, only for `id="inline-fallback"` (up to `ARTIFACT_INLINE_FALLBACK_MAX_BYTES`) |
| `local_path` | string \| null | Absolute local path written for `output_path`/`output_dir` |
| `export_error` | string \| null | Why the requested local copy was not written; the durable artifact is unaffected |

### ArtifactPersistenceIssue

| Field | Type | Description |
|---|---|---|
| `code` | string | `untrusted_output_host`, `output_too_large`, `invalid_output_mime`, `source_expired`, `download_failed`, or `storage_failed` |
| `message` | string | Credential- and URL-safe failure message |
| `retryable` | boolean | Whether persistence may succeed if attempted again |
| `artifact_limit_bytes` | integer | Maximum size accepted by the durable artifact policy |
| `source_url_expires_at` | string \| null | When the unpersisted provider URL (the artifact's `uri`) expires |

Recover a `provider-url` artifact with `seed_media_persist_url` before
`source_url_expires_at`.

### VariationResult

Result of a single variation within a parallel generation.

| Field | Type | Description |
|---|---|---|
| `index` | integer | 0-based variation index |
| `seed` | integer \| null | Seed used (image only) |
| `artifact` | ArtifactRef \| null | Generated artifact (null if failed) |
| `task_id` | string \| null | Provider task ID for Seedance polling, obtained from the enclosing background result |
| `error` | VariationError \| null | Error details if failed |
| `request_id` | string \| null | Provider request ID |
| `provider_log_id` | string \| null | Provider log ID (Seed Audio) |

### VariationError

| Field | Type | Description |
|---|---|---|
| `code` | string | Error code, e.g. `QUEUE_TIMEOUT`, `TIMEOUT`, `GATHER_ERROR`, a provider code, or an upper-cased persistence code |
| `message` | string | Human-readable message |
| `request_id` | string \| null | Provider request ID, if available |
| `retryable` | boolean | Whether the variation may succeed if retried |
| `ambiguous_completion` | boolean | Whether the provider may have completed despite the error |
| `phase` | `"queued"` \| `"generating"` \| `"persisting"` \| null | Stage at failure: `queued` never started (safe to retry), `generating` provider call in flight, `persisting` output generated but not stored |

### VariationSummary

Aggregate result of a parallel generation.

| Field | Type | Description |
|---|---|---|
| `total` | integer | Total variations requested |
| `succeeded` | integer | Variations that produced output |
| `failed` | integer | Variations that failed |
| `variations` | list[VariationResult] | Per-variation results |

---

## 1. ark_list_models

List the models this server is configured to call, with **per-model limits**,
and report which optional services are enabled. Call it before any generation
or understanding tool: their `model` argument accepts only the exact
`model_id` values listed here. Always registered, needs no scope, and **makes
no provider calls**.

On HTTP, anonymous calls return the configured bindings even without an
environment provider key or client credentials. On stdio, `models` is empty
when ModelArk is not configured. `services[].enabled` reports server
registration, not customer entitlement, provider-key validity or activation.
Discovery uses this server's scoped settings and capability registry; another
server instance's defaults cannot replace its bindings.

### Input

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | string | No | — | Filter to one model kind: `video`, `image`, or `understanding`. Omit to list every configured kind |

### Output

| Field | Type | Description |
|---|---|---|
| `models` | list[ModelInfo] | Configured models matching the filter |
| `services` | list[ServiceStatus] | Enablement of each optional service |

**ModelInfo:** `model_id` (exact ID to pass as `model`), `family`, `kind`,
`is_default` (used when `model` is omitted), `tool` (the tool that accepts the
model), and one limits object matching the kind: `video` (resolutions,
`duration_seconds` range, ratios, reference counts, Draft support, task types,
output formats), `image` (reference count, output formats, batch support,
sizes, transparent background), or `understanding` (modalities, media-part limit,
thinking support, reasoning efforts, response formats).

Discovery returns no prices. Cost estimates are built-in budgeting heuristics,
not account-specific rates. See [Runtime](runtime.md#cost-estimation-tools_costpy).

Understanding modalities and media limits describe the named `tool`, not
every possible use of the underlying model. The `seed_audio_understand`
entry advertises only `audio` (up to eight clips); it has no `model` argument.
Even when audio and visual defaults share an ID, use `seed_understand` for
images/videos. Neither route supports mixed audio/visual requests.

**ServiceStatus:** `service`, `enabled`, and `reason` (the env var or flag that
enables a disabled service; never a secret value). Services: `modelark`,
`seed_audio`, `omnihuman`, `object_storage`.

### Example

```json
{"kind": "video"}
```

---

## 2. seed_audio_generate

Generate full-scene audio through Seed Speech: **one clip, or up to five
independent variations in parallel**. Catalog label: `seed:audio:generate`.
**Required stdio background task**: run it through `ark_job_submit` (or native
task augmentation).

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `text_prompt` | string | No* | — | 1-3000 chars |
| `variations` | integer | No | `1` | 1-5 parallel generations |
| `variation_prompts` | list[string] | No | — | Exactly `variations` entries (each 1-3000 chars); overrides `text_prompt` |
| `audio_references` | list[AudioReference] | No | `[]` | Max 3 |
| `image_reference` | ReferenceImageInput | No | — | Mutually exclusive with audio |
| `output` | AudioOutputOptions | No | — | Format, rate, pitch |
| `watermark` | AudioWatermarkOptions | No | — | AIGC watermark |
| `persist` | boolean | No | `false` | Explicit local persistence; HTTP rejects true |
| `output_path` | string | No | — | Local file or directory (ending `/`); **must be a directory when `variations > 1`**; stdio only, requires `persist=true` |
| `overwrite` | boolean | No | `false` | Replace existing files at `output_path` |

\* Provide `text_prompt` or `variation_prompts`.

**Variations:** Seed Audio has no seed, so variations differ only by the
model's sampling. Partial failures are reported per variation in `summary`
rather than failing the call.

### AudioOutputOptions

| Field | Type | Default | Constraints |
|---|---|---|---|
| `format` | `"wav"` \| `"mp3"` \| `"pcm"` \| `"ogg"` | — | — |
| `sample_rate` | integer | — | 8000-48000 |
| `speech_rate` | integer | — | -50 to 100 |
| `loudness_rate` | integer | — | -50 to 100 |
| `pitch_rate` | integer | — | -12 to 12 |
| `subtitle` | boolean | — | — |
| `subtitle_type` | `"utterance"` \| `"word"` | — | — |

### Output

Returns `SeedAudioGenerateOutput` for both single calls and variations.

| Field | Type | Description |
|---|---|---|
| `provider` | `"byteplus-seed-speech"` | Fixed |
| `model` | `"seed-audio-1.0"` | Fixed |
| `duration_seconds` | float \| null | Output duration; `null` when `variations > 1` |
| `billing_duration_seconds` | float \| null | Billed duration; `null` when `variations > 1` |
| `artifact` | ArtifactRef \| null | Persisted audio; `null` when `variations > 1` |
| `subtitle` | Subtitle \| null | Optional subtitles |
| `request_id` | string \| null | Request ID |
| `provider_log_id` | string \| null | X-Tt-Logid |
| `source_url` | string \| null | Provider URL (2-hour expiry) |
| `summary` | VariationSummary \| null | Per-variation artifacts and errors when `variations > 1`; `null` otherwise |

### Examples

```json
// Single clip (arguments.input)
{
  "text_prompt": "Welcome to BytePlus.",
  "output": { "format": "wav", "sample_rate": 44100 }
}

// Background result
{
  "provider": "byteplus-seed-speech",
  "model": "seed-audio-1.0",
  "duration_seconds": 2.5,
  "billing_duration_seconds": 2.5,
  "artifact": {
    "id": "5828e515-...",
    "uri": "seed-media://artifacts/5828e515-...",
    "media_type": "audio",
    "mime_type": "audio/wav",
    "bytes": 2656078
  },
  "request_id": "",
  "provider_log_id": "20260721...",
  "summary": null
}
```

```json
// Three variations (arguments.input)
{ "text_prompt": "Hello world", "variations": 3 }

// Background result
{
  "provider": "byteplus-seed-speech",
  "model": "seed-audio-1.0",
  "duration_seconds": null,
  "billing_duration_seconds": null,
  "artifact": null,
  "summary": {
    "total": 3,
    "succeeded": 3,
    "failed": 0,
    "variations": [
      { "index": 0, "artifact": { "id": "...", "media_type": "audio", ... } },
      { "index": 1, "artifact": { "id": "...", "media_type": "audio", ... } },
      { "index": 2, "artifact": { "id": "...", "media_type": "audio", ... } }
    ]
  }
}
```

---

## 3. seedream_generate_image

**The only Seedream tool**: text-to-image, image-to-image and reference
editing, point/bbox edits, provider batches (`max_images`), parallel variations,
and dry runs. Registered whenever `BYTEPLUS_MODELARK_API_KEY` is set; catalog capability label `seedream:generate`. **Required background task**: run it through
`ark_job_submit` (or native task augmentation).

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `prompt` | string | No* | — | 1-4000 chars, **including** any point/bbox markup. With `images`, it is the edit instruction |
| `images` | list[ReferenceImageInput] | No | — | Reference or source images (HTTPS URL or Base64); native assets are rejected; per-model maximum checked at runtime |
| `point` | EditCoordinate | No | — | `x`, `y` in 0-999 (normalized) on the **first** image; requires `images` |
| `bbox` | EditBbox | No | — | `x1`, `y1`, `x2`, `y2` in 0-999 on the **first** image, `x1 <= x2`, `y1 <= y2`; requires `images` |
| `model` | string | No | `SEEDREAM_DEFAULT_MODEL` | Exact configured ID from `ark_list_models(kind='image')` |
| `size` | string | No | `2K` on 5.5 | 5.5: `1K`, `1.5K`, `2K`, or positive `WIDTHxHEIGHT` with 921600-4624220 pixels and ratio 1/16-16, inclusive. No generation `auto`; older families remain provider-validated |
| `seed` | integer | No | — | -1 to 2147483647; undocumented compatibility field on 5.5, omit unless verified; the **base seed** when `variations > 1` (see below) |
| `max_images` | integer | No | — | 1-15 images from **one provider call**; batch-capable models only. **Cannot be combined with `variations > 1`** |
| `output_format` | `"png"` \| `"jpeg"` | No | `png` on 5.5 and transparent output; provider default otherwise | Model-dependent |
| `response_format` | `"url"` \| `"b64_json"` | No | — | Base64 requires `persist=true`; the unusable combination is rejected even for dry runs, before submission |
| `watermark` | boolean | No | — | AIGC watermark |
| `prompt_optimization` | `"standard"` \| `"fast"` | No | `standard` on 5.5; operator setting on Pro | 5.5 rejects `fast`; Pro accepts both. Omitted 5.5 mode uses the provider default |
| `background` | `"auto"` \| `"opaque"` \| `"transparent"` | No | `auto` on 5.5; `opaque` otherwise | `auto` is 5.5-only; JPEG always opaque in auto mode. Transparent output requires PNG. 5.5 accepts text or references without alpha; Pro needs exactly one already-transparent PNG |
| `safety_identifier` | string | No | — | 5.5/Pro: 1-64 non-space printable ASCII characters; use a stable hashed user ID, not personal data. Redacted in previews and logs |
| `variations` | integer | No | `1` | **1-10** independent parallel generations |
| `variation_prompts` | list[string] | No | — | Exactly `variations` entries (each 1-4000 chars); overrides `prompt` |
| `persist` | boolean | No | `false` | Explicit local persistence; HTTP rejects true |
| `dry_run` | boolean | No | `false` | Validate and return `preview`; **no provider call, nothing billed** |
| `output_path` | string | No | — | Local file, or directory ending `/`; **must be a directory when `variations > 1` or `max_images > 1`**; stdio only, requires `persist=true` |
| `overwrite` | boolean | No | `false` | Replace existing files at `output_path` |

\* Provide `prompt` or `variation_prompts`.

Unknown input fields are rejected, including layer-decomposition/OCR controls;
only generation and editing are supported.

**Point and bbox edits.** The tool prepends coordinate markup to every prompt
(including each variation prompt): `Image 1<bbox>x1 y1 x2 y2</bbox>` and/or
`Image 1<point>x y</point>`, bbox first when both are set. The 4000-character
limit applies to the final prompt.

**Seed behavior.** Seedream 5.5 does not document this compatibility field;
omit it unless provider acceptance is verified. A single call (`variations=1`)
sends an explicitly supplied `seed` as-is. With
`variations > 1`, `seed` is the base seed:

| `seed` | Per-variation seeds |
|---|---|
| omitted | Provider randomizes each (not recorded) |
| `-1` | Client picks a random seed per variation (recorded in `summary`) |
| `N` | `N, N+1, N+2, ...` (modulo 2147483648) |

**Variations.** Each variation is its own provider call; partial failures are
reported per variation in `summary` rather than failing the call.

### Runtime Validation

Model limits are checked **before any provider call** against the resolved
model's capabilities. All violations are returned in **one error** that ends
with `Call ark_list_models(kind='image') for per-model limits.` Checks:
reference image count, `output_format`, `size`, `max_images > 1` without batch
support, `prompt_optimization` support, and the `background="transparent"`
rules.

Built-in family limits (**`ark_list_models(kind='image')` is authoritative**):

| Family | Max references | `max_images` batch | `output_format` | `prompt_optimization` | Transparent background |
|---|---|---|---|---|---|
| 5.5 (default `dola-seedream-5-5-261028`) | 10 | No (use `variations`) | png (default), jpeg | `standard` only (provider default) | Text-only and reference-based |
| Pro (Seedream 5.0 Pro, `dola-seedream-5-0-pro-260628`) | 10 | No (use `variations`) | png, jpeg | Yes (default `SEEDREAM_PROMPT_OPTIMIZATION_MODE`) | Existing transparent PNG only |
| Lite | 14 | Yes | png, jpeg | Yes | No |
| 4.x | 14 | Yes | jpeg | Yes | No |

Discovery's image limits include `supports_transparent_generation` and
`supports_prompt_optimization`, named size tiers, custom pixel/ratio bounds,
`background_modes`, `prompt_optimization_modes`, and `supports_safety_identifier`.
5.5 requires account authorization; see the
[default upgrade note](configuration.md#seedream-default-model-upgrade-note).
Examples below that return a 5.0 Pro model ID assume Pro is configured explicitly.

### Output

Returns `SeedreamGenerateOutput`, **the same shape for single calls,
variations, and dry runs**:

| Field | Type | Description |
|---|---|---|
| `provider` | `"byteplus-modelark"` | Fixed |
| `model` | string | Resolved model ID |
| `created_at` | string | ISO-8601 |
| `dry_run` | boolean | `true` when nothing was generated; see `preview` |
| `artifacts` | list[ArtifactRef] | Images from a single call (`variations=1`); an image that could not be stored is returned as a `provider-url` or `inline-fallback` reference with `persistence_error`. **Empty for variations and dry runs** |
| `item_errors` | list[SeedreamItemError] | Single-call errors (`index`, `code`, `message`): `NO_OUTPUT` for empty/missing output, `NO_DELIVERABLE_OUTPUT` for unexpected Base64-only output with `persist=false` |
| `usage` | SeedreamUsage \| null | Single-call usage: legacy token fields plus `input_images`, `generated_images`, `output_tokens`; `null` for variations and dry runs |
| `summary` | VariationSummary \| null | Per-variation `index`, `seed`, artifact or error, and `request_id` when `variations > 1` |
| `generations` | list[SeedreamGenerationMetadata] | Completed provider calls ordered by `variation_index` (0 for single calls); provenance, provider reports and advisory image inspections, described below. Empty on dry runs |
| `preview` | SeedreamGeneratePreview \| null | Set only for a dry run |

**Per-call provenance and image metadata:**

| Field | Description |
|---|---|
| `request_id` | Provider request ID, or `null` when absent; available for single calls and variations |
| `seed` | Submitted seed. Single-call `-1`/`null` means provider randomness, not a recovered actual seed |
| `prompt_sha256` | SHA-256 of the exact UTF-8 submitted prompt, including server-added point/bbox markup |
| `request_options` | Submitted size, formats, watermark, background, optimization and batch maximum when present, plus reference count. Excludes prompt, media and safety identifier; omitted options are not inferred |
| `usage`, `safety_identifier` | Provider usage and identifier echo; absent values remain `null` |
| `images[]` | Provider-data `index`, matching `artifact_id`, provider-reported `size`, `output_format`, `background` and independent `inspection` |
| `images[].inspection` | `null` for URL-only delivery; otherwise `status`, decoded `width`/`height`, byte-detected `output_format`, actual `has_transparency` and safe `issues` |

Inspection states are `verified`, `mismatch`, `invalid`, or `unavailable`.
`verified` means byte checks passed, not visual approval. Mismatches and
inspection failures retain billed artifacts and do not overwrite provider reports
or trigger another generation. See [image inspection](artifacts.md#seedream-image-inspection).
Variations report missing/undeliverable outputs as explicit errors in `summary`.

**SeedreamGeneratePreview:**

| Field | Type | Description |
|---|---|---|
| `requests` | list[object] | Provider request bodies, one per variation. Reference URLs are reduced to scheme and host, Base64 to its size, and `safety_identifier` redacted |
| `estimated_cost_usd` | number | Built-in budgeting estimate; **not actual billing or a provider quote** |
| `price_source` | `"builtin"` | Built-in budgeting estimate, not account-specific pricing or actual billing. Dry runs never fetch pricing |

### Examples

```json
// Text-to-image, via ark_job_submit
{
  "tool_name": "seedream_generate_image",
  "arguments": {
    "input": {
      "prompt": "A serene mountain landscape at sunset",
      "size": "2048x2048",
      "seed": 42,
      "output_format": "jpeg"
    }
  }
}

// Background result
{
  "provider": "byteplus-modelark",
  "model": "dola-seedream-5-0-pro-260628",
  "created_at": "2026-07-21T05:36:04+00:00",
  "dry_run": false,
  "artifacts": [
    {
      "id": "83ef8c61-...",
      "uri": "seed-media://artifacts/83ef8c61-...",
      "media_type": "image",
      "mime_type": "image/jpeg",
      "bytes": 428968
    }
  ],
  "item_errors": [],
  "usage": { "total_tokens": 4096 },
  "summary": null,
  "preview": null
}
```

```json
// Edit a region of the first image (arguments.input)
{
  "prompt": "Replace the object with a crown",
  "images": [{ "kind": "url", "url": "https://example.com/frame.png", "mime_type": "image/png" }],
  "bbox": { "x1": 100, "y1": 100, "x2": 400, "y2": 400 }
}
// Prompt sent: "Image 1<bbox>100 100 400 400</bbox> Replace the object with a crown"
```

```json
// Edit an image with transparency on Seedream 5.0 Pro (arguments.input)
{
  "model": "dola-seedream-5-0-pro-260628",
  "prompt": "Turn the circle into a glossy ceramic button, keep the background transparent",
  "images": [{ "kind": "url", "url": "https://example.com/circle-transparent.png", "mime_type": "image/png" }],
  "background": "transparent",
  "output_format": "png"
}
```

```json
// Three variations with a base seed (arguments.input)
{
  "model": "dola-seedream-5-0-pro-260628",
  "prompt": "A futuristic city skyline, cyberpunk",
  "variations": 3,
  "seed": 42,
  "output_path": "/Users/me/out/"
}

// Background result
{
  "provider": "byteplus-modelark",
  "model": "dola-seedream-5-0-pro-260628",
  "created_at": "2026-07-21T...",
  "dry_run": false,
  "artifacts": [],
  "item_errors": [],
  "usage": null,
  "summary": {
    "total": 3,
    "succeeded": 3,
    "failed": 0,
    "variations": [
      { "index": 0, "seed": 42, "artifact": { "id": "16cfa323-...", ... } },
      { "index": 1, "seed": 43, "artifact": { "id": "86f189f2-...", ... } },
      { "index": 2, "seed": 44, "artifact": { "id": "6f5978c9-...", ... } }
    ]
  },
  "preview": null
}
```

```json
// Dry run (arguments.input)
{ "prompt": "A lighthouse at dusk", "variations": 2, "seed": 7, "dry_run": true }

// Background result
{
  "provider": "byteplus-modelark",
  "model": "dola-seedream-5-0-pro-260628",
  "created_at": "2026-07-21T...",
  "dry_run": true,
  "artifacts": [],
  "item_errors": [],
  "usage": null,
  "summary": null,
  "preview": {
    "requests": [
      { "model": "dola-seedream-5-0-pro-260628", "prompt": "A lighthouse at dusk", "seed": 7, "stream": false, "optimize_prompt_options": { "mode": "standard" } },
      { "model": "dola-seedream-5-0-pro-260628", "prompt": "A lighthouse at dusk", "seed": 8, "stream": false, "optimize_prompt_options": { "mode": "standard" } }
    ],
    "estimated_cost_usd": 0.06,
    "price_source": "builtin"
  }
}
```

The `estimated_cost_usd` value above is illustrative only.

---

## 4. seedance_create_task

**One create tool for every configured Seedance model** (2.0, 2.0 Fast, 2.0
Mini, 2.5, and 2.5 Flash): single tasks, up to five parallel variations,
Draft mode, and dry runs. Registered whenever `BYTEPLUS_MODELARK_API_KEY` is
set; catalog capability label `seedance:create`. **Required background
submission**: run it through `ark_job_submit` (or native task augmentation).
Poll the returned task IDs with [`gen_task_get`](#10-gen_task_get).

### Model Selection

Set `model` to an **exact configured ID from `ark_list_models(kind='video')`**;
every video model listed there names `seedance_create_task` as its tool. Omit
`model` to use `SEEDANCE_DEFAULT_MODEL`, which defaults to
`dreamina-seedance-2-5-260628` (Seedance 2.5). Select `resolution="4k"` on
this same model or a configured 2.5 endpoint for retained server 4K acceptance.
Current model-specific provider docs list regular 2.5 only through 1080p;
see the [contract caveat](models.md#video-capabilities-videocapabilities).

Flash uses `dreamina-seedance-2-5-flash-261115` with `seedance_2_5_flash`
through this same tool. It is included when bindings are empty; explicit
binding lists must add it themselves. Regular 2.5 remains the default.
Discovery reports configured support, not account activation.

Family limits as shipped (**`ark_list_models(kind='video')` is authoritative**
for the models configured on a given server):

| Family | Resolutions | Duration (s) | Max images / videos / audios | Draft (final resolution) | Audio-only input | `omni_reference_task_type` | `output_format` |
|---|---|---|---|---|---|---|---|
| `seedance_2` | 480p, 720p, 1080p, 4k | 4-15 | 9 / 3 / 3 | No | No | — | — |
| `seedance_2_fast` | 480p, 720p | 4-15 | 9 / 3 / 3 | No | No | — | — |
| `seedance_2_mini` | 480p, 720p | 4-15 | 9 / 3 / 3 | No | No | — | — |
| `seedance_2_5` | 480p, 720p, 1080p, 4k | 4-30 | 30 / 10 / 10 | Yes (1080p) | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |
| `seedance_2_5_flash` | 480p, 720p | 4-30 | 10 / 5 / 5 | No | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `prompt` | string | No* | — | 1-32,000 chars. Optional when media or `variation_prompts` are given |
| `images` | list[SeedanceImageInput] | No | — | Schema max 30; per-model max checked at runtime. Roles `first_frame`, `last_frame`, `reference_image` |
| `videos` | list[SeedanceVideoInput] | No | — | Schema max 10; per-model max checked at runtime |
| `audios` | list[SeedanceAudioInput] | No | — | Schema max 10; per-model max checked at runtime. 2.5 models accept audio-only input; 2.0 models need an image or video too |
| `model` | string | No | `SEEDANCE_DEFAULT_MODEL` | Exact configured ID from `ark_list_models(kind='video')`. With `draft_task_id`, omit to reuse the Draft task's model |
| `resolution` | `"480p"` \| `"720p"` \| `"1080p"` \| `"4k"` | No | — | Per-model set checked at runtime. `draft=true` allows only `480p` (the default); `draft_task_id` allows only the model's Draft final resolution (the default) |
| `ratio` | string | No | — | `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, or `adaptive` (provider default). Edit, extend, first-frame, and first/last-frame requests on 2.5 require it omitted or `adaptive` |
| `duration` | integer | No | — | -1 (auto) or 4 up to the model max (15 for 2.0, 30 for 2.5). `edit` requires -1 or omitted |
| `omni_reference_task_type` | `"auto"` \| `"reference"` \| `"edit"` \| `"extend"` | No | — | 2.5 models only. `edit`/`extend` need at least one reference video |
| `output_format` | `"mp4"` \| `"mov"` | No | — | 2.5 models only. `mov` is H.264, YUV 4:4:4, PCM audio for post-production; some players cannot play it |
| `generate_audio` | boolean | No | — | Generate an audio track |
| `watermark` | boolean | No | `false` | AIGC watermark |
| `return_last_frame` | boolean | No | — | Return the last frame as a separate image output |
| `execution_expires_after` | integer | No | — | 3600-259200 seconds |
| `priority` | integer | No | — | 0-9; model range checked at runtime |
| `safety_identifier` | string | No | — | Max 64 chars |
| `draft` | boolean | No | — | Draft step 1 (regular 2.5 only, not Flash): 480p preview billed as a normal 480p video. Mutually exclusive with `draft_task_id` |
| `draft_task_id` | string | No | — | Draft step 2: render a succeeded Draft task as the final video. See [Draft Mode](#draft-mode) |
| `variations` | integer | No | `1` | 1-5. Each variation is a **separate billed task** |
| `variation_prompts` | list[string] | No | — | Exactly `variations` entries, each 1-32,000 chars; overrides `prompt` |
| `dry_run` | boolean | No | `false` | Validate and return provider request bodies plus a cost estimate; **nothing is submitted or billed** |

\* At least one of `prompt`, `images`, `videos`, or `audios` is required
(unless `draft_task_id` is set). `variations > 1` needs `prompt` or
`variation_prompts`.

### Runtime Validation

The schema stays permissive; each request is checked against the resolved
model's limits from the capability registry (resolution, ratio, duration
range, priority and expiry ranges, reference counts, Draft support,
audio-only input, task types, `output_format`). **Every violation is returned
in one error** before anything is submitted:

```text
Request is not valid for model '<id>' (<family>):
- <violation>
- <violation>
Call ark_list_models(kind='video') for per-model limits.
```

Existing authorized `asset://` references pass natively to Seedance.
The server checks syntax and request limits, not provider status, rights or
authorization, including on dry runs. There is no asset resolution fallback.

#### Auto-locked parameters by task type

When the provider detects (or is hinted via `omni_reference_task_type`)
that the task is video editing, extension, or first/last-frame generation,
certain parameters are auto-derived from the input media and cannot be
overridden:

| Task type | Aspect ratio | Duration |
|---|---|---|
| Video editing | Locked to input video's ratio | Locked to input video's duration (±0.3s) |
| Video extension | Locked to input video's ratio | Set freely |
| First/last-frame generation | Locked to first image's ratio | Set freely |
| Text-to-video / standard reference | Set freely | Set freely (or `-1` for auto) |

### Draft Mode

**Two steps, regular Seedance 2.5 only; Flash rejects both Draft fields:**

1. **Preview.** Call with `draft: true`. `resolution` must be omitted (becomes
   `480p`) or `480p`. Works with `variations` to compare several previews.
2. **Final.** Once a Draft has succeeded, call again with `draft_task_id` set
   to its `task_id`. The tool checks that the caller owns the task, that it
   succeeded, that it was created in Draft mode, and that it is within 14 days
   of creation (7 days if created before 2026-10-28 10:00 UTC+8).
   - The provider reuses the Draft's model, prompt, media, duration, ratio,
     seed, `generate_audio`, and `omni_reference_task_type`, so `prompt`,
     `images`, `videos`, `audios`, `duration`, `ratio`, `generate_audio`,
     `omni_reference_task_type`, and `draft` **must be omitted** (they are
     rejected even when they match).
   - `model` may be omitted (the Draft's model is used); a different model is
     rejected.
   - `resolution` must be omitted or the model's Draft final resolution
     (`1080p` for 2.5), which is the default. 4K applies to ordinary generation,
     not Draft promotion.
   - `return_last_frame`, `watermark`, `execution_expires_after`, `priority`,
     `safety_identifier`, and `output_format` may be set again.
   - Requires `variations=1` and no `variation_prompts`.

### Variations and Dry Run

- **Variations:** `variations` 2-5 creates that many provider tasks in
  parallel. Partial failures are reported per entry in `tasks` (with `error`)
  rather than failing the call.
- **Dry run:** `dry_run: true` runs all validation and returns `preview`
  instead of submitting. Through `ark_job_submit`, poll until terminal and
  inspect the nested result; completion on the first poll is not guaranteed.
- **Cost preview:** static video estimates do not account for resolution or
  duration, including 4K; they are not provider quotes. Flash currently reuses
  the static 2.5 per-task fallback, not its token-based provider price.

### SeedanceImageInput

Extends `MediaSource` with a `role` field. A bare URL string,
`"asset://<asset_id>"`, or `{"url": "..."}` is accepted and defaults to
`role: "reference_image"`.

| Field | Type | Description |
|---|---|---|
| `role` | `"first_frame"` \| `"last_frame"` \| `"reference_image"` | Image purpose |

### SeedanceVideoInput

Video references are URL-only. Unlike image and audio references, there is no
Base64 path — videos must be uploaded to a publicly reachable HTTPS endpoint
before the tool is called, or referenced as an existing authorized
`asset://<asset_id>`. The server does not check asset status, type or rights.
Use the `media_upload` tool to upload Base64 or a local
file (stdio only) to object storage (TOS or S3) and receive a presigned HTTPS
GET URL. Alternatively, host the video on your own HTTPS endpoint. The URL
must resolve to a public IP (loopback, private, and link-local addresses are
rejected by the SSRF policy). A bare URL string or `{"url": "..."}` is
accepted.

| Field | Type | Description |
|---|---|---|
| `kind` | `"url"` | Always `url` (hard-coded) |
| `url` | string | Public HTTPS URL of the reference video, or `asset://<asset_id>` |
| `role` | `"reference_video"` | Always `reference_video` |

### SeedanceAudioInput

Extends `MediaSource`; also accepts a bare URL string, `"asset://<asset_id>"`,
or `{"url": "..."}`.

| Field | Type | Description |
|---|---|---|
| `role` | `"reference_audio"` | Always `reference_audio` |

### Output

Successful single requests, variation batches and dry runs return
`SeedanceCreateTaskOutput`. A single-call provider or post-acceptance
ownership-record failure instead returns an error `ToolResult` with text, not this
structured success shape. That text retains any known accepted task ID and
diagnostic request ID; preserve them even when `isError=true`.

| Field | Type | Description |
|---|---|---|
| `model` | string | Resolved model ID |
| `family` | string | Resolved model family (e.g. `seedance_2_5`) |
| `dry_run` | boolean | `true` when nothing was submitted; see `preview` |
| `tasks` | list[SeedanceTaskRef] | One entry per requested variation, in order; empty for a dry run |
| `submitted` | integer | Entries with known accepted task IDs, including ownership-record errors |
| `failed` | integer | Entries with submission or ownership-record errors; may overlap with `submitted`. Budget-finalization log events do not add failures |
| `recommended_poll_after_ms` | integer \| null | Suggested delay before the first `gen_task_get` poll; `null` for a dry run |
| `preview` | SeedanceCreatePreview \| null | Set only for a dry run |

**SeedanceTaskRef:**

| Field | Type | Description |
|---|---|---|
| `index` | integer | 0-based variation index (`0` for a single request) |
| `task_id` | string \| null | Known accepted provider task ID, retained alongside ownership-record errors; null when acceptance is unknown or submission failed. HTTP polling requires recorded ownership. For `draft=true`, use as `draft_task_id` once succeeded |
| `request_id` | string \| null | Provider request ID, when returned |
| `error` | VariationError \| null | Submission or post-acceptance ownership-record failure; can coexist with `task_id`. Budget-finalization exceptions alone leave this null |

`submitted` and `failed` are independent counts, not a partition of `tasks`.
For example, two accepted IDs with one ownership-record error give `submitted=2`
and `failed=1`. Accepted ownership-record failures surface as `AcceptedTaskError`
(`OWNERSHIP_RECORD_FAILED`), are ambiguous/nonretryable and never trigger
resubmission. Retain every known ID; if ownership was not recorded, HTTP polling
fails closed and requires provider-side reconciliation with the task/request IDs.
Trusted stdio permits unrecorded IDs, but still rejects a recorded owner mismatch.

Budget-finalization exceptions only log `ERROR` event `budget_finalization_failed`;
they preserve the provider result/error and do not add to `failed`. Failed
commit/release leaves conservative reserved allowance. Reservation before
dispatch still fails closed; cancellation cleanup is shielded best effort, not
a guarantee that no reserved rows remain. See [Runtime](runtime.md#billable-call-composition-billed_provider_slot).

**SeedanceCreatePreview:**

| Field | Type | Description |
|---|---|---|
| `requests` | list[object] | Provider request bodies, one per variation. HTTPS media URLs are reduced to scheme and host, inline Base64 to its size; `asset://` references are kept |
| `estimated_cost_usd` | number | Static estimate from the server's price table for all requests; **not a provider quote** |

### Polling

Read each `tasks[].task_id` from the background result and pass **all of them
in one call** to [`gen_task_get`](#10-gen_task_get). **`queued` or `running` is
not a failure: poll with `gen_task_get`; never resubmit `seedance_create_task`
to poll**, because every submission is a new billed task.

### Examples

```json
// Single task (default model), via ark_job_submit
{
  "tool_name": "seedance_create_task",
  "arguments": {
    "input": {
      "prompt": "A cat walking through a garden",
      "images": ["https://example.com/cat.png"],
      "resolution": "1080p",
      "duration": 10
    }
  }
}

// Background result
{
  "model": "dreamina-seedance-2-5-260628",
  "family": "seedance_2_5",
  "dry_run": false,
  "tasks": [
    { "index": 0, "task_id": "cgt-20260721134956-h5cz9", "request_id": "021...", "error": null }
  ],
  "submitted": 1,
  "failed": 0,
  "recommended_poll_after_ms": 5000,
  "preview": null
}
```

```json
// Variations on a Seedance 2.0 model (arguments.input)
{
  "model": "dreamina-seedance-2-0-260128",
  "variations": 2,
  "variation_prompts": [
    "The cat walks forward slowly",
    "The cat jumps playfully"
  ],
  "images": [
    { "kind": "base64", "data": "...", "mime_type": "image/png", "role": "reference_image" }
  ],
  "resolution": "480p",
  "duration": 5
}

// Background result (one variation failed)
{
  "model": "dreamina-seedance-2-0-260128",
  "family": "seedance_2",
  "dry_run": false,
  "tasks": [
    { "index": 0, "task_id": "cgt-...-rq5gm", "request_id": "021...", "error": null },
    {
      "index": 1,
      "task_id": null,
      "request_id": null,
      "error": { "code": "TIMEOUT", "message": "...", "retryable": false, "ambiguous_completion": true, "phase": "generating" }
    }
  ],
  "submitted": 1,
  "failed": 1,
  "recommended_poll_after_ms": 5000,
  "preview": null
}
```

```json
// Draft step 1: 480p preview (arguments.input)
{ "prompt": "A paper boat drifting down a rainy street", "draft": true }

// Draft step 2: final render from the succeeded Draft (arguments.input)
{ "draft_task_id": "cgt-20260721134956-h5cz9" }
```

```json
// Dry run (arguments.input)
{ "prompt": "A lighthouse at dusk", "variations": 2, "dry_run": true }

// Background result (once ark_job_get is terminal)
{
  "model": "dreamina-seedance-2-5-260628",
  "family": "seedance_2_5",
  "dry_run": true,
  "tasks": [],
  "submitted": 0,
  "failed": 0,
  "recommended_poll_after_ms": null,
  "preview": {
    "requests": [
      { "model": "dreamina-seedance-2-5-260628", "content": [{ "type": "text", "text": "A lighthouse at dusk" }], "watermark": false },
      { "model": "dreamina-seedance-2-5-260628", "content": [{ "type": "text", "text": "A lighthouse at dusk" }], "watermark": false }
    ],
    "estimated_cost_usd": 1.2
  }
}
```

The `estimated_cost_usd` value above is illustrative only.

---

<span id="7-seed_understand"></span>

## 5. seed_understand

Understand images and videos, or reason about a task, through the Seed 2.1
multimodal model. Deep thinking is always on (depth set by `reasoning_effort`),
and only the final answer is returned: the reasoning trace is discarded and
never returned, logged, or saved. The default model
is `dola-seed-2-1-turbo-260628` (Seed 2.1 Turbo); `dola-seed-evolving` (the
latest Seed-series Pro-tier model) is also supported as a recognized built-in
ID — set `SEED_UNDERSTANDING_DEFAULT_MODEL=dola-seed-evolving` to opt in; its
family auto-resolves to `pro` so no explicit `SEED_UNDERSTANDING_MODEL_FAMILY`
is required. Other custom model IDs can be registered via
`SEED_UNDERSTANDING_MODEL_BINDINGS`. Video
Base64 is not supported by the chat endpoint — upload local videos via
`media_upload` first to obtain an HTTPS URL.

### Execution

On stdio, `seed_understand` declares `execution.taskSupport="required"`. A compatible
MCP client invokes it as a task, receives the server-generated task ID without
waiting for the ModelArk response, and polls for the final tool result. The
server recommends a two-second polling interval. Foreground invocation is
rejected immediately instead of waiting until the client timeout expires.
Clients must request a task TTL long enough for the expected analysis duration.
HTTP instead calls the tool directly without task opt-in.

The chat request timeout is `SEED_UNDERSTANDING_TIMEOUT_MS` (default:
`BYTEPLUS_REQUEST_TIMEOUT_MS`). A timeout after possible dispatch returns
`TIMEOUT` with `retryable=false` and `ambiguous_completion=true`: the completion
may have consumed tokens. Lost responses, read/write/protocol transport
failures and malformed provider 2xx responses are likewise ambiguous and
nonretryable. Reconcile by request ID when available; do not blindly repeat
the completion.

429 rejections remain eligible for bounded retries. Chat/mutation 5xx responses
remain marked `retryable=true` by HTTP normalization but are also ambiguous,
so the retry wrapper never retries them. Demonstrably pre-dispatch connection
failures can be retried; understanding's `retry_timeouts=False` disables even
connect/pool `TIMEOUT` retries. Explicit `json_retry` concerns a received
answer's JSON validation, not malformed provider responses or lost completions.

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `prompt` | string | Yes | — | 1-32,000 chars |
| `images` | list[UnderstandingImageInput] | No | — | Max 32; URL or Base64 |
| `videos` | list[UnderstandingVideoInput] | No | — | Max 32; URL only |
| `system` | string | No | — | Max 32,000 chars |
| `model` | string | No | Configured Seed 2.1 model | Must be in capability registry |
| `reasoning_effort` | `"low"` \| `"medium"` \| `"high"` | No | `"medium"` | Depth of deep thinking; always sent |
| `response_format` | UnderstandingResponseFormat | No | — | JSON / JSON Schema, enforced provider-side |
| `json_retry` | integer | No | `0` | 0-2 extra billed attempts on a JSON parse/validation failure; skipped when `finish_reason="length"` |
| `save_to` | string | No | — | Absolute file path; stdio only, inside an output root; validated before billing |
| `overwrite` | boolean | No | `false` | Replace an existing `save_to` file with different content |
| `return_content` | `"full"` \| `"summary"` \| `"none"` | No | `"full"` | `summary` inlines the first 2,000 characters; `none` inlines nothing |
| `temperature` | float | No | — | 0.0-2.0 |
| `max_tokens` | integer | No | — | 1-32,768, including deep-thinking tokens |
| `top_p` | float | No | — | 0.0-1.0 |
| `repetition_penalty` | float | No | — | 0.0-2.0; Ark-only |
| `thinking` | boolean | No | — | Deprecated and ignored; `false` only logs a warning |

### UnderstandingResponseFormat

| Field | Type | Required | Constraints |
|---|---|---|---|
| `type` | `"text"` \| `"json_object"` \| `"json_schema"` | Yes | — |
| `json_schema` | object | When `type="json_schema"` | Must be omitted otherwise |
| `json_schema.name` | string | Yes | `^[A-Za-z0-9_-]{1,64}$` |
| `json_schema.schema` | object | Yes | Valid JSON Schema draft 2020-12, at most 64 KB serialized; `$ref`, `$dynamicRef` and `$recursiveRef` must be fragment-only (`#...`). Validation is offline; external schemas are never retrieved |
| `json_schema.description` | string | No | Max 2,000 chars |
| `json_schema.strict` | boolean | No | Default `true` |

`save_to` writes the parsed JSON pretty-printed when the answer parsed as JSON,
otherwise the UTF-8 text. Reasoning is never written. If the write fails after
billing, the call still succeeds without `saved_path` and returns the full
answer inline.

### Output

| Field | Type | Description |
|---|---|---|
| `provider` | `"byteplus-modelark"` | Fixed |
| `model` | string | Model used |
| `completion_id` | string \| null | Provider completion ID |
| `choices` | list[UnderstandingChoice] | Final answers; see below |
| `usage` | UnderstandingUsage | Token usage summed over all attempts |
| `attempts` | integer | 1 plus any `json_retry` attempts used |
| `saved_path` | string \| null | Absolute path written for `save_to` |
| `saved_bytes` | integer \| null | Size of the written file |
| `request_id` | string \| null | Provider request ID |

**UnderstandingChoice:**

| Field | Type | Description |
|---|---|---|
| `role` | `"assistant"` | Fixed |
| `content` | string | Final answer; truncated for `summary`, empty for `none` |
| `content_chars` | integer | Full answer length before truncation |
| `content_truncated` | boolean | `true` when `content` is shorter than the full answer |
| `parsed` | object \| array \| null | Parsed JSON when a JSON `response_format` parsed (and, for `json_schema`, validated); returned even with `summary`/`none` |
| `schema_violation` | SchemaViolation \| null | `path` (JSON Pointer, `""` when not JSON), `message`, `finish_reason` |
| `finish_reason` | string | Provider finish reason; `length` means cut off by `max_tokens` |

**UnderstandingUsage:** `prompt_tokens`, `completion_tokens` (including
reasoning), `total_tokens`, and `reasoning_tokens` (thinking token cost when
the provider reports it).

### Example

```json
// Input
{
  "prompt": "Describe what happens in this video and identify the objects in this image.",
  "videos": [{ "kind": "url", "url": "https://.../sample.mp4", "mime_type": "video/mp4" }],
  "images": [{ "kind": "url", "url": "https://.../frame.png", "mime_type": "image/png" }],
  "reasoning_effort": "medium",
  "max_tokens": 4096
}
```

---

<span id="8-seed_audio_understand"></span>

## 6. seed_audio_understand

Understand, transcribe, translate, or reason about audio clips (speech, music,
or sound) through a ModelArk chat model with audio input. The model is set by
`SEED_AUDIO_UNDERSTANDING_MODEL` (default `seed-2-0-lite-260428`) and is not a
per-call argument. Deep thinking is always on (depth set by `reasoning_effort`),
and only the final answer is returned. Transcription and timestamps are
model-generated, not dedicated alignment; verify them against the recording.

The tool shares `seed_understand`'s answer-shaping fields and output shape:
`system`, `reasoning_effort`, `response_format`, `json_retry`, `save_to`,
`overwrite`, `return_content`, `temperature`, `max_tokens`, `top_p`, and
`repetition_penalty` behave exactly as documented in
[section 5](#5-seed_understand), including retry safety. It requires background
execution on stdio and direct foreground calls on HTTP, and uses the
`understanding:read` catalog label and `SEED_UNDERSTANDING_TIMEOUT_MS`.

`json_schema` is enforced by the provider for `seed-2-0-lite-260428`;
`json_object` is not enforced by that model, so prefer `json_schema` (or set
`json_retry`) when you need JSON.

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `prompt` | string | Yes | — | 1-32,000 chars |
| `audios` | list[UnderstandingAudioInput] | Yes | — | 1-8 clips, sent in order |
| `delivery` | `"auto"` \| `"direct"` \| `"files_api"` | No | `"auto"` | Automatic Files API fallback, direct only, or upload URLs first; Base64 stays inline |
| *(shared fields)* | — | No | — | As `seed_understand`, without `images`, `videos`, `model`, or `thinking` |

**UnderstandingAudioInput:** `kind` (`"url"` or `"base64"`), `url`, `data`,
`mime_type`.

- `kind="url"`: an HTTPS URL that passes the SSRF policy. The provider fetches
  and decodes it; `mime_type` is optional.
- `kind="base64"`: raw Base64 (no `data:` prefix), at most 10 MB decoded.
  `mime_type` is required and must be one of `audio/wav` (also `audio/x-wav`,
  `audio/wave`), `audio/mpeg` (`audio/mp3`), `audio/flac` (`audio/x-flac`),
  `audio/aac` (`audio/x-aac`), or `audio/mp4` (m4a). The provider rejects
  Base64 Ogg/Opus and raw PCM, so upload those via `media_upload` and pass the
  URL instead.

### Output

Same fields as [`seed_understand`](#5-seed_understand) (`provider`, `model`,
`completion_id`, `choices`, `usage`, `attempts`, `saved_path`, `saved_bytes`,
`request_id`). `model` is the configured `SEED_AUDIO_UNDERSTANDING_MODEL`.
Also returns `audio_delivery` (per-input `url`, `base64`, `files_api_audio`,
or `files_api_video`) and nullable `delivery_fallback_reason`.

Direct URL audio is limited to 25 MiB by the default model. Files API accepts
up to 512 MB, including video soundtracks with sampled frames at 0.2 fps
(frames consume input tokens). Automatic fallback only retries a 400 rejection
mentioning audio, once. Uploaded files are deleted best-effort after the call;
unremoved files expire after roughly one day. See [tool details](tools.md#seed_audio_understand).

### Example

```json
// Input
{
  "prompt": "Transcribe the speech and identify each speaker's emotion.",
  "audios": [{ "kind": "url", "url": "https://.../meeting.mp3" }],
  "reasoning_effort": "low",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "speech_analysis",
      "schema": {
        "type": "object",
        "properties": {
          "transcript": { "type": "string" },
          "emotion": { "type": "string" }
        },
        "required": ["transcript", "emotion"],
        "additionalProperties": false
      }
    }
  }
}
```

---

<span id="10-gen_task_get"></span>

## 7. gen_task_get

**One poller for Seedance video tasks**
(`seedance_create_task`, every Seedance model). Registered whenever ModelArk is
configured; catalog capability label `gen:read`. Optional background task (required
when `persist_output=true`).

Fetches tasks with one provider list call per page of 20 task IDs (at most
three pages), filtered by task ID, and re-fetches individually only tasks
missing from the list or succeeded without an output URL. Task IDs the caller
did not create are reported in `errors` instead of failing the call.

### Polling Workflow

1. Run a create tool through `ark_job_submit` and read each provider `task_id`
   from the background result.
2. Call `gen_task_get` in the foreground with **every** task ID you are waiting
   on (`persist_output=false`, the default).
3. While `all_terminal` is `false`, wait `recommended_poll_after_ms` (5000 ms
   while any task is active) and poll again. **`queued` or `running` is not a
   failure; never resubmit the create tool to retry polling**, because that
   creates a second billed task.
4. Once `all_terminal` is `true`, call `gen_task_get` again through
   `ark_job_submit` with `persist_output=true` (optionally `output_dir`) to keep
   the outputs as durable artifacts before the provider URLs expire (about 24
   hours).

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `task_ids` | list[string] | Yes | — | 1-50 Seedance task IDs (not Ark job IDs); duplicates ignored |
| `persist_output` | boolean | No | **`false`** | Persist each succeeded task's outputs once per task; `true` requires background execution (`ark_job_submit` or native task augmentation) |
| `output_dir` | string | No | — | Local directory; stdio only, requires `persist_output=true`; see [Local Output Paths](#local-output-paths) |
| `overwrite` | boolean | No | `false` | Replace existing files in `output_dir` |

### Output

Returns `GenTaskGetOutput`:

| Field | Type | Description |
|---|---|---|
| `tasks` | list[GenTask] | One entry per found task, in request order |
| `errors` | list[GenTaskLookupError] | `task_id`, `code` (`NOT_OWNED`, `NOT_FOUND`, or a provider code), `message` |
| `all_terminal` | boolean | `true` when every found task has finished, so polling can stop |
| `active_tasks` | integer | Found tasks still queued or running |
| `recommended_poll_after_ms` | integer \| null | `5000` while any task is active; `null` when `all_terminal` |

**GenTask:**

| Field | Type | Description |
|---|---|---|
| `task_id` | string | Provider task ID |
| `model` | string | Model ID that ran the task |
| `family` | string \| null | Registry family of the model; `null` when the model is not configured on this server |
| `kind` | `"video"` \| `"unknown"` | Output kind from the registry binding for `model` |
| `status` | GenTaskStatus | `queued`, `running`, `succeeded`, `failed`, `cancelled`, or `expired` |
| `created_at` / `updated_at` | string | ISO-8601 |
| `outputs` | list[TaskOutputFile] | Video and optional last-frame outputs; empty until available |
| `error` | TaskError \| null | Provider `code` and `message` when failed |
| `usage` | TaskUsage \| null | `prompt_tokens`, `completion_tokens`, `total_tokens` when reported |
| `draft` | boolean \| null | `true` for a Seedance Draft task (480p preview); once it has succeeded, pass its `task_id` as `draft_task_id` within 14 days of `created_at` (7 if created before 2026-10-28 10:00 UTC+8) |
| `settings` | SeedanceTaskSettings \| null | Video generation settings echoed by the provider when available |
| `queue` | SeedanceQueueInfo \| null | Server-derived queue timing for a queued or running video task; `null` once finished |

Without persistence, each output carries its expiring `source_url` and
`persistence="not_requested"`. With `persist_output=true`, outputs are copied
**once per task** under a single-flight lock, so overlapping polls never
download the same file twice; a storage failure returns the provider URL with
`persistence="failed"` and a later poll retries.

### TaskOutputFile

One file from a completed Seedance task:

| Field | Type | Description |
|---|---|---|
| `role` | `"video"` \| `"last_frame"` | Output kind |
| `artifact` | ArtifactRef \| null | Durable artifact when persisted |
| `source_url` | string \| null | Expiring HTTPS provider URL, retained when persistence is skipped or fails |
| `source_expires_at` | string \| null | ISO-8601 expiry of `source_url` |
| `persistence` | `"not_requested"` \| `"persisted"` \| `"failed"` | Storage outcome, independent of provider success |
| `persistence_issue` | ArtifactPersistenceIssue \| null | Safe explanation when persistence failed |

### SeedanceQueueInfo

ModelArk publishes no queue position or ETA. These values are derived by the
server from the task's timestamps and expiry setting; they are estimates, not a
provider SLA.

| Field | Type | Description |
|---|---|---|
| `queued_seconds` | integer \| null | Now minus `created_at` while queued; `updated_at` minus `created_at` once running (approximate) |
| `running_seconds` | integer \| null | Seconds since the last status update while running (approximate) |
| `service_tier` | string \| null | `default` or `flex` |
| `expires_at` | string \| null | `created_at + execution_expires_after`: the provider fails the task if unfinished by then |
| `expires_at_estimated` | boolean | `true` when `execution_expires_after` was not reported and the 48-hour default was assumed |
| `hint` | string \| null | Human-readable summary |

### Task Statuses

| Status | Meaning |
|---|---|
| `queued` | Waiting to start |
| `running` | Generating |
| `succeeded` | Completed, outputs available |
| `failed` | Failed, check `error` |
| `expired` | Expired before completion |
| `cancelled` | Was cancelled |

### Example

```json
// Input (foreground poll)
{ "task_ids": ["cgt-20260721134956-h5cz9", "cgt-20260721135012-k2m8p"] }

// Output (one still running)
{
  "tasks": [
    {
      "task_id": "cgt-20260721134956-h5cz9",
      "model": "dreamina-seedance-2-0-260128",
      "family": "seedance_2",
      "kind": "video",
      "status": "succeeded",
      "created_at": "2026-07-21T06:02:19+00:00",
      "updated_at": "2026-07-21T06:06:13+00:00",
      "outputs": [
        {
          "role": "video",
          "source_url": "https://ark-content-generation.example.com/video.mp4?sign=...",
          "source_expires_at": "2026-07-22T06:06:20+00:00",
          "persistence": "not_requested"
        }
      ],
      "usage": { "completion_tokens": 48400, "total_tokens": 48400 }
    },
    {
      "task_id": "cgt-20260721135012-k2m8p",
      "model": "dreamina-seedance-2-0-260128",
      "family": "seedance_2",
      "kind": "video",
      "status": "running",
      "created_at": "2026-07-21T06:02:35+00:00",
      "updated_at": "2026-07-21T06:03:10+00:00",
      "outputs": []
    }
  ],
  "errors": [],
  "all_terminal": false,
  "active_tasks": 1,
  "recommended_poll_after_ms": 5000
}

// Input (background persistence, via ark_job_submit)
{ "task_ids": ["cgt-20260721134956-h5cz9"], "persist_output": true }
```

---

<span id="11-gen_task_list"></span>

## 8. gen_task_list

List the caller's ModelArk generation tasks (Seedance video), **newest
first**, covering tasks created in the **last 7 days** (the provider's list
window). Registered whenever ModelArk is configured; catalog capability label `gen:read`. Use `gen_task_get` for outputs.

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `page_size` | integer | No | `20` | 1-100 |
| `cursor` | string | No | — | Opaque `next_cursor` from a previous call made with the same filters |
| `status` | GenTaskStatus | No | — | `queued`, `running`, `succeeded`, `failed`, `cancelled`, or `expired` |
| `model` | string | No | — | Exact model ID |
| `task_ids` | list[string] | No | — | Up to 100; IDs the caller does not own are skipped |

### Output

Returns `GenTaskPage`:

| Field | Type | Description |
|---|---|---|
| `tasks` | list[GenTaskSummary] | Matching tasks, newest first: `task_id`, `model`, `kind`, `status`, `created_at`, and `error` when failed |
| `next_cursor` | string \| null | Pass back as `cursor` to continue; `null` when there are no more tasks |

### Paging Rules

- **Follow `next_cursor` until it is `null`.** A page may hold **fewer than
  `page_size` tasks while `next_cursor` is non-null**, so a short page does not
  mean the list is finished.
- **Keep the same filters while paging.** A cursor is bound to `status`,
  `model`, `task_ids`, and `page_size`; changing any of them rejects the
  cursor. Repeat the original filters or start again without a cursor.
- Non-local principals page through their owned task IDs from the ownership
  store in slices of 100, so the provider request URL never overflows however
  many tasks the caller owns.

### Example

```json
// Input
{ "status": "succeeded", "page_size": 10 }

// Output
{
  "tasks": [
    {
      "task_id": "cgt-20260721134956-h5cz9",
      "model": "dreamina-seedance-2-0-260128",
      "kind": "video",
      "status": "succeeded",
      "created_at": "2026-07-21T06:02:19+00:00"
    }
  ],
  "next_cursor": null
}
```

---

<span id="12-gen_task_cancel_or_delete"></span>

## 9. gen_task_cancel_or_delete

Cancel (queued) or delete (terminal) a Seedance task.
Registered whenever ModelArk is configured; catalog capability label `gen:delete`. **Destructive.** The tool first fetches the task and
refuses to act when its actual status differs from `expected_status`. A deleted
task's outputs are no longer retrievable through `gen_task_get`.

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | Yes | ModelArk generation task ID |
| `mode` | `"cancel"` \| `"delete"` | Yes | Operation |
| `expected_status` | `"queued"` \| `"succeeded"` \| `"failed"` \| `"expired"` | Yes | Expected current status |
| `confirm` | `true` | Yes | Explicit confirmation |

### DELETE Semantics

| Status | Cancel | Delete |
|---|---|---|
| `queued` | Yes | No |
| `running` | No | No |
| `succeeded` | No | Yes |
| `failed` | No | Yes |
| `expired` | No | Yes |
| `cancelled` | No | No |

### Output

| Field | Type | Description |
|---|---|---|
| `task_id` | string | Task ID |
| `mode` | `"cancel"` \| `"delete"` | Operation performed |
| `previous_status` | string | Status before operation |
| `message` | string | Result message |

---

<span id="1921-omnihuman_create_task--omnihuman_get_task--omnihuman_cancel_task"></span>

## 10-12. omnihuman_create_task / omnihuman_get_task / omnihuman_cancel_task

Registered when `BYTEPLUS_OMNIHUMAN_ENABLED=true` and `BYTEPLUS_CV_API_KEY` is
set. Scopes: `omnihuman:create`, `omnihuman:read`, `omnihuman:cancel`.

`omnihuman_create_task` input: `image` and `audio` (HTTPS URL or
`seed-media://artifacts/<id>`), optional `prompt` (max 2000 characters), and
`watermark` (default `true`). Output: `provider`, `status="accepted"`,
`task_id`, `request_id`, `recommended_poll_after_ms`.

`omnihuman_get_task` input: `task_id`, `persist_output` (default `false`; true
requires local background execution and is rejected on HTTP), `output_path`, `overwrite`. Output: `status`
(`queued`, `running`, `succeeded`, `failed`, `canceled`, `expired`,
`not_found`), `video` (durable `ArtifactRef`), `source_url` and
`source_expires_at` (one-hour provider URL), `persistence`,
`persistence_issue`, `error` (`code`, `message`, failed tasks only).

`omnihuman_cancel_task` input: `task_id`. Output: `canceled`, `message`
(explains why a started task cannot be canceled), `request_id`. See
[tools.md](tools.md#omnihuman_create_task--omnihuman_get_task--omnihuman_cancel_task)
for limits and artifact-reference behavior.

---

## Resources

Stdio only. HTTP lists no resources or resource templates.

### seed-media://artifacts/{artifact_id}

Returns persisted media by artifact ID with the correct MIME type.

```json
{
  "contents": [
    {
      "content": "<base64-encoded-bytes>",
      "mime_type": "image/png"
    }
  ],
  "meta": {
    "artifact_id": "83ef8c61-...",
    "media_type": "image"
  }
}
```

### seed-health://status

Returns server health and configuration status as plain text, including the
build stamp, effective Seedream default model/family and background-job local
export configuration. It exposes neither credentials nor output-root paths.
These diagnostics do not check provider authorization or filesystem readiness;
`configured; needs request preflight` is not proof a destination is writable.

---

<span id="22-seed_media_get_artifact"></span>

## 13. seed_media_get_artifact

Retrieve persisted media by artifact ID. Returns the raw media bytes
(Base64-encoded) with MIME type, SHA-256 hash, and byte count. Use this to
fetch media after the provider URL has expired (2h audio, 24h image/video).
Always registered; catalog capability label `artifacts:read`.

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact_id` | string | Yes | Artifact ID returned by a previous generation call |

### Output

| Field | Type | Description |
|---|---|---|
| `artifact_id` | string | Artifact identifier |
| `media_type` | `"image"` \| `"audio"` \| `"video"` | Logical media type |
| `mime_type` | string | MIME type of the stored content |
| `sha256` | string | SHA-256 hex digest |
| `bytes` | integer | Size in bytes |
| `expires_at` | string \| null | Local artifact expiry, if applicable |
| `data` | string | Base64-encoded media data |

### Example

```json
// Input
{ "artifact_id": "71e9c2a8-..." }

// Output
{
  "artifact_id": "71e9c2a8-...",
  "media_type": "video",
  "mime_type": "video/mp4",
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "bytes": 1748096,
  "data": "AAAAIGZ0cBAAA..."
}
```

---

<span id="23-seed_media_export_artifact"></span>

## 14. seed_media_export_artifact

Locate or copy a persisted media artifact on the local filesystem. Returns the
absolute on-disk path instead of streaming Base64 through the MCP context.
Stdio transport only; the client and server must share a filesystem.
Always registered locally, absent on HTTP.

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact_id` | string | Yes | Artifact ID returned by a previous generation call |
| `destination_path` | string | No | Absolute file path inside an allowed output root where the server writes an atomic copy; omit to return the canonical store path |
| `overwrite` | boolean | No | Replace an existing destination file with different content (default `false`) |

`destination_path` follows the [Local Output Paths](#local-output-paths) policy.
It must be absolute and inside a client MCP root or `OUTPUT_ROOTS`; an existing
file is never silently overwritten (identical content is accepted).

### Output

| Field | Type | Description |
|---|---|---|
| `artifact_id` | string | Artifact identifier |
| `path` | string | Absolute on-disk path of the exported media file |
| `media_type` | `"image"` \| `"audio"` \| `"video"` | Logical media type |
| `mime_type` | string | MIME type of the stored content |
| `bytes` | integer | Size in bytes |
| `sha256` | string \| null | SHA-256 hex digest |
| `copied` | boolean | `true` when copied to `destination_path` (or an identical copy was already there); `false` when `path` is the canonical store location |

### Example

```json
// Input
{ "artifact_id": "71e9c2a8-..." }

// Output
{
  "artifact_id": "71e9c2a8-...",
  "path": "/abs/.artifacts/71/71e9c2a8-....mp4",
  "media_type": "video",
  "mime_type": "video/mp4",
  "bytes": 1748096,
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "copied": false
}
```

---

<span id="24-seed_media_persist_url"></span>

## 15. seed_media_persist_url

Persist a temporary provider output URL as a durable artifact. Use it to
recover an `ArtifactRef` with `id="provider-url"` and a `persistence_error`
before the provider URL expires. Always registered; catalog capability label `media:upload`. Optional background task.

Only trusted BytePlus provider hosts are downloaded, through the same
SSRF-resistant downloader, host allowlist, redirect re-validation, and size
limits as generation-time persistence.

### Input

| Field | Type | Required | Constraints |
|---|---|---|---|
| `url` | string | Yes | HTTPS provider URL, 1-8192 chars |
| `media_type` | `"image"` \| `"audio"` \| `"video"` | Yes | — |
| `mime_type` | string | Yes | Expected MIME type; a specific provider `Content-Type` takes precedence |
| `source_expires_at` | string | No | ISO-8601 URL expiry, copied from the original reference |

### Output

| Field | Type | Description |
|---|---|---|
| `artifact` | ArtifactRef | The new durable artifact |

A failure is a tool error naming the persistence code and whether it is
retryable.

---

<span id="25-media_upload"></span>

## 16. media_upload

Upload **1-50 files** to object storage (TOS or S3) in one call and return a
presigned HTTPS GET URL per file. Registered when the selected object-storage
backend credentials are set (`TOS_*` with default `OBJECT_STORAGE_BACKEND=tos`,
or `S3_*` with `OBJECT_STORAGE_BACKEND=s3`); catalog capability label `media:upload`. **Required background task**: run it through `ark_job_submit` (or native
task augmentation).

Use it for media that cannot be inlined as Base64, most notably Seedance video
references, which are URL-only.

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `items` | list[MediaUploadItem] | Yes | — | 1-50 files |
| `expires_in_seconds` | integer | No | Server presign TTL | 60-604800 seconds for every URL; use at least 3600 for asynchronous inputs |
| `max_concurrent` | integer | No | `4` | 1-8 uploads at once |

**MediaUploadItem:**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `media_type` | `"image"` \| `"audio"` \| `"video"` | Yes | Selects the MIME allow-list and size limit |
| `mime_type` | string | For `data` items | Must be in the allowed list for `media_type`. For `file_path` items it is guessed from the extension when omitted; if it cannot be guessed, that item fails with `Could not infer mime_type ...` |
| `data` | string | one of | Base64 bytes; mutually exclusive with `file_path` |
| `file_path` | string | one of | Absolute local path (stdio only); mutually exclusive with `data` |
| `key_prefix` | string | No | Default `"references"`; alphanumeric, `-`, `_`, `/` |

**Limits:**

- **Per item**: the media-policy maximum for its `media_type` (video up to
  200 MiB). An oversized or invalid item fails on its own.
- **Whole call**: the total decoded size is capped by
  `MEDIA_UPLOAD_BATCH_MAX_BYTES` (default 500 MiB) and **checked before any
  upload starts**. Exceeding it **fails the whole call** ("Split it into
  smaller calls"); it is not a per-item error.

Each object is stored at `<key_prefix>/<media_type>/<uuid>`, and its owner is
recorded for `media_presign` ownership checks. Both storage tools are stdio-only.

### Output

| Field | Type | Description |
|---|---|---|
| `items` | list[MediaUploadItemResult] | Per-item results in request order |
| `succeeded` | integer | Items uploaded |
| `failed` | integer | Items that failed; **check it and `items[].error` when non-zero** |
| `total_bytes` | integer | Bytes uploaded across successful items |

**MediaUploadItemResult:**

| Field | Type | Description |
|---|---|---|
| `index` | integer | 0-based position in the request |
| `file_path` | string \| null | The item's `file_path` as given, to match results to inputs |
| `url` | string \| null | Presigned HTTPS GET URL (null if failed) |
| `object_key` | string \| null | Object key, reusable with `media_presign` |
| `expires_at` | string \| null | ISO-8601 expiry of `url` |
| `mime_type` | string \| null | MIME type used for the upload |
| `bytes` | integer \| null | Uploaded byte count |
| `error` | string \| null | Why the item failed (validation, missing file, provider error); null on success |
| `retryable` | boolean \| null | Whether the failed item may succeed if uploaded again; null on success |

### Example

```json
// ark_job_submit input
{
  "tool_name": "media_upload",
  "arguments": {
    "input": {
      "items": [
        { "media_type": "video", "file_path": "/Users/me/clips/ref.mp4" },
        { "media_type": "image", "mime_type": "image/png", "data": "iVBORw0KGgo..." }
      ],
      "expires_in_seconds": 3600
    }
  }
}

// Background result
{
  "items": [
    {
      "index": 0,
      "file_path": "/Users/me/clips/ref.mp4",
      "url": "https://test-bucket.tos-ap-southeast-1.bytepluses.com/references/video/abc?X-Tos-Signature=...",
      "object_key": "references/video/abc",
      "expires_at": "2026-07-24T07:30:00+00:00",
      "mime_type": "video/mp4",
      "bytes": 1048576,
      "error": null,
      "retryable": null
    },
    {
      "index": 1,
      "file_path": null,
      "url": "https://test-bucket.tos-ap-southeast-1.bytepluses.com/references/image/def?X-Tos-Signature=...",
      "object_key": "references/image/def",
      "expires_at": "2026-07-24T07:30:00+00:00",
      "mime_type": "image/png",
      "bytes": 20480,
      "error": null,
      "retryable": null
    }
  ],
  "succeeded": 2,
  "failed": 0,
  "total_bytes": 1069056
}
```

---

<span id="26-media_presign"></span>

## 17. media_presign

Mint fresh presigned HTTPS GET URLs for **1-100 objects** already in storage
(TOS or S3), without re-uploading. Use it when a reference URL from
`media_upload` has expired or is about to. **No data is transferred.**
Registered with object storage; catalog capability label `media:presign`.
Foreground (read-only).

A malformed, unowned, or provider-failing key is **reported per key** while the
other keys succeed, so check `failed`.

### Input

| Field | Type | Required | Constraints |
|---|---|---|---|
| `object_keys` | list[string] | Yes | 1-100 keys from prior `media_upload` calls (e.g. `references/video/<uuid>`). Alphanumeric, `-`, `_`, `/`; must not start with `/` or `-` or contain empty segments |
| `expires_in_seconds` | integer | No | 60-604800 seconds for every URL; defaults to server presign TTL; use at least 3600 for asynchronous inputs |

### Output

| Field | Type | Description |
|---|---|---|
| `items` | list[MediaPresignItem] | Per-key results, in input order |
| `succeeded` | integer | Keys that produced a URL |
| `failed` | integer | Keys that failed; check `items[].error` when non-zero |

**MediaPresignItem:**

| Field | Type | Description |
|---|---|---|
| `object_key` | string | Key this entry corresponds to |
| `url` | string \| null | Fresh presigned URL (null if failed) |
| `expires_at` | string \| null | ISO-8601 expiry (null if failed) |
| `code` | string \| null | Error code when failed (see below) |
| `error` | string \| null | Human-readable error (null on success) |
| `request_id` | string \| null | Provider request ID for this key's presign call, when available |

| `code` | Meaning |
|---|---|
| `INVALID_KEY` | Malformed object key |
| `NOT_OWNED` | Key was not uploaded by the calling principal |
| `INTERNAL` | Unexpected server error |
| *(provider code)* | The storage provider rejected the presign |

### Example

```json
// Input
{
  "object_keys": ["references/video/abc-123-def", "references/image/def-456-ghi"]
}

// Output
{
  "items": [
    {
      "object_key": "references/video/abc-123-def",
      "url": "https://test-bucket.tos-ap-southeast-1.bytepluses.com/references/video/abc-123-def?X-Tos-Signature=...",
      "expires_at": "2026-07-24T07:30:00+00:00",
      "code": null,
      "error": null,
      "request_id": null
    },
    {
      "object_key": "references/image/def-456-ghi",
      "url": null,
      "expires_at": null,
      "code": "NOT_OWNED",
      "error": "Object key is not owned by the current principal.",
      "request_id": null
    }
  ],
  "succeeded": 1,
  "failed": 1
}
```

---

## Operational HTTP endpoints

When Streamable HTTP is enabled, the ASGI application also exposes:

| Path | Purpose |
|---|---|
| `/health` | Process liveness |
| `/ready` | Minimal SQLite state readiness; no provider probes |
| `/metrics` | Unavailable on HTTP |

These are operational endpoints rather than MCP resources. Protect their
network reachability at the ingress or reverse-proxy layer.
