"""Seed TTS 3 JSONL contract, using synthetic audio only."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from ark_mcp.domain.errors import ProviderError
from ark_mcp.execution import run_direct_call
from ark_mcp.providers.seed_speech.client import SeedSpeechGateway
from ark_mcp.providers.seed_speech.seed_tts import SeedTtsService

BASE = "https://voice.test.example.com"
PATH = "/api/v3/text-to-speech/test-voice/streaming"
READY = {"event": "ready", "session_id": "session-test"}
FINAL = {"event": "final", "is_final": True, "reason": "TTS_STREAM_FINAL_REASON_CLOSED"}


def audio(data: bytes) -> dict[str, str]:
    return {"event": "audio", "audio": base64.b64encode(data).decode()}


def wire(*events: object) -> bytes:
    return b"\n".join(json.dumps(event).encode() for event in events)


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes, failure: Exception | None = None) -> None:
        self.body = body
        self.failure = failure
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.body), 7):
            yield self.body[offset : offset + 7]
        if self.failure:
            raise self.failure

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
async def service() -> AsyncIterator[SeedTtsService]:
    instance = SeedTtsService(SeedSpeechGateway(api_key="synthetic", base_url=BASE))
    try:
        yield instance
    finally:
        await instance.close()


async def synthesize(service: SeedTtsService, *, limit: int = 10):
    return await service.synthesize(
        {"text": "Hello", "model_id": "dola-seed-tts-3.0"},
        voice_id="test-voice",
        request_id="req-test",
        max_audio_bytes=limit,
    )


@respx.mock
async def test_split_lines_decode_chunks_and_map_word_seconds(service: SeedTtsService) -> None:
    stream = FragmentedStream(
        wire(
            READY,
            audio(b"a"),
            {
                "event": "alignment",
                "text": "Hello",
                "words": [{"word": "Hello", "startTime": 0.1, "endTime": 0.6}],
            },
            audio(b"bc"),
            FINAL,
        )
    )
    route = respx.post(BASE + PATH).mock(
        return_value=httpx.Response(200, stream=stream, headers={"X-Tt-Logid": "log-test"})
    )
    result = await synthesize(service)
    assert result.audio == b"abc"
    assert result.session_id == "session-test"
    assert result.provider_log_id == "log-test"
    assert result.alignments[0].words[0].start_time == 0.1
    assert result.alignments[0].words[0].end_time == 0.6
    assert stream.closed
    request = route.calls.last.request
    assert request.headers["X-Api-Key"] == "synthetic"
    assert request.headers["X-Request-Id"] == "req-test"
    assert "X-Api-Request-Id" not in request.headers
    assert "Authorization" not in request.headers
    assert json.loads(request.content)["model_id"] == "dola-seed-tts-3.0"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        wire(READY, audio(b"x")),
        wire(READY, FINAL),
        wire(audio(b"x"), FINAL),
        wire(READY, READY, audio(b"x"), FINAL),
        wire(READY, audio(b"x"), {**FINAL, "reason": "other"}),
        wire(READY, audio(b"x"), {**FINAL, "is_final": False}),
        wire(READY, {"event": "audio", "audio": "invalid!"}, FINAL),
        wire(READY, {"event": "audio", "audio": 42}, FINAL),
        wire(READY, [], FINAL),
        wire(READY) + b"\nnot-json",
        wire(READY, {"event": "unexpected"}, FINAL),
        wire(
            READY,
            {
                "event": "alignment",
                "text": "x",
                "words": [{"word": "x", "startTime": 1, "endTime": 0}],
            },
            audio(b"x"),
            FINAL,
        ),
    ],
)
@respx.mock
async def test_invalid_stream_is_ambiguous_and_not_retried(
    service: SeedTtsService, body: bytes
) -> None:
    route = respx.post(BASE + PATH).respond(200, content=body)
    with pytest.raises(ProviderError) as error:
        await synthesize(service)
    assert not error.value.retryable
    assert error.value.ambiguous_completion
    assert route.call_count == 1


@respx.mock
async def test_audio_limit_before_persistence(service: SeedTtsService) -> None:
    respx.post(BASE + PATH).respond(200, content=wire(READY, audio(b"12345"), FINAL))
    with pytest.raises(ProviderError) as error:
        await synthesize(service, limit=4)
    assert error.value.code == "OUTPUT_TOO_LARGE"
    assert error.value.ambiguous_completion


@pytest.mark.parametrize("status", [400, 401, 429, 503])
@pytest.mark.parametrize("interrupted", [False, True])
@respx.mock
async def test_http_error_status_survives_interrupted_body(
    service: SeedTtsService, status: int, interrupted: bool
) -> None:
    stream = FragmentedStream(
        b""
        if interrupted
        else wire(
            {
                "error": {
                    "code": "voice_access_denied",
                    "request_id": "provider-request",
                    "logid": "provider-log",
                }
            }
        ),
        httpx.ReadError("disconnected") if interrupted else None,
    )
    route = respx.post(BASE + PATH).mock(
        return_value=httpx.Response(status, stream=stream, headers={"X-Tt-Logid": "log-test"})
    )
    with pytest.raises(ProviderError) as error:
        await synthesize(service)
    assert error.value.http_status == status
    assert error.value.code == ("TTS_PROVIDER_ERROR" if interrupted else "voice_access_denied")
    assert error.value.request_id == ("req-test" if interrupted else "provider-request")
    assert error.value.ambiguous_completion is (status >= 500)
    assert error.value.retryable is (status == 429)
    assert stream.closed
    assert route.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("timeout"), httpx.ReadError("broken"), httpx.DecodingError("compression")],
)
@respx.mock
async def test_disconnect_closes_without_retry(service: SeedTtsService, failure: Exception) -> None:
    stream = FragmentedStream(wire(READY, audio(b"x")) + b"\n", failure)
    route = respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    with pytest.raises(ProviderError) as error:
        await synthesize(service)
    assert error.value.ambiguous_completion
    assert not error.value.retryable
    assert route.call_count == 1
    assert stream.closed


@respx.mock
async def test_final_does_not_wait_for_eof(service: SeedTtsService) -> None:
    stream = FragmentedStream(wire(READY, audio(b"x"), FINAL) + b"\n", httpx.ReadError("late"))
    respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    assert (await synthesize(service)).audio == b"x"
    assert stream.closed


@respx.mock
async def test_voice_id_is_one_encoded_path_segment(service: SeedTtsService) -> None:
    route = respx.post(BASE + "/api/v3/text-to-speech/a%2Fb%3Fc/streaming").respond(
        200, content=wire(READY, audio(b"x"), FINAL)
    )
    await service.synthesize(
        {"text": "Hello"}, voice_id="a/b?c", request_id="req-test", max_audio_bytes=10
    )
    assert route.called


@pytest.mark.parametrize("terminated", [False, True])
@respx.mock
async def test_event_limit(
    service: SeedTtsService, monkeypatch: pytest.MonkeyPatch, terminated: bool
) -> None:
    monkeypatch.setattr("ark_mcp.providers.seed_speech.seed_tts.MAX_EVENT_BYTES", 64)
    stream = FragmentedStream(b"x" * 65 + (b"\n" if terminated else b""))
    respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    with pytest.raises(ProviderError) as error:
        await synthesize(service)
    assert error.value.code == "OUTPUT_TOO_LARGE"
    assert stream.closed


@respx.mock
async def test_provider_error_after_audio_is_ambiguous(service: SeedTtsService) -> None:
    respx.post(BASE + PATH).respond(
        200, content=wire(READY, audio(b"x"), {"event": "error", "error": {"code": "internal"}})
    )
    with pytest.raises(ProviderError) as error:
        await synthesize(service)
    assert error.value.code == "internal"
    assert error.value.ambiguous_completion


class WaitingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield wire(READY) + b"\n"
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


@respx.mock
async def test_external_cancellation_propagates(service: SeedTtsService) -> None:
    stream = WaitingStream()
    route = respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    task = asyncio.create_task(synthesize(service))
    await asyncio.wait_for(stream.started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    assert route.call_count == 1


@respx.mock
async def test_direct_deadline_records_mutation_and_closes_stream(service: SeedTtsService) -> None:
    stream = WaitingStream()
    route = respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    result = await run_direct_call(
        lambda: synthesize(service), timeout_seconds=0.02, read_only=False
    )
    assert result.is_error
    assert "ambiguous_completion=True" in result.content[0].text
    assert "TOOL_DEADLINE_EXCEEDED" in result.content[0].text
    assert "request_id=req-test" in result.content[0].text
    assert "task_id=" not in result.content[0].text
    assert stream.closed
    assert route.call_count == 1


@respx.mock
async def test_provider_deadline_closes_stream() -> None:
    stream = WaitingStream()
    respx.post(BASE + PATH).mock(return_value=httpx.Response(200, stream=stream))
    service = SeedTtsService(
        SeedSpeechGateway(api_key="synthetic", base_url=BASE),  # pragma: allowlist secret
        timeout_seconds=0.02,
    )
    try:
        with pytest.raises(ProviderError) as error:
            await synthesize(service)
        assert error.value.code == "TIMEOUT"
        assert error.value.ambiguous_completion
        assert stream.closed
    finally:
        await service.close()
