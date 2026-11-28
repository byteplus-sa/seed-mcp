"""``ark_list_models`` tool: discover configured models, their limits, and enabled services."""

from __future__ import annotations

from typing import Literal

from fastmcp import Context
from pydantic import BaseModel, Field

from ark_mcp.config.env import Settings, get_settings, settings_scope
from ark_mcp.config.model_capabilities import (
    ImageCapabilities,
    VideoCapabilities,
    get_capability_registry,
)
from ark_mcp.domain.tts import TTS_MAX_AUDIO_BYTES, TTS_MAX_CHARACTERS, TTS_MODEL
from ark_mcp.security.credentials import (
    endpoint_default,
    has_client_secret,
    has_provider_credential,
)

ModelKind = Literal["video", "image", "audio"]
EndpointTool = Literal["seedance_create_task", "seedream_generate_image"]
ConnectionIssueCode = Literal["missing_modelark_key", "missing_client_secret"]

VIDEO_TOOL = "seedance_create_task"
IMAGE_TOOL = "seedream_generate_image"


class ArkListModelsInput(BaseModel):
    """Input model for ``ark_list_models``."""

    kind: ModelKind | None = Field(
        None,
        description="Filter to video, image, or audio (Seed TTS). Omit to list all available kinds.",
    )
    check_connection: bool = Field(
        False,
        description=(
            "HTTP-only configuration check: ModelArk key/client-secret presence and exact "
            "endpoint bindings; no provider calls or authentication proof. Image/video kind "
            "checks that route; omitted kind checks both. Audio checks are not supported."
        ),
    )


class VideoModelLimits(BaseModel):
    """Per-model limits for a Seedance video model."""

    resolutions: list[str] = Field(..., description="Accepted resolution values.")
    duration_seconds: tuple[int, int] = Field(
        ...,
        description="Inclusive duration range in seconds; -1 (auto) is always accepted as well.",
    )
    ratios: list[str] = Field(..., description="Accepted ratio values.")
    max_reference_images: int = Field(..., description="Maximum reference images per request.")
    max_reference_videos: int = Field(..., description="Maximum reference videos per request.")
    max_reference_audios: int = Field(..., description="Maximum reference audio clips per request.")
    supports_draft: bool = Field(
        ..., description="Whether draft=true and draft_task_id are accepted."
    )
    draft_final_resolution: str | None = Field(
        None,
        description="Resolution a Draft task renders to when finalized; null without Draft support.",
    )
    supports_audio_only_input: bool = Field(
        ..., description="Whether audio may be the only media input."
    )
    task_types: list[str] = Field(
        ...,
        description="Accepted omni_reference_task_type values; empty when the field is unsupported.",
    )
    output_formats: list[str] = Field(
        ..., description="Accepted output_format values; empty when the field is unsupported."
    )


class ImageModelLimits(BaseModel):
    """Per-model limits for a Seedream image model."""

    max_reference_images: int = Field(..., description="Maximum reference images.")
    output_formats: list[str] = Field(..., description="Accepted output formats.")
    supports_batch: bool = Field(..., description="Accepts max_images > 1.")
    supported_sizes: list[str] | None = Field(
        None, description="Named size tiers (5.5 default: 2K); null for provider validation."
    )
    custom_size_pixels_range: tuple[int, int] | None = Field(
        None, description="Inclusive custom WIDTHxHEIGHT pixel-count bounds; null if unspecified."
    )
    custom_size_aspect_ratio_range: tuple[float, float] | None = Field(
        None, description="Inclusive custom width/height ratio bounds; null if unspecified."
    )
    background_modes: list[str] = Field(
        ..., description="Accepted backgrounds; 5.5 defaults to auto, older models to opaque."
    )
    prompt_optimization_modes: list[str] = Field(
        ..., description="Accepted explicit prompt_optimization modes."
    )
    supports_safety_identifier: bool = Field(
        ..., description="Accepts a hashed end-user safety_identifier."
    )
    supports_transparent_background: bool = Field(
        ..., description="Accepts background='transparent'."
    )
    supports_transparent_generation: bool = Field(
        ...,
        description="Transparent PNGs from text-only prompts or references without alpha (5.5).",
    )
    supports_prompt_optimization: bool = Field(
        ..., description="Accepts explicit prompt_optimization."
    )


class TtsModelLimits(BaseModel):
    """Seed TTS limits; the synthesis tool validates format combinations."""

    max_text_characters: int = Field(description="Maximum text characters per request.")
    max_ssml_characters: int = Field(description="Local safety limit for SSML characters.")
    max_audio_bytes: int = Field(
        TTS_MAX_AUDIO_BYTES, description="Maximum collected decoded TTS audio bytes: 30 MiB."
    )
    output_formats: list[str] = Field(description="Available audio encodings.")
    requires_voice_id: bool = Field(
        True, description="An authorized, compatible voice ID is required."
    )


