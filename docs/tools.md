# Tools Reference

The local stdio server exposes a conditional set of 13 typed tools. `ark_list_models`, `seed_media_get_artifact`,
`seed_media_export_artifact`, and `seed_media_persist_url` are always
available, provider tools are registered only when their credentials
are configured, and `media_upload` and `media_presign` are registered when
object storage credentials (TOS or S3) are present. Each
tool accepts a Pydantic input model and returns a Pydantic output model as
structured content. All tools accept a `ctx: Context` parameter for progress
reporting and logging.

HTTP exposes 7 discovery/provider tools, without
operator provider keys. Discovery is anonymous/static. Provider calls use the
selected BYOK header plus `X-MCP-Client-Secret` and run directly in the foreground.
HTTP has no jobs/native tasks/local storage/artifact tools/resources. No OAuth,
signup, server-issued key or environment-key fallback exists.
See [HTTP setup](setup/shared-server.md) and [Security](security.md).

Optional HTTP-only `media_prepare_upload` adds one tool (8 total).
Operator enrollment authorizes preparation without a generation-provider key;
the client uploads directly to TOS. See [temporary uploads](temporary-uploads.md).

Startup-key/artifact guidance below is **stdio-only**. Catalog
scope labels are metadata, not customer-selected roles. Seed Audio/Seedream
`persist` default to false globally.
HTTP rejects true, local paths and stored artifact references. Local true is
explicit; HTTP clients retrieve expiring URLs themselves.
`seed_tts_generate` always persists its streamed bytes on stdio and has no
`persist` switch. Configured HTTP hosts return private temporary TOS downloads.

## Tool Contract for MCP Clients

Every tool is self-describing through its JSON schema — MCP clients do not
need external documentation to understand inputs and outputs. The following
contract is enforced for all tools:

- **Tool descriptions.** Each tool's `description` comes from the handler
  function's docstring. It explains what the tool does, what it accepts, and
  what it returns.
- **Field descriptions on every input and output field.** Every Pydantic
  `Field` includes a `description` that explains the field's meaning, units,
  valid values, and constraints. This includes nested and shared domain models
  (`ArtifactRef`, `VariationSummary`, `SeedanceTaskSettings`, etc.).
