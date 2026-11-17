import asyncio
import sys
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server import Context
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _smoke_context import SmokeClient


class Request(BaseModel):
    persist_output: bool = False


class Result(BaseModel):
    task_id: str


@pytest.fixture
def image_payload():
    return {
        "prompt": "A serene mountain landscape at sunset, digital art",
        "images": None,
        "point": None,
        "bbox": None,
        "model": None,
        "size": "1024x1024",
        "seed": None,
        "max_images": None,
        "output_format": None,
        "response_format": "url",
        "watermark": None,
        "prompt_optimization": None,
        "background": None,
        "safety_identifier": None,
        "variations": 1,
        "variation_prompts": None,
        "persist": True,
        "dry_run": False,
        "output_path": None,
        "overwrite": False,
    }


@pytest.mark.parametrize(
    ("timeouts", "expected"),
    [
        ({}, 660.0),
        ({"MCP_TOOL_TIMEOUT_SECONDS": 900, "BYTEPLUS_REQUEST_TIMEOUT_MS": 120000}, 960.0),
        ({"MCP_TOOL_TIMEOUT_SECONDS": 120, "BYTEPLUS_REQUEST_TIMEOUT_MS": 900125}, 960.125),
        ({"MCP_TOOL_TIMEOUT_SECONDS": 0.5, "BYTEPLUS_REQUEST_TIMEOUT_MS": 500}, 60.5),
        ({"MCP_TOOL_TIMEOUT_SECONDS": 3600, "BYTEPLUS_REQUEST_TIMEOUT_MS": 600000}, 3660.0),
    ],
)
async def test_smoke_session_timeout_covers_tool_and_provider_deadlines(
    tmp_path, monkeypatch, timeouts, expected
):
    from unittest.mock import Mock

    from _smoke_context import smoke_session

    from ark_mcp.config.env import Settings

    client_factory = Mock(wraps=Client)
    monkeypatch.setattr("fastmcp.Client", client_factory)
    settings = Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path), **timeouts)
    async with smoke_session(settings) as (smoke, runtime):
        assert runtime.settings is settings
        assert Path(runtime.settings.artifact_dir) == tmp_path
        assert "ark_list_models" in {tool.name for tool in await smoke.client.list_tools()}
    client_factory.assert_called_once()
    assert client_factory.call_args.kwargs == {"timeout": expected}


@pytest.mark.parametrize("variation", [False, True])
@pytest.mark.parametrize("product", ["image", "audio"])
async def test_generation_workflows_preserve_serialized_payloads(image_payload, variation, product):
    from unittest.mock import AsyncMock

    import live_smoke_test as single
    import live_smoke_test_variations as multiple

    client = AsyncMock()
    client.call_tool.side_effect = RuntimeError("stopped before provider dispatch")
    smoke = SmokeClient(client)
    store = AsyncMock()
    module = multiple if variation else single
    workflow = getattr(module, f"test_{product}_{'variations' if variation else 'generation'}")

    with pytest.raises(RuntimeError, match="stopped before provider dispatch"):
        await workflow(smoke, store)

    if product == "image":
        expected = image_payload
        if variation:
            expected = {
                **expected,
                "prompt": "A beautiful mountain landscape, digital art",
                "variations": 3,
                "seed": 42,
            }
        tool_name = "seedream_generate_image"
    else:
        expected = {
            "text_prompt": (
                "Hello, this is a parallel variation test of the Seed Audio MCP tool."
                if variation
                else (
                    "Welcome to the Ark Seed Multimodal MCP Server. "
                    "This is a live smoke test of the Seed Audio generation tool. "
                    "The generated audio is persisted as a durable artifact."
                )
            ),
            "audio_references": [],
            "image_reference": None,
            "output": None,
            "watermark": None,
            "variations": 3 if variation else 1,
            "variation_prompts": None,
            "persist": True,
            "output_path": None,
            "overwrite": False,
        }
        tool_name = "seed_audio_generate"
    client.call_tool.assert_awaited_once_with(tool_name, {"input": expected})
    store.get.assert_not_awaited()


@pytest.mark.parametrize("error_type", [TimeoutError, RuntimeError, asyncio.CancelledError])
async def test_smoke_client_propagates_failures_without_retry(error_type):
    from unittest.mock import AsyncMock

    failure = error_type("submission interrupted")
    client = AsyncMock()
    client.call_tool.side_effect = failure
    smoke = SmokeClient(client)
    with pytest.raises(error_type) as raised:
        await smoke.call("submit", Request(), Result)
    assert raised.value is failure
    client.call_tool.assert_awaited_once_with("submit", {"input": {"persist_output": False}})


