"""End-to-end tests exercising the full MCP protocol layer.

Uses the FastMCP in-memory client transport to connect directly to the
server instance, mock provider HTTP responses with respx, and verify
tool discovery, tool invocation, artifact persistence, and resource
retrieval through the actual MCP protocol — not direct function calls.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from ark_mcp.config.env import get_settings
from ark_mcp.config.model_capabilities import refresh_capability_registry
from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
from ark_mcp.providers.modelark.generation_tasks import GenerationTaskService
from ark_mcp.providers.modelark.schemas import (
    GenerationTaskListResponse,
    GenerationTaskResponse,
)
from ark_mcp.providers.modelark.seedance import SeedanceService
from ark_mcp.providers.seed_speech.schemas import SeedAudioProviderResponse
from ark_mcp.providers.seed_speech.seed_audio import SeedAudioService
from ark_mcp.security.safe_downloader import DownloadedMedia

if TYPE_CHECKING:
    from ark_mcp.server import FastMCP

ARK_BASE = "https://ark.test.example.com/api/v3"


@pytest.fixture
def e2e_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_AUTH_MODE", "local")
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-modelark")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "sk-test-speech")
    monkeypatch.setenv("TOS_ACCESS_KEY", "ak-test-tos")
    monkeypatch.setenv("TOS_SECRET_KEY", "sk-test-tos")
    monkeypatch.setenv("TOS_BUCKET", "test-bucket")
    monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", ARK_BASE)
    monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.test.example.com")
    monkeypatch.setenv("SEEDREAM_DEFAULT_MODEL", "dola-seedream-5-5-261028")
    monkeypatch.setenv("SEEDANCE_DEFAULT_MODEL", "dreamina-seedance-2-0-260128")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / ".artifacts"))
    monkeypatch.setenv("ARTIFACT_BACKEND", "filesystem")

    get_settings.cache_clear()
    refresh_capability_registry()

    from ark_mcp.server import create_server

    yield SimpleNamespace(mcp=create_server(get_settings()))

    get_settings.cache_clear()
    refresh_capability_registry()


def _mock_seedream_response(
    img_b64: str | None = None,
    url: str | None = None,
    output_format: str | None = None,
    status: int = 200,
) -> httpx.Response:
    data: list[dict[str, object]] = []
    if img_b64 is not None:
        item: dict[str, object] = {"b64_json": img_b64}
        if output_format is not None:
            item["output_format"] = output_format
        data.append(item)
    elif url is not None:
        data.append({"url": url})
    body: dict[str, object] = {
        "created": 1721400000,
        "data": data,
        "usage": {"prompt_tokens": 10, "total_tokens": 20},
    }
    return httpx.Response(
        status,
        json=body,
        headers={"X-Request-Id": "req-e2e-123"},
    )


class TestToolDiscovery:
    """Verify tools are discoverable through the MCP protocol."""

    async def test_lists_all_configured_tools(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}
            assert tool_names == {
                "ark_list_models",
                "seed_audio_generate",
                "seed_tts_generate",
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

    async def test_tool_has_input_schema(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools if t.name == "seedream_generate_image")
            schema = tool.input_schema
            assert schema is not None
            assert "properties" in schema
            assert "input" in schema["properties"]

    async def test_tool_has_output_schema(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools if t.name == "seedream_generate_image")
            schema = tool.output_schema
            assert schema is not None
            assert "artifacts" in schema["properties"]
            assert "model" in schema["properties"]


class TestResourceTemplates:
    """Verify resource templates are registered and discoverable."""

    async def test_artifact_resource_template_registered(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            templates = await client.list_resource_templates()
            artifact_tmpl = next(t for t in templates if "artifacts" in t.uri_template)
            assert "artifact_id" in artifact_tmpl.uri_template

    async def test_health_resource_registered(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            resources = await client.list_resources()
            assert len(resources) >= 1


class TestDirectExecution:
    @pytest.mark.parametrize(
        "name",
        [
            "ark_job_capabilities",
            "ark_job_submit",
            "ark_job_get",
            "ark_job_cancel",
            "seed_understand",
            "seed_audio_understand",
        ],
    )
    @respx.mock
    async def test_removed_tools_reject_without_dispatch(self, e2e_server, name):
        async with Client(e2e_server.mcp) as client:
            with pytest.raises(ToolError, match="Unknown tool"):
                await client.call_tool(name, {})
        assert len(respx.calls) == 0

    @pytest.mark.parametrize("arguments", [{}, {"input": {"prompt": ""}}])
    @respx.mock
    async def test_invalid_arguments_reject_without_dispatch(self, e2e_server, arguments):
        async with Client(e2e_server.mcp) as client:
            result = await client.call_tool(
                "seedream_generate_image", arguments, raise_on_error=False
            )
        assert result.is_error
        assert len(respx.calls) == 0

    @respx.mock
    async def test_pending_generation_does_not_block_discovery(self, e2e_server):
        started = asyncio.Event()
        release = asyncio.Event()

        async def generate(request):
            started.set()
            await release.wait()
            return _mock_seedream_response(url="https://example.com/image.png")

        route = respx.post(f"{ARK_BASE}/images/generations").mock(side_effect=generate)
        async with Client(e2e_server.mcp) as client:
            call = asyncio.create_task(
                client.call_tool("seedream_generate_image", {"input": {"prompt": "square"}})
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                assert not call.done()
                discovery = await client.call_tool("ark_list_models", {"input": {}}, timeout=2)
                assert discovery.structured_content["models"]
            finally:
                release.set()
                result = await asyncio.wait_for(call, timeout=5)
        assert not result.is_error
        assert route.call_count == 1


class TestSeedreamGenerateImageE2E:
    """Full-path E2E tests for seedream_generate_image via MCP protocol."""

    async def test_generate_image_with_b64_json_persisted(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        img_b64 = base64.b64encode(b"fake-png-bytes").decode()

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(img_b64=img_b64, output_format="png")
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "a red circle", "persist": True}},
                )

        assert not result.is_error
        data = result.structured_content
        assert data["model"] == "dola-seedream-5-5-261028"
        assert len(data["artifacts"]) == 1
        artifact = data["artifacts"][0]
        assert artifact["uri"].startswith("seed-media://artifacts/")
        assert artifact["media_type"] == "image"
        assert artifact["mime_type"] == "image/png"
        assert artifact["id"] != "provider-url"
        assert data["usage"]["total_tokens"] == 20

    async def test_legacy_client_preserves_seedream_artifact_result(
        self,
        e2e_server: object,
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        img_b64 = base64.b64encode(b"compatibility-png-bytes").decode()

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(img_b64=img_b64, output_format="png")
            )
            async with Client(mcp, mode="legacy") as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "a blue square", "persist": True}},
                )

        assert result.is_error is False
        artifact = result.structured_content["artifacts"][0]
        assert artifact["uri"].startswith("seed-media://artifacts/")
        assert artifact["mime_type"] == "image/png"

    async def test_generate_image_persist_false_returns_provider_url(
        self, e2e_server: object
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        provider_url = "https://tos-ap-southeast.bytepluses.com/out.png"

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(url=provider_url)
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "a blue square", "persist": False}},
                )

        assert not result.is_error
        data = result.structured_content
        assert len(data["artifacts"]) == 1
        artifact = data["artifacts"][0]
        assert artifact["id"] == "provider-url"
        assert artifact["uri"] == provider_url

    async def test_retrieve_artifact_after_generation(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        raw_bytes = b"e2e-artifact-payload"
        img_b64 = base64.b64encode(raw_bytes).decode()

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(img_b64=img_b64, output_format="png")
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "a green triangle", "persist": True}},
                )
                artifact_uri = result.structured_content["artifacts"][0]["uri"]
                content = await client.read_resource(artifact_uri)

        assert len(content) >= 1
        item = content[0]
        assert hasattr(item, "blob")
        assert base64.b64decode(item.blob) == raw_bytes
        assert item.mime_type == "image/png"

    async def test_provider_error_returns_error_result(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]

        error_body = {
            "error": {
                "code": "FORBIDDEN",
                "message": "model not activated",
            }
        }

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=httpx.Response(
                    403,
                    json=error_body,
                    headers={"X-Request-Id": "req-err-001"},
                )
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "test"}},
                    raise_on_error=False,
                )

        assert result.is_error
        assert result.structured_content is None
        text = result.content[0].text
        assert "modelark generate_image failed" in text
        assert "code=FORBIDDEN" in text
        assert "request_id=req-err-001" in text

    async def test_batch_rejected_for_pro_model(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]

        async with Client(mcp) as client:
            result = await client.call_tool(
                "seedream_generate_image",
                {"input": {"prompt": "test", "max_images": 3}},
                raise_on_error=False,
            )

        assert result.is_error

    async def test_generate_image_with_url_persisted(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        provider_url = "https://tos-ap-southeast.bytepluses.com/image.png"

        with (
            patch(
                "ark_mcp.security.safe_downloader.SafeDownloader.download",
                new=AsyncMock(
                    return_value=DownloadedMedia(
                        body=b"downloaded-png-data",
                        content_type="image/png",
                        final_url=provider_url,
                    )
                ),
            ),
            respx.mock,
        ):
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(url=provider_url)
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {"input": {"prompt": "a purple star", "persist": True}},
                )
                artifact_uri = result.structured_content["artifacts"][0]["uri"]
                content = await client.read_resource(artifact_uri)

        assert not result.is_error
        data = result.structured_content
        assert len(data["artifacts"]) == 1
        assert data["artifacts"][0]["id"] != "provider-url"
        assert len(content) >= 1
        assert base64.b64decode(content[0].blob) == b"downloaded-png-data"


class TestHealthResourceE2E:
    """Verify the health resource is readable via MCP protocol."""

    async def test_read_health_resource(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        async with Client(mcp) as client:
            content = await client.read_resource("seed-health://status")

        assert len(content) >= 1
        item = content[0]
        assert hasattr(item, "text")
        text = item.text
        assert "Ark Seed MCP Server" in text
        assert "healthy" in text
        assert "ModelArk configured: True" in text
        assert "Seed Audio configured: True" in text


class TestSeedAudioE2E:
    """Verify Seed Audio executes through the MCP protocol surface."""

    async def test_generates_and_persists_audio(
        self, e2e_server: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        audio_b64 = base64.b64encode(b"e2e-audio-data").decode()

        async def mock_generate(
            self: SeedAudioService,
            request: object,
            *,
            request_id: str | None = None,
        ) -> tuple[SeedAudioProviderResponse, str | None]:
            return (
                SeedAudioProviderResponse(
                    code=0,
                    message="success",
                    audio=audio_b64,
                    duration=2.5,
                    original_duration=3.0,
                ),
                "seed-speech-log-e2e",
            )

        async def mock_close(self: SeedAudioService) -> None:
            return None

        monkeypatch.setattr(SeedAudioService, "generate", mock_generate)
        monkeypatch.setattr(SeedAudioService, "close", mock_close)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "seed_audio_generate",
                {"input": {"text_prompt": "a short ambient scene", "persist": True}},
            )
            artifact_uri = result.structured_content["artifact"]["uri"]
            content = await client.read_resource(artifact_uri)

        assert not result.is_error
        data = result.structured_content
        assert data["duration_seconds"] == 2.5
        assert data["billing_duration_seconds"] == 3.0
        assert data["provider_log_id"] == "seed-speech-log-e2e"
        assert data["artifact"]["media_type"] == "audio"
        assert base64.b64decode(content[0].blob) == b"e2e-audio-data"

    async def test_provider_error_returns_no_structured_content(
        self, e2e_server: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error results must not carry structured content.

        Strict MCP clients (e.g. TRAE) validate ``structuredContent`` against
        the tool's declared ``outputSchema``. The success-shaped schema
        requires ``duration_seconds`` / ``billing_duration_seconds`` /
        ``artifact``, so an error payload like ``{"error": ...}`` would be
        rejected and mask the real provider error. The error path therefore
        returns text-only content with ``isError=true``.
        """
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]

        async def mock_generate(
            self: SeedAudioService,
            request: object,
            *,
            request_id: str | None = None,
        ) -> tuple[SeedAudioProviderResponse, str | None]:
            raise ProviderError(
                NormalizedProviderError(
                    provider="seed-speech",
                    operation="generate_audio",
                    http_status=400,
                    code="INVALID_PARAM",
                    message="text too long",
                    request_id="req-audio-err-001",
                    retryable=False,
                )
            )

        async def mock_close(self: SeedAudioService) -> None:
            return None

        monkeypatch.setattr(SeedAudioService, "generate", mock_generate)
        monkeypatch.setattr(SeedAudioService, "close", mock_close)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "seed_audio_generate",
                {"input": {"text_prompt": "a short ambient scene"}},
                raise_on_error=False,
            )

        assert result.is_error
        assert result.structured_content is None
        text = result.content[0].text
        assert "seed-speech generate_audio failed" in text
        assert "code=INVALID_PARAM" in text
        assert "request_id=req-audio-err-001" in text


