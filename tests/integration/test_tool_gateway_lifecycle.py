"""Request gateway wiring and cleanup for the hosted BYOK tools lane."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fastmcp.tools import ToolResult

from ark_mcp.config.env import get_settings
from ark_mcp.config.model_capabilities import refresh_capability_registry
from ark_mcp.providers.base import BaseHttpGateway
from tests.fixtures.fake_context import FakeContext

CASES = [
    ("seed_audio_generate", "SeedAudioGenerateInput", {"text_prompt": "tone"}, "seed-speech", 1),
    (
        "seed_audio_generate",
        "SeedAudioGenerateInput",
        {"text_prompt": "tone", "variations": 2},
        "seed-speech",
        1,
    ),
    ("seedream_generate_image", "SeedreamGenerateInput", {"prompt": "square"}, "modelark", 1),
    (
        "seedream_generate_image",
        "SeedreamGenerateInput",
        {"prompt": "square", "variations": 2},
        "modelark",
        1,
    ),
    ("seedance_create_task", "SeedanceCreateTaskInput", {"prompt": "scene"}, "modelark", 1),
    (
        "seedance_create_task",
        "SeedanceCreateTaskInput",
        {"prompt": "scene", "variations": 2},
        "modelark",
        1,
    ),
    (
        "seedance_create_task",
        "SeedanceCreateTaskInput",
        {"draft_task_id": "draft-test"},
        "modelark",
        2,
    ),
    ("gen_task_get", "GenTaskGetInput", {"task_ids": ["task-test"]}, "modelark", 1),
    ("gen_task_list", "GenTaskListInput", {}, "modelark", 1),
    (
        "gen_task_cancel_or_delete",
        "GenTaskCancelOrDeleteInput",
        {"task_id": "task-test", "mode": "delete", "expected_status": "succeeded"},
        "modelark",
        2,
    ),
    (
        "omnihuman_create_task",
        "OmniHumanCreateTaskInput",
        {"image": "https://example.com/image.png", "audio": "https://example.com/audio.wav"},
        "vision-cv",
        1,
    ),
    ("omnihuman_get_task", "OmniHumanGetTaskInput", {"task_id": "task-test"}, "vision-cv", 1),
    ("omnihuman_cancel_task", "OmniHumanCancelTaskInput", {"task_id": "task-test"}, "vision-cv", 1),
]


def _response(request: httpx.Request, count: int) -> httpx.Response:
    path = request.url.path
    task = {
        "id": "draft-test" if path.endswith("draft-test") else "task-test",
        "model": "dreamina-seedance-2-5-260628",
        "status": "succeeded",
        "draft": True,
        "created_at": int(datetime.now(UTC).timestamp()),
        "content": {"video_url": "https://example.com/video.mp4"},
    }
    if path.endswith("/tts/create"):
        body = {"code": 0, "url": "https://example.com/audio.wav"}
    elif path.endswith("/images/generations"):
        body = {"data": [{"url": "https://example.com/image.png"}]}
    elif "/contents/generations/tasks" in path:
        if request.method == "POST":
            body = {"id": f"created-{count}"}
        elif path.endswith("/tasks"):
            body = {"data": [task], "has_more": False}
        else:
            body = task
    else:
        body = {
            "code": 10000,
            "data": {
                "task_id": "created-test",
                "status": "done",
                "video_url": "https://example.com/video.mp4",
            },
        }
    return httpx.Response(200, json=body, headers={"X-Request-Id": "synthetic-request"})


@pytest.mark.parametrize(("tool", "input_model", "arguments", "provider", "gateway_count"), CASES)
@pytest.mark.parametrize("outcome", ["success", "rejected", "cancelled"])
async def test_each_tool_uses_request_factory_and_closes_its_gateways(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    input_model: str,
    arguments: dict[str, Any],
    provider: str,
    gateway_count: int,
    outcome: str,
) -> None:
    module = importlib.import_module(f"ark_mcp.tools.{tool}")
    runtime = fake_ctx.lifespan_context["runtime"]
    runtime.settings = runtime.settings.model_copy(
        update={
            "modelark_api_key": None,
            "seed_speech_api_key": None,
            "cv_api_key": None,
            "omnihuman_enabled": True,
        }
    )
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "")
    monkeypatch.setenv("BYTEPLUS_CV_API_KEY", "")
    monkeypatch.setenv("SEEDANCE_DEFAULT_MODEL", "dreamina-seedance-2-5-260628")
    get_settings.cache_clear()
    refresh_capability_registry()
    checked: list[str] = []
    closed: list[BaseHttpGateway] = []
    clients: list[httpx.AsyncClient] = []
    original_close = BaseHttpGateway.close

    def selected_key(ctx: object, selected: str) -> str:
        assert ctx is fake_ctx
        assert selected == provider
        checked.append(selected)
        return "synthetic-request-key"

    async def close(gateway: BaseHttpGateway) -> None:
        closed.append(gateway)
        if gateway._client is not None:
            clients.append(gateway._client)
        await original_close(gateway)

    monkeypatch.setattr(module, "provider_api_key", selected_key)
    monkeypatch.setattr("ark_mcp.providers.factory.provider_api_key", selected_key)
    monkeypatch.setattr(BaseHttpGateway, "close", close)
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        header = "X-Api-Key" if provider == "seed-speech" else "Authorization"
        expected = (
            "synthetic-request-key" if provider == "seed-speech" else "Bearer synthetic-request-key"
        )
        assert request.headers[header] == expected
        if outcome == "cancelled":
            raise asyncio.CancelledError
        if outcome == "rejected":
            return httpx.Response(
                400, json={"error": {"code": "InvalidParameter", "message": "rejected"}}
            )
        return _response(request, len(calls))

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=respond)
        call = getattr(module, tool)(getattr(module, input_model)(**arguments), fake_ctx)
        if outcome == "cancelled" and arguments.get("variations", 1) == 1:
            with pytest.raises(asyncio.CancelledError):
                await call
        else:
            result = await call
            if outcome == "success":
                assert not isinstance(result, ToolResult), result
            elif arguments.get("variations", 1) == 1:
                assert isinstance(result, ToolResult) and result.is_error
    assert calls
    assert len(checked) == 1 + len(closed)
    expected_gateways = gateway_count if outcome == "success" else 1
    assert len(closed) == expected_gateways
    assert all(client.is_closed for client in clients)
