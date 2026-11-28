from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from ark_mcp.config.env import Settings, get_settings
from ark_mcp.config.model_capabilities import (
    CapabilityRegistry,
    refresh_capability_registry,
)
from ark_mcp.observability.logger import info as log_info
from ark_mcp.providers.modelark.schemas import SeedreamProviderResponse
from ark_mcp.providers.modelark.seedream import SeedreamService
from ark_mcp.tools._capability_checks import check_image_request
from ark_mcp.tools._seedream_shared import build_seedream_request
from ark_mcp.tools.seedream_generate_image import SeedreamGenerateInput

MODEL = "dola-seedream-5-5-261028"
PRO_MODEL = "dola-seedream-5-0-pro-260628"


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[CapabilityRegistry]:
    monkeypatch.setenv("SEEDREAM_DEFAULT_MODEL", MODEL)
    monkeypatch.setenv(
        "SEEDREAM_MODEL_BINDINGS",
        f'[{{"model_id":"{MODEL}","family":"seedream_5_5"}}]',
    )
    get_settings.cache_clear()
    yield refresh_capability_registry()
    get_settings.cache_clear()
    refresh_capability_registry()


def test_seedream55_is_default_without_configuration() -> None:
    settings = Settings(_env_file=None)
    assert settings.seedream_default_model == MODEL
    assert [(b.model_id, b.family.value) for b in settings.seedream_model_bindings] == [
        (MODEL, "seedream_5_5")
    ]


@pytest.mark.parametrize(
    "model",
    [
        PRO_MODEL,
        "seedream-5-0-260128",
        "seedream-5-0-lite-260128",
        "seedream-4-5-251128",
        "seedream-4-0-250828",
        "seedream-3-0-t2i-250415",
    ],
)
@pytest.mark.parametrize("binding", ["implicit", "family", "explicit"])
def test_retired_seedream_defaults_are_rejected(model: str, binding: str) -> None:
    options = {}
    if binding == "family":
        options["SEEDREAM_MODEL_FAMILY"] = "seedream_5_5"
    elif binding == "explicit":
        options["SEEDREAM_MODEL_BINDINGS"] = [{"model_id": model, "family": "seedream_5_5"}]
    with pytest.raises(ValidationError, match=r"Only Seedream 5\.5"):
        Settings(_env_file=None, SEEDREAM_DEFAULT_MODEL=model, **options)


@pytest.mark.parametrize("family", ["pro", "lite", "4x"])
@pytest.mark.parametrize("explicit_bindings", [False, True])
def test_retired_seedream_families_are_rejected(family: str, explicit_bindings: bool) -> None:
    options = (
        {"SEEDREAM_MODEL_BINDINGS": [{"model_id": MODEL, "family": family}]}
        if explicit_bindings
        else {"SEEDREAM_MODEL_FAMILY": family}
    )
    with pytest.raises(ValidationError, match="seedream_5_5"):
        Settings(_env_file=None, **options)


def test_seedream55_custom_endpoint_binding() -> None:
    settings = Settings(
        _env_file=None,
        SEEDREAM_DEFAULT_MODEL="ep-image-test",
        SEEDREAM_MODEL_FAMILY="seedream_5_5",
    )
    assert settings.seedream_model_bindings[0].model_id == "ep-image-test"
    assert settings.seedream_model_bindings[0].family.value == "seedream_5_5"


def test_explicit_bindings_still_require_the_default_to_be_present() -> None:
    with pytest.raises(ValueError, match="missing from its bindings"):
        Settings(
            _env_file=None,
            SEEDREAM_MODEL_BINDINGS=[{"model_id": "ep-image-test", "family": "seedream_5_5"}],
        )


def test_seedream55_is_the_only_image_family(registry: CapabilityRegistry) -> None:
    caps = registry.resolve_image_model(None)
    assert caps.model_id == MODEL
    assert caps.family.value == "seedream_5_5"
    assert caps.max_references == 10
    assert caps.supported_output_formats == ("png", "jpeg")
    assert caps.supported_sizes == ("1K", "1.5K", "2K")
    assert caps.custom_size_pixels_range == (921600, 8294400)
    assert not caps.supports_batch
    assert not caps.supports_streaming
    assert caps.supports_transparent_background
    assert caps.supports_transparent_generation
    assert caps.resolve_prompt_optimization(None) is None
    assert registry.list_image_models() == [MODEL]
    with pytest.raises(ValueError, match="not configured"):
        registry.resolve_image_model(PRO_MODEL)


