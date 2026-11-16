"""Frozen schema budgets for the 21 retained Seed Studio tools.

Measured with all four service gates enabled: 49,035 model-facing characters
and 92,334 output-schema characters. The budgets leave limited room for
description changes while preventing retired capabilities from returning.
"""

from __future__ import annotations

import json

from ark_mcp.config.env import get_settings
from ark_mcp.server import create_server

MAX_TOOLS = 21
MAX_MODEL_FACING_CHARS = 52_000
MAX_OUTPUT_SCHEMA_CHARS = 96_000


async def test_tool_schemas_stay_within_budget(all_services_enabled: None) -> None:
    tools = await create_server(get_settings()).list_tools()
    model_facing = sum(
        len(tool.description or "") + len(json.dumps(tool.parameters)) for tool in tools
    )
    output = sum(len(json.dumps(tool.output_schema or {})) for tool in tools)

    assert len(tools) <= MAX_TOOLS
    assert model_facing <= MAX_MODEL_FACING_CHARS, model_facing
    assert output <= MAX_OUTPUT_SCHEMA_CHARS, output
