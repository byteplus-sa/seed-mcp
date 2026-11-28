# Model Capability Registry

The capability registry (`config/model_capabilities.py`) describes, per
configured model, what inputs the server will accept before it ever calls
the provider. It validates image sizes, output formats, video resolutions,
and durations against family-specific rules, so unsupported requests fail fast
with an actionable `ValueError`.

## Seed TTS Discovery

Local stdio `ark_list_models(kind="audio")` lists `dola-seed-tts-3.0`,
family `seed_tts_3`, served by `seed_tts_generate` when a Seed Speech key
is configured. Its `tts` limits report 10,000 text/SSML characters,
MP3/PCM/Ogg Opus output and required voice selection. This is a fixed speech
model, not a ModelArk endpoint binding. HTTP does not list TTS, and
`check_connection=true` still supports image/video only.
See [Seed TTS 3.0](seed-tts.md).

## Families

`ModelFamily` (`StrEnum`) includes:

| Member | Value |
|---|---|
| `SEEDREAM_5_5` | `seedream_5_5` |
| `SEEDREAM_PRO` | `seedream_pro` |
| `SEEDREAM_LITE` | `seedream_lite` |
| `SEEDREAM_4X` | `seedream_4x` |
| `SEEDANCE_2` | `seedance_2` |
| `SEEDANCE_2_FAST` | `seedance_2_fast` |
| `SEEDANCE_2_MINI` | `seedance_2_mini` |
| `SEEDANCE_2_5` | `seedance_2_5` |
| `SEEDANCE_2_5_FLASH` | `seedance_2_5_flash` |

The binding enums (`config/env.py`):

- `SeedreamFamily`: `SEEDREAM_5_5 = "seedream_5_5"`, `PRO = "pro"`, `LITE = "lite"`, `V4X = "4x"`.
- `SeedanceFamily`: `STANDARD = "standard"`, `FAST = "fast"`, `MINI = "mini"`,
  `SEEDANCE_2_5 = "seedance_2_5"`, `SEEDANCE_2_5_FLASH = "seedance_2_5_flash"`.

## Image capabilities (`ImageCapabilities`)

| Field | `SEEDREAM_5_5` | `PRO` | `LITE` | `4X` |
|---|---|---|---|---|
| `max_references` | 10 | 10 | 14 | 14 |
| `supports_batch` | `False` | `False` | `True` | `True` |
| `supports_streaming` | `False` | `False` | `True` | `True` |
| `supported_output_formats` | `("png", "jpeg")` | `("png", "jpeg")` | `("png", "jpeg")` | `("jpeg",)` |
| `default_output_format` | `"png"` | `None` | `None` | `None` |
| `supported_sizes` | `("1K", "1.5K", "2K")` | `None` | `None` | `None` |
| `custom_size_pixels_range` | `(921600, 8294400)` | `None` | `None` | `None` |
| `custom_size_aspect_ratio_range` | `(1/16, 16)` | `None` | `None` | `None` |
| `supports_watermark` | `True` | `True` | `True` | `True` |
| `supports_prompt_optimization` | `True` | `True` | `True` | `True` |
| `prompt_optimization_modes` | `("standard",)` | `("standard", "fast")` | `("standard", "fast")` | `("standard", "fast")` |
| `default_prompt_optimization_mode` | `None` | `SEEDREAM_PROMPT_OPTIMIZATION_MODE` (`"standard"`) | `None` | `None` |
| `supports_transparent_background` | `True` | `True` | `False` | `False` |
| `supports_transparent_generation` | `True` | `False` | `False` | `False` |
| `supports_auto_background` | `True` | `False` | `False` | `False` |
| `supports_safety_identifier` | `True` | `True` | `False` | `False` |

