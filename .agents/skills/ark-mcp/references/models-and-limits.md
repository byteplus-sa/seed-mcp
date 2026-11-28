# Models and limits

Model discovery with `ark_list_models`, how the server binds model IDs to families, and the per-family limits for Seedance and Seedream. **This file is the one place per-family numbers live.** For the configured server, **`ark_list_models` is authoritative**: bindings are operator-configured, so a deployment can list fewer, more, or differently named models than the tables below. Tool parameters are in the tool schemas (see [API reference](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/api-reference.md)).

## Discovery with `ark_list_models`

- **No pricing discovery:** estimates use built-in budgeting heuristics, not
  account-specific provider prices. Discovery returns models, services and
  `connection` (null by default).

**Call it before any generation tool.** It is read-only and idempotent, needs no auth scope, and **makes no provider calls**; it reads the server's own configuration.

- **`kind`** (`video`, `image`, `audio`) filters the list; omit it for all available kinds. Audio lists configured Seed TTS on either transport.
- **`models[]`** lists configured image/video bindings on HTTP even without provider credentials. Local stdio also lists Seed TTS with a Seed Speech key, independently of ModelArk. Each entry carries `model_id`, `family`, `kind`, `is_default`, `tool`, and a limits object (`video`, `image`, or `tts`).
- **`model_id` is the exact value the `model` argument accepts.** `is_default`
  marks the server default; on HTTP an endpoint header can override it when
  create-tool `model` is omitted.
- HTTP endpoint defaults `X-ModelArk-Seedance-Endpoint` and
  `X-ModelArk-Seedream-Endpoint` must be exact registry bindings. Explicit tool
  `model` wins; no arbitrary opaque endpoint lineage is inferred.
- **`tool`** names the image/video generation tool that serves the model.
- **`services[]`** reports `modelark`, `seed_audio`, configured `seed_tts`, and
  `object_storage`, with `enabled` and a safe disabled `reason` naming required
  settings. Use it to check the running server; documentation alone does not
  prove a capability is available. On HTTP, `enabled` means registered, not
  customer entitlement, provider-key validity or model activation.

HTTP request-scoped settings and capability lookup keep this server's bindings
and defaults isolated from other server instances in the process.

### Optional HTTP preflight

Default `check_connection=false` is static/anonymous with `connection=null`,
without inspecting credentials in discovery. A live HTTP call with
`{"input":{"check_connection":true}}` checks header presence and exact
image/video defaults only. Omit `kind` for both routes; `"image"` or `"video"`
checks one. Other kinds, stdio and missing live HTTP context are rejected.

`connection` reports `modelark_key_present`, `client_secret_present`,
`configuration_valid`, `issues` and `routes`. Missing headers yield
`missing_modelark_key` / `missing_client_secret`. Route fields are `tool`,
`source` (`request_header` or `server_default`), `configured`, `model_id`,
`family`, and `issue`. Unknown/wrong-product selections yield
`endpoint_not_configured` with null ID/family; unknown IDs are not echoed.
Malformed headers can fail HTTP validation before diagnostics.

`configuration_valid=true` requires both headers and every checked binding.
`authentication_verified` and `provider_calls_made` are always false. This
does not prove key validity, endpoint existence/current lineage, activation,
permissions, balance or reachability. Explicit create-tool `model` still wins.
See `specs/SPEC_HOSTED_BYOK.md#http-configuration-preflight` in the selected checkout.

| `kind` | `tool` | Notes on `is_default` |
|---|---|---|
| `video` | `seedance_create_task` | One default (`SEEDANCE_DEFAULT_MODEL`) |
| `image` | `seedream_generate_image` | One default (`SEEDREAM_DEFAULT_MODEL`) |
| `audio` | `seed_tts_generate` | Configured stdio or HTTP; fixed `dola-seed-tts-3.0`, family `seed_tts_3` |

### Exact IDs and typos

`seedance_create_task` and `seedream_generate_image` accept
**configured IDs only**. Unknown IDs fail before provider dispatch.
Unknown image/video `ep-*` selections get safe `ENDPOINT_NOT_CONFIGURED`
guidance without echoing the ID: ask the operator to verify and bind it.
Other unknown model IDs list configured IDs and can receive a did-you-mean
hint (case-insensitive with `.` treated as `-`; no hint when nothing is close):

```text
Model '<id>' is not configured. Did you mean '<closest-id>'? Configured video models: [...]. Call ark_list_models(kind='video') for details.
```

### Request validation against limits

Create tools check the request against the resolved model's limits before spending quota, and **report every violation in one error** ending with `Call ark_list_models(kind='<kind>') for per-model limits.` With `dry_run: true` the same check runs without billing, so use it to test a request against a model before committing.

## Capability registry and bindings

