"""Native asset references require only the ModelArk data-plane credential."""

from __future__ import annotations

import json

import pytest
import respx
from fastmcp.tools import ToolResult

from ark_mcp.tools.seed_audio_generate import SeedAudioGenerateInput, seed_audio_generate
from ark_mcp.tools.seedance_create_task import SeedanceCreateTaskInput, seedance_create_task
from ark_mcp.tools.seedream_generate_image import SeedreamGenerateInput, seedream_generate_image
from tests.fixtures.fake_context import FakeContext


@respx.mock
async def test_seedance_passes_all_native_assets_without_administration(
    test_env: None, fake_ctx: FakeContext
) -> None:
    route = respx.post("https://ark.test.example.com/api/v3/contents/generations/tasks").respond(
        200, json={"id": "task-assets"}
    )

    result = await seedance_create_task(
        SeedanceCreateTaskInput(
            prompt="Image 1 moves with the video and audio references.",
            images=["asset://asset-image"],
            videos=["asset://asset-video"],
            audios=["asset://asset-audio"],
        ),
        fake_ctx,
    )

    assert not isinstance(result, ToolResult)
    assert [task.task_id for task in result.tasks] == ["task-assets"]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-test-modelark"
    content = json.loads(request.content)["content"]
    assert [part[part["type"]]["url"] for part in content[1:]] == [
        "asset://asset-image",
        "asset://asset-video",
        "asset://asset-audio",
    ]
    assert len(respx.calls) == 1


@respx.mock
async def test_seedance_asset_provider_rejection_is_returned_without_preflight(
    fake_ctx: FakeContext,
) -> None:
    route = respx.post("https://ark.test.example.com/api/v3/contents/generations/tasks").respond(
        400,
        json={"error": {"code": "InvalidParameter", "message": "Reference asset is unavailable"}},
    )

    result = await seedance_create_task(
        SeedanceCreateTaskInput(prompt="Animate Image 1.", images=["asset://asset-unavailable"]),
        fake_ctx,
    )

    assert isinstance(result, ToolResult) and result.is_error
    assert route.call_count == 1
    assert len(respx.calls) == 1


@pytest.mark.parametrize("product", ["image", "audio"])
async def test_other_generation_products_reject_native_assets(
    fake_ctx: FakeContext, product: str
) -> None:
    with pytest.raises(ValueError, match="does not accept asset://"):
        if product == "image":
            await seedream_generate_image(
                SeedreamGenerateInput(
                    prompt="Draw a portrait.",
                    images=[{"kind": "url", "url": "asset://asset-image"}],
                ),
                fake_ctx,
            )
        else:
            await seed_audio_generate(
                SeedAudioGenerateInput(
                    text_prompt="Generate ambient music.",
                    audio_references=[{"kind": "url", "url": "asset://asset-audio"}],
                ),
                fake_ctx,
            )