@pytest.mark.parametrize("content", [None, {}, {"task_id": None}])
async def test_smoke_client_rejects_invalid_output_without_retry(content):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.call_tool.return_value = SimpleNamespace(structured_content=content)
    smoke = SmokeClient(client)
    with pytest.raises(ValidationError):
        await smoke.call("submit", Request(), Result)
    client.call_tool.assert_awaited_once_with("submit", {"input": {"persist_output": False}})


@pytest.mark.asyncio
async def test_smoke_client_calls_directly_and_preserves_provider_ids(tmp_path):
    server = FastMCP("smoke-test")
    calls = []

    @server.tool
    async def submit(input: Request, ctx: Context) -> Result:
        assert ctx.task_id is None
        calls.append("submit")
        return Result(task_id="provider-123")

    @server.tool
    async def status(input: Request) -> Result:
        raise ValueError("poll interrupted")

    async with Client(server) as client:
        smoke = SmokeClient(client)
        result = await smoke.call("submit", Request(), Result)
        smoke.save_provider_ids(tmp_path, [result.task_id])
        with pytest.raises(Exception, match="poll interrupted"):
            await smoke.call("status", Request(), Result)
    assert calls == ["submit"]
    assert "provider-123" in (tmp_path / "smoke_provider_tasks.jsonl").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("variation", [False, True])
@pytest.mark.parametrize("poll_failure", [False, True])
async def test_video_workflows_persist_after_status_and_never_resubmit(
    tmp_path, monkeypatch, image_payload, variation, poll_failure
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import live_smoke_test as single
    import live_smoke_test_variations as multiple

    module = multiple if variation else single
    monkeypatch.setattr(module, "ARTIFACTS_DIR", tmp_path)
    artifact = SimpleNamespace(
        id="video", uri="seed-media://video", media_type="video", mime_type="video/mp4", bytes=3
    )
    store = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(data=b"abc", mime_type="image/png"))
    )
    runtime = SimpleNamespace(artifact_store=store)
    calls = []
    smoke = SmokeClient(None)

    async def call(name, params, output_type):
        calls.append((name, getattr(params, "persist_output", None)))
        if name == "seedream_generate_image":
            assert params.model_dump(mode="json") == {
                **image_payload,
                "prompt": "A fluffy orange cat sitting on a garden path, photorealistic",
                "response_format": "b64_json",
            }
            return SimpleNamespace(artifacts=[artifact])
        if name == "seedance_create_task":
            assert params.model_dump(mode="json") == {
                "idempotency_key": None,
                "prompt": (
                    None
                    if variation
                    else "The cat walks forward through the garden, gentle movement, warm sunlight"
                ),
                "images": [
                    {
                        "kind": "base64",
                        "url": None,
                        "data": "YWJj",
                        "mime_type": "image/png",
                        "role": "reference_image",
                    }
                ],
                "videos": None,
                "audios": None,
                "model": None,
                "resolution": "480p",
                "ratio": None,
                "duration": 5,
                "omni_reference_task_type": None,
                "output_format": None,
                "generate_audio": None,
                "watermark": False,
                "return_last_frame": None,
                "execution_expires_after": None,
                "priority": None,
                "safety_identifier": None,
                "draft": None,
                "draft_task_id": None,
                "variations": 2 if variation else 1,
                "variation_prompts": (
                    [
                        "A cat walks forward slowly through a garden",
                        "A cat looks around curiously, then jumps playfully",
                    ]
                    if variation
                    else None
                ),
                "dry_run": False,
            }
            return SimpleNamespace(
                tasks=[SimpleNamespace(task_id="provider-123", index=0, error=None)],
                submitted=1,
                failed=0,
                recommended_poll_after_ms=1,
            )
        assert "provider-123" in (tmp_path / "smoke_provider_tasks.jsonl").read_text()
        if name == "gen_task_list":
            assert params.model_dump(mode="json") == {
                "task_ids": ["provider-123"],
                "page_size": 20,
                "cursor": None,
                "status": None,
                "model": None,
            }
            return SimpleNamespace(tasks=[SimpleNamespace(task_id="provider-123")])
        assert params.model_dump(mode="json") == {
            "task_ids": ["provider-123"],
            "persist_output": params.persist_output,
            "output_dir": None,
            "overwrite": False,
        }
        if poll_failure:
            raise RuntimeError("poll interrupted")
        output = SimpleNamespace(role="video", artifact=artifact if params.persist_output else None)
        task = SimpleNamespace(
            status="succeeded",
            outputs=[output],
            error=None,
            model="test",
            created_at=None,
            updated_at=None,
        )
        return SimpleNamespace(tasks=[task])

    monkeypatch.setattr(smoke, "call", call)
    workflow = (
        multiple.test_seedance_variations(smoke, runtime, artifact)
        if variation
        else single.test_video_generation_with_image(smoke, runtime)
    )
    if poll_failure:
        with pytest.raises(RuntimeError, match="poll interrupted"):
            await workflow
    else:
        result = await workflow
        assert result == (True if variation else {"video": "video"})
        assert [entry[1] for entry in calls if entry[0] == "gen_task_get"] == [
            False,
            True,
        ]
        assert list(tmp_path.glob("*.mp4"))
    assert sum(name == "seedance_create_task" for name, _ in calls) == 1


