"""Cost estimation and rate limiting for parallel generation.

Provides cost estimation constants and logging for billable operations.
Rate limiting is handled via ``asyncio.Semaphore`` directly in each
variation tool handler.
"""

from __future__ import annotations

import re
from typing import Literal

from ark_mcp.observability.logger import info as log_info

# Provider cost estimates (USD per unit).
COST_PER_AUDIO_SECOND = 0.0031
COST_PER_TTS_MILLION_CHARACTERS = 20.0
COST_PER_VIDEO_TASK = 0.07
COST_PER_VIDEO_TASK_2_5 = 0.35
COST_PER_SEEDREAM_5_5_INPUT_IMAGE = 0.008
# Rounded pixel tiers from the supplied 261028 high-resolution output contract.
SEEDREAM_5_5_OUTPUT_TIERS = ((2_610_000, 0.020), (4_630_000, 0.035), (8_294_400, 0.079))

# Default max concurrent provider calls.
DEFAULT_MAX_CONCURRENT = 5

# Model-specific cost overrides for video tasks.
_VIDEO_COST_OVERRIDES: dict[str, float] = {}


def register_video_cost_override(model_id: str, cost_per_task: float) -> None:
    """Register a model-specific cost-per-task override for video generation."""
    _VIDEO_COST_OVERRIDES[model_id] = cost_per_task


def _video_cost_for_model(model_id: str | None, family: str | None = None) -> float:
    """Return the cost-per-task for a video model, keyed on its registry family.

    A model-specific override wins. Pricing follows the family so that a
    custom endpoint bound to Seedance 2.5 or Flash uses the static 2.5 fallback,
    not a token-based provider quote.
    """
    if model_id and model_id in _VIDEO_COST_OVERRIDES:
        return _VIDEO_COST_OVERRIDES[model_id]
    if family in ("seedance_2_5", "seedance_2_5_flash"):
        return COST_PER_VIDEO_TASK_2_5
    return COST_PER_VIDEO_TASK


def image_cost_estimate(
    model_id: str | None,
    count: int,
    *,
    family: str | None = None,
    size: str | None = None,
    reference_images: int = 0,
) -> tuple[float, Literal["builtin"]]:
    """Estimate each output and its references, using the resolved registry family."""
    if family not in (None, "seedream_5_5"):
        raise ValueError("Only Seedream 5.5 image estimates are supported.")
    pixels = {None: 2048 * 2048, "1K": 1024 * 1024, "1.5K": 1536 * 1536, "2K": 2048 * 2048}.get(
        size
    )
    if pixels is None and size is not None:
        dimensions = re.fullmatch(r"([1-9][0-9]{0,6})x([1-9][0-9]{0,6})", size)
        if dimensions:
            width, height = map(int, dimensions.groups())
            pixels = width * height
    # Callers validate size first; unknown sizes conservatively use the highest tier.
    output_cost = SEEDREAM_5_5_OUTPUT_TIERS[-1][1]
    if pixels is not None:
        output_cost = next(
            (rate for maximum, rate in SEEDREAM_5_5_OUTPUT_TIERS if pixels <= maximum),
            output_cost,
        )
    per_call = output_cost + reference_images * COST_PER_SEEDREAM_5_5_INPUT_IMAGE
    return round(count * per_call, 4), "builtin"


def price_source(product: str, model_id: str | None) -> str:
    """Identify the source of the built-in budgeting estimate."""
    return "builtin"


def estimate_cost(
    *,
    product: str,
    variations: int,
    duration_seconds: float = 0.0,
    characters: int = 0,
    model_id: str | None = None,
    video_family: str | None = None,
    image_family: str | None = None,
    image_size: str | None = None,
    reference_images: int = 0,
) -> float:
    """Estimate the cost of a parallel generation batch.

    Args:
        product: "image", "audio", "tts", or "video".
        variations: Number of variations.
        duration_seconds: Expected output duration (audio only).
        characters: TTS input characters, including SSML markup and audio tags.
        model_id: Model ID for an optional static video cost override.
        video_family: Registry family for video pricing (e.g. "seedance_2_5").
        image_family: Resolved registry family for image pricing.
        image_size: Validated image size; omitted uses the family's provider default.
        reference_images: Input images per image generation call, repeated for each variation.

    Returns:
        Estimated cost in USD.
    """
    if product == "image":
        return image_cost_estimate(
            model_id,
            variations,
            family=image_family,
            size=image_size,
            reference_images=reference_images,
        )[0]
    if product == "audio":
        return round(variations * max(duration_seconds, 10) * COST_PER_AUDIO_SECOND, 2)
    if product == "tts":
        return round(
            variations * max(characters, 0) * COST_PER_TTS_MILLION_CHARACTERS / 1_000_000, 6
        )
    if product == "video":
        return round(variations * _video_cost_for_model(model_id, video_family), 2)
    return 0.0


def log_cost_estimate(
    *,
    product: str,
    variations: int,
    duration_seconds: float = 0.0,
    characters: int = 0,
    model_id: str | None = None,
    video_family: str | None = None,
    image_family: str | None = None,
    image_size: str | None = None,
    reference_images: int = 0,
) -> float:
    """Log a cost estimate before dispatching a batch."""
    cost = estimate_cost(
        product=product,
        variations=variations,
        duration_seconds=duration_seconds,
        characters=characters,
        model_id=model_id,
        video_family=video_family,
        image_family=image_family,
        image_size=image_size,
        reference_images=reference_images,
    )
    log_info(
        "cost_estimate",
        product=product,
        variations=variations,
        estimated_cost_usd=cost,
        price_source=price_source(product, model_id),
    )
    return cost
