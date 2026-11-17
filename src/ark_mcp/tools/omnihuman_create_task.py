"""``omnihuman_create_task`` tool — submit an OmniHuman 2.0 image-plus-audio video task."""

from __future__ import annotations

from typing import Literal

from fastmcp import Context
from fastmcp.tools import ToolResult
from pydantic import BaseModel, Field, ValidationError

from ark_mcp.domain.errors import AcceptedTaskError, ProviderError
from ark_mcp.domain.submissions import IDEMPOTENCY_KEY_DESCRIPTION, IdempotencyKey
from ark_mcp.observability.logger import info as log_info
from ark_mcp.providers.factory import vision_cv_gateway
from ark_mcp.providers.vision_cv.omnihuman import OmniHumanService
from ark_mcp.providers.vision_cv.schemas import PROMPT_MAX_LENGTH, OmniHumanSubmitRequest
from ark_mcp.runtime import get_principal, get_runtime, record_accepted_task
from ark_mcp.security.credentials import provider_api_key
from ark_mcp.tools._errors import provider_error_result
from ark_mcp.tools._http_policy import validate_http_options
from ark_mcp.tools._omnihuman_shared import (
    MediaRefError,
    resolve_media_ref,
)
from ark_mcp.tools._task_execution import context_log

RECOMMENDED_POLL_AFTER_MS = 10_000


class OmniHumanCreateTaskInput(BaseModel):
    """Input for ``omnihuman_create_task``."""

    idempotency_key: IdempotencyKey | None = Field(None, description=IDEMPOTENCY_KEY_DESCRIPTION)
    image: str = Field(
        description=(
            "Portrait of the person to animate: public HTTPS URL. Stdio also accepts "
            "seed-media:// artifacts from object storage. jpeg/png/webp/bmp/tiff/gif/heic/heif, "
            "under 30 MB, width/height 0.4-2.5, each side 300-6000 px."
        )
    )
    audio: str = Field(
        description=(
            "Driving audio: public HTTPS URL, or seed-media:// artifact on stdio only. wav or mp3, under 15 MB, "
            "4-300 s; video length follows the audio."
        )
    )
    prompt: str | None = Field(
        default=None,
        max_length=PROMPT_MAX_LENGTH,
        description="Optional text steering the scene, movements and camera (zh, en, ja, ko, es-MX, id).",
    )
    watermark: bool = Field(
        default=True,
        description="Whether the provider watermarks the video.",
    )


class OmniHumanCreateTaskOutput(BaseModel):
    """Accepted OmniHuman 2.0 task."""

    provider: Literal["byteplus-vision-cv"] = Field(
        default="byteplus-vision-cv", description="Provider surface."
    )
    status: Literal["accepted"] = Field(default="accepted", description="Task accepted and queued.")
    task_id: str = Field(description="Pass to omnihuman_get_task or omnihuman_cancel_task.")
    request_id: str | None = Field(
        default=None, description="Provider diagnostic request ID, when returned."
    )
    recommended_poll_after_ms: int = Field(
        description="Suggested delay before polling omnihuman_get_task, in milliseconds."
    )


async def omnihuman_create_task(
    input: OmniHumanCreateTaskInput, ctx: Context
) -> OmniHumanCreateTaskOutput | ToolResult:
    """Generate a talking or performing video of a person from one image and one audio clip (OmniHuman 2.0).

    Returns a task_id; poll omnihuman_get_task for the temporary video URL (one-hour
    expiry). Submission is never retried automatically. HTTP runs in the foreground.
    HTTP requires idempotency_key; repeat identical arguments/key only to recover a
    successful receipt. Unresolved attempts need reconciliation, never a new key.
    Stdio uses ark_job_submit and allows explicit persistence when polling.
    """
    if input.idempotency_key is not None and get_runtime(ctx).settings.mcp_transport == "stdio":
        raise ValueError("idempotency_key is HTTP-only; omit it for local stdio.")
    validate_http_options(ctx, media_references=(input.image, input.audio))
    provider_api_key(ctx, "vision-cv")
    runtime = get_runtime(ctx)
    settings = runtime.settings
    if not settings.omnihuman_enabled:
        raise ValueError("OmniHuman is not enabled. Set BYTEPLUS_OMNIHUMAN_ENABLED=true.")

    owner = get_principal(ctx)
    try:
        image_url = await resolve_media_ref(
            input.image, "image", store=runtime.artifact_store, owner=owner
        )
        audio_url = await resolve_media_ref(
            input.audio, "audio", store=runtime.artifact_store, owner=owner
        )
        request = OmniHumanSubmitRequest.model_validate(
            {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": input.prompt,
                "enable_watermark": input.watermark,
            }
        )
    except MediaRefError as exc:
        return ToolResult(content=[{"type": "text", "text": str(exc)}], is_error=True)
    except ValidationError:
        return ToolResult(
            content=[
                {
                    "type": "text",
                    "text": "The image or audio reference did not resolve to an HTTPS URL.",
                }
            ],
            is_error=True,
        )
    except ProviderError as exc:
        return provider_error_result(exc)

    await context_log(ctx, "info", "Submitting OmniHuman 2.0 task")
    await ctx.report_progress(progress=20, total=100)
    service = OmniHumanService(gateway=vision_cv_gateway(ctx))
    try:
        await runtime.ownership_store.require_capacity()
        async with runtime.provider_limiters.acquire("vision-cv", owner):
            submission = await service.create(request)
        await record_accepted_task(ctx, "vision-cv", submission.task_id, submission.request_id)
    except AcceptedTaskError as exc:
        await context_log(
            ctx,
            "error",
            "OmniHuman task accepted, but ownership recording failed; do not resubmit.",
        )
        return provider_error_result(exc)
    except ProviderError as exc:
        await context_log(ctx, "error", f"OmniHuman submission failed: {exc.message}")
        return provider_error_result(exc)
    finally:
        await service.close()

    await ctx.report_progress(progress=100, total=100)
    log_info("omnihuman_create_task_accepted", task_id=submission.task_id)
    return OmniHumanCreateTaskOutput(
        task_id=submission.task_id,
        request_id=submission.request_id,
        recommended_poll_after_ms=RECOMMENDED_POLL_AFTER_MS,
    )


TOOL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