class ModelInfo(BaseModel):
    """One configured model binding."""

    model_id: str = Field(
        ..., description="Configured model ID; pass as `model` when the tool supports selection."
    )
    family: str = Field(..., description="Logical model family.")
    kind: ModelKind = Field(..., description="Model kind.")
    is_default: bool = Field(
        ...,
        description=("Server default, independent of HTTP endpoint-header overrides."),
    )
    tool: str = Field(..., description="Tool serving this configured model.")
    video: VideoModelLimits | None = Field(None, description="Limits for video models.")
    image: ImageModelLimits | None = Field(None, description="Limits for image models.")
    tts: TtsModelLimits | None = Field(None, description="Limits for speech synthesis.")


class ServiceStatus(BaseModel):
    """Whether one optional service is available."""

    service: str = Field(..., description="Service name.")
    enabled: bool = Field(..., description="Whether the service's tools or models are available.")
    reason: str | None = Field(
        None,
        description="Why the service is disabled, naming the env var or flag to set; never a secret value.",
    )


class EndpointSelectionCheck(BaseModel):
    """An exact configured image/video route, never an inference about an unknown endpoint."""

    tool: EndpointTool = Field(description="Image or video create tool checked.")
    source: Literal["request_header", "server_default"] = Field(
        description="Whether the default selection came from its endpoint header or server settings."
    )
    configured: bool = Field(description="Whether this exact ID is bound to the selected product.")
    model_id: str | None = Field(
        None,
        description="Configured model/endpoint ID; null for unknown selections, which are not echoed.",
    )
    family: str | None = Field(
        None, description="Operator-configured model family; null for unknown selections."
    )
    issue: Literal["endpoint_not_configured"] | None = Field(
        None, description="endpoint_not_configured when operator verification/binding is needed."
    )


class HttpConnectionCheck(BaseModel):
    """Local HTTP configuration diagnostics, not provider authentication or live lineage."""

    configuration_valid: bool = Field(
        description="True only when both required headers are present and all checked routes are configured."
    )
    modelark_key_present: bool = Field(
        description="Whether the live request includes a ModelArk key header."
    )
    client_secret_present: bool = Field(
        description="Whether the live request includes the independent client secret."
    )
    authentication_verified: Literal[False] = Field(
        False,
        description="Always false: provider authentication, entitlement and balance are not tested.",
    )
    provider_calls_made: Literal[False] = Field(
        False,
        description="Always false: this check performs no provider or endpoint metadata requests.",
    )
    issues: list[ConnectionIssueCode] = Field(
        description="Missing required headers: missing_modelark_key and/or missing_client_secret."
    )
    routes: list[EndpointSelectionCheck] = Field(
        description="Endpoint header or server-default checks for the requested image/video kinds."
    )


class ArkListModelsOutput(BaseModel):
    """Output model for ``ark_list_models``."""

    models: list[ModelInfo] = Field(..., description="Configured models matching the filter.")
    services: list[ServiceStatus] = Field(..., description="Enablement of each optional service.")
    connection: HttpConnectionCheck | None = Field(
        None,
        description=(
            "Opt-in HTTP configuration-only preflight. Null unless check_connection=true; "
            "never verifies upstream credentials, live endpoint lineage or permission."
        ),
    )


TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


async def ark_list_models(input: ArkListModelsInput, ctx: Context) -> ArkListModelsOutput:
    """List configured models, limits and service enablement without provider calls.

    Use exact model_id values for generation. HTTP check_connection=true checks header
    presence and configured image/video endpoint defaults, not upstream authorization or
    live lineage. Unknown endpoints need verified operator bindings. Explicit create-tool
    model arguments override endpoint headers. Default discovery is static and anonymous.
    Seed TTS is listed on HTTP when output storage is enabled, or on stdio with a speech key.
    """
    settings = get_settings()
    return ArkListModelsOutput(
        models=[model for model in describe_models(settings) if input.kind in (None, model.kind)],
        services=describe_services(settings),
        connection=_connection_check(input, settings) if input.check_connection else None,
    )


def _connection_check(input: ArkListModelsInput, settings: Settings) -> HttpConnectionCheck:
    if settings.mcp_transport != "http":
        raise ValueError(
            "check_connection requires live HTTP requests; it is not available on stdio."
        )
    if input.kind == "audio":
        raise ValueError("check_connection supports image/video only; Seed Speech is not checked.")
    key_present = has_provider_credential("modelark")
    secret_present = has_client_secret()
    issues: list[ConnectionIssueCode] = []
    if not key_present:
        issues.append("missing_modelark_key")
    if not secret_present:
        issues.append("missing_client_secret")
    with settings_scope(settings):
        routes = [
            _endpoint_selection(kind) for kind in ("video", "image") if input.kind in (None, kind)
        ]
    return HttpConnectionCheck(
        configuration_valid=not issues and all(route.configured for route in routes),
        modelark_key_present=key_present,
        client_secret_present=secret_present,
        issues=issues,
        routes=routes,
    )


