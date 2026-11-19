"""Offline live-request coverage for the opt-in, stateless TOS signing tool."""

import asyncio
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.tools._catalog import CATALOG
from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    OTHER_SECRET,
    PUBLIC_TOOLS,
    assert_denied,
    call_tool,
    http_server,
    rpc,
    successful,
)
from tests.unit.test_temporary_upload import upload_settings

INPUT = {"media_type": "image", "mime_type": "image/png", "size_bytes": 1234}
HEADERS = {"X-MCP-Client-Secret": CLIENT_SECRET}


@pytest.mark.parametrize("enabled", [False, True])
async def test_http_upload_inventory_and_instructions(tmp_path: Path, enabled: bool) -> None:
    settings = upload_settings(
        tmp_path,
        MCP_TEMPORARY_UPLOAD_ENABLED=enabled,
    )
    async with http_server(tmp_path, settings=settings) as (server, runtime, client):
        tools = (await rpc(client, "tools/list"))["result"]["tools"]
        expected = PUBLIC_TOOLS
        if enabled:
            expected |= {"media_prepare_upload"}
        assert {tool["name"] for tool in tools} == expected
        assert ("media_prepare_upload" in server.instructions) is enabled
        discovery = successful(await call_tool(client, "ark_list_models", {}))
        storage = next(row for row in discovery["services"] if row["service"] == "object_storage")
        assert storage["enabled"] is enabled
        assert runtime.budget_ledger is None
        assert (await rpc(client, "resources/list"))["result"]["resources"] == []
        assert (await client.get("/ready")).json() == {"status": "ready"}
    assert not (tmp_path / "artifacts").exists()
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_prepare_upload_is_never_a_stdio_tool() -> None:
    entry = next(entry for entry in CATALOG if entry.name == "media_prepare_upload")
    assert not entry.gate(
        Settings.model_construct(mcp_transport="stdio", temporary_upload_enabled=True)
    )


@pytest.mark.parametrize("headers", [None, {"X-MCP-Client-Secret": OTHER_SECRET}])
async def test_denied_clients_do_not_construct_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, headers: dict | None
) -> None:
    gateway = AsyncMock()
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", gateway)
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, _, client):
        result = await call_tool(client, "media_prepare_upload", INPUT, headers=headers)
        assert_denied(result)
        assert "enrollment" in str(result)
    gateway.assert_not_called()


async def test_enrolled_client_signs_without_provider_key_and_gets_new_keys(tmp_path: Path) -> None:
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, _, client):
        outputs = [
            successful(await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS))
            for _ in range(2)
        ]
    first, second = outputs
    assert first["object_key"] != second["object_key"]
    assert first["object_key"].split("/")[1] == second["object_key"].split("/")[1]
    assert first["object_key"].startswith("temporary-references/")
    assert first["form_fields"]["key"] == first["object_key"]
    assert first["method"] == "POST" and first["file_field"] == "file"
    assert first["size_bytes"] == INPUT["size_bytes"] and first["object_expires_days"] == 1
    assert (
        datetime.fromisoformat(first["reference_expires_at"])
        - datetime.fromisoformat(first["upload_expires_at"])
    ).total_seconds() == 86400 - 900
    assert CLIENT_SECRET not in str(outputs)


@pytest.mark.parametrize("extra", [{"file_path": "/tmp/file.png"}, {"expires": 60}])
async def test_extra_inputs_fail_before_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: dict
) -> None:
    gateway = AsyncMock()
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", gateway)
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, _, client):
        assert_denied(
            await call_tool(client, "media_prepare_upload", {**INPUT, **extra}, headers=HEADERS)
        )
    gateway.assert_not_called()


async def test_upload_rejects_native_task_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = AsyncMock()
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", gateway)
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, _, client):
        result = await rpc(
            client,
            "tools/call",
            {
                "name": "media_prepare_upload",
                "arguments": {"input": INPUT},
                "_meta": {"io.modelcontextprotocol/tasks": {}},
            },
            headers=HEADERS,
            task_capable=True,
        )
        assert_denied(result)
    gateway.assert_not_called()


async def test_signing_failures_are_sanitized_and_gateway_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tos.exceptions import TosClientError

    from ark_mcp.providers.tos.client import _normalize_client_error

    gateway = AsyncMock()
    gateway.prepare_upload.side_effect = _normalize_client_error(
        TosClientError("synthetic-upload-sk synthetic-sts-token"), "prepare_upload"
    )
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", lambda: gateway)
    async with http_server(tmp_path, settings=upload_settings(tmp_path)) as (_, _, client):
        result = await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS)
        assert_denied(result)
        assert "check TOS configuration" in str(result)
        assert "synthetic-upload-sk" not in str(result)
        assert "synthetic-sts-token" not in str(result)
    gateway.close.assert_awaited_once()


async def test_upload_enrollment_is_isolated_between_server_instances(tmp_path: Path) -> None:
    import hashlib

    async with AsyncExitStack() as stack:
        clients = []
        for index, secret in enumerate((CLIENT_SECRET, OTHER_SECRET)):
            settings = upload_settings(
                tmp_path / str(index),
                MCP_UPLOAD_CLIENT_SECRET_SHA256=hashlib.sha256(secret.encode("ascii")).hexdigest(),
            )
            _, _, client = await stack.enter_async_context(
                http_server(tmp_path / str(index), settings=settings)
            )
            clients.append(client)
        successful(await call_tool(clients[0], "media_prepare_upload", INPUT, headers=HEADERS))
        assert_denied(await call_tool(clients[1], "media_prepare_upload", INPUT, headers=HEADERS))
        successful(await call_tool(clients[0], "media_prepare_upload", INPUT, headers=HEADERS))


async def test_upload_admission_timeout_does_not_construct_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = AsyncMock()
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", gateway)
    settings = upload_settings(
        tmp_path,
        PROVIDER_MAX_CONCURRENCY=1,
        MCP_ADMISSION_TIMEOUT_SECONDS=0.02,
    )
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        limiter = runtime.provider_limiters.provider("tos")
        await limiter.acquire()
        try:
            result = await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS)
            assert_denied(result)
            assert "ADMISSION_TIMEOUT" in str(result)
            assert "did not dispatch" in str(result)
            gateway.assert_not_called()
        finally:
            limiter.release()
        assert not limiter.locked()


async def test_upload_deadline_closes_gateway_and_releases_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = AsyncMock()
    blocked = asyncio.Event()

    async def sign(**kwargs: object) -> None:
        await blocked.wait()

    gateway.prepare_upload.side_effect = sign
    monkeypatch.setattr("ark_mcp.providers.tos.client.TosGateway", lambda: gateway)
    settings = upload_settings(tmp_path, MCP_TOOL_TIMEOUT_SECONDS=0.05, PROVIDER_MAX_CONCURRENCY=1)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        result = await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS)
        assert_denied(result)
        assert "TOOL_DEADLINE_EXCEEDED" in str(result)
        gateway.prepare_upload.assert_awaited_once()
        gateway.close.assert_awaited_once()
        assert not runtime.provider_limiters.provider("tos").locked()
