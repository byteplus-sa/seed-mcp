"""Contract tests for the Seedance adapter (video task management).

Tests task creation, content building and error propagation. Task reads are
covered in ``test_generation_tasks_adapter.py``.
"""

from __future__ import annotations

import traceback

import httpx
import pytest
import respx

from ark_mcp.domain.errors import ProviderError
from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.providers.modelark.schemas import (
    SeedanceContentItem,
)
from ark_mcp.providers.modelark.seedance import SeedanceService
from ark_mcp.providers.retry import RetryPolicy, call_with_retry

MODELARK_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"


@pytest.fixture
def service() -> SeedanceService:
    """Create a SeedanceService with a test gateway."""
    gateway = ModelArkGateway(
        api_key="sk-test-key",  # pragma: allowlist secret
        base_url=MODELARK_BASE,
        timeout=10.0,
        connect_timeout=5.0,
    )
    return SeedanceService(gateway=gateway)


class TestSeedanceContentBuilding:
    """Tests for provider content array construction."""

    def test_text_only_content(self) -> None:
        content = SeedanceService.build_content(prompt="a cat playing")
        assert len(content) == 1
        assert content[0].type == "text"
        assert content[0].text == "a cat playing"

    def test_image_with_role(self) -> None:
        content = SeedanceService.build_content(
            prompt="animate this",
            images=[{"url": "https://cdn.example.com/frame.png", "role": "first_frame"}],
        )
        assert len(content) == 2  # text + image
        image_item = content[1]
        assert image_item.type == "image_url"
        assert image_item.role == "first_frame"

    def test_video_reference(self) -> None:
        content = SeedanceService.build_content(
            videos=[{"url": "https://cdn.example.com/ref.mp4"}],
        )
        assert len(content) == 1
        assert content[0].type == "video_url"
        assert content[0].role == "reference_video"

    def test_audio_reference(self) -> None:
        content = SeedanceService.build_content(
            images=[{"url": "https://cdn.example.com/img.png"}],
            audios=[{"url": "https://cdn.example.com/audio.wav"}],
        )
        assert len(content) == 2
        audio_item = content[1]
        assert audio_item.type == "audio_url"
        assert audio_item.role == "reference_audio"

    def test_mixed_content(self) -> None:
        content = SeedanceService.build_content(
            prompt="complex scene",
            images=[
                {"url": "https://cdn.example.com/first.png", "role": "first_frame"},
                {"url": "https://cdn.example.com/ref.png", "role": "reference_image"},
            ],
            videos=[{"url": "https://cdn.example.com/ref.mp4"}],
            audios=[{"url": "https://cdn.example.com/audio.wav"}],
        )
        assert len(content) == 5  # 1 text + 2 images + 1 video + 1 audio

    def test_build_request_passes_omni_reference_task_type(self) -> None:
        content = SeedanceService.build_content(prompt="edit this video")
        request = SeedanceService.build_request(
            model="dreamina-seedance-2-5-260628",
            content=content,
            omni_reference_task_type="edit",
        )
        assert request.omni_reference_task_type == "edit"

    def test_build_request_omni_reference_task_type_defaults_none(self) -> None:
        content = SeedanceService.build_content(prompt="generate a video")
        request = SeedanceService.build_request(
            model="dreamina-seedance-2-0-260128",
            content=content,
        )
        assert request.omni_reference_task_type is None

    def test_build_request_draft_serializes_flag(self) -> None:
        content = SeedanceService.build_content(prompt="a fox in the snow")
        request = SeedanceService.build_request(
            model="dreamina-seedance-2-5-260628",
            content=content,
            resolution="480p",
            draft=True,
        )
        body = request.model_dump(exclude_none=True)
        assert body["draft"] is True
        assert body["resolution"] == "480p"

    def test_build_request_omits_draft_by_default(self) -> None:
        content = SeedanceService.build_content(prompt="a fox in the snow")
        request = SeedanceService.build_request(
            model="dreamina-seedance-2-5-260628", content=content
        )
        assert "draft" not in request.model_dump(exclude_none=True)

    def test_build_draft_content_references_only_the_draft_task(self) -> None:
        content = SeedanceService.build_draft_content("cgt-draft-1")
        body = [item.model_dump(exclude_none=True) for item in content]
        assert body == [{"type": "draft_task", "draft_task": {"id": "cgt-draft-1"}}]

    def test_prompt_with_video_and_audio(self) -> None:
        content = SeedanceService.build_content(
            prompt="A dancer moving to music",
            videos=[{"url": "https://cdn.example.com/dance.mp4"}],
            audios=[{"url": "https://cdn.example.com/song.wav"}],
        )
        assert len(content) == 3  # 1 text + 1 video + 1 audio
        assert content[0].type == "text"
        assert content[0].text == "A dancer moving to music"
        assert content[1].type == "video_url"
        assert content[1].role == "reference_video"
        assert content[2].type == "audio_url"
        assert content[2].role == "reference_audio"


