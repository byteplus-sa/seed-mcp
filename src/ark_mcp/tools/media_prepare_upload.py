"""Restricted direct-to-TOS upload preparation; see specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastmcp import Context
from fastmcp.tools import ToolResult
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ark_mcp.config.env import get_settings
from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
from ark_mcp.providers.tos.constants import (
    TEMPORARY_OBJECT_EXPIRES_DAYS,
    TEMPORARY_REFERENCE_TTL_SECONDS,
    TEMPORARY_UPLOAD_TTL_SECONDS,
)
from ark_mcp.runtime import get_runtime
from ark_mcp.security.credentials import require_upload_scope
from ark_mcp.security.media_policy import MediaLimits, get_media_limits
from ark_mcp.tools._errors import provider_error_result

UPLOAD_MIME_TYPES = sorted(
    MediaLimits.ALLOWED_IMAGE_MIMES
    | MediaLimits.ALLOWED_AUDIO_MIMES
    | MediaLimits.ALLOWED_VIDEO_MIMES
)

UPLOAD_INSTRUCTIONS = (
    "Upload the binary file directly to upload_url using multipart/form-data POST. "
    "Include every form_fields entry unchanged, then append the file field LAST; "
    "let your HTTP library set the multipart boundary. Wait for successful TOS upload "
    "before passing reference_url to a generation tool. This call does not upload, "
    "inspect or verify any file. Signed MIME is declared metadata, not content validation. "
    "Keep all signed fields and URLs private. Permissions are bearer capabilities, not "
    "guaranteed one-use tokens; STS expiry can shorten their validity. Object deletion "
    "is day-based and scheduled, not exactly 24 hours; URL expiry does not delete the file. "
    "Submit generation promptly so the provider can fetch before reference_url expires."
)


class MediaPrepareUploadInput(BaseModel):
    """Metadata only; binary content is sent by the client directly to TOS."""

    model_config = ConfigDict(extra="forbid")

    media_type: Literal["image", "audio", "video"] = Field(
        ..., description="Media category: image, audio or video."
    )
    mime_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[!-~]+$",
        description=(
            "Exact allowlisted MIME type matching media_type; use image/* for image, "
            "audio/* for audio or video/* for video. Allowed values are in the schema enum. "
            "Signed as declared metadata; the bytes are not inspected."
        ),
        json_schema_extra={"enum": list(UPLOAD_MIME_TYPES)},
    )
    size_bytes: int = Field(
        ...,
        strict=True,
        gt=0,
        le=200 * 1024 * 1024,
        description=(
            "Exact binary file size in bytes, excluding multipart overhead. "
            "Maximum 10 MiB for images/audio, 200 MiB for video; policy fixes this size."
        ),
    )

    @model_validator(mode="after")
    def validate_media(self) -> MediaPrepareUploadInput:
        limits = get_media_limits()
        allowed, maximum = {
            "image": (limits.ALLOWED_IMAGE_MIMES, limits.image_max_bytes),
            "audio": (limits.ALLOWED_AUDIO_MIMES, limits.audio_max_bytes),
            "video": (limits.ALLOWED_VIDEO_MIMES, limits.video_max_bytes),
        }[self.media_type]
        if self.mime_type not in allowed:
            raise ValueError("mime_type must exactly match an allowed MIME for the media category.")
        if self.size_bytes > maximum:
            raise ValueError(f"{self.media_type} exceeds its {maximum}-byte upload limit.")
        return self


class MediaPrepareUploadOutput(BaseModel):
    """Upload instructions, not a successful-upload receipt."""

    upload_url: str = Field(..., description="Official HTTPS TOS bucket URL for multipart POST.")
    method: Literal["POST"] = Field(
        "POST", description="Upload HTTP method; use multipart/form-data."
    )
    form_fields: dict[str, str] = Field(
        ...,
        description=(
            "Include every signed form field unchanged. Sensitive bearer permissions, "
            "including policy/signature and optional STS token; never log or publish."
        ),
    )
    file_field: Literal["file"] = Field(
        "file", description="Append the binary file under this name LAST, after all form fields."
    )
    upload_expires_at: str = Field(
        ...,
        description="ISO-8601 UTC nominal upload-permission expiry (15 minutes); STS may expire earlier.",
    )
    reference_url: str = Field(
        ...,
        description=(
            "Signed HTTPS GET URL to use only AFTER successful client upload. "
            "Does not prove object existence or media validity."
        ),
    )
    reference_expires_at: str = Field(
        ...,
        description="ISO-8601 UTC nominal GET expiry (24 hours); STS may expire earlier.",
    )
    object_key: str = Field(
        ...,
        description="Server-selected unique key under temporary-references; not a provider asset.",
    )
    size_bytes: int = Field(..., description="Exact binary byte count fixed in the upload policy.")
    object_expires_days: Literal[1] = Field(
        1,
        description=(
            "TOS object expiration in whole days from Last-Modified; deletion starts "
            "at the following midnight and is scheduled, not exact 24-hour deletion."
        ),
    )
    instructions: str = Field(
        UPLOAD_INSTRUCTIONS,
        description="Required client upload sequence and security/expiry limits.",
    )


async def media_prepare_upload(
    input: MediaPrepareUploadInput, ctx: Context
) -> MediaPrepareUploadOutput | ToolResult:
    """Prepare a temporary direct-to-TOS upload for one image, audio or video (HTTP only, opt-in).

    Requires live X-MCP-Client-Secret enrolled by the operator; no generation-provider key is
    needed. Send metadata only, never a local path, Base64 or credentials. Returns restricted
    multipart POST fields (15 minutes) and a GET reference URL (24 hours). An upload-capable
    client must upload the binary directly to TOS, with file LAST, and wait for success before
    using reference_url in an existing generation tool. This call does not upload or inspect
    bytes, verify the object or create an asset. TOS expiry is one whole day with scheduled
    deletion; signed URL expiry is not deletion. STS expiry can shorten URL validity.
    Explicit operator IRSA mode may exchange OIDC with BytePlus STS before signing;
    no bucket/object provider call or generation-provider credential is used.
    Every call selects a new key; no durable state, replay or global upload budget exists.
    """
    principal = require_upload_scope()
    settings = get_settings()
    if settings.mcp_transport != "http" or not settings.temporary_upload_enabled:
        raise PermissionError("Temporary upload preparation is disabled.")
    from ark_mcp.providers.tos.client import TosGateway

    key = f"temporary-references/{principal.principal_id}/{input.media_type}/{uuid4()}"
    started = datetime.now(UTC)
    try:
        runtime = get_runtime(ctx)
        async with runtime.provider_limiters.acquire("tos", principal):
            if settings.tos_credential_mode == "irsa":
                from ark_mcp.providers.tos.credentials import IrsaCredentialsProvider

                if runtime.tos_credentials is None:
                    runtime.tos_credentials = IrsaCredentialsProvider(settings)
                gateway = TosGateway(credentials_provider=runtime.tos_credentials)
            else:
                gateway = TosGateway()
            try:
                upload_url, fields, reference_url = await gateway.prepare_upload(
                    key=key, mime_type=input.mime_type, size_bytes=input.size_bytes
                )
            except ProviderError as exc:
                if exc.code == "TOS_IRSA_CREDENTIALS_UNAVAILABLE":
                    raise ProviderError(
                        NormalizedProviderError(
                            provider="tos",
                            operation="prepare_upload",
                            code="TOS_IRSA_CREDENTIALS_UNAVAILABLE",
                            message="Could not obtain valid TOS IRSA credentials. Ask the operator to check TOS configuration.",
                            retryable=True,
                        )
                    ) from None
                raise ValueError(
                    "Could not prepare temporary upload permissions. Ask the operator to check TOS configuration."
                ) from None
            finally:
                await gateway.close()
    except ProviderError as exc:
        return provider_error_result(exc)
    return MediaPrepareUploadOutput(
        upload_url=upload_url,
        form_fields=fields,
        upload_expires_at=(started + timedelta(seconds=TEMPORARY_UPLOAD_TTL_SECONDS)).isoformat(),
        reference_url=reference_url,
        reference_expires_at=(
            started + timedelta(seconds=TEMPORARY_REFERENCE_TTL_SECONDS)
        ).isoformat(),
        object_key=key,
        size_bytes=input.size_bytes,
        object_expires_days=TEMPORARY_OBJECT_EXPIRES_DAYS,
    )


TOOL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