@pytest.mark.parametrize("count", [0, 1, 10])
def test_seedream55_transparency_accepts_optional_non_png_references(
    registry: CapabilityRegistry, count: int
) -> None:
    request = SeedreamGenerateInput(
        prompt="Embroidered heart sticker",
        background="transparent",
        images=[{"kind": "base64", "data": "YWJj", "mime_type": "image/jpeg"}] * count,
    )
    assert check_image_request(request, registry.resolve_image_model(MODEL)) == []


@pytest.mark.parametrize(
    ("arguments", "violation"),
    [
        ({"output_format": "jpeg", "background": "transparent"}, "requires output_format"),
        (
            {"images": [{"kind": "url", "url": "https://example.com/image.png"}] * 11},
            "maximum of 10",
        ),
    ],
)
def test_seedream55_rejects_invalid_combinations(
    registry: CapabilityRegistry, arguments: dict[str, object], violation: str
) -> None:
    request = SeedreamGenerateInput(prompt="test", **arguments)
    assert any(
        violation in item
        for item in check_image_request(request, registry.resolve_image_model(MODEL))
    )


@pytest.mark.parametrize("arguments", [{"max_images": 2}, {"prompt_optimization": "fast"}])
def test_legacy_controls_are_rejected_by_input_schema(arguments: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SeedreamGenerateInput(prompt="test", **arguments)


def test_schema_advertises_only_supported_controls() -> None:
    properties = SeedreamGenerateInput.model_json_schema()["properties"]
    assert properties["max_images"]["anyOf"][0]["maximum"] == 1
    assert properties["prompt_optimization"]["anyOf"][0]["const"] == "standard"


@pytest.mark.parametrize("output_format", [None, "png", "jpeg"])
def test_seedream55_request_uses_png_default_and_preserves_explicit_format(
    registry: CapabilityRegistry, output_format: str | None
) -> None:
    request = SeedreamGenerateInput(
        prompt="Embroidered heart sticker", output_format=output_format, size="2K"
    )
    body = build_seedream_request(
        request, registry.resolve_image_model(MODEL), None, prompt=request.prompt, seed=None
    ).model_dump(exclude_none=True)
    assert body == {
        "model": MODEL,
        "prompt": "Embroidered heart sticker",
        "size": "2K",
        "output_format": output_format or "png",
        "stream": False,
    }


def test_seedream55_request_matches_supplied_transparent_example(
    registry: CapabilityRegistry,
) -> None:
    request = SeedreamGenerateInput(
        prompt="Embroidered heart sticker",
        size="2K",
        output_format="png",
        response_format="url",
        background="transparent",
        watermark=True,
    )
    body = build_seedream_request(
        request, registry.resolve_image_model(MODEL), None, prompt=request.prompt, seed=None
    ).model_dump(exclude_none=True)
    assert body == {
        "model": MODEL,
        "prompt": "Embroidered heart sticker",
        "size": "2K",
        "response_format": "url",
        "output_format": "png",
        "background": "transparent",
        "watermark": True,
        "stream": False,
    }


@pytest.mark.parametrize(
    "size",
    [
        None,
        "1K",
        "1.5K",
        "2K",
        "1280x720",
        "2048x2048",
        "2140x2160",
        "2300x2000",
        "4880x305",
        "305x4880",
        "2830x1634",
        "2300x2011",
        "2091x2212",
        "3840x2160",
        "2160x3840",
        "2880x2880",
        "11520x720",
        "720x11520",
    ],
)
def test_seedream55_accepts_documented_sizes(
    registry: CapabilityRegistry, size: str | None
) -> None:
    request = SeedreamGenerateInput(prompt="test", size=size)
    assert check_image_request(request, registry.resolve_image_model(MODEL)) == []
    assert registry.validate_image_size(MODEL, size) == size


@pytest.mark.parametrize(
    "size",
    [
        "",
        "auto",
        "3K",
        "4K",
        "4k",
        "3841x2160",
        "2160x3841",
        "2881x2880",
        "4096x2160",
        "4096x4096",
        "1279x720",
        "4881x305",
        "305x4881",
        "0x2048",
        "-1000x2048",
        "2048.0x2048",
        "2048X2048",
        "2048x2048\n",
        "9" * 5000 + "x1000",
    ],
)
def test_seedream55_rejects_invalid_sizes_before_request_building(
    registry: CapabilityRegistry, size: str
) -> None:
    request = SeedreamGenerateInput(prompt="test", size=size)
    assert any(
        "size" in error
        for error in check_image_request(request, registry.resolve_image_model(MODEL))
    )
    with pytest.raises(ValueError, match=r"[Ss]ize"):
        registry.validate_image_size(MODEL, size)


def test_seedream55_custom_endpoint_shares_high_resolution_limits(
    registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEEDREAM_DEFAULT_MODEL", "ep-image-test")
    monkeypatch.setenv(
        "SEEDREAM_MODEL_BINDINGS", '[{"model_id":"ep-image-test","family":"seedream_5_5"}]'
    )
    get_settings.cache_clear()
    registry = refresh_capability_registry()
    caps = registry.resolve_image_model(None)
    assert caps.custom_size_pixels_range == (921600, 8294400)
    assert registry.validate_image_size(None, "3840x2160") == "3840x2160"
    with pytest.raises(ValueError, match="pixel count"):
        registry.validate_image_size(None, "3841x2160")


@pytest.mark.parametrize("size", ["3840x2160", "2160x3840", "2880x2880"])
def test_seedream55_high_resolution_request_preserves_dimensions(
    registry: CapabilityRegistry, size: str
) -> None:
    request = SeedreamGenerateInput(prompt="High-resolution landscape", size=size)
    body = build_seedream_request(
        request, registry.resolve_image_model(MODEL), None, prompt=request.prompt, seed=None
    ).model_dump(exclude_none=True)
    assert body["model"] == MODEL
    assert body["size"] == size
    assert body["output_format"] == "png"


def test_seedream55_size_schema_explains_uhd_dimensions() -> None:
    description = SeedreamGenerateInput.model_json_schema()["properties"]["size"]["description"]
    assert "8294400" in description
    assert "3840x2160" in description


@pytest.mark.parametrize("output_format", [None, "png", "jpeg"])
def test_auto_background_is_supported(
    registry: CapabilityRegistry, output_format: str | None
) -> None:
    request = SeedreamGenerateInput(prompt="test", background="auto", output_format=output_format)
    assert check_image_request(request, registry.resolve_image_model(MODEL)) == []


def test_55_standard_optimization_does_not_inherit_pro_fast_default(
    registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEEDREAM_PROMPT_OPTIMIZATION_MODE", "fast")
    get_settings.cache_clear()
    registry = refresh_capability_registry()
    caps = registry.resolve_image_model(MODEL)
    request = SeedreamGenerateInput(prompt="test", prompt_optimization="standard")
    assert check_image_request(request, caps) == []
    assert caps.resolve_prompt_optimization(None) is None
    assert caps.resolve_prompt_optimization("standard") == "standard"
    assert "seedream_prompt_optimization_mode" not in Settings.model_fields
    body = build_seedream_request(request, caps, None, prompt="test", seed=None).model_dump(
        exclude_none=True
    )
    assert body["optimize_prompt_options"] == {"mode": "standard"}


@pytest.mark.parametrize("identifier", ["user-hash", "a" * 64])
def test_safety_identifier_is_forwarded(registry: CapabilityRegistry, identifier: str) -> None:
    request = SeedreamGenerateInput(prompt="test", safety_identifier=identifier)
    assert check_image_request(request, registry.resolve_image_model(MODEL)) == []
    body = build_seedream_request(
        request, registry.resolve_image_model(MODEL), None, prompt="test", seed=None
    ).model_dump(exclude_none=True)
    assert body["safety_identifier"] == identifier


@pytest.mark.parametrize("identifier", ["", "a" * 65, "user\n", "\x00", "\u00e9", "user id"])
def test_safety_identifier_rejects_invalid_input(identifier: str) -> None:
    with pytest.raises(ValidationError, match="safety_identifier"):
        SeedreamGenerateInput(prompt="test", safety_identifier=identifier)


@pytest.mark.parametrize(
    "extra", [{"layer_decomposition": True}, {"layer_decomposition_options": {"max_images": 10}}]
)
def test_layer_decomposition_is_rejected_not_silently_ignored(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        SeedreamGenerateInput(prompt="test", **extra)


def test_seedream_metadata_does_not_infer_absent_provider_values() -> None:
    metadata = SeedreamService.extract_generation_metadata(
        SeedreamProviderResponse(data=[{"url": "https://example.com/output.png"}])
    )
    assert metadata.variation_index == 0
    assert metadata.safety_identifier is None
    assert metadata.usage is None
    assert metadata.images[0].background is None
    assert metadata.images[0].size is None
    assert metadata.images[0].output_format is None


def test_seedream_metadata_rejects_invalid_actual_background() -> None:
    with pytest.raises(ValidationError, match="background"):
        SeedreamProviderResponse(data=[{"background": "auto"}])


def test_safety_identifier_is_redacted_recursively_in_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_info("test", response={"generations": [{"safety_identifier": "sha256-test-user"}]})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sha256-test-user" not in captured.err
    assert "[REDACTED]" in captured.err
