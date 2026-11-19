"""Domain artifact models.

``ArtifactRef`` describes temporary provider URLs and explicit stdio persistence.
HTTP returns URL-only references; durable ``seed-media://artifacts/{id}``
resources are stdio-only. Provider URLs expire (2h for audio, 24h for
ModelArk image/video).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class MediaType(StrEnum):
    """Logical generated-media categories."""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class ArtifactPersistenceIssue(BaseModel):
    """Safe explanation for a provider output that could not be persisted."""

    code: Literal[
        "untrusted_output_host",
        "output_too_large",
        "invalid_output_mime",
        "source_expired",
        "download_failed",
        "storage_failed",
    ] = Field(description="Failure category.")
    message: str = Field(description="Safe failure message (no credentials or URLs).")
    retryable: bool = Field(description="Whether retrying persistence later may succeed.")
    artifact_limit_bytes: int = Field(description="Maximum durable artifact size in bytes.")
    source_url_expires_at: str | None = Field(
        default=None,
        description="ISO-8601 expiry of the unpersisted provider URL (the artifact uri).",
    )


class ArtifactRef(BaseModel):
    """Reference to temporary provider output or an explicitly persisted stdio artifact."""

    id: str = Field(
        ...,
        description="Stored artifact ID, or 'provider-url' / 'inline-fallback' for unpersisted output.",
    )
    uri: str = Field(
        ...,
        description="Temporary provider URL by default; stdio persistence may return seed-media://artifacts/{id} or an inline-fallback URI.",
    )
    media_type: MediaType = Field(..., description="image, audio or video.")
    mime_type: str = Field(..., description="MIME type, e.g. image/png.")
    bytes: int | None = Field(default=None, description="Size in bytes.")
    sha256: str | None = Field(default=None, description="SHA-256 hex digest.")
    created_at: str = Field(..., description="ISO-8601 timestamp of artifact creation.")
    expires_at: str | None = Field(
        default=None,
        description="ISO-8601 expiry of the stored artifact.",
    )
    source_expires_at: str | None = Field(
        default=None,
        description="ISO-8601 expiry of the provider URL.",
    )
    persistence_error: ArtifactPersistenceIssue | None = Field(
        default=None,
        description=(
            "Set when requested stdio persistence failed. id is then 'provider-url' (temporary "
            "URL; stdio can use seed_media_persist_url before source_expires_at) or "
            "'inline-fallback' (bytes in fallback_data). Null when persistence was not requested."
        ),
    )
    fallback_data: str | None = Field(
        default=None,
        description="Base64 output bytes from a stdio persistence fallback, only with id 'inline-fallback'.",
    )
    local_path: str | None = Field(
        default=None,
        description="Absolute path of the stdio-only local copy written for output_path/output_dir.",
    )
    export_error: str | None = Field(
        default=None,
        description="Why the requested local copy was not written (the artifact is unaffected).",
    )