**Seedream 5.5 is the built-in image default.** Start with the
[Seedream tool reference](/seed-mcp/tool-reference/seedream-generate-image/#seedream-5-5)
for transparent images and request previews.
This integration covers generation and editing,
not layer decomposition or OCR; those input fields are rejected. `background="transparent"` supports a text-only
prompt or up to ten references without requiring existing alpha. 5.0 Pro retains
its requirement for exactly one already-transparent PNG. Transparent output
uses PNG when `output_format` is omitted; JPEG is rejected locally.

5.5 accepts named tiers `1K`, `1.5K`, `2K` (provider default), or positive
`WIDTHxHEIGHT` dimensions with inclusive pixel count 921,600-8,294,400 and
width/height ratio 1/16-16. **For 4K UHD use `size="3840x2160"`** (16:9)
on the same `dola-seedream-5-5-261028` model or an endpoint bound to
`seedream_5_5`. Portrait `2160x3840` and square `2880x2880` also fit the
maximum. `4096x2160` exceeds it. No extra model or high-resolution flag is needed.
`auto`, `3K`, and the undocumented `4K` shorthand remain rejected; use explicit
dimensions for high-resolution output. Older-family size validation is unchanged
and remains provider-side.

`background` defaults to `auto` on 5.5: the prompt determines transparency,
except JPEG is always opaque. Explicit `prompt_optimization="standard"` is
accepted; `fast` is rejected. Omitted optimization uses the provider's standard
default, not the Pro-only operator setting.

Discovery exposes named tiers, custom-size bounds, `background_modes`,
`prompt_optimization_modes`, and `supports_safety_identifier`, alongside the
transparency flags. Optional `safety_identifier` accepts 1-64 non-space printable
ASCII characters on 5.5 and Pro. Use a stable hashed user identifier, not raw
personal data. Dry-run previews and structured logs redact it; generation
metadata preserves the provider's echo.

The baseline generation controls and reference bounds follow the GA
[image API](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/image-generation-api)
(accessed 2026-11-16). The raised 8,294,400-pixel limit and static image price
tiers come from the operator-supplied **Dola-Seedream-5.5 / 261028
High-resolution output** table (received 2026-11-27). That table specifies
`widthxheight`, not a new named `4K` tier. This update has offline validation
and mocked provider coverage, not live 4K generation evidence.
See [cost estimation](runtime.md#cost-estimation-tools_costpy) for the tiered
estimates, including input-image charges.

Seedream 5.5 does not document `seed` in either the
parameter reference or the official OpenAPI schema. The MCP retains it as an
explicit compatibility field; omit it unless provider acceptance has been
verified. The schema also lags GA fields such as `background="auto"`, so schema
omissions alone are not proof of rejection. These contract checks do not
establish live editing quality, output alpha or account access. Use the opt-in
`scripts/smoke_seedream55.py` checks and review the results before release;
the script is offline by default.

Per-call provenance records the provider request ID, submitted seed, final-prompt
SHA-256 and allowlisted options. Advisory byte inspection measures format,
dimensions and actual alpha without replacing provider reports. It does not
prove prompt adherence or visual quality; see [artifacts](artifacts.md#seedream-image-inspection)
and the [review/edit workflow](integration-guide.md#seedream-review-and-edit).

> `default_prompt_optimization_mode` controls what 5.0 Pro sends as
> `optimize_prompt_options.mode` when a caller omits `prompt_optimization`. It
> is operator-configurable through `SEEDREAM_PROMPT_OPTIMIZATION_MODE` and
> defaults to `standard` for prompt-following quality; set `fast` to favor
> latency.
>
> **Both modes are accepted by the 5.0 Pro API** — verified against the live
> endpoint, where `fast` and `standard` each returned HTTP 200 with an image.
> An earlier field report that `fast` is rejected did not reproduce. The choice
> is a quality-versus-latency tradeoff, not a compatibility constraint.
>
> An explicit per-call `prompt_optimization` always wins over the configured
> default; families without a default send no mode and the provider applies its
> own.

> Images have no separate `ratio` tool input. 5.5 custom `WIDTHxHEIGHT`
> dimensions are checked against `custom_size_aspect_ratio_range` and
> `custom_size_pixels_range`; older families leave those bounds unspecified.

## Video capabilities (`VideoCapabilities`)

The three Seedance 2.0 families share: `max_reference_images=9`,
`max_reference_videos=3`, `max_reference_audios=3`, `supports_seed=False`,
`supports_camera_fixed=False`, `supports_frames=False`,
`supports_service_tier_flex=False`, `duration_range=(4, 15)`,
`priority_range=(0, 9)`, `execution_expires_after_range=(3600, 259200)`.

Only `supported_resolutions` differs:

| Family | `supported_resolutions` |
|---|---|
| `seedance_2_5` | `("480p", "720p", "1080p", "4k")` |
| `seedance_2_5_flash` | `("480p", "720p")` |
| `MINI` | `("480p", "720p")` |
| `FAST` | `("480p", "720p")` |
| `STANDARD` | `("480p", "720p", "1080p", "4k")` |

> Seedance 2.5 differs from the 2.0 families in duration
> (`duration_range=(4, 30)` versus `(4, 15)`; `-1` for auto is accepted
> separately) and reference counts (`max_reference_images=30`,
> `max_reference_videos=10`, `max_reference_audios=10`). All four resolutions,
> including `4k`, use the same regular 2.5 model. Flash shares the 2.5 duration
> range but has reference limits of 10 images, 5 videos and 5 audios (20 total),
> and supports only 480p/720p and no Draft mode.
> Both 2.5 families set `supports_audio_only_input=True`,
> `supported_task_types=("auto", "reference", "edit", "extend")`, and
> `supported_output_formats=("mp4", "mov")`.
>
> No additional model or feature flag is required for 4K. Custom endpoints
> bound to `seedance_2_5` share these same resolution limits.
>
> Draft mode is described by `supports_draft` and `draft_final_resolution`:
> Only regular 2.5 sets `supports_draft=True`; Flash sets it to `False` with
> `draft_final_resolution=None`. Drafts are always `480p`, and a final rendered
> from a Draft is `1080p`. 4K Draft promotion is not advertised or accepted.

The GA [create-task API](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/create-video-generation-task-api)
(accessed 2026-11-16) confirms Flash's 10/5/5 reference limits. Drafts created
at or after **2026-10-28 10:00 UTC+8** (02:00 UTC) are valid for **14 days**;
earlier Drafts retain **seven days**. The local check selects the window using
the provider's creation timestamp, not the current date. Missing or unparsable
timestamps leave the expiry decision to the provider.

**Regular 2.5 4K contract caveat:** the server retains its existing `4k`
resolution acceptance on the same model, but the current model-specific API
docs list regular 2.5 only through 1080p and assign 4K to 2.0. The generic
OpenAPI resolution enum includes `4k` without establishing support for a
specific model. A successful dry run proves local validation only, not
provider acceptance; confirm support before a paid regular 2.5 4K request.

**Every Seedance model is called through one tool, `seedance_create_task`.**
Its input schema advertises the widest limits; at runtime the tool checks the
request against the selected model's `VideoCapabilities` (including
`supported_ratios`) and reports every violation in one error that points to
`ark_list_models(kind='video')`, which exposes these limits to clients.

## Default model IDs

| Field | Env var | Default | Implied family |
|---|---|---|---|
| `seedream_default_model` | `SEEDREAM_DEFAULT_MODEL` | `dola-seedream-5-5-261028` | `SEEDREAM_5_5` |
| `seedance_default_model` | `SEEDANCE_DEFAULT_MODEL` | `dreamina-seedance-2-5-260628` | `SEEDANCE_2_5` |

The "implied family" defaults are hard-coded in `Settings.validate_model_bindings`
and apply only when the default model ID equals one of the recognized built-in
IDs. `dola-seedream-5-0-pro-260628` remains recognized as `PRO` when explicitly
configured. See the [default upgrade note](configuration.md#seedream-default-model-upgrade-note).
`ark_list_models` returns configured models, limits and service availability,
not account-specific pricing. Cost previews use built-in estimates for
budgeting; they are not provider quotes.

## Environment variables

| Env var | Format | Default |
|---|---|---|
| `SEEDREAM_MODEL_BINDINGS` | JSON array of `{"model_id": str, "family": "seedream_5_5"\|"pro"\|"lite"\|"4x"}` | `[]` |
| `SEEDANCE_MODEL_BINDINGS` | JSON array of `{"model_id": str, "family": "standard"\|"fast"\|"mini"\|"seedance_2_5"\|"seedance_2_5_flash"}` | `[]` |
| `SEEDREAM_MODEL_FAMILY` | single family string | `""` |
| `SEEDANCE_MODEL_FAMILY` | single family string | `""` |

Examples (from `.env.example`):

```
SEEDREAM_MODEL_BINDINGS=[{"model_id":"my-image-endpoint","family":"pro"}]
SEEDANCE_MODEL_BINDINGS=[{"model_id":"my-video-endpoint","family":"standard"}]
```

These entries illustrate syntax, not verified endpoint lineage. Explicit
binding lists must include the configured default or set the corresponding
`*_DEFAULT_MODEL` to one of their IDs.

## How a `model_id` resolves to a family

Resolution is **binding-table based, not string-pattern based** (no inference
from the model ID string):

1. If `SEEDREAM_MODEL_BINDINGS` (resp. `SEEDANCE_MODEL_BINDINGS`) is set, it
   is the source of truth — each binding explicitly pairs `model_id` ↔
   `family`.
2. If the bindings list is empty and `SEEDREAM_MODEL_FAMILY` (resp.
   `SEEDANCE_MODEL_FAMILY`) is non-empty, a single binding is synthesized
   from the default model ID + that family.
3. If both are empty and the default model ID equals a recognized built-in
   ID, its known family is used (Seedream `SEEDREAM_5_5` or legacy `PRO`,
   Seedance `STANDARD`, `SEEDANCE_2_5`, or `SEEDANCE_2_5_FLASH`).
4. Otherwise (custom default model, no family, no bindings) → startup fails
   with `ValueError`.

When synthesizing Seedance bindings from an empty list, the server also adds
`dreamina-seedance-2-5-flash-261115` as `seedance_2_5_flash`, unless it is already
the default. Explicit non-empty binding lists are never augmented. Regular
2.5 remains the default when `SEEDANCE_DEFAULT_MODEL` is omitted.

## Validation rules

`CapabilityRegistry` methods (`get_image_capabilities(model_id)`,
`get_video_capabilities(model_id)`, `list_image_models()`,
`list_video_models()`, plus `validate_image_size`,
`validate_output_format`, `validate_resolution`, `validate_duration`):

| Check | Rejected when |
|---|---|
| Unknown `model_id` | Not in the registry; unknown image/video `ep-*` values use safe `ENDPOINT_NOT_CONFIGURED` guidance without echoing the ID. Other unknown IDs can receive configured-ID suggestions |
| Image `output_format` | not in `supported_output_formats` (e.g. `png` on a `4X` model, which only supports `jpeg`) |
| Image `size` | Not a supported named tier or valid custom dimensions. 5.5 enforces pixel-count and aspect-ratio bounds; older families leave sizes to the provider |
| Video `resolution` | not in `supported_resolutions` (e.g. `1080p`/`4k` on `MINI`/`FAST`) |
| Video `duration` | outside `duration_range` unless `-1` (auto) |

Settings startup additionally rejects: duplicate model IDs within a
family's bindings, a default model ID missing from bindings, a custom
default model with no family/binding, unknown family strings, non-HTTPS
provider URLs, non-positive `ARTIFACT_TTL_SECONDS` /
`MCP_INLINE_MEDIA_MAX_BYTES` / timeouts, invalid allowed origins, HTTP without
`MCP_AUTH_MODE=byok` and a valid `MCP_IDENTITY_HMAC_KEY`, nonofficial HTTP provider
origins, and non-positive HTTP rate/body/in-flight/state limits.

HTTP `X-ModelArk-Seedance-Endpoint` and `X-ModelArk-Seedream-Endpoint`
defaults must exactly match registered product bindings. Explicit tool `model`
wins. The server never infers an arbitrary opaque `ep-*` endpoint's lineage.
Anonymous static discovery reports bindings, not customer entitlement.

## BYOE Configuration Checks

An operator must verify a customer endpoint's model/version outside this
server before binding its exact ID to a supported family. The official
[GetEndpoint authentication section](https://ai.byteplus.com/ark/region:ap-southeast-1/docs/get-endpoint-api#authentication)
and OpenAPI schema require Access Key V4 (AK/SK), not a ModelArk Bearer key.
No AK/SK custody, live metadata lookup or arbitrary-endpoint self-service
is implemented. See the [durable authority contract](../specs/SPEC_HOSTED_BYOK.md#byoe-endpoint-authority).
Configured endpoint IDs appear in anonymous discovery; do not use bindings
as private credential storage.

Default `ark_list_models` is static/anonymous and returns `connection=null`.
For live HTTP only, `{"input":{"check_connection":true}}` checks ModelArk key
and client-secret presence plus exact image/video defaults. Omit `kind` for
both routes or select `"image"` / `"video"`; other kinds
and stdio checks are rejected.

Unknown or wrong-product defaults yield `configured=false`,
`issue="endpoint_not_configured"` and null `model_id`/`family`, without echoing
the unknown ID. The operator must verify and bind it. A configured route
returns its ID and operator-selected family, not live provider lineage.
`configuration_valid=true` requires both headers and all checked bindings;
`authentication_verified` and `provider_calls_made` always remain false.
This does not prove activation, permissions, balance, existence or reachability.

The check describes header/server defaults, not an explicit create request.
Explicit create-tool `model` wins; `models[].is_default` continues to describe
the server default. For missing-header remediation and generator examples,
see [shared-server setup](setup/shared-server.md#optional-imagevideo-configuration-check).

## Module-level singleton

- `get_capability_registry()` — returns a process-cached `CapabilityRegistry`
  (lazily built).
- `refresh_capability_registry()` — force-rebuilds after config changes (call
  `refresh_settings()` first).

## What the registry does not do

- It is **not a cost table.** Cost estimation (see
  [runtime.md](runtime.md#cost-estimation-tools_costpy)) is per product and
  per variation; 5.5 images use pixel tiers and input-image counts. Video
  families select a static per-task fallback, not a
  resolution-, duration-, or token-based provider quote.
- It does **not** infer size or ratio limits for families without configured bounds.
- It does **not** call the provider — it is a local, pre-flight validation
  layer built entirely from configuration.

## Checking capability drift

The server validates requests against the static registry in
`config/model_capabilities.py`. `ark_list_models` reports those limits to
clients for image/video generation. To compare the registry with BytePlus's ArkModels catalog:

```bash
make audit-capabilities CATALOG=path/to/arkmodels.json
```

The dump may be an ArkModels list or `arkcli models get <id> --format json`
output. Each row reports `OK`, `DRIFT` or `UNKNOWN` for one parameter of one
configured binding; `--strict` exits non-zero on drift. **The report is
advisory.** The ArkModels catalog has known stale entries (for example,
Seedance 2.5 Draft mode marked unsupported, which the official tutorial shows
working), so review drift against the official docs before changing the
registry.