The server maps each configured model ID to a **family**; the family decides the limits. The family is chosen by the operator, not inferred from the ID string (apart from the built-in IDs below).
For custom endpoints the operator must verify model/version outside this
server. Official GetEndpoint body and OpenAPI require Access Key V4 (AK/SK),
not ModelArk Bearer auth. No AK/SK custody, live lineage verification or arbitrary
BYOE self-service is implemented. Authority and source:
`specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority` in the selected checkout.

| Setting | Effect |
|---|---|
| `SEEDREAM_MODEL_BINDINGS`, `SEEDANCE_MODEL_BINDINGS` | JSON list of `{"model_id": "...", "family": "..."}` for explicit model or endpoint bindings |
| `SEEDREAM_MODEL_FAMILY`, `SEEDANCE_MODEL_FAMILY` | Family for a single custom default model when no bindings are set |
| `SEEDREAM_DEFAULT_MODEL`, `SEEDANCE_DEFAULT_MODEL` | Model used when `model` is omitted |

Family values: Seedream `seedream_5_5` only; Seedance `standard` (2.0) / `fast` / `mini` / `seedance_2_5` / `seedance_2_5_flash`.

### Built-in model IDs (no binding needed)

| Product | Default model ID | Family |
|---|---|---|
| Seedream 5.5 (default) | `dola-seedream-5-5-261028` | `seedream_5_5` |
| Seedance | `dreamina-seedance-2-5-260628` | 2.5 |
| Seedance Flash | `dreamina-seedance-2-5-flash-261115` | 2.5 Flash |
| Seedance 2.0 (opt-in) | `dreamina-seedance-2-0-260128` | Standard |

Seedance 2.0 Fast and Seedance 2.0 Mini have no built-in ID; bind the account's authorized ID to the family.

When Seedance bindings are empty, Flash is added alongside the selected default,
unless it is already the default. Regular 2.5 remains the default when omitted.
Explicit non-empty binding lists are never augmented. Listing Flash is not a
provider activation or account-entitlement check.

### Rules that fail startup

- **The default model must be one of the bound IDs, and bound IDs must be unique.** Startup fails with `... default model '<id>' is missing from its bindings. Set the default model env var to one of the bound IDs: [...]`.
- **Only Seedream 5.5 is supported and requires account authorization.** Older family settings and bindings fail startup. Replace them with verified 5.5 bindings; never relabel an older endpoint as 5.5. The obsolete `SEEDREAM_PROMPT_OPTIMIZATION_MODE` setting has no effect. Discovery does not prove provider access.
- **`SEEDANCE_DEFAULT_MODEL` defaults to Seedance 2.5.** A `SEEDANCE_MODEL_BINDINGS` that lists only a 2.0 model therefore fails startup unless `SEEDANCE_DEFAULT_MODEL` is set to that 2.0 ID (to keep 2.0 as the default) or a 2.5 binding is added.
- A custom default model ID with no family, no bindings, and no built-in match also fails startup (set the matching `*_MODEL_FAMILY` or bindings).

### Seedance 2.5 4K

