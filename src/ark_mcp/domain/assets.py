"""Validate native Seedance references to assets registered outside this server."""

from __future__ import annotations

import re

ASSET_URI_PREFIX = "asset://"
# Asset IDs look like ``asset-20260318035710-kctzf``. Copyright-IP and preset
# character IDs share the scheme; accept any conservative token so those work
# too, while rejecting paths, whitespace, and URL syntax.
_ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class AssetUriError(ValueError):
    """Raised for a malformed ``asset://`` reference."""


def is_asset_uri(value: object) -> bool:
    """Return True when ``value`` is a string using the ``asset://`` scheme."""
    return isinstance(value, str) and value[: len(ASSET_URI_PREFIX)].lower() == ASSET_URI_PREFIX


def validate_asset_id(asset_id: str) -> str:
    """Validate a bare asset ID and return it unchanged."""
    if not _ASSET_ID_PATTERN.match(asset_id):
        raise AssetUriError(
            "Invalid asset ID. Expected an ID such as 'asset-20260318035710-kctzf' "
            "(letters, digits, '-' and '_' only)."
        )
    return asset_id


def parse_asset_uri(value: str) -> str:
    """Return the asset ID from ``asset://<asset_id>``, validating its shape."""
    if not is_asset_uri(value):
        raise AssetUriError("Expected an asset reference of the form 'asset://<asset_id>'.")
    return validate_asset_id(value[len(ASSET_URI_PREFIX) :])


def asset_uri(asset_id: str) -> str:
    """Build the ``asset://<asset_id>`` reference used in generation requests."""
    return f"{ASSET_URI_PREFIX}{validate_asset_id(asset_id)}"
