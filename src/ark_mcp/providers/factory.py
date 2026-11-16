"""Request-key gateways for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.providers.seed_speech.client import SeedSpeechGateway
from ark_mcp.providers.vision_cv.client import VisionCvGateway
from ark_mcp.runtime import get_runtime
from ark_mcp.security.credentials import provider_api_key

if TYPE_CHECKING:
    from fastmcp import Context


def modelark_gateway(ctx: Context, *, understanding: bool = False) -> ModelArkGateway:
    """Create an invocation-owned gateway using only the selected live credential."""
    api_key = provider_api_key(ctx, "modelark")
    settings = get_runtime(ctx).settings
    timeout_ms = settings.request_timeout_ms
    if understanding and settings.seed_understanding_timeout_ms is not None:
        timeout_ms = settings.seed_understanding_timeout_ms
    return ModelArkGateway(
        api_key=api_key,
        base_url=settings.modelark_base_url,
        timeout=timeout_ms / 1000,
        connect_timeout=settings.connect_timeout_ms / 1000,
    )


def seed_speech_gateway(ctx: Context) -> SeedSpeechGateway:
    """Create an invocation-owned Seed Speech gateway."""
    api_key = provider_api_key(ctx, "seed-speech")
    settings = get_runtime(ctx).settings
    return SeedSpeechGateway(
        api_key=api_key,
        base_url=settings.seed_audio_base_url,
        timeout=settings.request_timeout_ms / 1000,
        connect_timeout=settings.connect_timeout_ms / 1000,
    )


def vision_cv_gateway(ctx: Context) -> VisionCvGateway:
    """Create an invocation-owned Vision AI gateway."""
    api_key = provider_api_key(ctx, "vision-cv")
    settings = get_runtime(ctx).settings
    return VisionCvGateway(
        api_key=api_key,
        base_url=settings.cv_base_url,
        timeout=settings.request_timeout_ms / 1000,
        connect_timeout=settings.connect_timeout_ms / 1000,
    )