class TestSeedanceLifecycleE2E:
    """Verify every Seedance task operation works through MCP protocol calls."""

    async def test_create_get_list_and_cancel_task(
        self,
        e2e_server: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        task = GenerationTaskResponse(
            id="task-e2e-123",
            model="dreamina-seedance-2-0-260128",
            status="queued",
            created_at=1721400000,
            updated_at=1721400000,
        )

        async def mock_create(self: SeedanceService, request: object) -> tuple[str, str | None]:
            return task.id, "create-request-e2e"

        async def mock_get(
            self: SeedanceService,
            task_id: str,
        ) -> tuple[GenerationTaskResponse, str | None]:
            assert task_id == task.id
            return task, "get-request-e2e"

        async def mock_list(
            self: SeedanceService, **kwargs: object
        ) -> tuple[GenerationTaskListResponse, str | None]:
            return GenerationTaskListResponse(
                data=[task], total=1, has_more=False
            ), "list-request-e2e"

        async def mock_delete(self: SeedanceService, task_id: str) -> str | None:
            assert task_id == task.id
            return "delete-request-e2e"

        async def mock_close(self: SeedanceService) -> None:
            return None

        monkeypatch.setattr(SeedanceService, "create_task", mock_create)
        monkeypatch.setattr(SeedanceService, "close", mock_close)
        monkeypatch.setattr(GenerationTaskService, "get_task", mock_get)
        monkeypatch.setattr(GenerationTaskService, "list_tasks", mock_list)
        monkeypatch.setattr(GenerationTaskService, "delete_task", mock_delete)
        monkeypatch.setattr(GenerationTaskService, "close", mock_close)

        red_pixel = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/"
            "PchI7wAAAABJRU5ErkJggg=="
        )
        async with Client(mcp) as client:
            created = await client.call_tool(
                "seedance_create_task",
                {
                    "input": {
                        "prompt": "A cat walks through a garden",
                        "images": [
                            {
                                "kind": "base64",
                                "data": red_pixel,
                                "mime_type": "image/png",
                                "role": "reference_image",
                            }
                        ],
                        "resolution": "480p",
                        "duration": 5,
                    }
                },
            )
            fetched = await client.call_tool(
                "gen_task_get",
                {"input": {"task_ids": [task.id]}},
            )
            async with Client(mcp, mode="legacy") as foreground_client:
                compatibility_created = await foreground_client.call_tool(
                    "seedance_create_task",
                    {
                        "input": {
                            "prompt": "A second cat walks through a garden",
                            "resolution": "480p",
                            "duration": 5,
                        }
                    },
                )
                compatibility_fetched = await foreground_client.call_tool(
                    "gen_task_get",
                    {"input": {"task_ids": [task.id], "persist_output": True}},
                )
            persisted_fetched = await client.call_tool(
                "gen_task_get",
                {"input": {"task_ids": [task.id], "persist_output": True}},
            )
            listed = await client.call_tool("gen_task_list", {"input": {}})
            cancelled = await client.call_tool(
                "gen_task_cancel_or_delete",
                {
                    "input": {
                        "task_id": task.id,
                        "mode": "cancel",
                        "expected_status": "queued",
                        "confirm": True,
                    }
                },
            )

        assert not created.is_error
        assert created.structured_content["tasks"][0]["task_id"] == task.id
        assert compatibility_created.structured_content["tasks"][0]["task_id"] == task.id
        assert fetched.structured_content["tasks"][0]["status"] == "queued"
        assert persisted_fetched.structured_content["tasks"][0]["status"] == "queued"
        assert compatibility_fetched.structured_content["tasks"][0]["status"] == "queued"
        assert listed.structured_content["next_cursor"] is None
        assert listed.structured_content["tasks"][0]["task_id"] == task.id
        assert cancelled.structured_content["mode"] == "cancel"


