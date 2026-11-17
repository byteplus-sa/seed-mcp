"""Direct protocol boundary per specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

import pytest
import respx
from fastmcp import Client
from mcp.client.extension import advertise

from ark_mcp.config.env import Settings
from ark_mcp.server import create_server


async def test_local_server_does_not_register_native_tasks(tmp_path):
    server = create_server(
        Settings(_env_file=None, MCP_TRANSPORT="stdio", ARTIFACT_DIR=str(tmp_path))
    )
    async with Client(server) as client:
        assert "io.modelcontextprotocol/tasks" not in server._extensions
        assert all(tool.execution is None for tool in await client.list_tools())


@pytest.mark.parametrize(
    "name", ["ark_list_models", "seedream_generate_image", "seedance_create_task"]
)
@respx.mock
async def test_local_native_opt_in_is_rejected_without_provider_dispatch(tmp_path, name):
    server = create_server(
        Settings(
            _env_file=None,
            MCP_TRANSPORT="stdio",
            BYTEPLUS_MODELARK_API_KEY="synthetic-key",  # pragma: allowlist secret
            ARTIFACT_DIR=str(tmp_path),
        )
    )
    arguments = {"input": {}} if name == "ark_list_models" else {"input": {"prompt": "square"}}
    async with Client(server, extensions=[advertise("io.modelcontextprotocol/tasks")]) as client:
        result = await client.call_tool(
            name,
            arguments,
            raise_on_error=False,
        )
    assert result.is_error
    assert result.structured_content is None
    assert "tasks extension opt-in" in result.content[0].text
    assert len(respx.calls) == 0
