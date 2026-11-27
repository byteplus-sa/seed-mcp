"""Direct TTS validation, billing, persistence, discovery and transport tests."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.tools import ToolResult
from pydantic import ValidationError

from ark_mcp.artifacts.store import ArtifactPersistenceError
from ark_mcp.config.env import Settings, get_settings
from ark_mcp.execution import run_direct_call
from ark_mcp.providers.seed_speech.seed_tts import SeedTtsService
from ark_mcp.runtime import BudgetExceededError
from ark_mcp.server import create_server
from ark_mcp.tools.ark_list_models import describe_models
from ark_mcp.tools.seed_tts_generate import (
    SeedTtsGenerateInput,
    SeedTtsGenerateOutput,
    seed_tts_generate,
)
from tests.contract.test_seed_tts_adapter import FINAL, READY, WaitingStream, audio, wire
from tests.fixtures.fake_context import FakeContext

URL = "https://voice.test.example.com/api/v3/text-to-speech/test-voice/streaming"
VOICE = {"voice_id": "test-voice"}


def response() -> httpx.Response:
    return httpx.Response(200, content=wire(READY, audio(b"synthetic audio"), FINAL))


def fail_after_close(monkeypatch: pytest.MonkeyPatch) -> None:
    close = SeedTtsService.close

    async def failing_close(service: SeedTtsService) -> None:
        await close(service)
        raise RuntimeError("Synthetic cleanup failure.")

    monkeypatch.setattr(SeedTtsService, "close", failing_close)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"text": ""},
        {"text": "  "},
        {"text": "x" * 10001},
        {"ssml": "x" * 10001},
        {"ssml": " "},
        {"text": "x", "ssml": "<speak>x</speak>"},
        {"text": "x", "model": "seed-tts-2.0"},
        {"text": "x", "voice_id": ".."},
        {"text": "x", "voice_id": " "},
        {"text": "x", "output_format": {"format": "wav"}},
        {"text": "x", "output_format": {"format": "ogg_opus", "sample_rate": 24000}},
        {"text": "x", "output_format": {"format": "pcm", "bit_rate": 64000}},
        {"text": "x", "output_format": {"sample_rate": 8000, "bit_rate": 160000}},
        {"text": "x", "voice_settings": {"speed": 2.01}},
        {"text": "x", "voice_settings": {"volume": 0.49}},
        {"text": "x", "voice_settings": {"pitch": 13}},
        {"text": "x", "silence_duration": 30001},
        {"text": "x", "silence_duration": float("nan")},
        {"text": "x", "pronunciation_dictionary": [{}]},
        {"text": "x", "pronunciation_dictionary": {"unexpected": ["word/replacement"]}},
        {"text": "x", "pronunciation_dictionary": {"tone": "word/replacement"}},
        {"text": "x", "pronunciation_dictionary": {"tone": [None]}},
        {"text": "x", "pronunciation_dictionary": {"tone": ["missing separator"]}},
        {"text": "x", "pronunciation_dictionary": {"tone": [" /replacement"]}},
        {"text": "x", "pronunciation_dictionary": {"tone": ["word/ "]}},
        {"text": "x", "pronunciation_dictionary": {"tone": ["word/" + "x" * 996]}},
        {"text": "x", "pronunciation_dictionary": {"tone": ["word/replacement"] * 101}},
        {"text": "x", "persist": False},
    ],
)
def test_invalid_input_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SeedTtsGenerateInput.model_validate(VOICE | fields)


def test_character_dictionary_boundaries_and_defaults() -> None:
    value = SeedTtsGenerateInput.model_validate(VOICE | {"text": "x" * 10000})
    assert value.output_format.resolved().sample_rate == 24000
    assert value.output_format.resolved().bit_rate == 64000
    for tone in ([], ["word/" + "x" * 995] * 100):
        value = SeedTtsGenerateInput.model_validate(
            VOICE | {"text": "Hello", "pronunciation_dictionary": {"tone": tone}}
        )
        assert value.pronunciation_dictionary is not None
        assert value.pronunciation_dictionary.tone == tone


@pytest.mark.parametrize(
    "encoding,mime,extension",
    [
        ("mp3", "audio/mpeg", ".mp3"),
        ("pcm", "audio/pcm", ".pcm"),
        ("ogg_opus", "audio/ogg", ".ogg"),
    ],
)
@respx.mock
async def test_persist_and_export_matching_encoding(
    fake_ctx: FakeContext,
    temp_store: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
    mime: str,
    extension: str,
) -> None:
    monkeypatch.setenv("OUTPUT_ROOTS", str(tmp_path))
    get_settings.cache_clear()
    route = respx.post(URL).mock(return_value=response())
    result = await seed_tts_generate(
        SeedTtsGenerateInput.model_validate(
            VOICE
            | {
                "text": "Hello",
                "output_format": {"format": encoding},
                "output_path": f"{tmp_path}/",
            }
        ),
        fake_ctx,
    )
    assert isinstance(result, SeedTtsGenerateOutput)
    assert result.artifact.mime_type == mime
    assert result.artifact.uri.startswith("seed-media://artifacts/")
    assert result.artifact.source_expires_at is None
    assert result.artifact.local_path.endswith(extension)
    assert (await temp_store.get(result.artifact.id)).data == b"synthetic audio"
    body = json.loads(route.calls.last.request.content)
    assert body["model_id"] == "dola-seed-tts-3.0"
    assert not {"model", "ssml", "voice_id", "output_path", "overwrite"} & body.keys()
    assert body["output_format"]["format"] == encoding
    assert (body["output_format"].get("bit_rate") is None) == (encoding == "pcm")
    assert result.session_id == READY["session_id"]


@respx.mock
async def test_ssml_and_controls_reach_provider(fake_ctx: FakeContext) -> None:
    route = respx.post(URL).mock(return_value=response())
    fields = {
        "ssml": "<speak>Hello</speak>",
        "language_code": "en",
        "session_id": "conversation",
        "enable_subtitle": True,
        "text_normalization": False,
        "enable_markdown_filter": True,
        "silence_duration": 30000,
        "voice_settings": {
            "speed": 0.5,
            "volume": 2,
            "pitch": -12,
            "instructions": ["Warm"],
            "similarity_boost": True,
        },
        "pronunciation_dictionary": {"tone": ["MCP/model context protocol"]},
    }
    result = await seed_tts_generate(SeedTtsGenerateInput.model_validate(VOICE | fields), fake_ctx)
    assert isinstance(result, SeedTtsGenerateOutput)
    body = json.loads(route.calls.last.request.content)
    assert "text" not in body
    for name, value in fields.items():
        assert body[name] == value


@pytest.mark.parametrize(
    "outcome,committed",
    [
        ("success", True),
        ("truncated", True),
        ("rejected", False),
        ("connect_timeout", False),
        ("pool_timeout", False),
        ("read_timeout", True),
        ("storage_failure", True),
    ],
)
@respx.mock
async def test_budget_tracks_confirmed_and_uncertain_outcomes(
    fake_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, outcome: str, committed: bool
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    ledger = runtime.budget_ledger
    commit, release, reserve = (
        AsyncMock(wraps=getattr(ledger, name)) for name in ("commit", "release", "reserve")
    )
    for name, mock in (("commit", commit), ("release", release), ("reserve", reserve)):
        monkeypatch.setattr(ledger, name, mock)
    provider_response = (
        httpx.Response(200, content=wire(READY))
        if outcome == "truncated"
        else httpx.Response(400, json={"error": {"code": "invalid_text"}})
        if outcome == "rejected"
        else response()
    )
    failure = {
        "connect_timeout": httpx.ConnectTimeout("connect"),
        "pool_timeout": httpx.PoolTimeout("pool"),
        "read_timeout": httpx.ReadTimeout("read"),
    }.get(outcome)
    route = respx.post(URL).mock(return_value=provider_response, side_effect=failure)
    if outcome == "storage_failure":
        monkeypatch.setattr(
            runtime.artifact_store,
            "put_base64",
            AsyncMock(
                side_effect=ArtifactPersistenceError(
                    "storage_failed", "Unavailable", retryable=False
                )
            ),
        )
    result = await seed_tts_generate(
        SeedTtsGenerateInput.model_validate(VOICE | {"ssml": "<speak>x</speak>"}), fake_ctx
    )
    assert commit.await_count == int(committed)
    assert release.await_count == int(not committed)
    assert reserve.call_args.args[1].amount_usd == pytest.approx(
        len("<speak>x</speak>") * 20 / 1_000_000
    )
    assert route.call_count == 1
    if outcome == "truncated" or failure:
        assert isinstance(result, ToolResult) and result.is_error
    if outcome == "storage_failure":
        assert result.artifact.id == "inline-fallback"
        assert result.artifact.persistence_error.artifact_limit_bytes is None
        assert base64.b64decode(result.artifact.fallback_data) == b"synthetic audio"


@respx.mock
async def test_budget_rejection_prevents_dispatch(
    fake_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx.post(URL).mock(return_value=response())
    monkeypatch.setattr(
        fake_ctx.lifespan_context["runtime"].budget_ledger,
        "reserve",
        AsyncMock(side_effect=BudgetExceededError("Daily budget exceeded.")),
    )
    with pytest.raises(BudgetExceededError):
        await seed_tts_generate(SeedTtsGenerateInput(**VOICE, text="Hello"), fake_ctx)
    assert not route.called


@respx.mock
@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("termination", ["cancel", "deadline"])
async def test_cancelled_dispatch_commits_and_releases_stream(
    fake_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_fails: bool,
    termination: str,
) -> None:
    if cleanup_fails:
        fail_after_close(monkeypatch)
    runtime = fake_ctx.lifespan_context["runtime"]
    commit = AsyncMock(wraps=runtime.budget_ledger.commit)
    monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
    stream = WaitingStream()
    route = respx.post(URL).mock(return_value=httpx.Response(200, stream=stream))
    task = asyncio.create_task(
        run_direct_call(
            lambda: seed_tts_generate(SeedTtsGenerateInput(**VOICE, text="Hello"), fake_ctx),
            timeout_seconds=0.1 if termination == "deadline" else 10,
            read_only=False,
        )
    )
    await asyncio.wait_for(stream.started.wait(), 1)
    if termination == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result.is_error
        assert "TOOL_DEADLINE_EXCEEDED" in result.content[0].text
        assert "ambiguous_completion=True" in result.content[0].text
    assert commit.await_count == 1
    assert stream.closed
    assert route.call_count == 1


@pytest.mark.parametrize("failure", ["cleanup", "progress_80", "progress_100"])
@respx.mock
async def test_post_synthesis_diagnostics_do_not_discard_audio(
    fake_ctx: FakeContext, temp_store: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "cleanup":
        fail_after_close(monkeypatch)
    else:
        original_progress = fake_ctx.report_progress

        async def failing_progress(*, progress: int, total: int) -> None:
            if failure == f"progress_{progress}":
                raise RuntimeError("Synthetic notification failure.")
            await original_progress(progress=progress, total=total)

        monkeypatch.setattr(fake_ctx, "report_progress", failing_progress)
    route = respx.post(URL).mock(return_value=response())
    result = await seed_tts_generate(SeedTtsGenerateInput(**VOICE, text="Hello"), fake_ctx)
    assert isinstance(result, SeedTtsGenerateOutput)
    assert (await temp_store.get(result.artifact.id)).data == b"synthetic audio"
    assert result.request_id == route.calls.last.request.headers["X-Request-Id"]
    assert route.call_count == 1


@pytest.mark.parametrize("cancel_progress", [80, 100])
@respx.mock
async def test_post_synthesis_progress_does_not_swallow_cancellation(
    fake_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, cancel_progress: int
) -> None:
    original_progress = fake_ctx.report_progress

    async def cancelled_progress(*, progress: int, total: int) -> None:
        if progress == cancel_progress:
            raise asyncio.CancelledError
        await original_progress(progress=progress, total=total)

    monkeypatch.setattr(fake_ctx, "report_progress", cancelled_progress)
    route = respx.post(URL).mock(return_value=response())
    with pytest.raises(asyncio.CancelledError):
        await seed_tts_generate(SeedTtsGenerateInput(**VOICE, text="Hello"), fake_ctx)
    assert route.call_count == 1


@respx.mock
async def test_cleanup_failure_does_not_mask_provider_rejection(
    fake_ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_after_close(monkeypatch)
    route = respx.post(URL).respond(400, json={"error": {"code": "invalid_text"}})
    result = await seed_tts_generate(SeedTtsGenerateInput(**VOICE, text="Hello"), fake_ctx)
    assert isinstance(result, ToolResult) and result.is_error
    assert "invalid_text" in result.content[0].text
    assert "cleanup failure" not in result.content[0].text
    assert route.call_count == 1


@pytest.mark.parametrize("fallback_cap", [0, 4])
@respx.mock
async def test_mcp_persistence_failure_keeps_completion_and_request_id(
    test_env: None, monkeypatch: pytest.MonkeyPatch, fallback_cap: int
) -> None:
    monkeypatch.setenv("ARTIFACT_INLINE_FALLBACK_MAX_BYTES", str(fallback_cap))
    get_settings.cache_clear()
    storage = AsyncMock(
        side_effect=ArtifactPersistenceError(
            "storage_failed", "Storage unavailable.", retryable=True
        )
    )
    monkeypatch.setattr(
        "ark_mcp.artifacts.filesystem_store.FilesystemArtifactStore.put_base64", storage
    )
    route = respx.post(URL).mock(return_value=response())
    async with Client(create_server(get_settings())) as client:
        result = await client.call_tool(
            "seed_tts_generate", {"input": VOICE | {"text": "Hello"}}, raise_on_error=False
        )
    assert result.is_error
    assert not result.structured_content
    text = result.content[0].text
    assert "Synthesis completed" in text
    assert "STORAGE_FAILED" in text
    assert route.calls.last.request.headers["X-Request-Id"] in text
    assert "retryable=False" in text
    assert "ambiguous_completion=False" in text
    assert "Do not automatically synthesize again" in text
    assert storage.await_count == 2
    assert route.call_count == 1


@respx.mock
async def test_real_mcp_direct_call_and_discovery(test_env: None) -> None:
    route = respx.post(URL).mock(return_value=response())
    async with Client(create_server(get_settings())) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "seed_tts_generate" in tools
        assert tools["seed_tts_generate"].annotations.idempotent_hint is False
        discovery = await client.call_tool("ark_list_models", {"input": {"kind": "audio"}})
        assert discovery.structured_content["models"][0]["tool"] == "seed_tts_generate"
        assert not route.called
        result = await client.call_tool("seed_tts_generate", {"input": VOICE | {"text": "Hello"}})
        assert result.structured_content["artifact"]["uri"].startswith("seed-media://")
        assert route.call_count == 1


async def test_http_never_advertises_or_dispatches_tts() -> None:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        BYTEPLUS_SEED_SPEECH_API_KEY="synthetic",  # pragma: allowlist secret
    )
    server = create_server(settings)
    assert "seed_tts_generate" not in {tool.name for tool in await server.list_tools()}
    assert not any(model.tool == "seed_tts_generate" for model in describe_models(settings))
    with respx.mock(assert_all_called=False) as router:
        async with Client(server) as client:
            result = await client.call_tool(
                "seed_tts_generate", {"input": VOICE | {"text": "Hello"}}, raise_on_error=False
            )
            assert result.is_error
            preflight = await client.call_tool(
                "ark_list_models",
                {"input": {"kind": "audio", "check_connection": True}},
                raise_on_error=False,
            )
            assert preflight.is_error
        assert not router.calls


async def test_speech_key_only_discovery_and_registration() -> None:
    settings = Settings(_env_file=None, BYTEPLUS_SEED_SPEECH_API_KEY="synthetic")
    assert [model.model_id for model in describe_models(settings)] == ["dola-seed-tts-3.0"]
    assert "seed_tts_generate" in {tool.name for tool in await create_server(settings).list_tools()}
    empty = Settings(_env_file=None)
    assert not describe_models(empty)
    assert "seed_tts_generate" not in {
        tool.name for tool in await create_server(empty).list_tools()
    }
