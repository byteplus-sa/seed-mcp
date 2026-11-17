"""Offline provider safety regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import inspect
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
import respx

from ark_mcp.domain.errors import ProviderError
from ark_mcp.providers.base import BaseHttpGateway
from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.providers.modelark.generation_tasks import GenerationTaskService
from ark_mcp.providers.modelark.seedance import SeedanceService
from ark_mcp.providers.modelark.seedream import SeedreamService
from ark_mcp.providers.retry import RetryPolicy, call_with_retry
from ark_mcp.providers.seed_speech.client import SeedSpeechGateway
from ark_mcp.providers.seed_speech.seed_audio import SeedAudioService
from ark_mcp.providers.vision_cv.client import VisionCvGateway
from ark_mcp.providers.vision_cv.omnihuman import OmniHumanService

MODELARK_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
TEST_CREDENTIAL = "synthetic-key"  # pragma: allowlist secret
GATEWAYS = [ModelArkGateway, SeedSpeechGateway, VisionCvGateway]
SERVICES = [
    SeedanceService,
    SeedreamService,
    GenerationTaskService,
    SeedAudioService,
    OmniHumanService,
]


@pytest.mark.parametrize("gateway_type", GATEWAYS)
def test_gateway_requires_explicit_key(gateway_type: type[BaseHttpGateway]) -> None:
    assert inspect.signature(gateway_type).parameters["api_key"].default is inspect.Parameter.empty


@pytest.mark.parametrize("service_type", SERVICES)
def test_service_requires_explicit_gateway(service_type: type[Any]) -> None:
    assert inspect.signature(service_type).parameters["gateway"].default is inspect.Parameter.empty


@pytest.mark.parametrize("gateway_type", GATEWAYS)
@pytest.mark.parametrize(
    "key",
    [
        "",
        " ",
        " canary",
        "canary ",
        "can ary",
        "canary\n",
        "canary\r",
        "canary\t",
        "canary\x00",
        "canary\x7f",
        "\u00a0",
        "\u00e9",
        "x" * 4097,
        None,
    ],
)
def test_gateway_rejects_invalid_key_without_startup_fallback(
    gateway_type: type[Any], key: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "BYTEPLUS_MODELARK_API_KEY",
        "BYTEPLUS_SEED_SPEECH_API_KEY",
        "BYTEPLUS_CV_API_KEY",
    ):
        monkeypatch.setenv(name, "synthetic-startup-key")
    with pytest.raises(ValueError, match="API key") as info:
        gateway_type(api_key=key)
    assert "synthetic-startup-key" not in str(info.value)
    if isinstance(key, str) and len(key) > 3:
        assert key not in str(info.value)


@pytest.mark.parametrize("gateway_type", GATEWAYS)
@pytest.mark.parametrize("key", ["x", "x" * 4096, "".join(chr(value) for value in range(33, 127))])
def test_gateway_preserves_printable_key_bytes(gateway_type: type[Any], key: str) -> None:
    gateway = gateway_type(api_key=key)
    headers = gateway._headers()
    assert headers.get("Authorization", headers.get("X-Api-Key")) in (key, f"Bearer {key}")


@pytest.mark.parametrize(
    "failure", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError, httpx.ReadTimeout]
)
@respx.mock
async def test_task_read_transport_failure_retries(failure: type[httpx.TransportError]) -> None:
    service = GenerationTaskService(
        ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE)
    )
    route = respx.get(f"{MODELARK_BASE}/contents/generations/tasks/task-1").mock(
        side_effect=[failure("lost response"), httpx.Response(200, json={"id": "task-1"})]
    )
    try:
        task, _ = await call_with_retry(
            lambda: service.get_task("task-1"), policy=RetryPolicy(base_delay_seconds=0)
        )
        assert task.id == "task-1"
        assert route.call_count == 2
    finally:
        await service.close()


@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
@respx.mock
async def test_task_delete_transport_failure_is_ambiguous(
    failure: type[httpx.TransportError],
) -> None:
    service = GenerationTaskService(
        ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE)
    )
    route = respx.delete(f"{MODELARK_BASE}/contents/generations/tasks/task-1").mock(
        side_effect=[failure("lost response"), httpx.Response(204)]
    )
    try:
        with pytest.raises(ProviderError) as info:
            await call_with_retry(
                lambda: service.delete_task("task-1"), policy=RetryPolicy(base_delay_seconds=0)
            )
        assert route.call_count == 1
        assert info.value.ambiguous_completion is True
        assert info.value.retryable is False
    finally:
        await service.close()


@respx.mock
async def test_transport_spans_and_exception_chain_do_not_capture_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canary = "synthetic-transport-secret-canary"
    events: list[str] = []
    span = Mock()
    span_options: dict[str, object] = {}

    @contextmanager
    def span_context(*args: object, **kwargs: object) -> Iterator[Mock]:
        span_options.update(kwargs)
        try:
            yield span
        except Exception as exc:
            if kwargs.get("record_exception", True):
                events.append("".join(traceback.format_exception(exc)))
            raise

    tracer = Mock()
    tracer.start_as_current_span.side_effect = span_context
    monkeypatch.setattr("ark_mcp.providers.base.get_tracer", lambda: tracer)
    monkeypatch.setattr(
        "ark_mcp.providers.base.record_span_error",
        lambda _span, exc: events.append("".join(traceback.format_exception(exc))),
    )
    respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
        side_effect=httpx.ReadError(f"{canary} https://private.example/?signature={canary}")
    )
    service = SeedanceService(ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE))
    try:
        with pytest.raises(ProviderError) as info:
            await service.create_task(SeedanceService.build_request(model="test", content=[]))
        assert events
        assert canary not in "".join(events)
        assert canary not in "".join(traceback.format_exception(info.value))
        assert canary not in capsys.readouterr().err
        assert span_options["record_exception"] is False
        assert span_options["set_status_on_exception"] is False
    finally:
        await service.close()


@pytest.fixture
def redact_canaries(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str, str]:
    from ark_mcp.security import credentials

    canaries = (
        "synthetic-modelark-canary",
        "synthetic-speech-canary",
        "synthetic-vision-canary",
        "synthetic-client-secret-canary",
    )

    def redact(text: str) -> str:
        for canary in canaries:
            text = text.replace(canary, "[REDACTED]")
        return text

    monkeypatch.setattr(credentials, "redact_request_secrets", redact)
    return canaries


@pytest.mark.parametrize("gateway_type", GATEWAYS)
def test_normalized_diagnostics_redact_all_request_secrets_and_urls(
    gateway_type: type[BaseHttpGateway],
    redact_canaries: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    detail = " ".join(redact_canaries) + " https://private.example/path?signature=signed"
    response = httpx.Response(
        400,
        json={
            "error": {"code": redact_canaries[0], "message": detail},
            "code": 50215,
            "message": detail,
            "request_id": redact_canaries[-1],
        },
        headers={"X-Request-Id": redact_canaries[-1], "X-Tt-Logid": redact_canaries[-1]},
    )
    error = gateway_type.normalize_error(response, "create_task")
    output = error.error.model_dump_json() + capsys.readouterr().err
    for canary in redact_canaries:
        assert canary not in output
    assert "private.example" not in output
    assert "signature=signed" not in output
    assert "[REDACTED]" in output


@pytest.mark.parametrize("gateway_type", [ModelArkGateway, SeedSpeechGateway])
@pytest.mark.parametrize(
    "body",
    [{"error": None}, {"code": [], "message": {"sensitive": "value"}}, None, [], "unexpected"],
)
def test_unexpected_error_shapes_are_safely_normalized(
    gateway_type: type[BaseHttpGateway], body: object
) -> None:
    error = gateway_type.normalize_error(httpx.Response(400, json=body), "create_task")
    assert error.http_status == 400
    assert error.retryable is False
    assert "sensitive" not in error.message


@pytest.mark.parametrize("gateway_type", GATEWAYS)
@pytest.mark.parametrize("retry_after", ["-1", "nan", "inf", "not-a-number"])
def test_invalid_retry_after_does_not_escape_as_validation_error(
    gateway_type: type[BaseHttpGateway], retry_after: str
) -> None:
    error = gateway_type.normalize_error(
        httpx.Response(429, json={"message": "Rate limited"}, headers={"Retry-After": retry_after}),
        "create_task",
    )
    assert error.retryable is True
    assert error.error.retry_after_seconds is None


@respx.mock
async def test_polled_task_errors_are_sanitized(
    redact_canaries: tuple[str, ...],
) -> None:
    detail = " ".join(redact_canaries) + " https://private.example/input"
    task = {
        "id": "task-1",
        "status": "failed",
        "error": {"code": redact_canaries[0], "message": detail},
    }
    respx.get(f"{MODELARK_BASE}/contents/generations/tasks/task-1").respond(200, json=task)
    respx.get(f"{MODELARK_BASE}/contents/generations/tasks").respond(200, json={"data": [task]})
    service = GenerationTaskService(
        ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE)
    )
    try:
        result, _ = await service.get_task("task-1")
        page, _ = await service.list_tasks()
        for output in (result.model_dump_json(), page.model_dump_json()):
            assert all(canary not in output for canary in redact_canaries)
            assert "private.example" not in output
    finally:
        await service.close()


@pytest.mark.parametrize("service_type", SERVICES)
async def test_service_close_owns_only_its_injected_gateway(service_type: type[Any]) -> None:
    from unittest.mock import AsyncMock

    gateway = Mock(close=AsyncMock())
    service = service_type(gateway=gateway)
    await service.close()
    gateway.close.assert_awaited_once_with()


@pytest.mark.parametrize("service_name", ["seedream", "seed_audio", "omnihuman"])
@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
@respx.mock
async def test_other_mutations_do_not_retry_uncertain_dispatch(
    service_name: str, failure: type[httpx.TransportError]
) -> None:
    from ark_mcp.providers.vision_cv.schemas import OmniHumanSubmitRequest

    service: Any
    if service_name == "seedream":
        service = SeedreamService(ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE))
        path = "/images/generations"
        request = SeedreamService.build_request(model="test", prompt="test")
        operation = partial(service.generate, request)
    elif service_name == "seed_audio":
        service = SeedAudioService(
            SeedSpeechGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE)
        )
        path = "/api/v3/tts/create"
        audio_request = SeedAudioService.build_request(text_prompt="test")
        operation = partial(service.generate, audio_request)
    else:
        service = OmniHumanService(VisionCvGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE))
        path = "/api/common/v3/submit_task_v2"
        avatar_request = OmniHumanSubmitRequest(
            image_url="https://example.com/face.png", audio_url="https://example.com/input.wav"
        )
        operation = partial(service.create, avatar_request)
    route = respx.post(f"{MODELARK_BASE}{path}").mock(side_effect=failure("uncertain dispatch"))
    try:
        with pytest.raises(ProviderError) as info:
            await call_with_retry(operation, policy=RetryPolicy(base_delay_seconds=0))
        assert route.call_count == 1
        assert info.value.ambiguous_completion is True
        assert info.value.retryable is False
        assert info.value.__cause__ is None
    finally:
        await service.close()


@respx.mock
async def test_predispatch_retries_are_bounded() -> None:
    route = respx.post(f"{MODELARK_BASE}/contents/generations/tasks").mock(
        side_effect=httpx.ConnectError("not dispatched")
    )
    service = SeedanceService(ModelArkGateway(api_key=TEST_CREDENTIAL, base_url=MODELARK_BASE))
    try:
        with pytest.raises(ProviderError) as info:
            await call_with_retry(
                lambda: service.create_task(
                    SeedanceService.build_request(model="test", content=[])
                ),
                policy=RetryPolicy(max_attempts=3, base_delay_seconds=0),
            )
        assert route.call_count == 3
        assert info.value.ambiguous_completion is False
    finally:
        await service.close()
