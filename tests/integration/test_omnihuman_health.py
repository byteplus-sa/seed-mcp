"""Local OmniHuman diagnostics and provider-free HTTP readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import Client

from ark_mcp.config.env import Settings
from ark_mcp.providers.base import BaseHttpGateway
from ark_mcp.server import create_server


def _settings(tmp_path: Path, *, enabled: bool, **overrides: Any) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "ARTIFACT_DIR": str(tmp_path / ".artifacts"),
            "BYTEPLUS_CV_API_KEY": "cv-test",  # pragma: allowlist secret
            "BYTEPLUS_OMNIHUMAN_ENABLED": enabled,
            "READINESS_CHECK_PROVIDERS": True,
            **overrides,
        }
    )


@pytest.mark.parametrize("enabled", [True, False])
async def test_health_resource_reports_omnihuman(tmp_path: Path, enabled: bool) -> None:
    server = create_server(_settings(tmp_path, enabled=enabled))

    async with Client(server) as client:
        content = await client.read_resource("seed-health://status")

    assert f"OmniHuman configured: {enabled}" in content[0].text


@pytest.mark.parametrize("enabled", [True, False])
def test_http_rejects_provider_readiness_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    probe = AsyncMock(side_effect=AssertionError("HTTP readiness must not probe providers"))
    monkeypatch.setattr(BaseHttpGateway, "health_check", probe)

    with pytest.raises(ValueError, match="HTTP readiness must not call providers"):
        _settings(
            tmp_path,
            enabled=enabled,
            MCP_TRANSPORT="http",
            MCP_AUTH_MODE="byok",
            MCP_IDENTITY_HMAC_KEY="a" * 64,
        )
    probe.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_stdio_server_cannot_expose_http_readiness(tmp_path: Path, enabled: bool) -> None:
    server = create_server(_settings(tmp_path, enabled=enabled))
    with pytest.raises(ValueError, match="MCP_TRANSPORT=http and BYOK settings"):
        server.http_app(path="/mcp", stateless_http=True, json_response=True)


@pytest.mark.parametrize("enabled", [True, False])
async def test_http_readiness_never_probes_vision_cv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    probe = AsyncMock(side_effect=AssertionError("HTTP readiness must not probe providers"))
    monkeypatch.setattr(BaseHttpGateway, "health_check", probe)
    settings = _settings(
        tmp_path,
        enabled=enabled,
        MCP_TRANSPORT="http",
        MCP_AUTH_MODE="byok",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        MCP_ALLOWED_HOSTS="testserver",
        READINESS_CHECK_PROVIDERS=False,
    )
    server = create_server(settings)
    app = server.http_app(path="/mcp", stateless_http=True, json_response=True)

    with respx.mock(assert_all_called=False) as router:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            ready = await client.get("/ready")
            health = await client.get("/health")

    assert ready.status_code == health.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert health.json() == {"status": "healthy"}
    probe.assert_not_called()
    assert not router.calls
