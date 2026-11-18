"""ASGI guard regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from starlette.types import Message, Scope

from ark_mcp.config.env import Settings
from ark_mcp.security.http_middleware import RateLimitMiddleware
from ark_mcp.server import create_server
from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    MODELARK,
    MODELARK_KEY,
    OPERATOR_KEY,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    rpc,
)


@pytest.mark.parametrize("operator_key", ["", OPERATOR_KEY])
@respx.mock
async def test_health_and_readiness_never_probe_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operator_key: str
) -> None:
    probe = AsyncMock(side_effect=AssertionError("HTTP readiness must not contact providers"))
    monkeypatch.setattr("ark_mcp.providers.base.BaseHttpGateway.health_check", probe)
    settings = http_settings(
        tmp_path,
        BYTEPLUS_MODELARK_API_KEY=operator_key,
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        health = await client.get("/health")
        ready = await client.get("/ready")
        metrics = await client.get("/metrics")
    assert health.status_code == ready.status_code == 200
    assert health.json() == {"status": "healthy"}
    assert ready.json() == {"status": "ready"}
    assert metrics.status_code == 404
    probe.assert_not_called()
    assert len(respx.calls) == 0


async def test_readiness_does_not_access_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with http_server(tmp_path) as (_, runtime, client):
        ping = AsyncMock(side_effect=RuntimeError("private database details"))
        monkeypatch.setattr(
            runtime.ownership_store,
            "ping",
            ping,
        )
        ready = await client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
        ping.assert_not_awaited()
        assert (await client.get("/health")).status_code == 200


async def test_anonymous_initialize_has_no_task_extension_or_session(tmp_path: Path) -> None:
    async with http_server(tmp_path, app_options={"stateless_http": False}) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert "mcp-session-id" not in response.headers
        capabilities = response.json()["result"]["capabilities"]
        assert "tasks" not in capabilities
        assert "io.modelcontextprotocol/tasks" not in capabilities.get("extensions", {})
        assert (await rpc(client, "tools/list"))["result"]["tools"]


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Origin": "https://evil.example.com"}, 403),
        ({"Host": "evil.example.com"}, 421),
    ],
)
@respx.mock
async def test_host_origin_guards_cannot_be_disabled_through_http_app(
    tmp_path: Path, headers: dict[str, str], status: int
) -> None:
    options = {
        "host_origin_protection": False,
        "allowed_hosts": ["evil.example.com"],
        "allowed_origins": ["https://evil.example.com"],
    }
    async with http_server(tmp_path, app_options=options) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                **credentials(),
                **headers,
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
    assert response.status_code == status
    assert len(respx.calls) == 0


def test_stdio_server_cannot_construct_http_app(tmp_path: Path) -> None:
    options: dict[str, Any] = {
        "_env_file": None,
        "MCP_TRANSPORT": "stdio",
        "ARTIFACT_DIR": str(tmp_path / "artifacts"),
    }
    server = create_server(Settings(**options))
    with pytest.raises(ValueError, match="HTTP"):
        server.http_app()


@pytest.mark.parametrize("authorization", ["Bearer synthetic-old-key", "Basic synthetic", ""])
@respx.mock
async def test_authorization_is_rejected_even_with_valid_byok_headers(
    tmp_path: Path, authorization: str
) -> None:
    async with http_server(tmp_path) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers={**credentials(), "Authorization": authorization},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 400
        assert "provider-specific BYOK" in response.text
        assert "synthetic" not in response.text
    assert len(respx.calls) == 0


@respx.mock
async def test_query_string_credentials_cannot_authorize_provider_work(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        response = await client.post(
            "/mcp",
            params={"api_key": MODELARK_KEY, "X-MCP-Client-Secret": CLIENT_SECRET},
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "seedream_generate_image",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "seedream_generate_image",
                    "arguments": {"input": {"prompt": "square"}},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            },
        )
        assert response.status_code == 200, response.text
        assert_denied(response.json())
    assert len(respx.calls) == 0


@respx.mock
async def test_duplicate_raw_credentials_are_rejected_at_asgi_boundary(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers=[
                ("X-ModelArk-Api-Key", MODELARK_KEY),
                ("x-modelark-api-key", "synthetic-duplicate"),
                ("X-MCP-Client-Secret", CLIENT_SECRET),
            ],
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 400
    assert "Duplicate" in response.text
    assert MODELARK_KEY not in response.text
    assert "synthetic-duplicate" not in response.text
    assert len(respx.calls) == 0


@pytest.mark.parametrize("streamed", [False, True])
@respx.mock
async def test_oversized_body_is_rejected_before_mcp(tmp_path: Path, streamed: bool) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * 512
        yield b"x" * 513

    settings = http_settings(tmp_path, MCP_HTTP_MAX_BODY_BYTES=1024)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        response = await client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            content=chunks() if streamed else b"x" * 1025,
        )
    assert response.status_code == 413
    assert len(respx.calls) == 0


async def test_invalid_content_length_is_rejected(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        response = await client.post("/mcp", headers={"Content-Length": "invalid"}, content=b"{}")
    assert response.status_code == 400


async def test_rate_limit_covers_anonymous_discovery_and_ignores_spoofed_proxy(
    tmp_path: Path,
) -> None:
    settings = http_settings(tmp_path, RATE_LIMIT_RPM=1, RATE_LIMIT_BURST=1)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        assert (await rpc(client, "tools/list"))["result"]["tools"]
        blocked = await client.post(
            "/mcp",
            headers={
                "X-Forwarded-For": "203.0.113.10",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
    assert blocked.status_code == 429
    retry_after = int(blocked.headers["retry-after"])
    assert retry_after > 0
    assert blocked.headers["x-ratelimit-limit"] == "1"
    assert blocked.headers["x-ratelimit-remaining"] == "0"
    reset_epoch = int(blocked.headers["x-ratelimit-reset"])
    assert time.time() <= reset_epoch <= time.time() + retry_after


class TestRateLimitMiddlewareBucketing:
    """Only trusted proxy hops affect canonical client buckets."""

    @staticmethod
    def _scope(client_ip: str, forwarded_for: str | None = None) -> Scope:
        headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]
        return {"type": "http", "client": (client_ip, 1234), "headers": headers}

    def test_trusted_proxy_uses_first_untrusted_hop_from_right(self) -> None:
        middleware = RateLimitMiddleware(AsyncMock(), rpm=10, trusted_proxy_cidrs=("10.0.0.0/8",))
        assert middleware._client_key(self._scope("10.0.0.5", "1.2.3.4, 5.6.7.8")) == "5.6.7.8"

    def test_trusted_proxy_hops_group_same_client(self) -> None:
        middleware = RateLimitMiddleware(AsyncMock(), rpm=10, trusted_proxy_cidrs=("10.0.0.0/8",))
        first = middleware._client_key(self._scope("10.0.0.5", "1.2.3.4, 10.0.0.7"))
        second = middleware._client_key(self._scope("10.0.0.6", "1.2.3.4"))
        assert first == second == "1.2.3.4"

    def test_empty_proxy_trust_uses_client_ip(self) -> None:
        middleware = RateLimitMiddleware(None, rpm=10)  # type: ignore[arg-type]
        assert middleware._client_key(self._scope("10.0.0.5", "1.2.3.4")) == "10.0.0.5"

    def test_distinct_client_ips_are_not_grouped(self) -> None:
        middleware = RateLimitMiddleware(None, rpm=10)  # type: ignore[arg-type]
        assert middleware._client_key(self._scope("10.0.0.1")) != middleware._client_key(
            self._scope("10.0.0.2")
        )

    async def test_bucket_count_stays_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [0.0]
        monkeypatch.setattr("ark_mcp.security.http_middleware.time.monotonic", lambda: clock[0])
        middleware = RateLimitMiddleware(None, rpm=60000, burst=60000)  # type: ignore[arg-type]
        for index in range(middleware._MAX_BUCKETS):
            assert await middleware._consume(f"ip-{index}") == 0
        for index in range(100):
            assert await middleware._consume(f"overflow-{index}") > 0
        assert len(middleware._buckets) == middleware._MAX_BUCKETS

        clock[0] = 10_000_000
        assert await middleware._consume("ip-final") == 0
        assert len(middleware._buckets) <= middleware._MAX_BUCKETS


async def test_create_server_applies_body_and_rate_limit_middleware(tmp_path: Path) -> None:
    settings = http_settings(tmp_path, RATE_LIMIT_TRUSTED_PROXY_CIDRS="127.0.0.1/32")
    server = create_server(settings)
    app = server.http_app(path="/mcp", json_response=True)

    stack: list[tuple[str, object]] = []
    node: object = app.build_middleware_stack()
    while node is not None:
        stack.append((type(node).__name__, node))
        node = getattr(node, "app", None)

    names = [name for name, _ in stack]
    assert names.index("InFlightLimitMiddleware") < names.index("RequestBodyLimitMiddleware")
    assert names.index("RequestBodyLimitMiddleware") < names.index("RateLimitMiddleware")
    assert names.index("RateLimitMiddleware") < names.index("ByokHeadersMiddleware")
    rate_limit_node = next(node for name, node in stack if name == "RateLimitMiddleware")
    assert isinstance(rate_limit_node, RateLimitMiddleware)
    assert rate_limit_node.trusted_proxy_networks == settings.trusted_proxy_networks


async def test_probe_traffic_does_not_throttle_discovery(tmp_path: Path) -> None:
    settings = http_settings(tmp_path, RATE_LIMIT_RPM=1, RATE_LIMIT_BURST=1)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        for _ in range(3):
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
        assert (await rpc(client, "tools/list"))["result"]["tools"]
        assert (await client.post("/mcp", json={})).status_code == 429
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/ready")).status_code == 200


@respx.mock
async def test_trusted_proxy_spoofed_prefix_cannot_reset_discovery_bucket(tmp_path: Path) -> None:
    settings = http_settings(
        tmp_path,
        RATE_LIMIT_RPM=1,
        RATE_LIMIT_BURST=1,
        RATE_LIMIT_TRUSTED_PROXY_CIDRS="127.0.0.1/32,10.0.0.0/8",
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        result = await rpc(
            client, "tools/list", headers={"X-Forwarded-For": "198.51.100.1,192.0.2.1,10.0.0.1"}
        )
        assert result["result"]["tools"]
        blocked = await client.post(
            "/mcp",
            headers={"X-Forwarded-For": "198.51.100.2,192.0.2.1,10.0.0.2"},
            json={},
        )
        assert blocked.status_code == 429
        independent = await rpc(client, "tools/list", headers={"X-Forwarded-For": "192.0.2.2"})
        assert independent["result"]["tools"]
        malformed = await client.post(
            "/mcp", headers={"X-Forwarded-For": "private-invalid-forwarding"}, json={}
        )
        assert malformed.status_code == 400
        assert malformed.text == "Invalid forwarding headers."
    assert len(respx.calls) == 0


@respx.mock
async def test_global_admission_rejects_before_reading_body_and_recovers(tmp_path: Path) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"data": [{"url": "https://example.com/image.png"}]})

    respx.post(f"{MODELARK}/images/generations").mock(side_effect=generate)
    settings = http_settings(tmp_path, MCP_HTTP_MAX_IN_FLIGHT=1)
    server = create_server(settings)
    app = server.http_app(path="/mcp", json_response=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        pending = asyncio.create_task(
            call_tool(
                client, "seedream_generate_image", {"prompt": "square"}, headers=credentials()
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            messages: list[Message] = []
            receive = AsyncMock(side_effect=AssertionError("Overload must not read the body"))

            async def send(message: Message) -> None:
                messages.append(message)

            scope: Scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/mcp",
                "raw_path": b"/mcp",
                "query_string": b"",
                "headers": [(b"host", b"testserver")],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            }
            await app(scope, receive, send)
            assert messages[0]["status"] == 503
            receive.assert_not_called()
        finally:
            release.set()
            result = await pending
        assert result["result"]["isError"] is False
        assert (await rpc(client, "tools/list"))["result"]["tools"]
