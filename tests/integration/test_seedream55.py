from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from io import BytesIO
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError
from PIL import Image

from ark_mcp.config.env import get_settings
from ark_mcp.config.model_capabilities import refresh_capability_registry
from ark_mcp.server import create_server

MODEL = "dola-seedream-5-5-261028"
ARK_BASE = "https://ark.test.example.com/api/v3"


@pytest.fixture
def configured(test_env: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("SEEDREAM_DEFAULT_MODEL")
    get_settings.cache_clear()
    refresh_capability_registry()
    yield
    get_settings.cache_clear()
    refresh_capability_registry()


async def _image_call(client: Client, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(
        "seedream_generate_image", {"input": arguments}, raise_on_error=False
    )
    return {
        "is_error": result.is_error,
        "structured_content": result.structured_content,
        "content": [item.model_dump() for item in result.content],
    }


async def test_seedream55_discovery_reports_default_and_transparency(configured: None) -> None:
    async with Client(create_server(get_settings())) as client:
        result = await client.call_tool("ark_list_models", {"input": {"kind": "image"}})
    assert result.structured_content is not None
    assert len(result.structured_content["models"]) == 1
    model = result.structured_content["models"][0]
    assert model["model_id"] == MODEL
    assert model["is_default"]
    assert model["family"] == "seedream_5_5"
    assert model["tool"] == "seedream_generate_image"
    assert model["image"]["supports_transparent_generation"]
    assert model["image"]["supports_prompt_optimization"]
    assert model["image"]["prompt_optimization_modes"] == ["standard"]
    assert model["image"]["supported_sizes"] == ["1K", "1.5K", "2K"]
    assert model["image"]["custom_size_pixels_range"] == [921600, 8294400]
    assert model["image"]["custom_size_aspect_ratio_range"] == [0.0625, 16]
    assert model["image"]["background_modes"] == ["opaque", "transparent", "auto"]
    assert model["image"]["supports_safety_identifier"]


async def test_seedream55_transparent_dry_run_matches_example(configured: None) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "model": MODEL,
                    "prompt": "Embroidered heart sticker",
                    "size": "2K",
                    "response_format": "url",
                    "output_format": "png",
                    "background": "transparent",
                    "watermark": True,
                    "dry_run": True,
                },
            )
    assert not router.calls
    assert not result["is_error"]
    data = result["structured_content"]
    assert data["dry_run"]
    assert data["preview"]["requests"] == [
        {
            "model": MODEL,
            "prompt": "Embroidered heart sticker",
            "size": "2K",
            "response_format": "url",
            "output_format": "png",
            "background": "transparent",
            "watermark": True,
            "stream": False,
        }
    ]


