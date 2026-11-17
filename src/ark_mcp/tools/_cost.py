"""Cost estimation and rate limiting for parallel generation.

Provides cost estimation constants and logging for billable operations.
Rate limiting is handled via ``asyncio.Semaphore`` directly in each
variation tool handler.
"""

from __future__ import annotations

from typing import Literal

from ark_mcp.observability.logger import info as log_info

# Provider cost estimates (USD per unit).
COST_PER_IMAGE = 0.03
COST_PER_AUDIO_SECOND = 0.0031
COST_PER_VIDEO_TASK = 0.07
COST_PER_VIDEO_TASK_2_5 = 0.35

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


def image_cost_estimate(model_id: str | None, count: int) -> tuple[float, Literal["builtin"]]:
    """Return a built-in estimate, never an account-specific billing quote."""
    return round(count * COST_PER_IMAGE, 4), "builtin"


def price_source(product: str, model_id: str | None) -> str:
    """Identify the source of the built-in budgeting estimate."""
    return "builtin"


def estimate_cost(
    *,
    product: str,
    variations: int,
    duration_seconds: float = 0.0,
    model_id: str | None = None,
    video_family: str | None = None,
) -> float:
    """Estimate the cost of a parallel generation batch.

    Args:
        product: "image", "audio", or "video".
        variations: Number of variations.
        duration_seconds: Expected output duration (audio only).
        model_id: Model ID for an optional static video cost override.
        video_family: Registry family for video pricing (e.g. "seedance_2_5").

    Returns:
        Estimated cost in USD.
    """
    if product == "image":
        return image_cost_estimate(model_id, variations)[0]
    if product == "audio":
        return round(variations * max(duration_seconds, 10) * COST_PER_AUDIO_SECOND, 2)
    if product == "video":
        return round(variations * _video_cost_for_model(model_id, video_family), 2)
    return 0.0


def log_cost_estimate(
    *,
    product: str,
    variations: int,
    duration_seconds: float = 0.0,
    model_id: str | None = None,
    video_family: str | None = None,
) -> float:
    """Log a cost estimate before dispatching a batch."""
    cost = estimate_cost(
        product=product,
        variations=variations,
        duration_seconds=duration_seconds,
        model_id=model_id,
        video_family=video_family,
    )
    log_info(
        "cost_estimate",
        product=product,
        variations=variations,
        estimated_cost_usd=cost,
        price_source=price_source(product, model_id),
    )
    return cost
