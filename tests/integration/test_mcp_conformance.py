"""MCP protocol conformance tests.

Verifies tool discovery, inputSchema/outputSchema auto-generation,
ToolAnnotations propagation, resource template registration, and
conditional tool registration based on credentials.

These tests exercise the FastMCP layer directly — no provider calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ark_mcp.config.env import Settings, get_settings
from ark_mcp.server import create_server


@pytest.fixture
def configured_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set test env vars and re-register tools with fake credentials."""
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "sk-test")
    monkeypatch.setenv("TOS_ACCESS_KEY", "ak-test-tos")
    monkeypatch.setenv("TOS_SECRET_KEY", "sk-test-tos")
    monkeypatch.setenv("TOS_BUCKET", "test-bucket")

    # Clear cached settings.
    get_settings.cache_clear()

    yield SimpleNamespace(mcp=create_server(get_settings()))

    get_settings.cache_clear()


@pytest.fixture
def no_creds_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure server with no API keys set."""
    monkeypatch.delenv("BYTEPLUS_MODELARK_API_KEY", raising=False)
    monkeypatch.delenv("BYTEPLUS_SEED_SPEECH_API_KEY", raising=False)
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "")

    get_settings.cache_clear()

    yield SimpleNamespace(
        mcp=create_server(
            Settings(
                _env_file=None,
                BYTEPLUS_MODELARK_API_KEY="",
                BYTEPLUS_SEED_SPEECH_API_KEY="",
            )
        )
    )

    get_settings.cache_clear()


@pytest.fixture
def s3_only_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure server with S3-only object storage creds."""
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "sk-test")
    monkeypatch.setenv("S3_ACCESS_KEY", "ak-s3-test")
    monkeypatch.setenv("S3_SECRET_KEY", "sk-s3-test")
    monkeypatch.setenv("S3_BUCKET", "test-s3-bucket")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "s3")

    get_settings.cache_clear()

    yield SimpleNamespace(mcp=create_server(get_settings()))

    get_settings.cache_clear()


class TestToolDiscovery:
    """Verify configured tools are discoverable when credentials are set."""

    async def test_all_retained_tools_are_direct(
        self, configured_server: None, omnihuman_server: None
    ) -> None:
        tools = [
            *await configured_server.mcp.list_tools(),
            *await omnihuman_server.mcp.list_tools(),
        ]
        assert len({tool.name for tool in tools}) == 15
        for tool in tools:
            assert tool.task_config.mode == "forbidden"
            assert tool.to_mcp_tool().execution is None

    async def test_only_four_tools_are_always_registered(self, no_creds_server: None) -> None:
        assert {tool.name for tool in await no_creds_server.mcp.list_tools()} == {
            "ark_list_models",
            "seed_media_export_artifact",
            "seed_media_get_artifact",
            "seed_media_persist_url",
        }

    async def test_all_tools_registered(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "ark_list_models",
            "seed_audio_generate",
            "seed_media_export_artifact",
            "seed_media_get_artifact",
            "seed_media_persist_url",
            "seedream_generate_image",
            "seedance_create_task",
            "gen_task_get",
            "gen_task_list",
            "gen_task_cancel_or_delete",
            "media_upload",
            "media_presign",
        }

    async def test_seedance_4k_is_a_resolution_not_a_tool(
        self,
        configured_server: None,
    ) -> None:
        tools = await configured_server.mcp.list_tools()
        assert not {tool.name for tool in tools if "premium" in tool.name or "4k" in tool.name}
        tool = next(t for t in tools if t.name == "seedance_create_task")
        assert tool.task_config.mode == "forbidden"
        assert '"4k"' in json.dumps(tool.parameters)

    async def test_direct_tool_schemas_describe_public_fields(
        self,
        configured_server: None,
    ) -> None:
        tools = {tool.name: tool.to_mcp_tool() for tool in await configured_server.mcp.list_tools()}
        for tool_name in tools:
            tool = tools[tool_name]
            assert tool.description
            assert tool.output_schema is not None
            assert all(
                property_schema.get("description")
                for property_schema in tool.output_schema["properties"].values()
            )

        for tool_name in tools:
            input_schema = tools[tool_name].input_schema
            input_property = input_schema["properties"]["input"]
            if reference := input_property.get("$ref"):
                model_schema = input_schema["$defs"][reference.rsplit("/", 1)[-1]]
            else:
                model_schema = input_property
            assert all(
                property_schema.get("description")
                for property_schema in model_schema["properties"].values()
            )

    async def test_media_upload_registered_with_s3_only(self, s3_only_server: None) -> None:
        server = s3_only_server
        tools = await server.mcp.list_tools()
        tool_names = {t.name for t in tools}
        assert "media_upload" in tool_names
        assert "media_presign" in tool_names


