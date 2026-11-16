"""Frozen schema budgets for the 21 retained Seed Studio tools.

Measured with all four service gates enabled: 49,035 model-facing characters
and 92,334 output-schema characters. The budgets leave limited room for
description changes while preventing retired capabilities from returning.
"""

from __future__ import annotations

import json

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.server import create_server

MAX_TOOLS = 21
MAX_MODEL_FACING_CHARS = 52_000
MAX_OUTPUT_SCHEMA_CHARS = 96_000


@pytest.mark.parametrize("transport,tool_count", [("stdio", 21), ("http", 12)])
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
        ("omnihuman_get_task", "persist_output"),
    ):
        schema = tools[tool_name].parameters
        field = schema["properties"]["input"]["properties"][field_name]
        assert field["default"] is False, tool_name
        assert field["description"], tool_name
