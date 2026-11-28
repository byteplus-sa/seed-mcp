"""Live ASGI credential isolation for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import Context, copy_context
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.server.dependencies import get_context

from ark_mcp.config.env import Settings
from ark_mcp.runtime import RuntimeServices, create_runtime_services
from ark_mcp.security.credentials import (
    provider_api_key,
    request_principal,
)
from ark_mcp.server import create_server

MODELARK = "https://ark.ap-southeast.bytepluses.com/api/v3"
SPEECH = "https://voice.ap-southeast-1.bytepluses.com"
VIDEO_MODEL = "dreamina-seedance-2-5-260628"
IMAGE_MODEL = "dola-seedream-5-5-261028"
MODELARK_KEY = "synthetic-modelark-canary!+/="
SPEECH_KEY = "synthetic-speech-canary!+/="
CLIENT_SECRET = "b1" * 32  # pragma: allowlist secret
OTHER_SECRET = "c2" * 32  # pragma: allowlist secret
HMAC_KEY = "d3" * 32
OPERATOR_KEY = "synthetic-operator-never-dispatch"
CANARIES = (MODELARK_KEY, SPEECH_KEY, CLIENT_SECRET, HMAC_KEY, OPERATOR_KEY)
PUBLIC_TOOLS = {
    "ark_list_models",
    "seedream_generate_image",
    "seedance_create_task",
    "gen_task_get",
    "gen_task_list",
    "gen_task_cancel_or_delete",
    "seed_audio_generate",
    "seed_tts_generate",
}


def http_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "MCP_TRANSPORT": "http",
            "MCP_HOST": "127.0.0.1",
            "MCP_IDENTITY_HMAC_KEY": HMAC_KEY,
            "MCP_ALLOWED_HOSTS": "testserver",
            "MCP_ALLOWED_ORIGINS": "https://client.example.com",
            "ARTIFACT_DIR": str(tmp_path / "artifacts"),
            "BYTEPLUS_MODELARK_BASE_URL": MODELARK,
            "BYTEPLUS_SEED_AUDIO_BASE_URL": SPEECH,
            "SEEDANCE_DEFAULT_MODEL": VIDEO_MODEL,
            "SEEDREAM_DEFAULT_MODEL": IMAGE_MODEL,
            "RATE_LIMIT_RPM": 600,
            **overrides,
        },
    )


def credentials(
    key: str = MODELARK_KEY,
    secret: str = CLIENT_SECRET,
    *,
    header: str = "X-ModelArk-Api-Key",
) -> dict[str, str]:
    return {header: key, "X-MCP-Client-Secret": secret}


@asynccontextmanager
async def http_server(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    app_options: dict[str, Any] | None = None,
) -> AsyncIterator[tuple[FastMCP, RuntimeServices, httpx.AsyncClient]]:
    runtimes: list[RuntimeServices] = []

    async def factory(config: Settings) -> RuntimeServices:
        runtime = await create_runtime_services(config)
        runtimes.append(runtime)
        return runtime

    server = create_server(settings or http_settings(tmp_path), runtime_factory=factory)
    app = server.http_app(path="/mcp", json_response=True, **(app_options or {}))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        yield server, runtimes[0], client


async def rpc(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    task_capable: bool = False,
    expected_status: int = 200,
) -> dict[str, Any]:
    params = dict(params or {})
    meta = dict(params.pop("_meta", {}))
    meta.update(
        {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": (
                {"extensions": {"io.modelcontextprotocol/tasks": {}}} if task_capable else {}
            ),
        }
    )
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "Mcp-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
        "Origin": "https://client.example.com",
    }
    name = params.get("name", params.get("taskId", params.get("uri")))
    if name is not None:
        request_headers["Mcp-Name"] = name
    response = await client.post(
        "/mcp",
        headers={**request_headers, **(headers or {})},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {**params, "_meta": meta},
        },
    )
    assert response.status_code == expected_status, response.text
    assert "mcp-session-id" not in response.headers
    return cast("dict[str, Any]", response.json())


async def call_tool(
    client: httpx.AsyncClient,
    name: str,
    input_data: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    task_capable: bool = False,
) -> dict[str, Any]:
    return await rpc(
        client,
        "tools/call",
        {"name": name, "arguments": {"input": input_data} if input_data is not None else {}},
        headers=headers,
        task_capable=task_capable,
    )


def successful(result: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in result, result
    assert result["result"].get("isError", False) is False, result
    assert "taskId" not in result["result"], result
    return cast("dict[str, Any]", result["result"]["structuredContent"])


def assert_denied(result: dict[str, Any]) -> None:
    assert "error" in result or result.get("result", {}).get("isError") is True, result
    assert "taskId" not in result.get("result", {})


def assert_no_canaries(text: str) -> None:
    from urllib.parse import quote

    for canary in CANARIES:
        assert canary not in text
        assert quote(canary, safe="") not in text


@pytest.mark.parametrize("header", ["X-ModelArk-Api-Key", "X-Seed-Speech-Api-Key"])
@pytest.mark.parametrize(
    ("name", "input_data"),
    [
        ("seedream_generate_image", {"prompt": "square"}),
        ("seedream_generate_image", {"prompt": "square", "dry_run": True}),
        ("ark_list_models", {"check_connection": True}),
        (
            "media_prepare_upload",
            {"media_type": "image", "mime_type": "image/png", "size_bytes": 1234},
        ),
    ],
)
@respx.mock
async def test_credential_reuse_returns_safe_http_error_before_tool_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    header: str,
    name: str,
    input_data: dict[str, Any],
) -> None:
    from tests.unit.test_temporary_upload import upload_settings

    gateway = Mock()
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", gateway)
    caplog.set_level(logging.DEBUG)
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, runtime, client):
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": name,
                "Origin": "https://client.example.com",
                **credentials(),
                header: CLIENT_SECRET,
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {"input": input_data},
                    "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                },
            },
        )
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text.startswith("CREDENTIAL_REUSE:")
        assert "X-MCP-Client-Secret" in response.text
        assert "32 random bytes" in response.text
        assert "64 lowercase hex characters" in response.text
        assert "Keep your provider API keys unchanged" in response.text
        assert "rejected before tool execution" in response.text
        assert runtime.tos_credentials is None
        assert len(respx.calls) == 0
        successful(await call_tool(client, "ark_list_models", {}))
    gateway.assert_not_called()
    assert len(respx.calls) == 0
    assert_no_canaries(response.text + caplog.text + capsys.readouterr().err)
    assert not (tmp_path / "artifacts").exists()


@respx.mock
async def test_anonymous_catalog_and_resources_are_static(tmp_path: Path) -> None:
    settings = http_settings(tmp_path)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        anonymous = await rpc(client, "tools/list")
        authenticated = await rpc(client, "tools/list", headers=credentials())
        assert anonymous == authenticated
        tools = anonymous["result"]["tools"]
        expected = PUBLIC_TOOLS
        assert {tool["name"] for tool in tools} == expected
        assert len(tools) == 8
        assert (await rpc(client, "resources/list"))["result"]["resources"] == []
        assert (await rpc(client, "resources/templates/list"))["result"]["resourceTemplates"] == []
        discovery = successful(await call_tool(client, "ark_list_models", {}))
        assert discovery
        assert_no_canaries(json.dumps([anonymous, discovery]))
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    ("name", "input_data", "header", "key"),
    [
        ("seedream_generate_image", {"prompt": "square"}, "X-ModelArk-Api-Key", MODELARK_KEY),
        ("seed_audio_generate", {"text_prompt": "tone"}, "X-Seed-Speech-Api-Key", SPEECH_KEY),
    ],
)
@respx.mock
async def test_only_selected_customer_key_is_sent_to_official_origin(
    tmp_path: Path, name: str, input_data: dict[str, Any], header: str, key: str
) -> None:
    routes = {
        "seedream_generate_image": (
            f"{MODELARK}/images/generations",
            {"data": [{"url": "https://example.com/image.png"}]},
        ),
        "seed_audio_generate": (
            f"{SPEECH}/api/v3/tts/create",
            {"code": 0, "url": "https://example.com/audio.wav"},
        ),
    }
    url, body = routes[name]
    route = respx.post(url).respond(200, json=body)
    settings = http_settings(
        tmp_path,
        BYTEPLUS_MODELARK_API_KEY=OPERATOR_KEY,
        BYTEPLUS_SEED_SPEECH_API_KEY=OPERATOR_KEY,
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        result = successful(
            await call_tool(client, name, input_data, headers=credentials(key, header=header))
        )
    assert route.call_count == len(respx.calls) == 1
    request = route.calls[0].request
    if name == "seed_audio_generate":
        assert request.headers["X-Api-Key"] == key
        assert "Authorization" not in request.headers
    else:
        assert request.headers["Authorization"] == f"Bearer {key}"
    assert "X-MCP-Client-Secret" not in request.headers
    assert "X-ModelArk-Api-Key" not in request.headers
    assert CLIENT_SECRET not in request.content.decode()
    assert OPERATOR_KEY not in str(request.headers)
    assert_no_canaries(json.dumps(result))


@pytest.mark.parametrize(
    ("output", "expected_mime"),
    [
        ({}, "audio/wav"),
        ({"format": "wav"}, "audio/wav"),
        ({"format": "mp3"}, "audio/mpeg"),
        ({"format": "ogg"}, "audio/ogg"),
        ({"format": "pcm"}, "audio/pcm"),
    ],
)
@pytest.mark.parametrize("variations", [1, 2])
@respx.mock
async def test_http_audio_format_metadata_and_controls(
    tmp_path: Path, output: dict[str, Any], expected_mime: str, variations: int
) -> None:
    controls = {**output, "sample_rate": 24000, "subtitle": True, "subtitle_type": "word"}
    route = respx.post(f"{SPEECH}/api/v3/tts/create").respond(
        200, json={"code": 0, "url": "https://example.com/audio"}
    )
    async with http_server(tmp_path) as (_, _, client):
        result = successful(
            await call_tool(
                client,
                "seed_audio_generate",
                {"text_prompt": "tone", "output": controls, "variations": variations},
                headers=credentials(SPEECH_KEY, header="X-Seed-Speech-Api-Key"),
            )
        )
    artifacts = (
        [result["artifact"]]
        if variations == 1
        else [item["artifact"] for item in result["summary"]["variations"]]
    )
    assert all(artifact["mime_type"] == expected_mime for artifact in artifacts)
    assert all(artifact["id"] == "provider-url" for artifact in artifacts)
    assert result["subtitle"] is None
    assert route.call_count == len(respx.calls) == variations
    for call in route.calls:
        assert json.loads(call.request.content)["audio_config"] == controls
        assert call.request.headers["X-Api-Key"] == SPEECH_KEY
        assert "X-MCP-Client-Secret" not in call.request.headers
    assert_no_canaries(json.dumps(result))
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize(
    ("name", "input_data"),
    [
        ("seedream_generate_image", {"prompt": "square"}),
        ("seedream_generate_image", {"prompt": "square", "dry_run": True}),
        ("seedance_create_task", {"prompt": "scene", "dry_run": True}),
        ("seed_audio_generate", {"text_prompt": "tone"}),
    ],
)
@pytest.mark.parametrize("supplied", ["none", "key_only", "secret_only", "wrong_provider"])
@respx.mock
async def test_missing_credentials_never_fall_back_to_operator(
    tmp_path: Path, name: str, input_data: dict[str, Any], supplied: str
) -> None:
    selected = "X-Seed-Speech-Api-Key" if name == "seed_audio_generate" else "X-ModelArk-Api-Key"
    headers = {
        "none": {},
        "key_only": {selected: MODELARK_KEY},
        "secret_only": {"X-MCP-Client-Secret": CLIENT_SECRET},
        "wrong_provider": credentials(
            SPEECH_KEY,
            header="X-ModelArk-Api-Key"
            if selected != "X-ModelArk-Api-Key"
            else "X-Seed-Speech-Api-Key",
        ),
    }[supplied]
    settings = http_settings(
        tmp_path,
        BYTEPLUS_MODELARK_API_KEY=OPERATOR_KEY,
        BYTEPLUS_SEED_SPEECH_API_KEY=OPERATOR_KEY,
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        result = await call_tool(client, name, input_data, headers=headers)
        assert_denied(result)
        assert "Configure" in str(result)
        assert_no_canaries(json.dumps(result))
    assert len(respx.calls) == 0


@respx.mock
async def test_concurrent_customer_requests_keep_credentials_and_outputs_separate(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    seen: list[str] = []
    keys = ["synthetic-concurrent-first", "synthetic-concurrent-second"]

    async def generate(request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        seen.append(key)
        if len(seen) == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), 5)
        index = keys.index(key)
        return httpx.Response(200, json={"data": [{"url": f"https://example.com/{index}.png"}]})

    respx.post(f"{MODELARK}/images/generations").mock(side_effect=generate)
    async with http_server(tmp_path) as (_, _, client):
        results = await asyncio.gather(
            *(
                call_tool(
                    client,
                    "seedream_generate_image",
                    {"prompt": "square"},
                    headers=credentials(key),
                )
                for key in keys
            )
        )
    assert sorted(seen) == sorted(keys)
    assert [successful(result)["artifacts"][0]["uri"] for result in results] == [
        "https://example.com/0.png",
        "https://example.com/1.png",
    ]


@pytest.mark.parametrize("outcome", ["success", "transport_error", "cancel"])
@respx.mock
async def test_live_request_context_expires_even_when_copied(tmp_path: Path, outcome: str) -> None:
    contexts: list[tuple[Context, Any]] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def generate(request: httpx.Request) -> httpx.Response:
        contexts.append((copy_context(), get_context()))
        assert provider_api_key(get_context(), "modelark") == MODELARK_KEY
        entered.set()
        if outcome == "cancel":
            await release.wait()
        if outcome == "transport_error":
            raise httpx.ReadError("synthetic request failure", request=request)
        return httpx.Response(200, json={"data": [{"url": "https://example.com/image.png"}]})

    respx.post(f"{MODELARK}/images/generations").mock(side_effect=generate)
    async with http_server(tmp_path) as (_, _, client):
        pending = asyncio.create_task(
            call_tool(
                client, "seedream_generate_image", {"prompt": "square"}, headers=credentials()
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if outcome == "cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                result = await pending
                if outcome == "success":
                    successful(result)
                else:
                    assert_denied(result)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        assert len(contexts) == 1
        copied, ctx = contexts[0]
        with pytest.raises(PermissionError):
            copied.run(request_principal)
        with pytest.raises(PermissionError):
            copied.run(provider_api_key, ctx, "modelark")
        with pytest.raises(PermissionError):
            request_principal()
        assert_denied(await call_tool(client, "seedream_generate_image", {"prompt": "square"}))
    assert len(contexts) == 1


@respx.mock
async def test_in_memory_http_server_cannot_reuse_restored_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restored = Mock(return_value=credentials())
    monkeypatch.setattr("fastmcp.server.dependencies.get_http_headers", restored)
    server = create_server(http_settings(tmp_path, BYTEPLUS_MODELARK_API_KEY=OPERATOR_KEY))
    async with Client(server) as client:
        result = await client.call_tool(
            "seedream_generate_image", {"input": {"prompt": "square"}}, raise_on_error=False
        )
    assert result.is_error
    restored.assert_not_called()
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    ("name", "input_data"),
    [
        ("seedream_generate_image", {"prompt": "square", "persist": True}),
        ("seed_audio_generate", {"text_prompt": "tone", "persist": True}),
        ("gen_task_get", {"task_ids": ["private"], "persist_output": True}),
        ("seedream_generate_image", {"prompt": "square", "output_path": "/tmp/private.png"}),
    ],
)
@respx.mock
async def test_http_persistence_and_server_files_are_denied_before_dispatch(
    tmp_path: Path, name: str, input_data: dict[str, Any]
) -> None:
    headers = {
        **credentials(),
        "X-Seed-Speech-Api-Key": SPEECH_KEY,
    }
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(await call_tool(client, name, input_data, headers=headers))
    assert len(respx.calls) == 0


@respx.mock
async def test_url_only_result_does_not_write_artifacts_or_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.post(f"{MODELARK}/images/generations").respond(
        200, json={"data": [{"url": "https://example.com/image.png"}]}
    )
    async with http_server(tmp_path) as (_, runtime, client):
        store = runtime.artifact_store
        writes = [AsyncMock(), AsyncMock(), AsyncMock()]
        monkeypatch.setattr(store, "put_base64", writes[0])
        monkeypatch.setattr(store, "copy_from_trusted_url", writes[1])
        monkeypatch.setattr(runtime.task_artifact_cache, "set", writes[2])
        result = successful(
            await call_tool(
                client, "seedream_generate_image", {"prompt": "square"}, headers=credentials()
            )
        )
        assert result["artifacts"][0]["uri"] == "https://example.com/image.png"
        assert result["artifacts"][0]["fallback_data"] is None
        for write in writes:
            write.assert_not_called()
    assert not list(tmp_path.rglob("*.meta.json"))
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert_no_canaries(path.read_bytes().decode("latin-1"))


@pytest.mark.parametrize("failure", ["provider_error", "transport_error"])
@respx.mock
async def test_canary_credentials_stay_out_of_results_logs_spans_and_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    spans: list[tuple[str, dict[str, Any], Mock]] = []
    exceptions: list[str] = []

    @contextmanager
    def span_context(name: str, **options: Any) -> Iterator[Mock]:
        span = Mock()
        span.attributes = dict(options.get("attributes") or {})
        span.dropped_attributes = 0
        span.is_recording.return_value = True
        span.record_exception.side_effect = lambda exc: exceptions.append(
            "".join(traceback.format_exception(exc))
        )
        spans.append((name, options, span))
        try:
            yield span
        except Exception as exc:
            if options.get("record_exception", True):
                span.record_exception(exc)
            raise

    tracer = Mock()
    tracer.start_as_current_span.side_effect = span_context
    monkeypatch.setattr("fastmcp.telemetry.otel_get_tracer", lambda *args, **kwargs: tracer)
    caplog.set_level(logging.DEBUG)
    detail = " ".join((MODELARK_KEY, SPEECH_KEY, CLIENT_SECRET))
    route = respx.post(f"{MODELARK}/images/generations")
    if failure == "transport_error":
        route.mock(side_effect=httpx.ReadError(detail))
    else:
        route.respond(
            400,
            json={"error": {"code": "SYNTHETIC_DENIED", "message": detail}},
            headers={"X-Request-Id": CLIENT_SECRET},
        )
    async with http_server(tmp_path) as (_, _, client):
        response = await call_tool(
            client,
            "seedream_generate_image",
            {"prompt": "square"},
            headers={
                **credentials(),
                "X-Seed-Speech-Api-Key": SPEECH_KEY,
            },
        )
        assert_denied(response)
    assert route.call_count == 1
    assert any(name.startswith("provider.") for name, _, _ in spans)
    assert any(not name.startswith("provider.") for name, _, _ in spans)
    assert any(record.name.startswith(("fastmcp", "mcp")) for record in caplog.records)
    output = json.dumps(response) + caplog.text + capsys.readouterr().err
    output += str([(name, options, span.mock_calls) for name, options, span in spans])
    output += "".join(exceptions)
    assert_no_canaries(output)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert_no_canaries(path.read_bytes().decode("latin-1"))
