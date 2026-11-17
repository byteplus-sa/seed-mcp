from __future__ import annotations

import base64
import sys
import textwrap

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def _mock_server_transport(tmp_path) -> StdioTransport:
    script = tmp_path / "server.py"
    script.write_text(
        textwrap.dedent("""
        import base64
        import httpx
        import pytest_socket
        from ark_mcp.config.env import Settings
        from ark_mcp.providers.base import BaseHttpGateway
        from ark_mcp.server import create_server

        pytest_socket.disable_socket(allow_unix_socket=True)
        calls = []

        def respond(request):
            assert request.method == "POST"
            assert request.url.path == "/api/v3/images/generations"
            assert request.headers["Authorization"] == "Bearer test-key"
            calls.append(request)
            return httpx.Response(200, json={
                "data": [{
                    "b64_json": base64.b64encode(b"stdio-image").decode(),
                    "output_format": "png",
                }]
            })

        async def ensure_client(self):
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    transport=httpx.MockTransport(respond), trust_env=False
                )
            return self._client

        BaseHttpGateway._ensure_client = ensure_client
        settings = Settings(
            _env_file=None,
            BYTEPLUS_MODELARK_API_KEY="test-key",
            MCP_TRANSPORT="stdio",
            MCP_AUTH_MODE="local",
            artifact_dir="ARTIFACT_PATH",
        )
        create_server(settings).run(transport="stdio", show_banner=False)
        assert len(calls) == 1
    """).replace("ARTIFACT_PATH", str(tmp_path / "artifacts"))
    )
    transport = StdioTransport(
        command=sys.executable,
        args=[str(script)],
        env={"BYTEPLUS_MODELARK_API_KEY": "test-key"},
        keep_alive=False,
    )
    return transport


@pytest.mark.parametrize("mode", ["modern", "legacy"])
async def test_stdio_direct_call_persists_and_reads_media_with_child_network_blocked(
    tmp_path, mode
):
    transport = _mock_server_transport(tmp_path)
    options = {"mode": "legacy"} if mode == "legacy" else {}
    async with Client(transport, **options) as client:
        tools = await client.list_tools()
        assert all(tool.execution is None for tool in tools)
        assert not any(tool.name.startswith("ark_job_") for tool in tools)
        result = await client.call_tool(
            "seedream_generate_image",
            {"input": {"prompt": "A blue square", "persist": True}},
            timeout=20,
        )
        assert not result.is_error
        artifact = result.structured_content["artifacts"][0]
        assert artifact["uri"].startswith("seed-media://artifacts/")
        resource = await client.read_resource(artifact["uri"])
        assert base64.b64decode(resource[0].blob) == b"stdio-image"