class TestSeedanceCreateTask:
    """Tests for POST /contents/generations/tasks."""

    @respx.mock
    async def test_create_success(self, service: SeedanceService) -> None:
        respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
            return_value=httpx.Response(
                200,
                json={"id": "task-abc-123"},
                headers={"X-Request-Id": "req-1"},
            )
        )
        content = SeedanceService.build_content(
            prompt="a cat", images=[{"url": "https://cdn.example.com/cat.png"}]
        )
        request = SeedanceService.build_request(
            model="dreamina-seedance-2-0-260128", content=content
        )
        task_id, request_id = await service.create_task(request)
        assert task_id == "task-abc-123"
        assert request_id == "req-1"

    @respx.mock
    async def test_create_validation_error(self, service: SeedanceService) -> None:
        respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
            return_value=httpx.Response(
                400,
                json={"error": {"code": "INVALID_PARAM", "message": "content is empty"}},
            )
        )
        request = SeedanceService.build_request(model="test", content=[])
        with pytest.raises(ProviderError) as exc_info:
            await service.create_task(request)
        assert exc_info.value.http_status == 400

    @respx.mock
    async def test_create_timeout_ambiguous(self, service: SeedanceService) -> None:
        respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        request = SeedanceService.build_request(
            model="test", content=[SeedanceContentItem(type="text", text="hi")]
        )
        with pytest.raises(ProviderError) as exc_info:
            await service.create_task(request)
        assert exc_info.value.ambiguous_completion is True


class TestSeedanceInvalidResponse:
    """2xx responses with non-JSON bodies must fail as INVALID_RESPONSE."""

    @respx.mock
    async def test_create_non_json_success_body(self, service: SeedanceService) -> None:
        respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
            return_value=httpx.Response(200, content=b"<html>not json</html>")
        )
        request = SeedanceService.build_request(
            model="test", content=[SeedanceContentItem(type="text", text="hi")]
        )
        with pytest.raises(ProviderError) as exc_info:
            await service.create_task(request)
        assert exc_info.value.code == "INVALID_RESPONSE"
        assert exc_info.value.http_status == 200


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadError,
        httpx.WriteError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.RemoteProtocolError,
        httpx.LocalProtocolError,
        httpx.TransportError,
    ],
)
@respx.mock
async def test_lost_create_response_is_never_resubmitted(
    service: SeedanceService, failure: type[httpx.TransportError]
) -> None:
    canary = "synthetic-request-secret-canary"
    route = respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
        side_effect=[
            failure(f"{canary} https://private.example/input?token={canary}"),
            httpx.Response(200, json={"id": "duplicate-task"}),
        ]
    )
    request = SeedanceService.build_request(model="test", content=[])
    try:
        with pytest.raises(ProviderError) as info:
            await call_with_retry(
                lambda: service.create_task(request),
                policy=RetryPolicy(base_delay_seconds=0),
            )
        assert route.call_count == 1
        assert info.value.ambiguous_completion is True
        assert info.value.retryable is False
        assert info.value.__cause__ is None
        assert canary not in "".join(traceback.format_exception(info.value))
        assert "private.example" not in info.value.message
    finally:
        await service.close()


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
@respx.mock
async def test_predispatch_failure_can_retry_create(
    service: SeedanceService, failure: type[httpx.TransportError]
) -> None:
    route = respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
        side_effect=[
            failure("not dispatched"),
            httpx.Response(200, json={"id": "task-created"}, headers={"X-Request-Id": "req-safe"}),
        ]
    )
    request = SeedanceService.build_request(model="test", content=[])
    try:
        assert await call_with_retry(
            lambda: service.create_task(request),
            policy=RetryPolicy(base_delay_seconds=0),
        ) == ("task-created", "req-safe")
        assert route.call_count == 2
    finally:
        await service.close()


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b"null",
        b'"unexpected"',
        b"{}",
        b'{"id":null}',
        b'{"id":1}',
        b'{"id":{}}',
        b'{"id":""}',
        b'{"id":"  "}',
        b'{"id":"\\n\\t"}',
    ],
)
@respx.mock
async def test_invalid_create_response_is_ambiguous_without_retry(
    service: SeedanceService, body: bytes
) -> None:
    route = respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
        side_effect=[
            httpx.Response(200, content=body, headers={"X-Request-Id": "req-accepted"}),
            httpx.Response(200, json={"id": "duplicate-task"}),
        ]
    )
    request = SeedanceService.build_request(model="test", content=[])
    try:
        with pytest.raises(ProviderError) as info:
            await call_with_retry(
                lambda: service.create_task(request),
                policy=RetryPolicy(base_delay_seconds=0),
            )
        assert route.call_count == 1
        assert info.value.code == "INVALID_RESPONSE"
        assert info.value.http_status == 200
        assert info.value.request_id == "req-accepted"
        assert info.value.ambiguous_completion is True
        assert info.value.retryable is False
        assert info.value.__cause__ is None
    finally:
        await service.close()