- **Tool annotations.** Each tool declares MCP hints (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`) so clients can reason
  about side effects before calling.
- **Output schemas.** Each tool registers a `output_schema` (via
  `model_json_schema()`) so clients get typed structured content, not just
  text.
- **Error handling.** Provider errors are returned as `ToolResult` with
  `is_error=True` and a human-readable text summary. The declared output
  schema always represents the success shape; error results carry no
  `structured_content` to avoid schema-validation conflicts under strict MCP
  clients.

### Long-running tool execution

Both transports use ordinary direct calls, with no MCP jobs, native tasks,
snapshots or worker execution claims. Explicit task opt-in is rejected.
The direct result is the original tool's `ToolResult`: check `is_error`
before reading `structured_content`.

Use a 660-second client timeout with the default 600-second cooperative tool
deadline. Admission waits up to 2 seconds for owner then provider slots;
budget reservation follows admission. Settings and ranges are in
[Direct Execution](../specs/SPEC_DIRECT_EXECUTION.md).
SDK/SQLite cleanup may exceed the deadline. `ADMISSION_TIMEOUT` means this
attempt did not dispatch, not the entire batch. `TOOL_DEADLINE_EXCEEDED`
retains mutation uncertainty and known safe IDs. Never blindly resubmit.

Seedance returns provider task IDs from create. Poll with
`gen_task_get`, never create again to poll.
Provider queues remain asynchronous. Poll with `persist_output=false`, then
call directly with `persist_output=true` on stdio to store successful outputs.
HTTP clients download their temporary URLs.

### Writing outputs to local paths

On stdio transport, generation and retrieval tools can write their output
straight to a local file, so a client does not need a separate
`seed_media_export_artifact` call:

| Tool | Field | Notes |
|---|---|---|
| `seedream_generate_image` | `output_path` | Must be a directory (ending with `/`) when `variations > 1` or `max_images > 1`; extra images written to a file path get `-2`, `-3` suffixes |
| `seed_audio_generate` | `output_path` | Must be a directory (ending with `/`) when `variations > 1` |
| `seed_tts_generate` | `output_path` | One synthesized clip; always persists; stdio only |
| `gen_task_get` | `output_dir` | One file per artifact: every output of each succeeded task |

`output_path` names a file, or a directory when it ends with `/`; files written
into a directory are named `<artifact_id>.<ext>`. Every tool that has one of
these fields also has `overwrite` (default `false`). The rules are the same
everywhere:

- **stdio only.** The fields are rejected on HTTP transport.
- **Absolute paths inside an allowed output root.** The roots are the client's
  MCP roots (`roots/list`) when the client provides them, otherwise
  `OUTPUT_ROOTS` (comma-separated absolute directories). With neither, path
  writing is disabled and the field is rejected.
  `persist_output=true` itself works without output roots.
- **Validated before the provider call**, so a bad path never produces paid
  output that cannot be written.
- **Needs a persisted artifact.** `output_path`/`output_dir` require
  `persist=true` (Seed Audio/Seedream) or `persist_output=true` (retrieval tools).
  Seed TTS always persists and needs no switch.
- **Exclusive, symlink-safe writes.** An existing file is replaced only with
  `overwrite=true`; a file that already holds identical bytes counts as
  success, so repeated polls stay idempotent.
- **A failed local write never fails the call.** The durable artifact is kept
  and the reference reports `local_path` (on success) or `export_error`.

See [Security](security.md#local-output-paths) for the full output-root
policy.

## ark_list_models

**Call this first.** Lists the models this server is configured to call, with
the limits the server validates before submitting, and reports which optional
services are enabled. Read-only, no provider calls, always registered, and
needs no scope.

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | `"video"` \| `"image"` \| `"audio"` | No | Filter to one kind; audio lists configured TTS on either transport; omit for all available kinds |
| `check_connection` | boolean | No | Default `false`. Opt-in live HTTP header-presence and exact image/video binding check; omitted `kind` checks both |

### Output

- **`models`**: one entry per configured binding with `model_id` (the exact
  value to pass as `model`), `family`, `kind`, `is_default`, `tool`, and a
  kind-specific limits object:
  - `video`: resolutions, `duration_seconds` (inclusive; `-1` auto is always
    accepted), ratios, reference-count maxima, Draft support and final
    resolution, audio-only input, `task_types`, `output_formats`.
  - `image`: reference maximum, output formats, batch support, sizes,
    transparent-background support.
- **`services`**: `modelark`, `seed_audio`, `object_storage`,
  each with `enabled` and, when disabled,
  a `reason` naming the setting to change (never a secret value).
- **`connection`**: null by default. With `check_connection=true`, reports
  `configuration_valid`, `modelark_key_present`, `client_secret_present`,
  `issues` and checked `routes`. `authentication_verified` and
  `provider_calls_made` are always false. Full
  [connection and route fields](api-reference.md#http-connection-fields).
- Discovery returns no account pricing. Cost previews use built-in estimates,
  not account-specific quotes.

Models are listed only when their service is enabled. Regular Seedance 2.5
and Flash share the ModelArk service; discovery does not verify account entitlement.

Default discovery stays anonymous/static and does not inspect credentials.
For an optional HTTP configuration check, use this MCP arguments object:

```json
{"input": {"check_connection": true}}
```

Missing headers are reported as `missing_modelark_key` / `missing_client_secret`.
Unbound defaults have `routes[].issue="endpoint_not_configured"` and null
ID/family; unknown IDs are not echoed. Ask the operator to verify and bind them.
Preflight does not authenticate, check live lineage, entitlement, balance or
reachability, and is rejected on stdio or without live HTTP context. An explicit
create-tool `model` wins over endpoint headers; `models[].is_default` describes
only the server default. See the [setup workflow](setup/shared-server.md#verify).

## seed_media_get_artifact

Retrieve persisted media inline by artifact ID.

**Annotations:** `readOnlyHint=True`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact_id` | string | Yes | Artifact ID returned by a previous generation call |

### Output

Returns `SeedMediaGetArtifactOutput` with `artifact_id`, `media_type`,
`mime_type`, `sha256`, `bytes`, and Base64 `data`.

## seed_media_export_artifact

Locate or copy a persisted artifact on the local filesystem. Returns the
absolute on-disk path instead of streaming Base64 through the MCP context.
Stdio transport only — the client and server must share a filesystem.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact_id` | string | Yes | Artifact ID returned by a previous generation call |
| `destination_path` | string | No | Absolute file path inside an allowed output root where the server writes an atomic copy; omit to return the canonical store path |
| `overwrite` | boolean | No | Replace an existing destination file with different content (default: false) |

`destination_path` follows the [local output path](#writing-outputs-to-local-paths)
rules: it must be absolute and inside an allowed output root (client MCP roots,
or `OUTPUT_ROOTS`), and an existing file with different content is replaced
only when `overwrite=true`. An existing file with identical content is always
accepted. With the object-storage artifact backend, `destination_path` is
required because the store keeps no local file.

### Output

Returns `SeedMediaExportArtifactOutput` with `artifact_id`, `path`,
`media_type`, `mime_type`, `bytes`, `sha256`, and `copied`. `copied` is `false`
when `path` is the canonical store location (filesystem backend) and `true`
when the artifact was copied to `destination_path` (or an identical copy was
already there).

## seed_media_persist_url

Persist a temporary provider output URL as a durable artifact. Use it when a
generation or retrieval result returned an artifact with `id="provider-url"`
and a `persistence_error`: the output was generated and billed, but could not
be stored at the time. Call it before the provider URL expires (2 hours for
Seed Audio, 24 hours for ModelArk images/video).
Always registered; uses the
`media:upload` scope (catalog capability label).

Only trusted BytePlus provider hosts are accepted. The URL goes through the
same SSRF-resistant downloader, host allowlist, redirect re-validation, and
size limits as generation-time persistence; any other URL is rejected.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=False`, `openWorldHint=True`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | Yes | Temporary HTTPS provider URL, typically the `uri` of an `ArtifactRef` whose `id` is `provider-url` |
| `media_type` | "image" \| "audio" \| "video" | Yes | Logical media type of the output |
| `mime_type` | string | Yes | Expected MIME type (e.g. `video/mp4`); a specific provider `Content-Type` takes precedence |
| `source_expires_at` | string | No | ISO-8601 expiry of the provider URL, copied from the original `ArtifactRef.source_expires_at` |

### Output

Returns `SeedMediaPersistUrlOutput` with `artifact`, the new durable
`ArtifactRef`. A persistence failure is a tool error that names the failure
code and whether it is retryable.

## seed_tts_generate

Enabled by `BYTEPLUS_SEED_SPEECH_API_KEY` on stdio, or by operator-configured
TOS output storage and live Seed Speech/client-secret headers on HTTP.
Catalog scope: `seed:tts:generate`. Speaks supplied text or SSML using Seed TTS 3.0 and a
compatible, authorized `voice_id`. Call directly; no jobs, polling or retries.
The JSONL provider stream becomes one durable audio artifact, not live MCP audio.

Supports MP3, PCM and Ogg Opus, delivery controls, pronunciation rules and optional
word alignment in seconds. Stdio persists, with bounded fallback on storage
failure; HTTP returns an expiring download without inline fallback. There is
no `persist` option or provider URL. Optional `output_path`
uses normal stdio output roots.

See [Seed TTS 3.0](seed-tts.md) for complete controls, voice selection,
examples, streaming limits and uncertainty-aware recovery.

## seed_audio_generate

Generate full-scene audio through Seed Speech: one clip, or up to 5
independent variations in parallel.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=False`, `openWorldHint=True`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `text_prompt` | string | No* | Text describing the audio (1-3000 chars) |
| `audio_references` | list[AudioReference] | No | Up to 3 audio references (speaker/url/base64). Base64 WAV preflight-checked against 30s limit. Mutually exclusive with `image_reference` |
| `image_reference` | ReferenceImageInput | No | Image reference (mutually exclusive with audio) |
| `output` | AudioOutputOptions | No | Format, sample rate, speech rate, pitch |
| `watermark` | AudioWatermarkOptions | No | AIGC watermark controls |
| `variations` | integer | No | Independent generations to run in parallel (1-5, default 1). Seed Audio has no seed, so variations differ by the model's sampling |
| `variation_prompts` | list[string] | No | One prompt per variation (each 1-3000 chars), overriding `text_prompt`; must have exactly `variations` entries |
| `persist` | boolean | No | Persist output locally (default: false; HTTP rejects true) |
| `output_path` | string | No | Local file, or directory ending with `/` (**required when `variations > 1`**); stdio only, requires `persist=true`. See [local output paths](#writing-outputs-to-local-paths) |
| `overwrite` | boolean | No | Allow `output_path` to replace an existing file (default: false) |

\* Either `text_prompt` or `variation_prompts` must be provided.

### Output

Returns a `SeedAudioGenerateOutput`. For a single clip it carries
`duration_seconds`, `billing_duration_seconds`, `artifact`, optional
`subtitle`, `request_id`, `provider_log_id`, and optional `source_url`.

Audio artifact MIME follows `output.format`: WAV is `audio/wav` (default),
MP3 is `audio/mpeg`, OGG is `audio/ogg`, and raw PCM is `audio/pcm`. This applies
to URL references, persisted audio, variations and persistence fallbacks.
It is declared format metadata, not independent byte inspection. Raw PCM is
not a WAV container; its encoding, channels and actual rate need verification.

`output.sample_rate`, `output.subtitle` and `output.subtitle_type` are forwarded
in `audio_config`; they are requests, not delivery guarantees. Live checks
observed missing word/utterance subtitles (`subtitle=null`) and an OGG file at
48,000 Hz for a 24,000 Hz request. Their provider-versus-adapter causes remain
unresolved. Check subtitles and decoded audio before acceptance; preserve the
billed output and request/log IDs instead of regenerating automatically.

**With `variations > 1`, `artifact`, `duration_seconds`, and
`billing_duration_seconds` are `null`** and `summary` (`VariationSummary`)
carries `total`, `succeeded`, `failed`, and per-variation results (artifact or
error).

If the billed audio cannot be stored, the call still succeeds: `artifact`
carries a `persistence_error` and is either the provider URL
(`id="provider-url"`) or, when the provider returned no URL, the inline bytes
in `fallback_data` (`id="inline-fallback"`, up to
`ARTIFACT_INLINE_FALLBACK_MAX_BYTES`). See
[Artifacts](artifacts.md#persistence-failures).

### Example

```json
{
  "text_prompt": "Hello, welcome to BytePlus."
}
```

Three takes written to a local directory:

```json
{
  "text_prompt": "A warm narrator says: welcome back to the show.",
  "variations": 3,
  "output_path": "/Users/me/Audio/takes/"
}
```

## seedream_generate_image

**The only Seedream tool**: text-to-image, image-to-image and reference
editing, point or box edits, transparent PNG generation (5.5), transparency-preserving
edits (5.0 Pro), provider batches
(`max_images`), and parallel variations. Registered when
`BYTEPLUS_MODELARK_API_KEY` is set and has catalog capability label `seedream:generate`.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=False`, `openWorldHint=True`

### Model selection and validation

- **`model` takes an exact configured ID** from `ark_list_models(kind='image')`;
  omit it to use `SEEDREAM_DEFAULT_MODEL`.
- **Model limits are checked at runtime.** Every violation (reference count,
  `output_format`, `size`, `max_images` without batch support,
  `prompt_optimization`, transparent background rules) is reported in one
  error that ends with `Call ark_list_models(kind='image') for per-model limits.`

Built-in family limits (`ark_list_models` is authoritative for your server):

| Family | Max reference images | `max_images` batch | `output_format` | `background="transparent"` |
|---|---|---|---|---|
| Seedream 5.5 (default) | 10 | No (use `variations`) | `png` (default), `jpeg` | Text-only or reference-based generation |
| Seedream 5.0 Pro | 10 | No (use `variations`) | `png`, `jpeg` | Existing transparent PNG only |
| Seedream Lite | 14 | Yes | `png`, `jpeg` | No |
| Seedream 4.x | 14 | Yes | `jpeg` | No |

5.5's model ID is `dola-seedream-5-5-261028`; account authorization is required.
Its `seed` compatibility field is not documented by the GA API; omit it unless
provider acceptance has been verified. See the [contract notes](models.md#image-capabilities-imagecapabilities).
Explicit existing defaults stay unchanged. See the
[upgrade note](configuration.md#seedream-default-model-upgrade-note).

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | No* | What to generate, or the edit instruction when `images` are given (1-4000 chars, including any point/bbox markup) |
| `images` | list[ReferenceImageInput] | No | Reference or source images; per-model maximum checked at runtime. Accepts URLs, Base64, and `asset://<asset_id>` |
| `point` | EditCoordinate | No | Edit mode: `{x, y}` in normalized `0..999` space on the **first** image. Requires `images` |
| `bbox` | EditBbox | No | Edit mode: `{x1, y1, x2, y2}` in normalized `0..999` space (`x1 <= x2`, `y1 <= y2`) on the **first** image. Requires `images` |
| `model` | string | No | Exact configured model ID; omit for the default |
| `size` | string | No | 5.5: `1K`, `1.5K`, `2K` (default), or positive `WIDTHxHEIGHT` with 921600-8294400 pixels and width/height ratio 1/16-16, inclusive. For 4K UHD use `3840x2160`, not `"4K"`. `auto` is not a generation size. Older families remain provider-validated |
| `seed` | integer | No | `-1` to `2147483647`. For a single call it is sent as is. **With `variations > 1` it is the base seed**: omitted lets the provider randomize each variation, `-1` picks a random seed per variation (recorded in `summary`), and `N` uses `N`, `N+1`, `N+2`, ... |
| `max_images` | integer | No | Images from one provider call (1-15), batch-capable models only. **Cannot be combined with `variations > 1`** |
| `output_format` | `"png"` \| `"jpeg"` | No | Defaults to `png` on 5.5 and for transparent output; otherwise provider default |
| `response_format` | `"url"` \| `"b64_json"` | No | Base64 requires `persist=true`; invalid combinations are rejected before submission, even for dry runs |
| `watermark` | boolean | No | AIGC watermark |
| `prompt_optimization` | `"standard"` \| `"fast"` | No | 5.5: `standard` only (provider default); `fast` rejected. 5.0 Pro defaults to `SEEDREAM_PROMPT_OPTIMIZATION_MODE` (`standard`) |
| `background` | `"auto"` \| `"opaque"` \| `"transparent"` | No | 5.5 defaults to `auto` (prompt decides; JPEG always opaque). `auto` is 5.5-only. `transparent` requires PNG output; 5.5 accepts text or references without alpha; Pro requires exactly one already-transparent PNG |
| `safety_identifier` | string | No | 5.5/Pro: stable hashed end-user ID, 1-64 non-space printable ASCII characters. Never send raw personal data; redacted from previews and logs |
| `variations` | integer | No | Independent generations to run in parallel (1-10, default 1); partial failures are reported per variation |
| `variation_prompts` | list[string] | No | One prompt per variation, overriding `prompt`; must have exactly `variations` entries |
| `persist` | boolean | No | Persist output locally (default: false; HTTP rejects true) |
| `dry_run` | boolean | No | Validate and return the provider request bodies and a cost estimate without calling the provider or billing (default: false) |
| `output_path` | string | No | Local file, or directory ending with `/` (**required when `variations > 1` or `max_images > 1`**); stdio only, requires `persist=true`. See [local output paths](#writing-outputs-to-local-paths) |
| `overwrite` | boolean | No | Allow `output_path` to replace an existing file (default: false) |

\* Either `prompt` or `variation_prompts` must be provided.

Unknown fields, including `layer_decomposition` and
`layer_decomposition_options`, are rejected before job submission.
Layer decomposition and rich-text OCR are not exposed.

With `point` or `bbox`, the tool prepends coordinate markup to every prompt
(`Image 1<bbox>x1 y1 x2 y2</bbox>` and/or `Image 1<point>x y</point>`), so
refer to the target as "Image 1" in the instruction.

### Output

Returns `SeedreamGenerateOutput`:

| Field | Description |
|---|---|
| `provider`, `model`, `created_at` | Provider (`byteplus-modelark`), model ID used, and ISO-8601 timestamp |
| `dry_run` | `true` when nothing was generated; see `preview` |
| `artifacts` | Images from a single call (`variations=1`); empty for variations and dry runs |
| `item_errors` | Single-call image errors: `NO_OUTPUT` for empty/missing output, `NO_DELIVERABLE_OUTPUT` for unexpected Base64-only output without persistence |
| `usage` | Single-call usage, including provider-reported `input_images`, `generated_images`, `output_tokens`, and legacy token fields; `null` for variations and dry runs |
| `summary` | `VariationSummary` when `variations > 1`: `total`, `succeeded`, `failed`, and per-variation `index`, `seed`, artifact or error |
| `generations` | Completed calls ordered by `variation_index`, with `request_id`, submitted `seed`, final `prompt_sha256` and allowlisted `request_options`; per-call provider usage/identifier echo and `images` with artifact mapping, provider reports and independent `inspection`. Absent provider values stay null; empty for dry runs |
| `preview` | Dry run only: redacted `requests`, `estimated_cost_usd` and `price_source="builtin"`. A budgeting estimate, not account billing or a provider quote |

Image inspection reports decoded dimensions, format and actual alpha separately
from provider claims: `verified`, `mismatch`, `invalid` or `unavailable`, or null
for URL-only delivery. It retains billed artifacts without rerolls; verified
bytes do not establish visual acceptance. A single-call seed of `-1` or null is
provider randomness, not a recovered actual seed. Full contracts:
[API reference](api-reference.md#3-seedream_generate_image),
[image inspection](artifacts.md#seedream-image-inspection) and
[bounded review/edit](integration-guide.md#seedream-review-and-edit).

A storage failure does not fail the call. Each image degrades on its own:
URL outputs come back as `id="provider-url"` references to the temporary
provider URL, and `b64_json` outputs as `id="inline-fallback"` references with
the bytes in `fallback_data`, both with `persistence_error` set. Items that were
already stored are unaffected.

### Examples

Text-to-image:

```json
{"prompt": "A lighthouse on a cliff at golden hour, watercolor", "size": "2048x2048"}
```

Box edit of the first image:

```json
{
  "prompt": "Replace the object in the box with a red bicycle",
  "images": [{"kind": "url", "url": "https://cdn.example.com/street.png"}],
  "bbox": {"x1": 120, "y1": 400, "x2": 560, "y2": 900}
}
```

Generate a transparent PNG from text with Seedream 5.5 (`arguments.input`):

```json
{
  "model": "dola-seedream-5-5-261028",
  "prompt": "Realistic embroidered heart and daisy stickers, cream stitched borders, transparent background",
  "size": "2K",
  "response_format": "url",
  "output_format": "png",
  "background": "transparent",
  "watermark": true
}
```

Edit an image with transparency on Seedream 5.0 Pro (bind/select Pro; the input PNG must
already have transparent pixels):

```json
{
  "prompt": "Turn the circle into a glossy ceramic button, keep the background transparent",
  "images": [{"kind": "url", "url": "https://cdn.example.com/circle-transparent.png"}],
  "background": "transparent",
  "output_format": "png"
}
```

Four variations with a deterministic base seed, previewed first:

```json
{
  "name": "seedream_generate_image",
  "arguments": {
    "input": {
      "prompt": "Minimal poster of a fox, flat colors",
      "variations": 4,
      "seed": 1000,
      "dry_run": true
    }
  }
}
```

Drop `dry_run` (and add `output_path` ending in `/` on stdio) to generate.

## seedance_create_task

**One tool for every Seedance model**: 2.0 (and its Fast and Mini variants),
2.5, and 2.5 Flash. Pick the model with `model`; set
`variations` to create several tasks in parallel; set `dry_run` to preview the
request and its cost without billing. Registered when
`BYTEPLUS_MODELARK_API_KEY` is set and has catalog capability label `seedance:create`.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=False`, `openWorldHint=True`

### Model selection and validation

- **`model` takes an exact configured ID** from `ark_list_models(kind='video')`,
  which also lists each model's limits. Omit it to use `SEEDANCE_DEFAULT_MODEL`
  (default `dreamina-seedance-2-5-260628`, Seedance 2.5).
- **4K is a resolution, not a separate model.** Set `resolution="4k"` on
  `dreamina-seedance-2-5-260628` or a configured 2.5 endpoint. This is retained
  server acceptance; current model-specific provider docs do not list regular
  2.5 4K. See the [contract caveat](models.md#video-capabilities-videocapabilities).
- **Flash** uses `dreamina-seedance-2-5-flash-261115` with family
  `seedance_2_5_flash`: 480p/720p and no Draft mode. It is added automatically
  when bindings are empty; explicit binding lists must include it themselves.
- **The input schema advertises the widest limits; the model's own limits are
  checked at runtime.** Every violation (resolution, ratio, duration, reference
  counts, priority and expiry ranges, Draft, audio-only input, task type,
  `output_format`) is reported in one error that ends with
  `Call ark_list_models(kind='video') for per-model limits.`

Built-in family limits (`ark_list_models` is authoritative for what your
server has configured):

| Family | Resolutions | Duration (s) | Max images / videos / audios | Draft (final resolution) | Audio-only input | `omni_reference_task_type` | `output_format` |
|---|---|---|---|---|---|---|---|
| Seedance 2.0 | 480p, 720p, 1080p, 4k | 4-15 | 9 / 3 / 3 | No | No | No | No |
| Seedance 2.0 Fast, 2.0 Mini | 480p, 720p | 4-15 | 9 / 3 / 3 | No | No | No | No |
| Seedance 2.5 | 480p, 720p, 1080p, 4k | 4-30 | 30 / 10 / 10 | Yes (1080p) | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |
| Seedance 2.5 Flash | 480p, 720p | 4-30 | 10 / 5 / 5 | No | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |

Static video cost estimates are not provider quotes and do not account for
resolution or duration, including 4K. Flash reuses the static 2.5 per-task
fallback; it is not a quote derived from the provider's token prices.

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | No | Text prompt (1-32,000 chars). Optional when media or `variation_prompts` are given |
| `images` | list[SeedanceImageInput] | No | Up to 30 (per-model maximum at runtime); roles `first_frame`, `last_frame`, `reference_image`. Each entry may be a plain URL string, `asset://<asset_id>`, or `{"url": ...}` (coerced to `role=reference_image`) |
| `videos` | list[SeedanceVideoInput] | No | Up to 10 reference videos (per-model maximum at runtime); URL string, `asset://<asset_id>`, or `{"url": ...}` |
| `audios` | list[SeedanceAudioInput] | No | Up to 10 reference audio clips (per-model maximum at runtime). Seedance 2.5 models accept audio as the only media input; 2.0 models need an image or video as well |
| `model` | string | No | Exact configured model ID from `ark_list_models(kind='video')`; omit for the default. With `draft_task_id`, omit it to reuse the Draft task's model |
| `resolution` | `"480p"` \| `"720p"` \| `"1080p"` \| `"4k"` | No | Output resolution; supported set checked per model. `draft=true` allows only `480p` (the default); `draft_task_id` allows only the model's Draft final resolution (the default) |
| `ratio` | `"16:9"` \| `"4:3"` \| `"1:1"` \| `"3:4"` \| `"9:16"` \| `"21:9"` \| `"adaptive"` | No | Aspect ratio; `adaptive` is the provider default. Edit, extend, first-frame, and first/last-frame requests on Seedance 2.5 require it omitted or `adaptive` |
| `duration` | integer | No | `-1` for auto, or 4 up to the model's maximum (15 for 2.0, 30 for 2.5). `edit` requires `-1` or omitted |
| `omni_reference_task_type` | `"auto"` \| `"reference"` \| `"edit"` \| `"extend"` | No | Seedance 2.5 models only. `edit`/`extend` need at least one reference video and `ratio` omitted or `adaptive`; `edit` also needs `duration` omitted or `-1` |
| `output_format` | `"mp4"` \| `"mov"` | No | Seedance 2.5 models only. `mov` uses H.264, YUV 4:4:4, and PCM audio for post-production; some players cannot play it |
| `generate_audio` | boolean | No | Generate an audio track |
| `watermark` | boolean | No | AIGC watermark (default: false) |
| `return_last_frame` | boolean | No | Return the last frame as a separate image output |
| `execution_expires_after` | integer | No | Seconds before an unfinished task expires (3600-259200) |
| `priority` | integer | No | Priority (0-9) |
| `safety_identifier` | string | No | Safety identifier (max 64 chars) |
| `draft` | boolean | No | Draft mode step 1 (regular Seedance 2.5 only, not Flash): a 480p preview. Mutually exclusive with `draft_task_id`. See [Draft mode](#draft-mode) |
| `draft_task_id` | string | No | Draft mode step 2: render a succeeded Draft task as the final video. Requires `variations=1` |
| `variations` | integer | No | Tasks to create in parallel (1-5, default 1). **Each variation is a separate billed task**; partial failures are reported per variation |
| `variation_prompts` | list[string] | No | One prompt per variation (each 1-32,000 chars), overriding `prompt`; must have exactly `variations` entries |
| `dry_run` | boolean | No | Validate and return the provider request bodies and a cost estimate without submitting or billing (default: false) |

At least one of `prompt`, `images`, `videos`, or `audios` is required (except
with `draft_task_id`), and `variations > 1` needs `prompt` or
`variation_prompts`. Text-only input is supported for text-to-video.

Private asset library references (`asset://<asset_id>`, see
[assets.md](assets.md)) are passed through natively. Refer to them in the
prompt by position ("Image 1", "Video 1"), never by ID. The server validates
syntax and request limits only, not asset status or authorization. There is
no asset lookup, preflight or resolution fallback.

#### Auto-locked parameters by task type

When the provider detects (or is hinted via `omni_reference_task_type`)
that the task is video editing, extension, or first/last-frame generation,
certain parameters are auto-derived from the input media:

| Task type | Aspect ratio | Duration |
|---|---|---|
| Video editing | Locked to input video | Locked to input video (±0.3s) |
| Video extension | Locked to input video | Set freely |
| First/last-frame | Locked to first image | Set freely |
| Text-to-video / reference | Set freely | Set freely (or `-1`) |

### Draft mode

Draft mode is a two-step flow for checking a video cheaply before paying for
the final render. Regular Seedance 2.5 supports it; Flash and Seedance 2.0 models
do not.

1. Call `seedance_create_task` with `draft: true` and the usual prompt and
   media. The tool sends `draft=true` at `480p`, the only Draft resolution. The
   Draft is billed as a normal 480p video, and `gen_task_get` reports
   `draft: true`. `variations` may be greater than 1 to compare several Drafts.
2. Once the Draft task has `succeeded`, call `seedance_create_task` again with
   `draft_task_id` set to its task ID (and `variations=1`). The provider reuses
   the Draft task's model, prompt, media, duration, ratio, seed,
   `generate_audio`, and `omni_reference_task_type`, so those fields (and
   `draft`, even `false`) must be omitted; the provider rejects them even when
   they match. `resolution` may only be omitted or the model's Draft final
   resolution, which is also the default: `1080p` on Seedance 2.5.
   Ordinary generation supports 4K, but Draft promotion remains 1080p.
   `return_last_frame`, `watermark`, `execution_expires_after`, `priority`,
   `safety_identifier`, and `output_format` can be set again; omitted values
   use the model defaults, not the Draft's values. The final video is billed
   separately at its resolution.

Hosted HTTP is database-free: provider-key task authorization, no durable replay or shared budget accounting. Omit legacy operation keys; never automatically resubmit uncertain creates. Local stdio persistence remains available.

### Output

Successful single calls, variation batches and dry runs return
`SeedanceCreateTaskOutput`. A single-call failure instead returns error
`ToolResult` text with any known accepted task/request IDs, not this structured
success shape.

| Field | Description |
|---|---|
| `model`, `family` | Resolved model ID and family |
| `dry_run` | `true` when nothing was submitted; see `preview` |
| `tasks` | One entry per requested variation, in order (empty for a dry run): `index`, `task_id`, `request_id`, and `error`. `task_id` and `error` can coexist after local ownership-record failure; a null ID means submission failed or acceptance is unknown |
| `submitted`, `failed` | Independent counts of known accepted IDs and entries with errors; accepted tasks with local ownership-record errors count in both. Local budget-finalization log events do not add failures |
| `recommended_poll_after_ms` | Suggested delay before the first `gen_task_get` poll; `null` for a dry run |
| `preview` | Dry run only: `requests` (provider request bodies, one per variation, with HTTPS media URLs reduced to scheme and host, inline Base64 reduced to its size, and `asset://` references kept) and `estimated_cost_usd` (a static estimate from the server's price table, not a provider quote) |

See the database-free HTTP contract above; local stdio persistence is unchanged.

### Examples

Single Seedance 2.5 task (default model):

```json
{
  "prompt": "A paper boat drifts down a rain-soaked street at dusk",
  "resolution": "1080p",
  "duration": 8
}
```

Flash multimodal reference generation (the `input` payload of a direct
`seedance_create_task` call):

```json
{
  "model": "dreamina-seedance-2-5-flash-261115",
  "prompt": "Use Video 1 POV and Audio 1 as music for a fruit tea promotional ad.",
  "images": [
    "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic1.jpg",
    "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic2.jpg"
  ],
  "videos": ["https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_video/r2v_tea_video1.mp4"],
  "audios": ["https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_audio/r2v_tea_audio1.mp3"],
  "resolution": "720p",
  "generate_audio": true,
  "ratio": "16:9",
  "duration": 11,
  "watermark": false,
  "dry_run": true
}
```

Plain image URLs use `reference_image`, so the explicit 16:9 ratio is valid.
Remove `dry_run` only when ready to submit a billed task. Discovery does not
verify account activation.

Three variations on an explicit model, as a direct MCP call:

```json
{
  "name": "seedance_create_task",
  "arguments": {
    "input": {
      "model": "dreamina-seedance-2-0-260128",
      "variations": 3,
      "variation_prompts": [
        "The cat walks forward slowly through the garden",
        "The cat looks around curiously",
        "The cat jumps onto a stone wall"
      ],
      "images": [
        "https://cdn.example.com/cat.png"
      ],
      "resolution": "720p",
      "duration": 5
    }
  }
}
```

Dry run (returns `preview`, bills nothing):

```json
{"prompt": "Slow dolly shot of a lighthouse at dawn", "duration": 20, "dry_run": true}
```

Draft step 2 (render the final video from a succeeded Draft):

```json
{"draft_task_id": "cgt-20261017-draft"}
```

## gen_task_get

Check the status and outputs of Seedance
video tasks (2.0, regular 2.5, and 2.5 Flash). Pass every task ID you
are waiting on in one call. Registered when `BYTEPLUS_MODELARK_API_KEY` is set
and has catalog capability label `gen:read`.

The server makes one provider list call per page of 20 task IDs (at most
three), filtered by the requested IDs, and re-fetches individually only the
tasks missing from the list or reported succeeded without their primary
video URL; a last-frame URL alone is not sufficient.
Persistence uses a per-task single-flight cache. Later polls fill missing or
failed outputs without downloading cached successful outputs again. MOV
outputs retain `video/quicktime` and `.mov` filenames on directory export.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `task_ids` | list[string] | Yes | 1-50 Seedance provider task IDs, not Ark job IDs; duplicates are ignored |
| `persist_output` | boolean | No | Copy each succeeded task's outputs into durable storage, once per task (default: **false**) |
| `output_dir` | string | No | Local directory for each succeeded task's files (`<artifact_id>.<ext>`); stdio only, requires `persist_output=true`. See [local output paths](#writing-outputs-to-local-paths) |
| `overwrite` | boolean | No | Allow `output_dir` writes to replace existing files (default: false) |

### Output

Returns `GenTaskGetOutput`:

| Field | Description |
|---|---|
| `tasks` | One `GenTask` per found task, in request order |
| `errors` | Task IDs that could not be checked, each with `task_id`, `code` (`NOT_OWNED`, `NOT_FOUND`, or a provider code), and `message` |
| `all_terminal` | `true` when every found task has finished, so polling can stop |
| `active_tasks` | Number of found tasks still queued or running |
| `recommended_poll_after_ms` | Suggested delay before the next poll (5000 while any task is active); `null` when `all_terminal` |

Each `GenTask` contains:

| Field | Description |
|---|---|
| `task_id`, `model` | Provider task ID and the model that ran it |
| `family` | Registry family of the model; `null` when the model is not configured on this server |
| `kind` | `video` or `unknown`, from the registry binding for `model` |
| `status` | `queued`, `running`, `succeeded`, `failed`, `cancelled`, or `expired` |
| `created_at`, `updated_at` | ISO-8601 creation and last status-change times |
| `outputs` | List of `TaskOutputFile` with roles `video` and `last_frame`. Empty until the task succeeds |
| `error` | Provider failure `code` and `message` when failed |
| `usage` | Token usage reported by the provider |
| `draft` | `true` for a Seedance Draft task (480p preview); pass `task_id` as `draft_task_id` within 14 days of creation (7 if created before 2026-10-28 10:00 UTC+8) |
| `settings` | Video generation settings echoed by the provider when available |
| `queue` | Server-derived queue timing for a queued or running video task (below); `null` once finished |

Each `TaskOutputFile` carries `role`, the expiring provider `source_url`
(about 24 hours, kept even when persistence is skipped or fails),
`source_expires_at`, `persistence` (`not_requested`, `persisted`, or
`failed`), a durable `artifact` when persisted (with `local_path` when also
exported), and a safe `persistence_issue` when the copy failed. Re-persist a
failed output with `seed_media_persist_url` before its source URL expires.

Task IDs not created by the caller are reported in `errors` instead of failing
the call. A failure of the provider list call itself fails the whole call.

`queue` (`SeedanceQueueInfo`) is set only while the task is `queued` or
`running` and is `null` once it finishes. It is derived by this server from the
task's own timestamps, because ModelArk publishes no queue position or ETA:

| Field | Description |
|---|---|
| `queued_seconds` | Seconds queued: now minus `created_at` while queued, or `updated_at` minus `created_at` once running (approximate) |
| `running_seconds` | Seconds since the last status update while running (approximate) |
| `service_tier` | `default` or `flex`; flex tasks usually queue longer |
| `expires_at` | ISO-8601 time after which the provider fails an unfinished task: `created_at + execution_expires_after` |
| `expires_at_estimated` | `true` when the provider did not report `execution_expires_after` and the 48-hour default was assumed |
| `hint` | Human-readable summary to relay to the user |

### Example

Foreground status poll of three tasks:

```json
{"task_ids": ["cgt-20261017-aaaa", "cgt-20261017-bbbb", "cgt-20261017-cccc"]}
```

Once `all_terminal` is `true`, keep the outputs durably (and optionally write
them locally) through a direct stdio call:

```json
{
  "name": "gen_task_get",
  "arguments": {
    "input": {
      "task_ids": [
        "cgt-20261017-aaaa",
        "cgt-20261017-bbbb"
      ],
      "persist_output": true,
      "output_dir": "/Users/me/Videos/seedance/"
    }
  }
}
```

### Polling workflow

1. Call `seedance_create_task` directly and read the provider `task_id`
   (or every variation's task ID) from the direct result.
2. Call `gen_task_get` in the foreground with all the task IDs and the default
   `persist_output=false`. `queued` or `running` is not a failure; wait
   `recommended_poll_after_ms` and poll again.
3. When `all_terminal` is `true`, call `gen_task_get` directly on stdio
   with `persist_output=true` before the ~24-hour source URLs
   expire.

**Never resubmit the create tool to poll**: that creates a second billed task.

## gen_task_list

List your ModelArk generation tasks (Seedance video), **newest first**,
from the last 7 days (the provider's list window). Registered when
`BYTEPLUS_MODELARK_API_KEY` is set and has catalog capability label `gen:read`. Use
`gen_task_get` for outputs.

**Annotations:** `readOnlyHint=True`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `page_size` | integer | No | Maximum tasks to return (1-100, default 20) |
| `cursor` | string | No | Opaque `next_cursor` from a previous call made with the same filters |
| `status` | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` \| `expired` | No | Only return tasks in this status |
| `model` | string | No | Only return tasks run by this exact model ID |
| `task_ids` | list[string] | No | Only return these task IDs (up to 100); IDs the caller does not own are skipped |

### Output

Returns `GenTaskPage` with `tasks` (newest first) and `next_cursor`. Each
summary has `task_id`, `model`, `kind` (`video` or `unknown`),
`status`, `created_at`, and `error` (when failed). Follow `next_cursor` until
it is `null`. **A page may hold fewer than `page_size` tasks while
`next_cursor` is non-null**, so keep paging.

**Cursors are bound to their filters.** Changing `status`, `model`,
`task_ids`, or `page_size` between pages rejects the cursor; repeat the
original filters or start again without a cursor.

**Ownership:** For the local stdio principal the tool lists the account's
tasks directly from the provider. For every other principal it pages the caller's owned task IDs from the ownership
store in slices of 100 and asks the provider only for those IDs, so the
provider request URL never overflows and other callers' tasks are never
listed.

## gen_task_cancel_or_delete

Cancel (queued) or delete (terminal) a Seedance task.
Registered when `BYTEPLUS_MODELARK_API_KEY` is set and
has catalog capability label `gen:delete`. A deleted task's outputs are no longer
retrievable through `gen_task_get`.

**Annotations:** `readOnlyHint=False`, `destructiveHint=True`,
`idempotentHint=False`, `openWorldHint=True`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | Yes | ModelArk generation task ID |
| `mode` | "cancel" \| "delete" | Yes | Operation mode |
| `expected_status` | "queued" \| "succeeded" \| "failed" \| "expired" | Yes | Expected current status |
| `confirm` | true | Yes | Explicit confirmation required |

The handler fetches the current task state and rejects the operation if the
actual status does not match `expected_status`. This prevents accidental
cancellation of a running task.

### DELETE Semantics

| Current Status | Cancel | Delete |
|---|---|---|
| `queued` | Yes → `cancelled` | No |
| `running` | No | No |
| `succeeded` | No | Yes |
| `failed` | No | Yes |
| `expired` | No | Yes |
| `cancelled` | No | No |


## Parallel Variations

`seedream_generate_image`, `seed_audio_generate`, and `seedance_create_task`
take a `variations` field that generates multiple variations in a single call.
Each variation runs independently — partial failures are captured per
variation.

Variations have no individual wall-clock timeout, and time spent waiting for a
concurrency slot never counts against a variation. One batch deadline bounds
the whole call (see [Multi-Generation](multi-generation.md#deadlines-and-failure-phases)).
A variation stopped by the deadline or by a storage failure reports
`error.phase`: `queued` (never started, code `QUEUE_TIMEOUT`, safe to retry),
`generating` (provider call in flight, may have completed), or `persisting`
(output generated, storing it failed). Ordinary provider errors leave `phase`
null. Outputs that could not be stored but have a provider URL or fit inline
are returned as successful variations with `persistence_error` set.

### Seedream and Seed Audio variations

Variations are part of the base tools: set `variations` (and optionally
`variation_prompts`) on [`seedream_generate_image`](#seedream_generate_image)
(1-10; `seed` is the base seed) or [`seed_audio_generate`](#seed_audio_generate)
(1-5). The output's `summary` (`VariationSummary`) holds `total`,
`succeeded`, `failed`, and per-variation results (artifact or error); write
every persisted variation locally with `output_path` set to a directory ending
in `/`.

### Seedance variations

Seedance variations are part of [`seedance_create_task`](#seedance_create_task):
set `variations` (1-5) and optionally `variation_prompts`. Each variation is a
separate billed provider task. The direct result lists every variation in
`tasks` (with `task_id` and/or `error`); retain all known IDs and poll them
in one `gen_task_get` call, subject to the ownership rules above.

## media_prepare_upload

HTTP-only, opt-in restricted TOS signing for one image, audio or video reference.
Input fields are `media_type`, exact allowlisted `mime_type`, and strict positive
`size_bytes` (10 MiB image/audio, 200 MiB video). No bytes/local path or extras.
An operator-enrolled live `X-MCP-Client-Secret` is required; no generation key.

Returns `upload_url`, `method="POST"`, `form_fields`, `file_field="file"`,
`upload_expires_at`, `reference_url`, `reference_expires_at`, `object_key`,
`size_bytes`, `object_expires_days=1` and instructions. Upload directly with all
fields unchanged and file LAST; wait for success before using the GET URL.
Nominal 15-minute POST / 24-hour GET / one-day scheduled object expiry.
Signing uses static AK/SK or explicit operator VKE IRSA. STS expiry can shorten
both permissions; the default one-hour IRSA session may leave an hour or less.
Refresh never renews issued URLs. IRSA exchange is lazy after enrollment/
admission; it adds no readiness probes, database or client-side credentials.
Signed permissions are sensitive; declared MIME is not byte inspection.
No upload receipt, DB, URL renewal or global quota. Full workflow and operator
prerequisites: [temporary uploads](temporary-uploads.md).

## media_upload

Upload 1-50 image, audio, or video files to object storage (TOS or S3) and
receive a presigned HTTPS URL for each. Registered with object storage and
has catalog capability label `media:upload`.

**Execution:** Direct call where registered. Explicit persistence is stdio-only; use a 660-second client timeout. Provider video generation is polled separately.

**Annotations:** `readOnlyHint=False`, `destructiveHint=False`,
`idempotentHint=False`, `openWorldHint=True`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `items` | list[MediaUploadItem] | Yes | 1-50 files to upload |
| `expires_in_seconds` | integer | No | Presigned URL validity (60–604800) applied to every item. Defaults to the configured TTL; allow enough time for asynchronous provider workers to fetch inputs |
| `max_concurrent` | integer | No | Uploads running at the same time (1-8, default 4) |

**MediaUploadItem:**

| Field | Type | Required | Description |
|---|---|---|---|
| `media_type` | "image" \| "audio" \| "video" | Yes | Media category for MIME and size validation |
| `mime_type` | string | No* | MIME type such as `video/mp4`; optional for `file_path` items (guessed from the file extension), required for `data` items |
| `data` | string | No** | Base64-encoded media bytes |
| `file_path` | string | No** | Absolute local path; stdio transport only |
| `key_prefix` | string | No | Optional object key prefix (default `references`; letters, digits, `-`, `_`, `/`) |

\* A `file_path` item whose MIME type cannot be guessed fails on its own and
asks for `mime_type`. \*\* Provide exactly one of `data` or `file_path` per
item.

Every item is validated, and the total decoded size is checked against
`MEDIA_UPLOAD_BATCH_MAX_BYTES` (default 500 MiB), before any upload starts.
**An oversized request fails as a whole**; split it into smaller calls.

### Output

Returns `MediaUploadOutput`:

| Field | Description |
|---|---|
| `items` | Per-item results in request order: `index`, `file_path` (as given), `url`, `object_key` (reusable with `media_presign`), `expires_at`, `mime_type`, `bytes`, and on failure `error` and `retryable` |
| `succeeded`, `failed` | Number of items uploaded and failed |
| `total_bytes` | Bytes uploaded across successful items |

**Items fail independently** (validation, missing file, or provider error)
without failing the call, so always check `failed` and `items[].error`.

### Example

```json
{
  "name": "media_upload",
  "arguments": {
    "input": {
      "items": [
        {
          "media_type": "video",
          "file_path": "/Users/me/clips/reference.mp4"
        },
        {
          "media_type": "image",
          "mime_type": "image/png",
          "data": "<base64>"
        }
      ],
      "expires_in_seconds": 3600
    }
  }
}
```

## media_presign

Generate fresh presigned HTTPS GET URLs for 1-100 existing objects without
re-uploading. Use it when a previously uploaded reference's URL has expired
or is about to expire. Registered with object storage and uses the
`media:presign` scope (catalog capability label).

**Annotations:** `readOnlyHint=True`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`

### Input

| Field | Type | Required | Description |
|---|---|---|---|
| `object_keys` | list[string] | Yes | Object keys returned by prior `media_upload` calls (1–100) |
| `expires_in_seconds` | integer | No | Presigned URL validity (60–604800) applied to every key. Defaults to the configured TTL; allow enough time for provider input retrieval |

### Output

Returns `MediaPresignOutput` with `items` in input order (each with
`object_key`, `url`, `expires_at`, and on failure `code`, `error`, and
`request_id`), plus `succeeded` and `failed`. **Failures are per key**:
`INVALID_KEY` (malformed key), `NOT_OWNED` (not uploaded by the caller),
`INTERNAL`, or a provider error code. Check `failed`.
