"""Key-only BYOK keeps authorization and bounded admission without client enrollment."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from tests.contract.test_seed_tts_adapter import FINAL, READY, audio, wire
from tests.integration.test_byok_http import (
    MODELARK,
    MODELARK_KEY,
    SPEECH,
    SPEECH_KEY,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)


@respx.mock
async def test_omitted_secret_shares_admission_and_explicit_secret_separates_it(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    dispatched: list[str] = []

    async def generate(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["prompt"]
        dispatched.append(prompt)
        if prompt == "blocked":
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"data": [{"url": "https://example.com/result.png"}]})

    respx.post(MODELARK + "/images/generations").mock(side_effect=generate)
    settings = http_settings(
        tmp_path, PRINCIPAL_MAX_CONCURRENCY=1, MCP_ADMISSION_TIMEOUT_SECONDS=0.02
    )
    key_only = credentials(secret=None)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        pending = asyncio.create_task(
            call_tool(client, "seedream_generate_image", {"prompt": "blocked"}, headers=key_only)
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            denied = await call_tool(
                client, "seedream_generate_image", {"prompt": "same-key"}, headers=key_only
            )
            assert_denied(denied)
            assert "ADMISSION_TIMEOUT" in str(denied)
            assert "same-key" not in dispatched
            for prompt, headers in (
                ("explicit-client", credentials()),
                ("different-key", credentials(key="synthetic-other-key", secret=None)),
            ):
                successful(
                    await call_tool(
                        client, "seedream_generate_image", {"prompt": prompt}, headers=headers
                    )
                )
        finally:
            release.set()
            await asyncio.wait_for(pending, 3)
        successful(
            await call_tool(
                client, "seedream_generate_image", {"prompt": "recovered"}, headers=key_only
            )
        )
    assert dispatched == ["blocked", "explicit-client", "different-key", "recovered"]


@respx.mock
async def test_tts_works_with_only_the_speech_key(tmp_path: Path) -> None:
    route = respx.post(SPEECH + "/api/v3/text-to-speech/test-voice/streaming").respond(
        200, content=wire(READY, audio(b"synthetic"), FINAL)
    )
    async with http_server(tmp_path) as (_, runtime, client):
        result = await call_tool(
            client,
            "seed_tts_generate",
            {"voice_id": "test-voice", "text": "Synthetic test."},
            headers=credentials(SPEECH_KEY, secret=None, header="X-Seed-Speech-Api-Key"),
        )
        successful(result)
        assert result["result"]["content"][0]["type"] == "audio"
        assert runtime.budget_ledger is None
    assert route.call_count == 1
    assert route.calls.last.request.headers["X-Api-Key"] == SPEECH_KEY
    assert "X-MCP-Client-Secret" not in route.calls.last.request.headers
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("secret", ["", "A" * 64, "short", "z" * 64, "a" * 65])
@respx.mock
async def test_invalid_optional_header_rejected_before_provider(
    tmp_path: Path, secret: str
) -> None:
    async with http_server(tmp_path) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers={"X-ModelArk-Api-Key": MODELARK_KEY, "X-MCP-Client-Secret": secret},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 400
        assert MODELARK_KEY not in response.text
    assert not respx.calls