4K is selected through `resolution="4k"` on `dreamina-seedance-2-5-260628`
or an endpoint bound to `seedance_2_5`. No separate model, binding, or feature
flag is needed. Old separate-model configuration must be removed explicitly;
the server provides no compatibility aliases.
This is retained server acceptance, not proof of provider support. Current
model-specific API docs list regular 2.5 only through 1080p; confirm acceptance
before paid 4K use. See the [contract caveat](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/models.md#video-capabilities-videocapabilities).

## Seedance (`kind: video`)

| Family | Resolutions | Duration | Max images / videos / audios | Draft (final res.) | Audio-only input | `omni_reference_task_type` | `output_format` |
|---|---|---|---|---|---|---|---|
| 2.0 | 480p, 720p, 1080p, 4k | 4-15 s | 9 / 3 / 3 | No | No | none | none |
| 2.0 Fast | 480p, 720p | 4-15 s | 9 / 3 / 3 | No | No | none | none |
| 2.0 Mini | 480p, 720p | 4-15 s | 9 / 3 / 3 | No | No | none | none |
| 2.5 (default) | 480p, 720p, 1080p, 4k | 4-30 s | 30 / 10 / 10 | Yes (1080p) | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |
| 2.5 Flash | 480p, 720p | 4-30 s | 10 / 5 / 5 | No | Yes | `auto`, `reference`, `edit`, `extend` | `mp4`, `mov` |

- **Ratios** for every family: `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, `adaptive`.
- **Duration `-1` (auto)** is accepted by every family in addition to the range.
- **`priority` 0-9 and `execution_expires_after` 3600-259200 seconds** apply to every family.
- **An empty `task_types` or `output_formats` list means the field is unsupported** on that model; setting it is rejected.
- **Audio-only input** means audio references may be the only media input; on 2.0 families an audio reference needs an image or video alongside it.

**Choosing a model.** Use regular 2.5 for 4K or Draft mode. Flash shares the 2.5 reference/edit/extend features up to 30 s at 480p/720p but rejects Draft requests. Use 2.0 when its legacy behavior is needed, or Fast/Mini for speed and lower cost. Static video estimates do not account for resolution or duration; Flash reuses the static 2.5 per-task fallback, not its token-based provider price.

**Draft mode (regular 2.5 only; not Flash).** Step 1: `draft: true` renders a cheap 480p preview (resolution omitted or `480p`). Step 2, once the Draft task has succeeded (within 14 days of creation, or 7 if created before 2026-10-28 10:00 UTC+8; owned by the caller): `draft_task_id` renders the final video at **1080p**, not 4K. The provider reuses the Draft's model, prompt, media, duration, ratio, seed, `generate_audio`, and `omni_reference_task_type`, so omit them (they are rejected even when they match); leave `variations` at 1. `return_last_frame`, `watermark`, `execution_expires_after`, `priority`, `safety_identifier`, and `output_format` may be set again. Each step is billed separately. Polling and the `draft` flag in results: [polling-and-artifacts.md](polling-and-artifacts.md).

## Seedream (`kind: image`)

| Family | Max references | `max_images` batch | `output_format` | Prompt optimization | Transparent background |
|---|---|---|---|---|---|
| 5.5 (default) | 10 | No | `png` (default), `jpeg` | `standard` only (provider default) | Text-only or references without alpha |

- **5.5 sizes:** `1K`, `1.5K`, `2K` (default), or positive `WIDTHxHEIGHT` with inclusive pixel count 921600-8294400 and width/height ratio 1/16-16. 4K UHD uses `3840x2160` on the same model or custom 5.5 endpoint; portrait `2160x3840` and square `2880x2880` also fit. `4096x2160` is too large. `auto`, `3K`, and the undocumented `4K` shorthand remain rejected.
- **5.5 estimates:** output pixel tiers are $0.020 through 2.61M, $0.035 above 2.61M through 4.63M, and $0.079 above 4.63M through the 8294400-pixel limit; add $0.008 per input image per variation. These static estimates follow the supplied 261028 high-resolution table, not account pricing or live 4K validation.
- **`max_images` vs `variations`.** `max_images` accepts only 1 or omission. `variations` (1-10) runs separate calls in parallel.
- **`background="transparent"`** requires `output_format` omitted or `png`. 5.5 supports text-only and reference-based generation without existing alpha.
- **5.5 background:** `auto` (default), `opaque`, `transparent`; JPEG in auto mode is always opaque.
- **Safety IDs:** optional `safety_identifier`, 1-64 non-space printable ASCII characters; use a stable hash, not personal data.
- **5.5 `seed`:** retained as an explicit compatibility field but absent from the current provider parameter docs and OpenAPI schema; omit unless provider acceptance is verified.
- Discovery reports transparency, named/custom size limits, `background_modes`, `prompt_optimization_modes`, and `supports_safety_identifier`. Source and remaining live-alpha validation: [model capabilities](https://github.com/byteplus-sa/seed-mcp/blob/main/docs/models.md#image-capabilities-imagecapabilities). Layer-decomposition/OCR inputs are rejected.

## Seed TTS (`kind: audio`)

`dola-seed-tts-3.0` requires an authorized compatible voice and exactly one of
text/SSML, up to 10,000 characters. Encodings are MP3, PCM and Ogg Opus.
Opus requires 48000 Hz; MP3/PCM default to 24000 Hz. Compressed audio defaults
to 64000 bits/s; omit bitrate for PCM. The create tool validates combinations.
Voice compatibility is not proven by discovery; there is no ModelArk binding.
See [TTS controls](tool-reference.md#seed-tts-3).
HTTP registration needs no TOS or operator provider key; stdio
requires a local Seed Speech key. Both use bounded 30 MiB stream collection.

## Health

**`seed-health://status`** is an MCP resource that needs no authentication and
exposes no credentials or output-root paths. It prints the build stamp, configured
products, storage backends, transport, effective Seedream default model/family
and local-export configuration. These are configuration-only
diagnostics, not provider authorization or filesystem readiness. A configured
absolute `OUTPUT_ROOTS` entry still needs request preflight; direct calls can
use live client roots. This resource is stdio-only. Backend `/health` and `/ready`
return minimal process/state status without provider checks; VKE Caddy exposes
only `/mcp` and `/health`. Public `/metrics` is unavailable; an optional
HTTP-runtime listener is loopback-only and off by default.
HTTP discovery is anonymous/static, with 12 tools, including the four managed Files operations.
Generation registration remains
independent of operator provider keys. For per-service
enablement prefer `ark_list_models.services`. Settings: [environment.md](environment.md).
