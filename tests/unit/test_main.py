"""Entrypoint dispatch tests for ``python -m ark_mcp``."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

import ark_mcp.__main__ as entrypoint
from ark_mcp.config.env import Settings
from ark_mcp.security.http_middleware import RateLimitMiddleware


def test_main_runs_stdio_transport(monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr(entrypoint, "get_settings", lambda: SimpleNamespace(mcp_transport="stdio"))
    monkeypatch.setattr(entrypoint.mcp, "run", run)

    entrypoint.main()

    run.assert_called_once_with(transport="stdio")


def test_main_configures_protected_http(monkeypatch) -> None:
    run = Mock()
    settings = SimpleNamespace(
        mcp_transport="http",
        mcp_host="127.0.0.1",
        mcp_port=3100,
        allowed_hosts=["127.0.0.1"],
        allowed_origins=["https://client.example.com"],
        request_timeout_ms=600_000,
        tool_timeout_seconds=600.0,
    )
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.mcp, "run", run)

    entrypoint.main()

    kwargs = run.call_args.kwargs
    assert kwargs["transport"] == "http"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 3100
    assert kwargs["host_origin_protection"] is True
    assert kwargs["allowed_hosts"] == ["127.0.0.1"]
    assert kwargs["allowed_origins"] == ["https://client.example.com"]
    assert kwargs["stateless_http"] is True
    assert kwargs["uvicorn_config"] == {
        "timeout_graceful_shutdown": 630.0,
        "proxy_headers": False,
        "access_log": False,
    }
    assert "middleware" not in kwargs


def test_main_wires_rate_limiter_when_enabled(monkeypatch) -> None:
    run = Mock()
    settings = SimpleNamespace(
        mcp_transport="http",
        mcp_host="127.0.0.1",
        mcp_port=3100,
        allowed_hosts=["127.0.0.1"],
        allowed_origins=["https://client.example.com"],
        request_timeout_ms=600_000,
        tool_timeout_seconds=600.0,
    )
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.mcp, "run", run)

    entrypoint.main()

    kwargs = run.call_args.kwargs
    assert kwargs["transport"] == "http"
    assert kwargs["stateless_http"] is True
    assert "middleware" not in kwargs


@pytest.mark.parametrize(
    ("tool_seconds", "provider_ms", "expected"),
    [
        (600.0, 600_000, 630.0),
        (900.0, 600_000, 930.0),
        (120.0, 900_000, 930.0),
        (0.125, 1, 30.125),
        (0.125, 126, 30.126),
        (3600.0, 600_000, 3630.0),
    ],
)
def test_shutdown_uses_exact_longer_deadline_plus_cleanup(
    monkeypatch: pytest.MonkeyPatch, tool_seconds: float, provider_ms: int, expected: float
) -> None:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        MCP_TOOL_TIMEOUT_SECONDS=tool_seconds,
        BYTEPLUS_REQUEST_TIMEOUT_MS=provider_ms,
    )
    run = Mock()
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.mcp, "run", run)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")

    entrypoint.main()

    assert entrypoint.graceful_shutdown_timeout_seconds(settings) == expected
    config = run.call_args.kwargs["uvicorn_config"]
    assert config["timeout_graceful_shutdown"] == expected
    assert config["proxy_headers"] is False
    assert config["access_log"] is False


async def test_entrypoint_uvicorn_stack_preserves_peer_despite_environment_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, MCP_TRANSPORT="http", MCP_IDENTITY_HMAC_KEY="a" * 64)
    run = Mock()
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint.mcp, "run", run)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    access_logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(access_logger, "handlers", [])
    monkeypatch.setattr(access_logger, "propagate", False)
    entrypoint.main()
    seen_peers = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen_peers.append((scope["client"], scope["scheme"]))
        await PlainTextResponse("ok")(scope, receive, send)

    limiter = RateLimitMiddleware(app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    config = uvicorn.Config(
        limiter, log_config=None, lifespan="off", **run.call_args.kwargs["uvicorn_config"]
    )
    config.load()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=config.loaded_app, client=("192.0.2.1", 1234)),
        base_url="http://testserver",
    ) as client:
        first = await client.get(
            "/mcp", headers={"X-Forwarded-For": "198.51.100.1", "X-Forwarded-Proto": "https"}
        )
        second = await client.get("/mcp", headers={"X-Forwarded-For": "198.51.100.2"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert seen_peers == [(("192.0.2.1", 1234), "http")]
