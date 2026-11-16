"""Unit tests for ``asset://`` parsing and which media inputs accept it."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from pydantic import ValidationError

from ark_mcp.domain.assets import AssetUriError, asset_uri, is_asset_uri, parse_asset_uri
from ark_mcp.domain.media import AudioReference, MediaSource, ReferenceImageInput
from ark_mcp.providers.modelark.seedance import SeedanceService
from ark_mcp.security.url_policy import UrlValidationError, validate_url
from ark_mcp.tools._asset_shared import require_url_references
from ark_mcp.tools._seedance_shared import (
    SeedanceAudioInput,
    SeedanceImageInput,
    SeedanceVideoInput,
)

ASSET = "asset://asset-20260318035710-kctzf"


def test_parse_and_build_asset_uri() -> None:
    assert is_asset_uri(ASSET)
    assert is_asset_uri("ASSET://asset-1")
    assert not is_asset_uri("https://example.com/a.png")
    assert parse_asset_uri(ASSET) == "asset-20260318035710-kctzf"
    assert asset_uri("Asset-2026-abc") == "asset://Asset-2026-abc"


@pytest.mark.parametrize(
    "bad",
    [
        "asset://",
        "asset://../etc",
        "asset://a b",
        "asset://x/y",
        "asset://asset-id?token=test",
        "asset://asset-id#fragment",
        "asset://user@asset-id",
    ],
)
def test_malformed_asset_uri_rejected(bad: str) -> None:
    with pytest.raises(AssetUriError):
        parse_asset_uri(bad)


def test_url_policy_still_rejects_asset_scheme() -> None:
    with pytest.raises(UrlValidationError):
        validate_url(ASSET)


def test_generic_media_source_rejects_asset_uri() -> None:
    with pytest.raises(ValidationError, match="not supported for this input"):
        MediaSource(kind="url", url=ASSET)


def test_reference_image_and_audio_reference_accept_asset_uri() -> None:
    assert ReferenceImageInput(kind="url", url=ASSET).url == ASSET
    assert AudioReference(kind="url", url=ASSET).url == ASSET
    with pytest.raises(ValidationError):
        ReferenceImageInput(kind="url", url="asset://bad id")


def test_reference_image_accepts_plain_media_source_instance() -> None:
    source = MediaSource(kind="url", url="https://example.com/a.png")
    assert ReferenceImageInput.model_validate(source).url == "https://example.com/a.png"


def test_seedance_inputs_accept_asset_uri_shorthand() -> None:
    image = SeedanceImageInput.model_validate(ASSET)
    assert image.url == ASSET
    assert image.role == "reference_image"
    assert SeedanceVideoInput.model_validate(ASSET).url == ASSET
    assert SeedanceAudioInput.model_validate(ASSET).url == ASSET


@pytest.mark.parametrize("model", [SeedanceImageInput, SeedanceVideoInput, SeedanceAudioInput])
@pytest.mark.parametrize(
    "reference",
    [
        None,
        "",
        [],
        {},
        {"asset_id": "asset-id"},
        {"url": None},
        {"url": {"asset_id": "asset-id"}},
        {"url": "asset://"},
        {"url": "asset://bad id"},
        {"url": "asset://asset-id", "kind": "asset"},
    ],
)
def test_native_seedance_references_reject_invalid_shapes(
    model: type[SeedanceImageInput | SeedanceVideoInput | SeedanceAudioInput], reference: object
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(reference)


def test_seedance_content_passes_asset_uri_through() -> None:
    content = SeedanceService.build_content(
        prompt="The character in Image 1 waves",
        images=[SeedanceImageInput.model_validate(ASSET).model_dump()],
        videos=[SeedanceVideoInput.model_validate("asset://asset-video-1").model_dump()],
        audios=[SeedanceAudioInput.model_validate("asset://asset-audio-1").model_dump()],
    )
    urls = [
        (item.image_url or item.video_url or item.audio_url or {}).get("url")
        for item in content
        if item.type != "text"
    ]
    assert urls == [ASSET, "asset://asset-video-1", "asset://asset-audio-1"]


@pytest.mark.parametrize("product", ["Seedream", "Seed Audio"])
@pytest.mark.parametrize(
    "items",
    [
        None,
        [],
        [{"url": "https://example.com/reference"}],
        [{"data": "aGVsbG8=", "mime_type": "image/png"}],
    ],
)
def test_non_seedance_references_preserve_regular_inputs(
    product: Literal["Seedream", "Seed Audio"], items: list[dict[str, Any]] | None
) -> None:
    assert require_url_references(items, product=product) == items


@pytest.mark.parametrize("product", ["Seedream", "Seed Audio"])
@pytest.mark.parametrize("url", [ASSET, "ASSET://asset-1"])
def test_non_seedance_references_reject_assets_with_https_guidance(
    product: Literal["Seedream", "Seed Audio"], url: str
) -> None:
    with pytest.raises(ValueError, match=f"{product} does not accept asset://.*regular HTTPS URL"):
        require_url_references(
            [{"url": "https://example.com/reference"}, {"url": url}],
            product=product,
        )