class TestVariationToolsE2E:
    """Verify every variation tool serializes successful MCP responses."""

    async def test_seed_audio_variations(
        self, e2e_server: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        audio_b64 = base64.b64encode(b"e2e-variation-audio").decode()

        async def mock_generate(
            self: SeedAudioService,
            request: object,
            *,
            request_id: str | None = None,
        ) -> tuple[SeedAudioProviderResponse, str | None]:
            return (
                SeedAudioProviderResponse(
                    code=0,
                    message="success",
                    audio=audio_b64,
                    duration=1.0,
                    original_duration=1.0,
                ),
                "seed-speech-variation-log",
            )

        async def mock_close(self: SeedAudioService) -> None:
            return None

        monkeypatch.setattr(SeedAudioService, "generate", mock_generate)
        monkeypatch.setattr(SeedAudioService, "close", mock_close)

        async with Client(mcp) as client:
            result = await client.call_tool(
                "seed_audio_generate",
                {"input": {"text_prompt": "gentle rain", "variations": 2, "persist": True}},
            )

        assert not result.is_error
        summary = result.structured_content["summary"]
        assert summary["total"] == 2
        assert summary["succeeded"] == 2
        assert all(variation["artifact"] for variation in summary["variations"])

    async def test_seedream_variations(self, e2e_server: object) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]
        image_b64 = base64.b64encode(b"e2e-variation-image").decode()

        with respx.mock:
            respx.post(f"{ARK_BASE}/images/generations").mock(
                return_value=_mock_seedream_response(img_b64=image_b64)
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "seedream_generate_image",
                    {
                        "input": {
                            "prompt": "A small paper boat",
                            "variations": 2,
                            "seed": 10,
                            "persist": True,
                        }
                    },
                )

        assert not result.is_error
        summary = result.structured_content["summary"]
        assert summary["total"] == 2
        assert summary["succeeded"] == 2
        assert [item["seed"] for item in summary["variations"]] == [10, 11]

    async def test_seedance_variations(
        self, e2e_server: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mcp: FastMCP = e2e_server.mcp  # type: ignore[attr-defined]

        async def mock_create(self: SeedanceService, request: Any) -> tuple[str, str | None]:
            content = request.content
            prompt = next(item.text for item in content if item.type == "text")
            return f"task-{prompt[-1]}", "seedance-variation-request"

        async def mock_close(self: SeedanceService) -> None:
            return None

        monkeypatch.setattr(SeedanceService, "create_task", mock_create)
        monkeypatch.setattr(SeedanceService, "close", mock_close)
        red_pixel = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/"
            "PchI7wAAAABJRU5ErkJggg=="
        )

        async with Client(mcp) as client:
            result = await client.call_tool(
                "seedance_create_task",
                {
                    "input": {
                        "variation_prompts": ["scene 1", "scene 2"],
                        "variations": 2,
                        "images": [
                            {
                                "kind": "base64",
                                "data": red_pixel,
                                "mime_type": "image/png",
                                "role": "reference_image",
                            }
                        ],
                        "resolution": "480p",
                        "duration": 5,
                    }
                },
            )

        assert not result.is_error
        payload = result.structured_content
        assert (payload["submitted"], payload["failed"]) == (2, 0)
        assert {item["task_id"] for item in payload["tasks"]} == {"task-1", "task-2"}
