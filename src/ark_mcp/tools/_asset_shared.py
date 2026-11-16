"""Reject native Seedance asset references in other generation products."""

from __future__ import annotations

from typing import Any, Literal

from ark_mcp.domain.assets import is_asset_uri


def require_url_references(
    items: list[dict[str, Any]] | None,
    *,
    product: Literal["Seedream", "Seed Audio"],
) -> list[dict[str, Any]] | None:
    """Require regular URLs for products without native asset support."""
    if items and any(is_asset_uri(item.get("url")) for item in items):
        raise ValueError(
            f"{product} does not accept asset:// references; only Seedance uses them "
            "natively. Pass a regular HTTPS URL."
        )
    return items
