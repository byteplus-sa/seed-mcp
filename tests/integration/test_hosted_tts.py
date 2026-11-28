"""Hosted TTS returns native audio without storage or paid provider calls."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from mcp.types import AudioContent, CallToolResult

from tests.contract.test_seed_tts_adapter import FINAL, READY, audio, wire
from tests.integration.test_byok_http import (
    SPEECH,
    SPEECH_KEY,
    assert_denied,
    assert_no_canaries,
    call_tool,
    credentials,
    http_server,
    http_settings,
    rpc,
    successful,
)

URL = f"{SPEECH}/api/v3/text-to-speech/test-voice/streaming"
INPUT = {"voice_id": "test-voice", "text": "Synthetic test."}
HEADERS = credentials(SPEECH_KEY, header="X-Seed-Speech-Api-Key")


@pytest.fixture(autouse=True)
def no_storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    constructor = MagicMock(side_effect=AssertionError("HTTP TTS must not open object storage"))
    monkeypatch.setattr("ark_mcp.providers.s3.client.boto3.client", constructor)
    yield constructor
    constructor.assert_not_called()


@respx.mock
async def test_anonymous_discovery_advertises_tts_without_storage(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, runtime, client):
        tools = (await rpc(client, "tools/list"))["result"]["tools"]
        assert len(tools) == 12
        assert "seed_tts_generate" in {tool["name"] for tool in tools}
        assert "media_prepare_upload" not in {tool["name"] for tool in tools}
        discovery = successful(await call_tool(client, "ark_list_models", {"kind": "audio"}))
        assert discovery["models"][0]["model_id"] == "dola-seed-tts-3.0"
        assert next(s for s in discovery["services"] if s["service"] == "seed_tts")["enabled"]
        assert discovery["connection"] is None
        assert runtime.budget_ledger is None
        assert (await client.get("/ready")).status_code == 200
        assert_denied(
            await call_tool(client, "ark_list_models", {"kind": "audio", "check_connection": True})
        )
    assert not respx.calls
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "encoding,mime", [("mp3", "audio/mpeg"), ("pcm", "audio/pcm"), ("ogg_opus", "audio/ogg")]
)
@respx.mock
async def test_http_tts_returns_audio_once_with_matching_metadata(
    tmp_path: Path, encoding: str, mime: str
) -> None:
    data = b"synthetic audio \x00\xff"
    alignment = {
        "event": "alignment",
        "text": "Hello",
        "words": [
            {"word": "Hello", "startTime": 0.1, "endTime": 0.5},
        ],
    }
    route = respx.post(URL).respond(
        200,
        content=wire(READY, audio(data[:5]), alignment, audio(data[5:]), FINAL),
        headers={"X-Tt-Logid": "synthetic-log"},
    )
    async with http_server(tmp_path) as (_, runtime, client):
        response = await call_tool(
            client,
            "seed_tts_generate",
            INPUT | {"output_format": {"format": encoding}, "enable_subtitle": True},
            headers=HEADERS,
        )
        metadata = successful(response)
        assert runtime.budget_ledger is None
    result = CallToolResult.model_validate(response["result"])
    assert len(result.content) == 2
    block = result.content[0]
    assert isinstance(block, AudioContent)
    assert block.mime_type == mime
    assert base64.b64decode(block.data, validate=True) == data
    assert metadata["artifact"] is None
    assert metadata["audio"] == {
        "content_index": 0,
        "mime_type": mime,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    assert metadata["session_id"] == READY["session_id"]
    assert metadata["provider_log_id"] == "synthetic-log"
    assert metadata["request_id"] == route.calls.last.request.headers["X-Request-Id"]
    assert metadata["alignments"][0]["words"][0]["start_time"] == 0.1
    assert metadata["output_format"]["format"] == encoding
    text = response["result"]["content"][1]["text"]
    assert json.loads(text) == metadata
    assert block.data not in text and block.data not in json.dumps(metadata)
    assert_no_canaries(json.dumps(response))
    assert route.calls.last.request.headers["X-Api-Key"] == SPEECH_KEY
    assert route.call_count == 1
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("extra_byte", [False, True])
@respx.mock
async def test_thirty_mib_boundary(tmp_path: Path, extra_byte: bool) -> None:
    chunk = b"\x00\x01" * (1024 * 512)
    route = respx.post(URL).respond(
        200,
        content=wire(
            READY,
            *(audio(chunk) for _ in range(30)),
            *([audio(b"x")] if extra_byte else []),
            FINAL,
        ),
    )
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS)
    assert route.call_count == 1
    if extra_byte:
        assert_denied(result)
        assert "OUTPUT_TOO_LARGE" in str(result)
        assert all(block["type"] == "text" for block in result["result"]["content"])
        return
    metadata = successful(result)
    encoded = result["result"]["content"][0]["data"]
    assert metadata["audio"]["bytes"] == 30 * 1024 * 1024
    assert len(base64.b64decode(encoded, validate=True)) == 30 * 1024 * 1024
    assert json.dumps(result).count(encoded) == 1
    assert route.call_count == 1


@pytest.mark.parametrize("headers", [{}, credentials(), {"X-Seed-Speech-Api-Key": SPEECH_KEY}])
@respx.mock
async def test_tts_requires_live_speech_key_and_client_secret(
    tmp_path: Path, headers: dict
) -> None:
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(await call_tool(client, "seed_tts_generate", INPUT, headers=headers))
    assert not respx.calls


@pytest.mark.parametrize(
    "extra", [{"output_path": "/tmp/forbidden.mp3"}, {"overwrite": True}, {"persist": True}]
)
@respx.mock
async def test_local_options_fail_before_synthesis(tmp_path: Path, extra: dict) -> None:
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(await call_tool(client, "seed_tts_generate", INPUT | extra, headers=HEADERS))
    assert not respx.calls


@pytest.mark.parametrize("kind", ["rejected", "incomplete", "oversized"])
@respx.mock
async def test_provider_failure_returns_no_audio_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr("ark_mcp.tools.seed_tts_generate.TTS_MAX_AUDIO_BYTES", 3)
    route = respx.post(URL).respond(
        403 if kind == "rejected" else 200,
        content=(
            b'{"error":{"code":"denied"}}'
            if kind == "rejected"
            else wire(READY, audio(b"x"))
            if kind == "incomplete"
            else wire(READY, audio(b"1234"), FINAL)
        ),
    )
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS)
    assert_denied(result)
    assert all(block["type"] == "text" for block in result["result"]["content"])
    assert "structuredContent" not in result["result"]
    assert_no_canaries(json.dumps(result))
    assert route.call_count == 1


@pytest.mark.parametrize("termination", ["cancel", "deadline"])
@respx.mock
async def test_synthesis_cancellation_and_deadline_do_not_return_partial_audio(
    tmp_path: Path, termination: str
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield wire(READY, audio(b"partial")) + b"\n"
            entered.set()
            await release.wait()
            yield wire(FINAL)

    route = respx.post(URL).mock(return_value=httpx.Response(200, stream=Stream()))
    settings = http_settings(
        tmp_path,
        MCP_TOOL_TIMEOUT_SECONDS=0.1 if termination == "deadline" else 10,
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        task = asyncio.create_task(call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if termination == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await asyncio.wait_for(task, 2)
                assert_denied(result)
                assert "TOOL_DEADLINE_EXCEEDED" in str(result)
                assert route.calls.last.request.headers["X-Request-Id"] in str(result)
                assert all(block["type"] == "text" for block in result["result"]["content"])
        finally:
            release.set()
        assert route.call_count == 1