@pytest.mark.parametrize("size", ["3840x2160", "2160x3840", "2880x2880"])
@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("references", [0, 2])
async def test_seedream55_high_resolution_dry_run(
    configured: None, size: str, variations: int, references: int
) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "A high-resolution landscape",
                    "size": size,
                    "variations": variations,
                    "images": [{"kind": "url", "url": "https://example.com/reference.png"}]
                    * references,
                    "dry_run": True,
                },
            )
    assert not router.calls
    assert not result["is_error"]
    preview = result["structured_content"]["preview"]
    assert len(preview["requests"]) == variations
    assert all(body["size"] == size and body["model"] == MODEL for body in preview["requests"])
    assert preview["estimated_cost_usd"] == round(variations * (0.079 + references * 0.008), 4)
    assert preview["price_source"] == "builtin"


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("edit", [False, True])
async def test_seedream55_uhd_dispatch_and_metadata(
    configured: None, variations: int, edit: bool
) -> None:
    arguments: dict[str, Any] = {
        "prompt": "A high-resolution landscape",
        "size": "3840x2160",
        "variations": variations,
    }
    if edit:
        arguments.update(
            images=[{"kind": "url", "url": "https://example.com/input.png"}],
            bbox={"x1": 0, "y1": 0, "x2": 500, "y2": 500},
        )
    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"url": "https://example.com/output.png", "size": "3840x2160"}]},
            )
        )
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(client, arguments)
    assert not result["is_error"]
    assert route.call_count == variations
    for call in route.calls:
        body = json.loads(call.request.content)
        assert body["model"] == MODEL
        assert body["size"] == "3840x2160"
        if edit:
            assert body["image"] == "https://example.com/input.png"
            assert body["prompt"].startswith("Image 1<bbox>0 0 500 500</bbox>")
    for generation in result["structured_content"]["generations"]:
        assert generation["request_options"]["size"] == "3840x2160"
        assert generation["images"][0]["size"] == "3840x2160"


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize(("size", "references"), [("3840x2160", 0), ("1K", 10)])
async def test_seedream55_budget_uses_output_and_reference_rates(
    configured: None,
    monkeypatch: pytest.MonkeyPatch,
    variations: int,
    size: str,
    references: int,
) -> None:
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.05")
    get_settings.cache_clear()
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "test",
                    "size": size,
                    "variations": variations,
                    "images": [{"kind": "url", "url": "https://example.com/input.png"}]
                    * references,
                },
            )
    assert not router.calls
    if variations == 1:
        assert result["is_error"]
        assert "Daily budget" in str(result["content"])
    else:
        summary = result["structured_content"]["summary"]
        assert summary["failed"] == variations
        assert all("Daily budget" in item["error"]["message"] for item in summary["variations"])


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("persist", [True, False])
async def test_seedream55_direct_keeps_png_metadata_when_format_is_omitted(
    configured: None, variations: int, persist: bool
) -> None:
    buffer = BytesIO()
    with Image.new("RGBA", (960, 960), (255, 0, 0, 0)) as image:
        image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    item = (
        {"b64_json": base64.b64encode(image_bytes).decode()}
        if persist
        else {"url": "https://example.com/output.png"}
    )
    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(
            return_value=httpx.Response(200, json={"created": 1721400000, "data": [item]})
        )
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "Embroidered heart sticker",
                    "size": "2K",
                    "background": "transparent",
                    "persist": persist,
                    "variations": variations,
                },
            )
            assert not result["is_error"]
            data = result["structured_content"]
            assert data["model"] == MODEL
            artifacts = (
                data["artifacts"]
                if variations == 1
                else [item["artifact"] for item in data["summary"]["variations"]]
            )
            assert len(artifacts) == variations
            assert all(artifact["mime_type"] == "image/png" for artifact in artifacts)
            if persist:
                for artifact in artifacts:
                    resource = await client.read_resource(artifact["uri"])
                    assert base64.b64decode(resource[0].blob) == image_bytes
    assert route.call_count == variations
    for call in route.calls:
        body = json.loads(call.request.content)
        assert body["model"] == MODEL
        assert body["output_format"] == "png"
        assert body["background"] == "transparent"
        assert "image" not in body
        assert "optimize_prompt_options" not in body


async def test_seedream55_invalid_transparent_jpeg_never_calls_provider(configured: None) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {"prompt": "test", "background": "transparent", "output_format": "jpeg"},
            )
    assert not router.calls
    assert result["is_error"]
    assert result["structured_content"] is None
    assert "background='transparent' requires output_format" in result["content"][0]["text"]


async def test_seedream55_provider_access_error_is_not_retried(configured: None) -> None:
    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(
            return_value=httpx.Response(
                403,
                json={"error": {"code": "AccessDenied", "message": "Early access required"}},
                headers={"X-Request-Id": "req-seedream55-denied"},
            )
        )
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(client, {"prompt": "Embroidered heart sticker"})
    assert route.call_count == 1
    assert result["is_error"]
    assert "req-seedream55-denied" in str(result["content"])


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("background", ["opaque", "transparent"])
async def test_seedream55_preserves_actual_metadata_and_usage(
    configured: None, variations: int, background: str
) -> None:
    usage = {
        "input_images": 1,
        "generated_images": 1,
        "output_tokens": 16428,
        "total_tokens": 16428,
    }
    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "url": "https://example.com/output.png",
                            "size": "1776x2368",
                            "output_format": "png",
                            "background": background,
                        }
                    ],
                    "safety_identifier": "sha256-test-user",
                    "usage": usage,
                },
            )
        )
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "Extract the subject",
                    "images": [{"kind": "url", "url": "https://example.com/input.jpg"}],
                    "size": "2830x1634",
                    "background": "auto",
                    "prompt_optimization": "standard",
                    "safety_identifier": "sha256-test-user",
                    "persist": False,
                    "variations": variations,
                },
            )
    assert not result["is_error"]
    data = result["structured_content"]
    artifacts = (
        data["artifacts"]
        if variations == 1
        else [variation["artifact"] for variation in data["summary"]["variations"]]
    )
    assert len(data["generations"]) == variations
    for index, metadata in enumerate(data["generations"]):
        assert metadata["variation_index"] == index
        assert metadata["safety_identifier"] == "sha256-test-user"
        assert metadata["images"] == [
            {
                "index": 0,
                "artifact_id": artifacts[index]["id"],
                "size": "1776x2368",
                "output_format": "png",
                "background": background,
                "inspection": None,
            }
        ]
        assert all(metadata["usage"][key] == value for key, value in usage.items())
    if variations == 1:
        assert all(data["usage"][key] == value for key, value in usage.items())
    for call in route.calls:
        body = json.loads(call.request.content)
        assert body["size"] == "2830x1634"
        assert body["background"] == "auto"
        assert body["optimize_prompt_options"] == {"mode": "standard"}
        assert body["safety_identifier"] == "sha256-test-user"
        assert body["image"] == "https://example.com/input.jpg"


