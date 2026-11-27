"""Bounded schemas for 13 local tools, including stdio TTS and HTTP connection preflight.

The preflight adds about 2,900 output-schema characters and has its own size
guard. Removed job and understanding schemas cannot expand the inventory.
"""

from __future__ import annotations

import json

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.server import create_server
from ark_mcp.tools.ark_list_models import HttpConnectionCheck

MAX_TOOLS = 13
MAX_MODEL_FACING_CHARS = 60_000
MAX_OUTPUT_SCHEMA_CHARS = 100_000


def test_connection_output_has_a_bounded_schema_and_no_authentication_claim() -> None:
    schema = HttpConnectionCheck.model_json_schema()
    assert len(json.dumps(schema)) <= 3500
    assert schema["properties"]["authentication_verified"]["const"] is False
    assert schema["properties"]["provider_calls_made"]["const"] is False


@pytest.mark.parametrize("transport,tool_count", [("stdio", 13), ("http", 7)])
async def test_tool_schemas_stay_within_budget(
    all_services_enabled: None, transport: str, tool_count: int
) -> None:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT=transport,
        MCP_AUTH_MODE="byok" if transport == "http" else "local",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
    )
    tools = await create_server(settings).list_tools()
    model_facing = sum(
        len(tool.description or "") + len(json.dumps(tool.parameters)) for tool in tools
    )
    output = sum(len(json.dumps(tool.output_schema or {})) for tool in tools)

    assert len(tools) == tool_count <= MAX_TOOLS
    assert model_facing <= MAX_MODEL_FACING_CHARS, model_facing
    assert output <= MAX_OUTPUT_SCHEMA_CHARS, output


@pytest.mark.parametrize("transport", ["stdio", "http"])
async def test_published_persistence_defaults_are_opt_in(
    all_services_enabled: None, transport: str
) -> None:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT=transport,
        MCP_AUTH_MODE="byok" if transport == "http" else "local",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
    )
    tools = {tool.name: tool for tool in await create_server(settings).list_tools()}
    for tool_name, field_name in (
        ("seed_audio_generate", "persist"),
        ("seedream_generate_image", "persist"),
    ):
        schema = tools[tool_name].parameters
        field = schema["properties"]["input"]["properties"][field_name]
        assert field["default"] is False, tool_name
        assert field["description"], tool_name
