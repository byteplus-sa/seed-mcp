"""Direct Seed TTS synthesis under specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastmcp import Context
from fastmcp.tools import ToolResult
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ark_mcp.artifacts.store import ArtifactPersistenceError, artifact_limit_bytes
from ark_mcp.domain.artifacts import ArtifactRef, MediaType
from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
from ark_mcp.domain.tts import (
    TTS_MAX_CHARACTERS,
    TtsAlignment,
    TtsOutputFormat,
    TtsPronunciationDictionary,
    TtsVoiceSettings,
)
from ark_mcp.observability.logger import warning as log_warning
from ark_mcp.providers.factory import seed_speech_gateway
from ark_mcp.providers.seed_speech.seed_tts import SeedTtsService
from ark_mcp.providers.tos.constants import TEMPORARY_REFERENCE_TTL_SECONDS
from ark_mcp.runtime import billed_provider_slot, get_principal, get_runtime
from ark_mcp.tools._cost import log_cost_estimate
from ark_mcp.tools._errors import provider_error_result
from ark_mcp.tools._local_export import local_export, output_path_field, overwrite_field
from ark_mcp.tools._persistence import persist_base64


class SeedTtsGenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description=(
            "Authorized cloned voice ID or Speaker ID from the BytePlus Seed TTS 3.0 Voice List: "
            "https://docs.byteplus.com/en/docs/byteplusvoice/voicelist-3-0. "
            "Example English preset: multi_female_skye_v3_uranus_bigtts."
        ),
    )
    text: str | None = Field(
        None,
        min_length=1,
        max_length=TTS_MAX_CHARACTERS,
        description="Text to speak (1-10000 characters); exactly one of text or ssml is required.",
    )
    ssml: str | None = Field(
        None,
        min_length=1,
        max_length=TTS_MAX_CHARACTERS,
        description="Complete SSML instead of text; local safety cap 10000 characters. Tag support depends on voice/model.",
    )
    model: Literal["dola-seed-tts-3.0"] = Field(
        "dola-seed-tts-3.0", description="Seed TTS 3 model; account and voice must be authorized."
    )
    language_code: str = Field(
        "auto",
        min_length=1,
        max_length=64,
        description="Provider language or dialect code, e.g. en for US English; auto by default.",
    )
    output_format: TtsOutputFormat = Field(
        default_factory=lambda: TtsOutputFormat(format="mp3", sample_rate=None, bit_rate=None),
        description="Encoding, sample rate and bitrate.",
    )
    voice_settings: TtsVoiceSettings | None = Field(
        None, description="Optional voice delivery controls."
    )
    enable_subtitle: bool = Field(
        False, description="Return word-level alignment when supported by the language."
    )
    pronunciation_dictionary: TtsPronunciationDictionary | None = Field(
        None,
        description="Optional pronunciation corrections and text replacements before synthesis.",
    )
    session_id: str | None = Field(
        None,
        min_length=1,
        max_length=256,
        description="Reuse only for sequential requests in one conversation; provider history is time/turn limited.",
    )
    text_normalization: bool = Field(True, description="Normalize numbers, dates and similar text.")
    enable_markdown_filter: bool = Field(False, description="Parse Markdown in the input text.")
    silence_duration: float = Field(
        0,
        ge=0,
        le=30000,
        allow_inf_nan=False,
        description="Silence appended after the final sentence, in milliseconds (0-30000).",
    )
    output_path: str | None = output_path_field("the synthesized speech")
    overwrite: bool = overwrite_field()

    @field_validator("text", "ssml", "voice_id", "session_id", "language_code")
    @classmethod
    def validate_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value must not be blank.")
        return value

    @model_validator(mode="after")
    def validate_input(self) -> SeedTtsGenerateInput:
        if (self.text is None) == (self.ssml is None):
            raise ValueError("Provide exactly one of text or ssml.")
        if self.voice_id in {".", ".."}:
            raise ValueError("voice_id must not be a relative path segment.")
        return self


class SeedTtsGenerateOutput(BaseModel):
    provider: Literal["byteplus-seed-speech"] = Field(
        "byteplus-seed-speech", description="Speech synthesis provider."
    )
    model: Literal["dola-seed-tts-3.0"] = Field(
        "dola-seed-tts-3.0", description="Model used for speech synthesis."
    )
    artifact: ArtifactRef = Field(
        ...,
        description=(
            "Complete audio: a private expiring HTTPS download on configured HTTP hosts, "
            "or a persisted stdio artifact with an explicit storage fallback on failure."
        ),
    )
    output_format: TtsOutputFormat = Field(
        ..., description="Resolved audio encoding, sample rate and bitrate."
    )
    session_id: str = Field(
        ..., description="Synthesis session identifier returned by the provider."
    )
    alignments: list[TtsAlignment] = Field(
        default_factory=list,
        description="Subtitle segments in receive order; empty if not returned.",
    )
    request_id: str = Field(..., description="Client-generated X-Request-Id for correlation.")
    provider_log_id: str | None = Field(None, description="Provider X-Tt-Logid, if returned.")


async def _completion_progress(ctx: Context, progress: int) -> None:
    """Do not discard billed audio on notification failure; cancellation still propagates."""
    try:
        await ctx.report_progress(progress=progress, total=100)
    except Exception:
        log_warning("seed_tts_progress_failed", progress=progress)


async def _hosted_audio(audio: bytes, mime_type: str, request_id: str, ctx: Context) -> ArtifactRef:
    """Deliver bytes without local state, response Base64 or automatic synthesis retries."""
    from ark_mcp.providers.tos.client import TosGateway

    artifact_id = str(uuid4())
    extension = {"audio/mpeg": "mp3", "audio/pcm": "pcm", "audio/ogg": "ogg"}[mime_type]
    key = f"tts-output/{get_principal(ctx).principal_id}/{artifact_id}.{extension}"
    created = datetime.now(UTC)
    gateway: TosGateway | None = None
    try:
        gateway = TosGateway(max_retry_count=0)
        url = await gateway.upload_tts_output(key=key, data=audio, mime_type=mime_type)
    except Exception:
        # Storage errors can include signed URLs or operator credentials; never forward them.
        raise ProviderError(
            NormalizedProviderError(
                provider="seed-speech",
                operation="deliver_speech",
                code="TTS_DELIVERY_FAILED",
                message=(
                    "Synthesis completed but its download link could not be delivered. "
                    "Storage may contain the expiring audio. Keep the request ID and "
                    "contact the operator; do not automatically synthesize again."
                ),
                request_id=request_id,
                retryable=False,
                ambiguous_completion=False,
            )
        ) from None
    finally:
        try:
            if gateway is not None:
                await gateway.close()
        except Exception:
            log_warning("seed_tts_storage_cleanup_failed")
    return ArtifactRef(
        id=artifact_id,
        uri=url,
        media_type=MediaType.AUDIO,
        mime_type=mime_type,
        bytes=len(audio),
        sha256=hashlib.sha256(audio).hexdigest(),
        created_at=created.isoformat(),
        source_expires_at=(
            created + timedelta(seconds=TEMPORARY_REFERENCE_TTL_SECONDS)
        ).isoformat(),
    )


@local_export("artifact")
async def seed_tts_generate(
    input: SeedTtsGenerateInput, ctx: Context
) -> SeedTtsGenerateOutput | ToolResult:
    """Synthesize text or SSML with Seed TTS 3 and an authorized voice_id.

    Call directly; collects at most 10 MiB of complete audio, not live MCP audio.
    HTTP requires operator-enabled TTS output storage and live Seed Speech/client-secret
    headers. Returns a private signed HTTPS download, nominally valid 24 hours; STS expiry
    may shorten it. Objects have one-day scheduled expiry, not exact 24-hour deletion.
    Download promptly; no renewal, replay or hosted artifact resource exists.
    Stdio always persists locally. No persist switch; output_path/overwrite are stdio only.
    Returns optional word alignment in seconds. No automatic synthesis retries.
    Undeliverable persistence errors retain the request ID and confirmed synthesis status.
    Use seed_audio_generate for full-scene audio; this tool speaks supplied text.
    """
    runtime = get_runtime(ctx)
    hosted = runtime.settings.mcp_transport == "http"
    if hosted and not runtime.settings.hosted_tts_enabled:
        raise ValueError("Hosted TTS output storage is not configured; ask the operator.")
    if hosted and (input.output_path is not None or input.overwrite):
        raise ValueError("output_path and overwrite are stdio only.")
    output_format = input.output_format.resolved()
    body = input.model_dump(
        exclude={"model", "voice_id", "output_path", "overwrite"}, exclude_none=True
    )
    body["model_id"] = input.model
    body["output_format"] = output_format.model_dump(exclude_none=True)
    request_id = str(uuid4())
    estimated_cost = log_cost_estimate(
        product="tts", variations=1, characters=len(input.text or input.ssml or "")
    )
    service = SeedTtsService(
        seed_speech_gateway(ctx),
        timeout_seconds=runtime.settings.request_timeout_ms / 1000,
    )
    try:
        await ctx.report_progress(progress=10, total=100)
        async with billed_provider_slot(
            ctx, provider="seed-speech", product="tts", estimated_cost_usd=estimated_cost
        ):
            response = await service.synthesize(
                body,
                voice_id=input.voice_id,
                request_id=request_id,
                max_audio_bytes=artifact_limit_bytes(MediaType.AUDIO),
            )
            if hosted:
                # Keep admission held through upload so completed audio cannot accumulate.
                artifact = await _hosted_audio(
                    response.audio, output_format.mime_type, request_id, ctx
                )
    except ProviderError as exc:
        return provider_error_result(exc)
    finally:
        try:
            await service.close()
        except Exception:
            log_warning("seed_tts_cleanup_failed")
    await _completion_progress(ctx, 80)
    try:
        if not hosted:
            artifact = await persist_base64(
                runtime.artifact_store,
                data=base64.b64encode(response.audio).decode("ascii"),
                media_type=MediaType.AUDIO,
                mime_type=output_format.mime_type,
                source_expires_at=None,
                auth=get_principal(ctx),
            )
    except ArtifactPersistenceError as exc:
        return provider_error_result(
            ProviderError(
                NormalizedProviderError(
                    provider="seed-speech",
                    operation="persist_speech",
                    code=exc.code.upper(),
                    message=(
                        "Synthesis completed, but audio could not be persisted. "
                        "No provider URL is available, and inline fallback is disabled "
                        "or exceeds its size limit. Do not automatically synthesize again."
                    ),
                    request_id=request_id,
                    retryable=False,
                    ambiguous_completion=False,
                )
            )
        )
    await _completion_progress(ctx, 100)
    return SeedTtsGenerateOutput(
        artifact=artifact,
        output_format=output_format,
        session_id=response.session_id,
        alignments=response.alignments,
        request_id=request_id,
        provider_log_id=response.provider_log_id,
    )


TOOL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