async def test_seedream55_auto_jpeg_returns_opaque_metadata(configured: None) -> None:
    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "url": "https://example.com/output.jpeg",
                            "output_format": "jpeg",
                            "background": "opaque",
                        }
                    ]
                },
            )
        )
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "test",
                    "background": "auto",
                    "output_format": "jpeg",
                    "persist": False,
                },
            )
    assert not result["is_error"]
    data = result["structured_content"]
    assert data["artifacts"][0]["mime_type"] == "image/jpeg"
    assert data["generations"][0]["images"][0]["background"] == "opaque"
    assert data["generations"][0]["images"][0]["size"] is None
    assert data["generations"][0]["safety_identifier"] is None
    assert json.loads(route.calls[0].request.content)["output_format"] == "jpeg"


async def test_seedream55_dry_run_redacts_safety_identifier(configured: None) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "prompt": "test",
                    "safety_identifier": "sha256-test-user",
                    "dry_run": True,
                },
            )
    assert not router.calls
    assert not result["is_error"]
    assert "sha256-test-user" not in json.dumps(result)
    data = result["structured_content"]
    assert data["preview"]["requests"][0]["safety_identifier"] == "[REDACTED]"
    assert data["generations"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"size": "auto"},
        {"size": "4K"},
        {"size": "3841x2160"},
        {"size": "2881x2880"},
        {"size": "4096x2160"},
    ],
)
async def test_invalid_api_controls_never_reach_provider(
    configured: None, arguments: dict[str, Any]
) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(client, {"prompt": "test", **arguments})
    assert not router.calls
    assert result["is_error"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"layer_decomposition": True},
        {"layer_decomposition_options": {"max_images": 10}},
        {"safety_identifier": "a" * 65},
        {"prompt_optimization": "fast"},
        {"max_images": 2},
    ],
)
async def test_unsupported_input_is_rejected_before_provider_dispatch(
    configured: None, arguments: dict[str, Any]
) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            with pytest.raises(ToolError, match=next(iter(arguments))):
                await client.call_tool(
                    "seedream_generate_image", {"input": {"prompt": "test", **arguments}}
                )
    assert not router.calls


@pytest.mark.parametrize(
    "model",
    [
        "dola-seedream-5-0-pro-260628",
        "seedream-5-0-260128",
        "seedream-5-0-lite-260128",
        "seedream-4-5-251128",
        "seedream-4-0-250828",
        "seedream-3-0-t2i-250415",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
async def test_retired_models_never_reach_provider(
    configured: None, model: str, dry_run: bool
) -> None:
    with respx.mock(assert_all_called=False) as router:
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client, {"prompt": "test", "model": model, "dry_run": dry_run}
            )
    assert not router.calls
    assert result["is_error"]
    assert "not configured" in str(result["content"])


async def test_seedream55_metadata_survives_partial_variation_failure(configured: None) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["prompt"] == "denied":
            return httpx.Response(
                403, json={"error": {"code": "AccessDenied", "message": "Denied"}}
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "url": "https://example.com/output.png",
                        "background": "transparent",
                    }
                ]
            },
        )

    with respx.mock:
        route = respx.post(f"{ARK_BASE}/images/generations").mock(side_effect=respond)
        async with Client(create_server(get_settings())) as client:
            result = await _image_call(
                client,
                {
                    "variations": 2,
                    "variation_prompts": ["denied", "success"],
                    "persist": False,
                },
            )
    assert route.call_count == 2
    assert not result["is_error"]
    data = result["structured_content"]
    assert data["summary"]["failed"] == 1
    assert data["summary"]["succeeded"] == 1
    assert [metadata["variation_index"] for metadata in data["generations"]] == [1]
    image = data["generations"][0]["images"][0]
    assert image["artifact_id"] == data["summary"]["variations"][1]["artifact"]["id"]
    assert image["background"] == "transparent"
