from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult

from ark_mcp.observability import metrics


@pytest.fixture
def instruments(monkeypatch):
    counters = {name: Mock() for name in ("TOOL_REQUESTS", "TOOL_DURATION")}
    for name, counter in counters.items():
        monkeypatch.setattr(metrics, name, counter)
    return counters


async def test_direct_middleware_records_one_success(instruments):
    async def measured(value: int = 1) -> int:
        return value

    server = FastMCP(middleware=[metrics.MetricsMiddleware()])
    server.tool(name="media_presign")(measured)
    async with Client(server) as client:
        assert (await client.call_tool("media_presign", {"value": 9})).data == 9
    instruments["TOOL_REQUESTS"].labels.assert_called_once_with(
        tool="media_presign", status="success"
    )
    instruments["TOOL_DURATION"].labels.return_value.observe.assert_called_once()


@pytest.mark.parametrize("outcome", ["success", "error", "exception"])
async def test_direct_client_records_terminal_outcome_once(instruments, outcome):
    async def measured() -> ToolResult:
        if outcome == "exception":
            raise ValueError("synthetic failure")
        return ToolResult(content="result", is_error=outcome == "error")

    server = FastMCP(middleware=[metrics.MetricsMiddleware()])
    server.tool(name="seedream_generate_image")(measured)
    async with Client(server) as client:
        result = await client.call_tool("seedream_generate_image", {}, raise_on_error=False)
    assert result.is_error == (outcome != "success")
    instruments["TOOL_REQUESTS"].labels.assert_called_once_with(
        tool="seedream_generate_image", status=outcome
    )
    instruments["TOOL_DURATION"].labels.return_value.observe.assert_called_once()


async def test_direct_middleware_records_and_propagates_cancellation(instruments):
    started = asyncio.Event()
    middleware = metrics.MetricsMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="gen_task_get"))

    async def call_next(context):
        started.set()
        await asyncio.Event().wait()

    call = asyncio.create_task(middleware.on_call_tool(context, call_next))
    await asyncio.wait_for(started.wait(), timeout=5)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    instruments["TOOL_REQUESTS"].labels.assert_called_once_with(
        tool="gen_task_get", status="cancelled"
    )
    instruments["TOOL_DURATION"].labels.return_value.observe.assert_called_once()


async def test_direct_validation_failure_does_not_enter_handler(instruments):
    dispatch = AsyncMock()

    async def measured(value: int) -> int:
        await dispatch()
        return value

    server = FastMCP(middleware=[metrics.MetricsMiddleware()])
    server.tool(name="seedream_generate_image")(measured)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("seedream_generate_image", {"value": "invalid"})
    dispatch.assert_not_awaited()
    instruments["TOOL_REQUESTS"].labels.assert_called_once_with(
        tool="seedream_generate_image", status="exception"
    )
    instruments["TOOL_DURATION"].labels.return_value.observe.assert_called_once()


async def test_registered_direct_server_records_safe_pre_provider_failure(
    instruments, monkeypatch, tmp_path
):
    from ark_mcp.config.env import Settings
    from ark_mcp.providers.modelark.seedream import SeedreamService
    from ark_mcp.server import create_server

    build_request = Mock(side_effect=RuntimeError("private-pre-provider-sentinel"))
    generate = AsyncMock(side_effect=AssertionError("Invalid input reached the provider"))
    monkeypatch.setattr(SeedreamService, "build_request", build_request)
    monkeypatch.setattr(SeedreamService, "generate", generate)
    server = create_server(
        Settings(
            _env_file=None,
            BYTEPLUS_MODELARK_API_KEY="test-placeholder",  # pragma: allowlist secret
            ARTIFACT_DIR=str(tmp_path),
        )
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "seedream_generate_image", {"input": {"prompt": "square"}}, raise_on_error=False
        )
    assert result.is_error
    assert result.structured_content is None
    assert "private-pre-provider-sentinel" not in str(result)
    build_request.assert_called_once()
    generate.assert_not_awaited()
    instruments["TOOL_REQUESTS"].labels.assert_called_once_with(
        tool="seedream_generate_image", status="exception"
    )
    instruments["TOOL_DURATION"].labels.return_value.observe.assert_called_once()
