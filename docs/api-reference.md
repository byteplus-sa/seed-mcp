# API Reference

Complete schemas, inputs, outputs, and examples for the conditional MCP tool
surface.

The static catalog has 12 local stdio tools, four always registered locally.
HTTP exposes tools 1-7 below, and the
13th definition `media_prepare_upload` when temporary uploads are enabled.
Generation-tool registration does not require operator generation keys; discovery
is anonymous/static. Temporary preparation requires operator TOS configuration
and client enrollment.
Provider calls run directly in the foreground with selected BYOK headers and
required client secret. No jobs/native tasks/local storage/artifact tools/resources
exist on HTTP. No OAuth, signup, server-issued key or provider-key fallback.
See [HTTP setup](setup/shared-server.md). Catalog scope strings below are
metadata, not customer-selected roles.
Explicit per-call `io.modelcontextprotocol/tasks` opt-in is rejected on both transports,
including discovery, before provider dispatch, snapshot capture/save or queue
creation. Omit task opt-in; ordinary jobs are not an HTTP fallback.

**Artifact and startup-key guidance below is stdio-only.**

## Temporary Upload Preparation

`media_prepare_upload` is HTTP-only and opt-in. It takes category, exact MIME
and byte count, returns restricted TOS POST fields and a GET reference URL,
and requires operator enrollment of the live client secret, not a generation
key. The client uploads directly before using the reference. See
[tool details](tools.md#media_prepare_upload) and
[operator/client workflow](temporary-uploads.md).
Seed Audio/Seedream `persist` default to
false globally. HTTP rejects true, local paths and stored artifact references;
local explicit true remains supported. HTTP clients download expiring URLs.
Generated per-tool pages show both transports and exact current schemas.

## Tool Inventory

| # | Tool | Product | Type | Auth |
|---|---|---|---|---|
| 1 | `ark_list_models` | Discovery | Read-only | No extra tool scope |
| 2 | `seed_audio_generate` | Seed Audio | Direct call | Seed Speech |
| 3 | `seedream_generate_image` | Seedream | Direct call | ModelArk |
| 4 | `seedance_create_task` | Seedance (every configured model; 2.5 supports 4K) | Direct provider submission | ModelArk |
| 5 | `gen_task_get` | Seedance tasks | Direct retrieval | ModelArk |
| 6 | `gen_task_list` | Seedance tasks | Read-only | ModelArk |
| 7 | `gen_task_cancel_or_delete` | Seedance tasks | Destructive | ModelArk |
| 8 | `seed_media_get_artifact` | Artifacts | Read-only | Local stdio only |
| 9 | `seed_media_export_artifact` | Artifacts | Locate (read-only) or copy (stdio only) | Local stdio |
| 10 | `seed_media_persist_url` | Artifacts | Direct call | Local stdio only |
| 11 | `media_upload` | Object storage (optional) | Direct call (1-50 files) | TOS / S3 |
| 12 | `media_presign` | Object storage (optional) | Read-only (1-100 keys) | TOS / S3 |

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
| `seed_media_get_artifact` | true | false | true | false |
| `seed_media_export_artifact` | false | false | true | false |
| `seed_media_persist_url` | false | false | false | true |

The task poller `gen_task_get` is not read-only because `output_dir` writes local files.

## Direct Execution

Call every retained tool directly with its original arguments and `input`
wrapper. The **direct result** is the tool's `ToolResult`; inspect `is_error`
before using `structured_content`. No MCP jobs, worker queue, native tasks,
snapshots or execution claims exist. Provider queues and ownership remain.

Use client timeout 660 seconds with `MCP_TOOL_TIMEOUT_SECONDS=600.0`
(finite positive, max 3600). The cooperative timer starts at wrapper entry,
before credentials and admission. SDK/local SQLite cleanup may exceed it.
`MCP_ADMISSION_TIMEOUT_SECONDS=2.0` (finite positive, max 30) bounds combined
owner-first/provider waiting, before local stdio budget reservation. `ADMISSION_TIMEOUT`
means this attempt did not dispatch, not the whole batch.
`TOOL_DEADLINE_EXCEEDED` is text-only and preserves uncertainty and safe
accepted IDs. Never blindly resubmit or assume timeout cancelled upstream work.
See [Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).

Poll provider task IDs with `gen_task_get`, default
`persist_output=false`. Local stdio can directly call with explicit true to
persist successful outputs. `seed_media_persist_url` always downloads and
stores; it has no status-only mode. HTTP remains URL-only.

## Local Output Paths

On stdio transport, these fields write output straight to a local file:
`output_path` on `seedream_generate_image` and `seed_audio_generate`; `output_dir` on `gen_task_get`; and `destination_path` on
`seed_media_export_artifact`. Each comes with an `overwrite` boolean (default
`false`).

| Rule | Behavior |
|---|---|
| Transport | stdio only; rejected on HTTP |
| Path form | Absolute. `output_path` names a file, or a directory when it ends with `/` (files named `<artifact_id>.<ext>`) |
| Allowed roots | Live client MCP roots (`roots/list`) first, otherwise `OUTPUT_ROOTS`; with neither, path writing is disabled |
| Timing | Validated before any provider call |
| Preconditions | Media-output paths require `persist=true` or `persist_output=true`; image/audio `output_path` must be a directory ending `/` for `variations > 1` or image `max_images > 1` |
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
authorized assets through without a lookup. Other products do not support native assets. See [assets.md](assets.md).

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
| `source_expires_at` | string | Provider URL expiry (2h audio, 24h ModelArk image/video) |
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
| `task_id` | string \| null | Provider task ID for Seedance polling, obtained from the enclosing direct result |
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
and report which optional services are enabled. Call it before generation:
the image/video `model` argument accepts only the exact
`model_id` values listed here. Always registered, needs no scope, and **makes
no provider calls**.

On HTTP, anonymous calls return the configured bindings even without an
environment provider key or client credentials. On stdio, `models` is empty
when ModelArk is not configured. `services[].enabled` reports server
registration, not customer entitlement, provider-key validity or activation.
Discovery uses this server's scoped settings and capability registry; another
server instance's defaults cannot replace its bindings.
Default `check_connection=false` returns `connection=null` without inspecting
credentials in discovery. Opt-in preflight below checks HTTP image/video
configuration only.

### Input

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | string | No | — | Filter to `video` or `image`. Omit to list both |
| `check_connection` | boolean | No | `false` | Live HTTP only: check ModelArk/client-secret header presence and exact image/video bindings without provider calls. Omit `kind` for both routes |

### Output

| Field | Type | Description |
|---|---|---|
| `models` | list[ModelInfo] | Configured models matching the filter |
| `services` | list[ServiceStatus] | Enablement of each optional service |
| `connection` | HttpConnectionCheck or null | Null unless `check_connection=true`; configuration diagnostics, never provider authentication, live lineage or entitlement proof |

**ModelInfo:** `model_id` (exact ID to pass as `model`), `family`, `kind`,
`is_default` (server default, not a request-header override), `tool` (the tool that accepts the
model), and one limits object matching the kind: `video` (resolutions,
`duration_seconds` range, ratios, reference counts, Draft support, task types,
output formats), `image` (reference count, output formats, batch support,
sizes, transparent background).

Discovery returns no prices. Cost estimates are built-in budgeting heuristics,
not account-specific rates. See [Runtime](runtime.md#cost-estimation-tools_costpy).

**ServiceStatus:** `service`, `enabled`, and `reason` (the env var or flag that
enables a disabled service; never a secret value). Services: `modelark`,
`seed_audio`, `object_storage`.

### HTTP Connection Fields

| Field | Type | Description |
| --- | --- | --- |
| `configuration_valid` | boolean | Both required headers present and all checked routes configured |
| `modelark_key_present` | boolean | Live `X-ModelArk-Api-Key` present |
| `client_secret_present` | boolean | Live independent `X-MCP-Client-Secret` present |
| `authentication_verified` | literal `false` | Authentication, entitlement and balance are not tested |
| `provider_calls_made` | literal `false` | No provider or endpoint-metadata requests |
| `issues` | list[string] | `missing_modelark_key` and/or `missing_client_secret`, otherwise empty |
| `routes` | list[EndpointSelectionCheck] | Requested route(s), video then image when both are checked |

**EndpointSelectionCheck:**

| Field | Type | Description |
| --- | --- | --- |
| `tool` | `seedance_create_task` or `seedream_generate_image` | Route checked |
| `source` | `request_header` or `server_default` | Endpoint header when present, otherwise operator default |
| `configured` | boolean | Exact ID bound to that product |
| `model_id` | string or null | Configured model/endpoint ID; unknown values are null and not echoed |
| `family` | string or null | Operator-configured family, not verified live lineage; null when unknown |
| `issue` | `endpoint_not_configured` or null | Operator verification/binding needed, otherwise null |

Missing headers produce diagnostics; malformed HTTP headers still fail the
transport boundary. Stdio or missing live HTTP context rejects opt-in checks.
`configuration_valid=true` does not establish endpoint existence, current
lineage, activation, permissions, balance or reachability. The check covers
defaults, not explicit create payloads: an explicit create-tool `model` wins.
See the [durable contract](../specs/SPEC_HOSTED_BYOK.md#http-configuration-preflight)
and [setup check table](setup/shared-server.md#optional-imagevideo-configuration-check).

### Examples

Default discovery, on either transport (MCP arguments object):

```json
{"input": {"kind": "video"}}
```

HTTP-only video route check, without generation:

```json
{"input": {"kind": "video", "check_connection": true}}
```

---

## 2. seed_audio_generate

Generate full-scene audio through Seed Speech: **one clip, or up to five
independent variations in parallel**. Catalog label: `seed:audio:generate`.
Call directly on either transport.

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
| `format` | `"wav"` \| `"mp3"` \| `"pcm"` \| `"ogg"` | provider WAV | Requested encoding; PCM has no WAV container |
| `sample_rate` | integer | provider setting | 8000, 16000, 24000, 32000, 44100 or 48000 Hz; actual rate may differ |
| `speech_rate` | integer | — | -50 to 100 |
| `loudness_rate` | integer | — | -50 to 100 |
| `pitch_rate` | integer | — | -12 to 12 |
| `subtitle` | boolean | — | Requests subtitles; provider may omit them |
| `subtitle_type` | `"utterance"` \| `"word"` | — | — |

Output controls are forwarded in `audio_config`. Missing subtitles and a
24,000 Hz OGG request delivered at 48,000 Hz were observed in live checks;
provider-versus-adapter causes remain unresolved. Verify downloaded media
and retain request/log IDs; do not regenerate automatically.

### Output

Returns `SeedAudioGenerateOutput` for both single calls and variations.

| Field | Type | Description |
|---|---|---|
| `provider` | `"byteplus-seed-speech"` | Fixed |
| `model` | `"seed-audio-1.0"` | Fixed |
| `duration_seconds` | float \| null | Output duration; `null` when `variations > 1` |
| `billing_duration_seconds` | float \| null | Billed duration; `null` when `variations > 1` |
| `artifact` | ArtifactRef \| null | Temporary URL or explicitly persisted stdio audio; `null` when `variations > 1` |
| `subtitle` | Subtitle \| null | Provider-supplied subtitles; null if omitted, even when requested, or for variations |
| `request_id` | string \| null | Request ID |
| `provider_log_id` | string \| null | X-Tt-Logid |
| `source_url` | string \| null | Provider URL (2-hour expiry) |
| `summary` | VariationSummary \| null | Per-variation artifacts and errors when `variations > 1`; `null` otherwise |

Artifact MIME follows the requested format, not independent byte inspection:
`audio/wav` (default), `audio/mpeg` for MP3, `audio/ogg`, or `audio/pcm`.
The same mapping applies to variations and persistence fallbacks.

### Examples

```json
// Single clip (arguments.input)
{
  "text_prompt": "Welcome to BytePlus.",
  "output": { "format": "wav", "sample_rate": 44100 }
}

// Direct result
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

// Direct result
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
and dry runs. Registered whenever `BYTEPLUS_MODELARK_API_KEY` is set on stdio;
catalog capability label `seedream:generate`. Call directly on either transport.

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
// Text-to-image, direct MCP call
{
  "name": "seedream_generate_image",
  "arguments": {
    "input": {
      "prompt": "A serene mountain landscape at sunset",
      "size": "2048x2048",
      "seed": 42,
      "output_format": "jpeg"
    }
  }
}

// Direct result
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

// Direct result
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

// Direct result
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

One create tool serves all configured Seedance models: single tasks, up to five
parallel variations, supported Draft workflows and dry runs. Poll returned IDs
with [`gen_task_get`](#5-gen_task_get). Hosted HTTP uses provider-key task
authorization without durable replay or shared budget accounting. Omit
`idempotency_key`; supplied legacy keys are rejected, including dry runs.
Never automatically resubmit uncertain creates. Local stdio persistence remains
available.

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
| `idempotency_key` | string \| null | No | `null` | Deprecated legacy input; non-null values are rejected on both transports before dispatch |
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
  in the direct result without submitting provider work.
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
local ownership-record failure instead returns an error `ToolResult` with text, not this
structured success shape. That text retains any known accepted task ID and
diagnostic request ID; preserve them even when `isError=true`.

| Field | Type | Description |
|---|---|---|
| `model` | string | Resolved model ID |
| `family` | string | Resolved model family (e.g. `seedance_2_5`) |
| `dry_run` | boolean | `true` when nothing was submitted; see `preview` |
| `tasks` | list[SeedanceTaskRef] | One entry per requested variation, in order; empty for a dry run |
| `submitted` | integer | Entries with known accepted task IDs, including local ownership-record errors |
| `failed` | integer | Entries with submission or local ownership-record errors; may overlap with `submitted`. Local budget-finalization log events do not add failures |
| `recommended_poll_after_ms` | integer \| null | Suggested delay before the first `gen_task_get` poll; `null` for a dry run |
| `preview` | SeedanceCreatePreview \| null | Set only for a dry run |

**SeedanceTaskRef:**

| Field | Type | Description |
|---|---|---|
| `index` | integer | 0-based variation index (`0` for a single request) |
| `task_id` | string \| null | Known accepted provider task ID, retained alongside local ownership-record errors; null when acceptance is unknown or submission failed. HTTP polling uses provider-key authorization. For `draft=true`, use as `draft_task_id` once succeeded |
| `request_id` | string \| null | Provider request ID, when returned |
| `error` | VariationError \| null | Submission or post-acceptance local ownership-record failure; can coexist with `task_id`. Local budget-finalization exceptions alone leave this null |

See the database-free HTTP contract above; local stdio persistence is unchanged.

Local stdio budget-finalization exceptions only log `ERROR` event `budget_finalization_failed`;
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

Read each `tasks[].task_id` from the direct result and pass **all of them
in one call** to [`gen_task_get`](#5-gen_task_get). **`queued` or `running` is
not a failure: poll with `gen_task_get`; never resubmit `seedance_create_task`
to poll**. Same-key HTTP receipt recovery does not refresh provider status;
a new create can bill again. Draft creation and promotion are distinct intended
operations with separate HTTP keys; a saved promotion receipt replays before
Draft lookup, subject to existing ownership.

### Examples

```json
// Single task (default model), direct MCP call
{
  "name": "seedance_create_task",
  "arguments": {
    "input": {
      "prompt": "A cat walking through a garden",
      "images": [
        "https://example.com/cat.png"
      ],
      "resolution": "1080p",
      "duration": 10
    }
  }
}

// Direct result
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

// Direct result (one variation failed)
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

// Direct result
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


<span id="7-gen_task_get"></span>

## 5. gen_task_get

**One poller for Seedance video tasks**
(`seedance_create_task`, every Seedance model). Registered whenever ModelArk is
configured on stdio; catalog capability label `gen:read`.
Direct on both transports; explicit persistence is stdio-only.

Fetches tasks with one provider list call per page of 20 task IDs (at most
three pages), filtered by task ID, and re-fetches individually only tasks
missing from the list or succeeded without an output URL. Task IDs the caller
did not create are reported in `errors` instead of failing the call.

### Polling Workflow

1. Call the create tool directly and read each provider `task_id`
   from the direct result.
2. Call `gen_task_get` in the foreground with **every** task ID you are waiting
   on (`persist_output=false`, the default).
3. While `all_terminal` is `false`, wait `recommended_poll_after_ms` (5000 ms
   while any task is active) and poll again. **`queued` or `running` is not a
   failure; never resubmit the create tool to retry polling**, because that
   creates a second billed task.
4. Once `all_terminal` is `true`, call `gen_task_get` directly on stdio
   with `persist_output=true` (optionally `output_dir`) to keep
   the outputs as durable artifacts before the provider URLs expire (about 24
   hours).

### Input

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `task_ids` | list[string] | Yes | — | 1-50 Seedance task IDs (not Ark job IDs); duplicates ignored |
| `persist_output` | boolean | No | **`false`** | Persist each succeeded task's outputs once per task in a direct stdio call; HTTP rejects true |
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

// Input (direct stdio persistence)
{ "task_ids": ["cgt-20260721134956-h5cz9"], "persist_output": true }
```

---

<span id="11-gen_task_list"></span>

<span id="8-gen_task_list"></span>

## 6. gen_task_list

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

<span id="9-gen_task_cancel_or_delete"></span>

## 7. gen_task_cancel_or_delete

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
build stamp, effective Seedream default model/family and local
export configuration. It exposes neither credentials nor output-root paths.
These diagnostics do not check provider authorization or filesystem readiness;
`configured; needs request preflight` is not proof a destination is writable.

---

<span id="22-seed_media_get_artifact"></span>

<span id="13-seed_media_get_artifact"></span>

## 8. seed_media_get_artifact

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

<span id="14-seed_media_export_artifact"></span>

## 9. seed_media_export_artifact

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

<span id="15-seed_media_persist_url"></span>

## 10. seed_media_persist_url

Persist a temporary provider output URL as a durable artifact. Use it to
recover an `ArtifactRef` with `id="provider-url"` and a `persistence_error`
before the provider URL expires. Always registered; catalog capability label `media:upload`. Direct call.

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

<span id="16-media_upload"></span>

## 11. media_upload

Upload **1-50 files** to object storage (TOS or S3) in one call and return a
presigned HTTPS GET URL per file. Registered when the selected object-storage
backend credentials are set (`TOS_*` with default `OBJECT_STORAGE_BACKEND=tos`,
or `S3_*` with `OBJECT_STORAGE_BACKEND=s3`); catalog capability label `media:upload`.
Call directly on stdio; the tool is unavailable on HTTP.

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
// Direct media_upload MCP call
{
  "name": "media_upload",
  "arguments": {
    "input": {
      "items": [
        {
          "media_type": "video",
          "file_path": "/Users/me/clips/ref.mp4"
        },
        {
          "media_type": "image",
          "mime_type": "image/png",
          "data": "iVBORw0KGgo..."
        }
      ],
      "expires_in_seconds": 3600
    }
  }
}

// Direct result
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

<span id="17-media_presign"></span>

## 12. media_presign

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
| `/ready` | HTTP lifespan readiness only; no storage or provider probes; blocked by VKE Caddy |
| `/metrics` | Absent from main app/public proxy; optional separate loopback listener |

These are operational endpoints rather than MCP resources. Protect their
network reachability at the ingress or reverse-proxy layer. VKE Caddy exposes
only `/mcp` and `/health`. `MCP_METRICS_PORT=0` disables private metrics;
nonzero 1024-65535 ports bind only 127.0.0.1 for the HTTP runtime. See
[private metrics access](observability.md#metrics-endpoint).
Hosted HTTP readiness checks lifespan availability without storage or provider probes.
Local stdio retains local persistence. See [runtime operations](runtime.md).