@pytest.mark.asyncio
async def test_smoke_session_persists_video_through_real_server(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from _smoke_context import smoke_session

    import ark_mcp.runtime as runtime_module
    from ark_mcp.config.env import Settings, get_settings
    from ark_mcp.config.model_capabilities import refresh_capability_registry
    from ark_mcp.providers.modelark.generation_tasks import GenerationTaskService
    from ark_mcp.providers.modelark.schemas import (
        GenerationTaskListResponse,
        GenerationTaskResponse,
    )
    from ark_mcp.security.safe_downloader import DownloadedMedia, SafeDownloader
    from ark_mcp.tools.gen_task_get import GenTaskGetInput, GenTaskGetOutput

    get_settings.cache_clear()
    refresh_capability_registry()
    create_runtime = AsyncMock(wraps=runtime_module.create_runtime_services)
    monkeypatch.setattr(runtime_module, "create_runtime_services", create_runtime)

    settings = Settings(
        _env_file=None, ARTIFACT_DIR=str(tmp_path), BYTEPLUS_MODELARK_API_KEY="test-key"
    )
    from fastmcp.server.dependencies import get_context

    task_contexts = []

    async def list_tasks(*args, **kwargs):
        task_contexts.append(get_context().task_id)
        task = GenerationTaskResponse(
            id="provider-123",
            model="dreamina-seedance-2-5-260628",
            status="succeeded",
            created_at=1721400000,
            updated_at=1721400000,
            content={"video_url": "https://example.com/video.mp4"},
        )
        return GenerationTaskListResponse(data=[task]), None

    monkeypatch.setattr(GenerationTaskService, "list_tasks", list_tasks)
    download = AsyncMock(
        return_value=DownloadedMedia(
            body=b"video", content_type="video/mp4", final_url="https://example.com/video.mp4"
        )
    )
    monkeypatch.setattr(SafeDownloader, "download", download)
    async with smoke_session(settings) as (smoke, runtime):
        status = await smoke.call(
            "gen_task_get",
            GenTaskGetInput(task_ids=["provider-123"]),
            GenTaskGetOutput,
        )
        assert status.tasks[0].status == "succeeded"
        assert status.tasks[0].outputs[0].artifact is None
        result = await smoke.call(
            "gen_task_get",
            GenTaskGetInput(task_ids=["provider-123"], persist_output=True),
            GenTaskGetOutput,
        )
        video = result.tasks[0].outputs[0].artifact
        assert video is not None
        assert (await runtime.artifact_store.get(video.id)).data == b"video"
    download.assert_awaited_once()
    assert task_contexts == [None, None]
    create_runtime.assert_awaited_once()


async def test_audio_variation_smoke_explicitly_persists_and_exports_every_result(
    tmp_path, monkeypatch
):
    import base64

    import live_smoke_test_variations as multiple
    from _smoke_context import smoke_session
    from fastmcp.server.dependencies import get_context

    from ark_mcp.config.env import Settings
    from ark_mcp.providers.seed_speech.schemas import SeedAudioProviderResponse
    from ark_mcp.providers.seed_speech.seed_audio import SeedAudioService

    calls = []

    async def generate(self, request, *, request_id=None):
        assert get_context().task_id is None
        calls.append(request)
        return SeedAudioProviderResponse(
            code=0,
            message="success",
            audio=base64.b64encode(b"variation-audio").decode(),
            duration=1.0,
            original_duration=1.0,
        ), "synthetic-audio-log"

    monkeypatch.setattr(multiple, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(SeedAudioService, "generate", generate)
    settings = Settings(
        _env_file=None,
        BYTEPLUS_SEED_SPEECH_API_KEY="test-speech",  # pragma: allowlist secret
        ARTIFACT_DIR=str(tmp_path / "store"),
    )
    async with smoke_session(settings) as (smoke, runtime):
        assert await multiple.test_audio_variations(smoke, runtime.artifact_store)
    assert len(calls) == 3
    assert all(
        request.to_api_dict()
        == {
            "model": "seed-audio-1.0",
            "text_prompt": "Hello, this is a parallel variation test of the Seed Audio MCP tool.",
        }
        for request in calls
    )
    for index in range(3):
        assert (tmp_path / f"variation_audio_{index}.wav").read_bytes() == b"variation-audio"
