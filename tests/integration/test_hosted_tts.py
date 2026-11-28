"""Hosted TTS delivery with mocked speech and TOS; no paid or cloud calls."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx
from pydantic import ValidationError
from tos.enum import ACLType, StorageClassType

from ark_mcp.config.env import Settings
from ark_mcp.providers.tos.client import TosGateway
from tests.contract.test_seed_tts_adapter import FINAL, READY, audio, wire
from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    OTHER_SECRET,
    SPEECH,
    SPEECH_KEY,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    rpc,
    successful,
)

URL = f"{SPEECH}/api/v3/text-to-speech/test-voice/streaming"
INPUT = {"voice_id": "test-voice", "text": "Synthetic test."}
BUCKET = "synthetic-tts-output"
HEADERS = credentials(SPEECH_KEY, header="X-Seed-Speech-Api-Key")


def tts_settings(tmp_path: Path, **overrides: object) -> Settings:
    return http_settings(
        tmp_path,
        **{
            "MCP_HOSTED_TTS_ENABLED": True,
            "TOS_ACCESS_KEY": "synthetic-tts-ak",
            "TOS_SECRET_KEY": "synthetic-tts-sk",  # pragma: allowlist secret
            "TOS_BUCKET": BUCKET,
            **overrides,
        },
    )


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.pre_signed_url.side_effect = lambda *args, **kwargs: SimpleNamespace(
        signed_url=(
            f"https://{kwargs['bucket']}.tos-ap-southeast-1.bytepluses.com/"
            f"{kwargs['key']}?signature=synthetic"
        )
    )
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr("ark_mcp.providers.tos.client.tos.TosClientV2", constructor)
    client.constructor = constructor
    return client


@pytest.mark.parametrize(
    "overrides",
    [
        {"MCP_TRANSPORT": "stdio"},
        {"TOS_ACCESS_KEY": "", "TOS_SECRET_KEY": ""},
        {"TOS_BUCKET": ""},
        {"TOS_BUCKET": "bad.bucket"},
        {"TOS_REGION": "bad"},
        {"TOS_ENDPOINT": "http://tos-ap-southeast-1.bytepluses.com"},
        {"TOS_ENDPOINT": "https://untrusted.example"},
        {"TOS_CREDENTIAL_MODE": "irsa"},
        {"OBJECT_STORAGE_BACKEND": "s3"},
    ],
)
def test_hosted_tts_invalid_storage_fails_at_startup(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValidationError):
        tts_settings(tmp_path, **overrides)


@respx.mock
async def test_discovery_is_anonymous_and_never_opens_storage(
    tmp_path: Path, sdk: MagicMock
) -> None:
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, runtime, client):
        tools = (await rpc(client, "tools/list"))["result"]["tools"]
        assert len(tools) == 8
        assert "seed_tts_generate" in {tool["name"] for tool in tools}
        assert "media_prepare_upload" not in {tool["name"] for tool in tools}
        discovery = successful(await call_tool(client, "ark_list_models", {"kind": "audio"}))
        assert discovery["models"][0]["model_id"] == "dola-seed-tts-3.0"
        assert next(s for s in discovery["services"] if s["service"] == "seed_tts")["enabled"]
        assert discovery["connection"] is None
        assert runtime.budget_ledger is None
        assert (await client.get("/ready")).status_code == 200
        preflight = await call_tool(
            client, "ark_list_models", {"kind": "audio", "check_connection": True}
        )
        assert_denied(preflight)
    sdk.constructor.assert_not_called()
    assert not respx.calls
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "encoding,mime", [("mp3", "audio/mpeg"), ("pcm", "audio/pcm"), ("ogg_opus", "audio/ogg")]
)
@respx.mock
async def test_http_tts_returns_private_download_without_local_state(
    tmp_path: Path, sdk: MagicMock, encoding: str, mime: str
) -> None:
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic audio"), FINAL))
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, runtime, client):
        result = successful(
            await call_tool(
                client,
                "seed_tts_generate",
                INPUT | {"output_format": {"format": encoding}},
                headers=HEADERS,
            )
        )
        assert runtime.budget_ledger is None
    artifact = result["artifact"]
    assert artifact["uri"].startswith(
        f"https://{BUCKET}.tos-ap-southeast-1.bytepluses.com/tts-output/"
    )
    assert artifact["bytes"] == len(b"synthetic audio")
    assert artifact["mime_type"] == mime
    assert artifact["fallback_data"] is None
    assert artifact["local_path"] is None
    assert artifact["persistence_error"] is None
    assert (
        datetime.fromisoformat(artifact["source_expires_at"])
        - datetime.fromisoformat(artifact["created_at"])
    ).total_seconds() == 86400
    put = sdk.put_object.call_args.kwargs
    assert put["content"] == b"synthetic audio"
    assert put["content_type"] == mime
    assert put["acl"] == ACLType.ACL_Private
    assert put["storage_class"] == StorageClassType.Storage_Class_Standard
    assert put["object_expires"] == 1
    assert put["forbid_overwrite"] is True
    assert put["cache_control"] == "private, no-store"
    assert sdk.pre_signed_url.call_args.kwargs["expires"] == 86400
    assert sdk.pre_signed_url.call_args.kwargs["key"] == put["key"]
    assert sdk.constructor.call_args.kwargs["max_retry_count"] == 0
    assert route.calls.last.request.headers["X-Api-Key"] == SPEECH_KEY
    assert route.call_count == sdk.put_object.call_count == 1
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("headers", [{}, credentials(), {"X-Seed-Speech-Api-Key": SPEECH_KEY}])
@respx.mock
async def test_tts_requires_live_speech_key_and_client_secret(
    tmp_path: Path, sdk: MagicMock, headers: dict
) -> None:
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        assert_denied(await call_tool(client, "seed_tts_generate", INPUT, headers=headers))
    assert not respx.calls
    sdk.constructor.assert_not_called()


@pytest.mark.parametrize(
    "extra", [{"output_path": "/tmp/forbidden.mp3"}, {"overwrite": True}, {"persist": True}]
)
@respx.mock
async def test_local_options_fail_before_synthesis(
    tmp_path: Path, sdk: MagicMock, extra: dict
) -> None:
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        assert_denied(await call_tool(client, "seed_tts_generate", INPUT | extra, headers=HEADERS))
    assert not respx.calls
    sdk.constructor.assert_not_called()


@respx.mock
async def test_tts_never_retries_synthesis_after_storage_failure(
    tmp_path: Path, sdk: MagicMock
) -> None:
    sdk.put_object.side_effect = RuntimeError(f"secret {SPEECH_KEY} {CLIENT_SECRET}")
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic"), FINAL))
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        result = await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS)
    assert_denied(result)
    text = result["result"]["content"][0]["text"]
    assert "TTS_DELIVERY_FAILED" in text
    assert "Synthesis completed" in text
    assert "retryable=False" in text and "ambiguous_completion=False" in text
    assert route.calls.last.request.headers["X-Request-Id"] in text
    assert SPEECH_KEY not in text and CLIENT_SECRET not in text
    assert route.call_count == sdk.put_object.call_count == 1
    sdk.close.assert_called_once()


@respx.mock
async def test_output_keys_separate_clients_and_calls(tmp_path: Path, sdk: MagicMock) -> None:
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic"), FINAL))
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        for secret in (CLIENT_SECRET, CLIENT_SECRET, OTHER_SECRET):
            successful(
                await call_tool(
                    client,
                    "seed_tts_generate",
                    INPUT,
                    headers=credentials(SPEECH_KEY, secret, header="X-Seed-Speech-Api-Key"),
                )
            )
    keys = [call.kwargs["key"] for call in sdk.put_object.call_args_list]
    assert len(set(keys)) == 3
    assert keys[0].split("/")[1] == keys[1].split("/")[1]
    assert keys[1].split("/")[1] != keys[2].split("/")[1]
    assert all(SPEECH_KEY not in key and CLIENT_SECRET not in key for key in keys)
    assert route.call_count == 3


@respx.mock
async def test_admission_stays_held_until_upload_finishes(
    tmp_path: Path, sdk: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def upload(**kwargs: object) -> str:
        entered.set()
        await release.wait()
        return "https://synthetic.example/tts"

    monkeypatch.setattr(TosGateway, "upload_tts_output", AsyncMock(side_effect=upload))
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic"), FINAL))
    config = tts_settings(tmp_path, PROVIDER_MAX_CONCURRENCY=1, MCP_ADMISSION_TIMEOUT_SECONDS=0.02)
    async with http_server(tmp_path, settings=config) as (_, _, client):
        first = asyncio.create_task(call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            rejected = await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS)
            assert_denied(rejected)
            assert "ADMISSION_TIMEOUT" in str(rejected)
            assert route.call_count == 1
        finally:
            release.set()
        successful(await first)


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic-tts-output.tos-ap-southeast-1.bytepluses.com/wrong?signature=x",
        "https://untrusted.example/output?signature=x",
        "https://synthetic-tts-output.tos-ap-southeast-1.bytepluses.com/wrong?signature=x",
    ],
)
@respx.mock
async def test_invalid_signed_destination_never_uploads(
    tmp_path: Path, sdk: MagicMock, url: str
) -> None:
    sdk.pre_signed_url.side_effect = None
    sdk.pre_signed_url.return_value = SimpleNamespace(signed_url=url)
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic"), FINAL))
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        result = await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS)
    assert_denied(result)
    assert "TTS_DELIVERY_FAILED" in str(result) and url not in str(result)
    sdk.put_object.assert_not_called()
    assert route.call_count == 1


@respx.mock
async def test_provider_rejection_cannot_spend_operator_storage(
    tmp_path: Path, sdk: MagicMock
) -> None:
    route = respx.post(URL).respond(403, json={"error": {"code": "denied"}})
    async with http_server(tmp_path, settings=tts_settings(tmp_path)) as (_, _, client):
        assert_denied(await call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS))
    assert route.call_count == 1
    sdk.constructor.assert_not_called()


@pytest.mark.parametrize("termination", ["cancel", "deadline"])
@respx.mock
async def test_upload_drains_before_cancellation_and_keeps_deadline_request_id(
    tmp_path: Path, sdk: MagicMock, termination: str
) -> None:
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def put(**kwargs: object) -> None:
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)

    sdk.put_object.side_effect = put
    route = respx.post(URL).respond(200, content=wire(READY, audio(b"synthetic"), FINAL))
    settings = tts_settings(
        tmp_path, MCP_TOOL_TIMEOUT_SECONDS=0.1 if termination == "deadline" else 10
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        call = asyncio.create_task(call_tool(client, "seed_tts_generate", INPUT, headers=HEADERS))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if termination == "cancel":
                call.cancel()
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(0.15)
            assert not call.done()
            release.set()
            if termination == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await call
            else:
                result = await call
                assert_denied(result)
                assert "TOOL_DEADLINE_EXCEEDED" in str(result)
                assert route.calls.last.request.headers["X-Request-Id"] in str(result)
        finally:
            release.set()
        assert route.call_count == sdk.put_object.call_count == 1
        sdk.close.assert_called_once()