def _endpoint_selection(kind: str) -> EndpointSelectionCheck:
    tool: EndpointTool = "seedance_create_task" if kind == "video" else "seedream_generate_image"
    selected = endpoint_default(tool)
    source: Literal["request_header", "server_default"] = (
        "request_header" if selected is not None else "server_default"
    )
    registry = get_capability_registry()
    try:
        caps = (
            registry.resolve_video_model(selected)
            if kind == "video"
            else registry.resolve_image_model(selected)
        )
    except ValueError:
        return EndpointSelectionCheck(
            tool=tool, source=source, configured=False, issue="endpoint_not_configured"
        )
    return EndpointSelectionCheck(
        tool=tool, source=source, configured=True, model_id=caps.model_id, family=caps.family.value
    )


def describe_models(settings: Settings) -> list[ModelInfo]:
    """Describe every configured binding whose service is enabled."""
    models = []
    if settings.mcp_transport == "http" or settings.has_seed_audio:
        models.append(
            ModelInfo(
                model_id=TTS_MODEL,
                family="seed_tts_3",
                kind="audio",
                is_default=True,
                tool="seed_tts_generate",
                tts=TtsModelLimits(
                    max_text_characters=TTS_MAX_CHARACTERS,
                    max_ssml_characters=TTS_MAX_CHARACTERS,
                    output_formats=["mp3", "pcm", "ogg_opus"],
                ),
            )
        )
    if settings.mcp_transport != "http" and not settings.has_modelark:
        return models
    with settings_scope(settings):
        image_caps, video_caps = get_capability_registry().configured_models()
    models += [_video_info(caps, settings) for caps in video_caps.values()]
    models += [_image_info(caps, settings) for caps in image_caps.values()]
    return models


def _video_info(caps: VideoCapabilities, settings: Settings) -> ModelInfo:
    return ModelInfo(
        model_id=caps.model_id,
        family=caps.family.value,
        kind="video",
        is_default=caps.model_id == settings.seedance_default_model,
        tool=VIDEO_TOOL,
        video=VideoModelLimits(
            resolutions=list(caps.supported_resolutions),
            duration_seconds=caps.duration_range,
            ratios=list(caps.supported_ratios),
            max_reference_images=caps.max_reference_images,
            max_reference_videos=caps.max_reference_videos,
            max_reference_audios=caps.max_reference_audios,
            supports_draft=caps.supports_draft,
            draft_final_resolution=caps.draft_final_resolution,
            supports_audio_only_input=caps.supports_audio_only_input,
            task_types=list(caps.supported_task_types),
            output_formats=list(caps.supported_output_formats),
        ),
    )


def _image_info(caps: ImageCapabilities, settings: Settings) -> ModelInfo:
    return ModelInfo(
        model_id=caps.model_id,
        family=caps.family.value,
        kind="image",
        is_default=caps.model_id == settings.seedream_default_model,
        tool=IMAGE_TOOL,
        image=ImageModelLimits(
            max_reference_images=caps.max_references,
            output_formats=list(caps.supported_output_formats),
            supports_batch=caps.supports_batch,
            supported_sizes=list(caps.supported_sizes) if caps.supported_sizes else None,
            custom_size_pixels_range=caps.custom_size_pixels_range,
            custom_size_aspect_ratio_range=caps.custom_size_aspect_ratio_range,
            background_modes=list(caps.background_modes),
            prompt_optimization_modes=(
                list(caps.prompt_optimization_modes) if caps.supports_prompt_optimization else []
            ),
            supports_safety_identifier=caps.supports_safety_identifier,
            supports_transparent_background=caps.supports_transparent_background,
            supports_transparent_generation=caps.supports_transparent_generation,
            supports_prompt_optimization=caps.supports_prompt_optimization,
        ),
    )


def describe_services(settings: Settings) -> list[ServiceStatus]:
    """Report each optional service and the setting that enables it."""
    if settings.mcp_transport == "http":
        return [
            ServiceStatus(service="modelark", enabled=True),
            ServiceStatus(service="seed_audio", enabled=True),
            ServiceStatus(service="seed_tts", enabled=True),
            ServiceStatus(
                service="object_storage",
                enabled=settings.temporary_upload_enabled,
                reason=None
                if settings.temporary_upload_enabled
                else (
                    "Local storage/artifacts are stdio only. For HTTP preparation, configure "
                    "MCP_TEMPORARY_UPLOAD_ENABLED=true, TOS and operator client enrollment."
                ),
            ),
        ]
    storage_vars = (
        "S3_ACCESS_KEY, S3_SECRET_KEY and S3_BUCKET"
        if settings.object_storage_backend == "s3"
        else "TOS_ACCESS_KEY, TOS_SECRET_KEY and TOS_BUCKET"
    )
    services = (
        ("modelark", settings.has_modelark, "Set BYTEPLUS_MODELARK_API_KEY."),
        ("seed_audio", settings.has_seed_audio, "Set BYTEPLUS_SEED_SPEECH_API_KEY."),
        ("seed_tts", settings.has_seed_audio, "Set BYTEPLUS_SEED_SPEECH_API_KEY."),
        ("object_storage", settings.has_object_storage, f"Set {storage_vars}."),
    )
    return [
        ServiceStatus(service=name, enabled=enabled, reason=None if enabled else reason)
        for name, enabled, reason in services
    ]