class TestToolAnnotations:
    """Verify ToolAnnotations are correctly propagated."""

    async def test_seed_audio_annotations(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seed_audio_generate")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is False
        assert tool.annotations.open_world_hint is True

    async def test_seedream_annotations(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedream_generate_image")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.open_world_hint is True

    async def test_seedance_create_annotations(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedance_create_task")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.open_world_hint is True

    async def test_gen_task_get_annotations(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "gen_task_get")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False  # output_dir can write local files
        assert tool.annotations.idempotent_hint is True

    async def test_gen_task_list_readonly(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "gen_task_list")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True

    async def test_gen_task_cancel_destructive(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "gen_task_cancel_or_delete")
        assert tool.annotations is not None
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.read_only_hint is False


class TestInputSchemas:
    """Verify inputSchema is auto-generated for each tool."""

    async def test_seed_audio_input_schema(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seed_audio_generate")
        schema = tool.parameters
        assert schema is not None
        assert "properties" in schema
        assert "text_prompt" in schema["properties"]["input"]["properties"]
        assert "required" not in schema["properties"]["input"]

    async def test_seedream_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedream_generate_image")
        input_props = tool.parameters["properties"]["input"]["properties"]
        assert {
            "prompt",
            "images",
            "point",
            "bbox",
            "background",
            "variations",
            "dry_run",
        } <= input_props.keys()

    async def test_seedance_create_input_schema(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedance_create_task")
        schema = tool.parameters
        assert schema is not None
        assert "properties" in schema

    async def test_gen_task_get_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "gen_task_get")
        schema = tool.parameters
        assert schema is not None
        assert "task_ids" in schema["properties"]["input"]["properties"]
        assert schema["properties"]["input"]["required"] == ["task_ids"]

    async def test_gen_task_cancel_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "gen_task_cancel_or_delete")
        schema = tool.parameters
        assert schema is not None
        input_props = schema["properties"]["input"]["properties"]
        assert {"task_id", "mode", "expected_status", "confirm"} <= input_props.keys()


class TestOutputSchemas:
    """Verify outputSchema is auto-generated for each tool."""

    async def test_seedream_output_schema(self, configured_server: None) -> None:
        server = configured_server
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedream_generate_image")
        schema = tool.output_schema
        assert schema is not None
        assert "properties" in schema
        assert "artifacts" in schema["properties"]
        assert "model" in schema["properties"]

    async def test_seedance_create_output_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedance_create_task")
        schema = tool.output_schema
        assert schema is not None
        assert {"model", "family", "tasks", "submitted", "failed", "preview"} <= schema[
            "properties"
        ].keys()


class TestVariationToolAnnotations:
    """Verify ToolAnnotations for the three variation tools."""

    async def test_seedream_variations_are_part_of_generate(self, configured_server: None) -> None:
        names = {tool.name for tool in await configured_server.mcp.list_tools()}
        assert "seedream_generate_image" in names
        assert not {"seedream_edit_image", "seedream_generate_image_variations"} & names

    async def test_seed_audio_variations_are_part_of_generate(
        self, configured_server: None
    ) -> None:
        names = {tool.name for tool in await configured_server.mcp.list_tools()}
        assert "seed_audio_generate" in names
        assert "seed_audio_generate_variations" not in names

    async def test_seedance_variations_are_part_of_create(self, configured_server: None) -> None:
        names = {tool.name for tool in await configured_server.mcp.list_tools()}
        assert "seedance_create_task" in names
        assert "seedance_create_task_variations" not in names


class TestVariationInputSchemas:
    """Verify inputSchema is auto-generated for variation tools."""

    async def test_seedream_variations_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedream_generate_image")
        input_props = tool.parameters["properties"]["input"]["properties"]
        assert {"variations", "variation_prompts", "seed"} <= input_props.keys()
        assert "base_seed" not in input_props

    async def test_seed_audio_variations_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seed_audio_generate")
        input_props = tool.parameters["properties"]["input"]["properties"]
        assert {"text_prompt", "variations", "variation_prompts"} <= input_props.keys()

    async def test_seedance_variations_input_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedance_create_task")
        input_props = tool.parameters["properties"]["input"]["properties"]
        assert {"variations", "variation_prompts", "dry_run", "draft_task_id"} <= input_props.keys()


class TestVariationOutputSchemas:
    """Verify outputSchema is auto-generated for variation tools."""

    async def test_seedream_variations_output_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedream_generate_image")
        schema = tool.output_schema
        assert schema is not None
        assert {"artifacts", "summary", "preview"} <= schema["properties"].keys()

    async def test_seed_audio_variations_output_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seed_audio_generate")
        schema = tool.output_schema
        assert schema is not None
        assert {"artifact", "summary"} <= schema["properties"].keys()

    async def test_seedance_variations_output_schema(self, configured_server: None) -> None:
        tools = await configured_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "seedance_create_task")
        schema = tool.output_schema
        assert schema is not None
        assert "tasks" in schema["properties"]
        assert "recommended_poll_after_ms" in schema["properties"]


class TestResourceTemplate:
    """Verify the seed-media artifact resource template is registered."""

    async def test_resource_template_registered(self, configured_server: None) -> None:
        server = configured_server
        templates = await server.mcp.list_resource_templates()
        assert len(templates) >= 1
        artifact_tmpl = next(t for t in templates if "artifacts" in t.uri_template)
        assert "artifact_id" in artifact_tmpl.uri_template
        assert artifact_tmpl.name == "get_artifact"

    async def test_health_resource_registered(self, configured_server: None) -> None:
        server = configured_server
        resources = await server.mcp.list_resources()
        # Health resource is a static resource, not a template.
        assert len(resources) >= 1


OMNIHUMAN_TOOLS = {"omnihuman_create_task", "omnihuman_get_task", "omnihuman_cancel_task"}


@pytest.fixture
def omnihuman_server() -> SimpleNamespace:
    """OmniHuman is configured alone: no ModelArk key, and no ``.env`` file is read."""
    return SimpleNamespace(
        mcp=create_server(
            Settings(
                _env_file=None,
                BYTEPLUS_CV_API_KEY="cv-test",  # pragma: allowlist secret
                BYTEPLUS_OMNIHUMAN_ENABLED=True,
            )
        )
    )


class TestOmniHumanDiscovery:
    async def test_task_modes(self, omnihuman_server: SimpleNamespace) -> None:
        tools = {tool.name: tool for tool in await omnihuman_server.mcp.list_tools()}

        assert tools["omnihuman_create_task"].task_config.mode == "forbidden"
        assert tools["omnihuman_get_task"].task_config.mode == "forbidden"
        assert tools["omnihuman_cancel_task"].task_config.mode == "forbidden"

    async def test_tools_registered_when_enabled_with_key(
        self, omnihuman_server: SimpleNamespace
    ) -> None:
        tools = {tool.name: tool for tool in await omnihuman_server.mcp.list_tools()}

        assert tools.keys() >= OMNIHUMAN_TOOLS
        for name in OMNIHUMAN_TOOLS:
            assert tools[name].description
            assert tools[name].output_schema is not None
            assert all(
                prop.get("description") for prop in tools[name].output_schema["properties"].values()
            )

    async def test_tools_absent_without_flag_or_key(self, no_creds_server: SimpleNamespace) -> None:
        names = {tool.name for tool in await no_creds_server.mcp.list_tools()}
        assert OMNIHUMAN_TOOLS.isdisjoint(names)

    async def test_tools_absent_when_key_set_but_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYTEPLUS_CV_API_KEY", "cv-test")
        monkeypatch.delenv("BYTEPLUS_OMNIHUMAN_ENABLED", raising=False)
        get_settings.cache_clear()
        try:
            server = create_server(Settings(_env_file=None, BYTEPLUS_CV_API_KEY="cv-test"))
            names = {tool.name for tool in await server.list_tools()}
        finally:
            get_settings.cache_clear()
        assert OMNIHUMAN_TOOLS.isdisjoint(names)
