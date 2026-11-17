"""Proxy regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from ipaddress import IPv4Network, IPv6Network, ip_network
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

from ark_mcp.security.http_middleware import RateLimitMiddleware, RequestBodyLimitMiddleware


async def ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


@pytest.fixture(autouse=True)
def frozen_bucket_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ark_mcp.security.http_middleware.time", Mock(monotonic=lambda: 0.0, time=lambda: 0.0)
    )


async def request(
    app: RateLimitMiddleware,
    *,
    peer: str = "127.0.0.1",
    forwarded: str | None = None,
    headers: list[tuple[str, str]] | None = None,
    path: str = "/mcp",
) -> httpx.Response:
    values = list(headers or [])
    if forwarded is not None:
        values.append(("X-Forwarded-For", forwarded))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 1234)),
        base_url="http://testserver",
    ) as client:
        return await client.get(path, headers=values)


@pytest.mark.parametrize(
    ("peer", "networks"),
    [
        ("127.0.0.1", ("127.0.0.1/32",)),
        ("::ffff:127.0.0.1", ("127.0.0.1/32",)),
        ("127.0.0.1", ("::ffff:127.0.0.1/128",)),
        ("::1", ("::1/128",)),
        ("127.0.0.1", (ip_network("127.0.0.1/32"),)),
    ],
)
async def test_trusted_immediate_peer_separates_clients(
    peer: str, networks: tuple[str | IPv4Network | IPv6Network, ...]
) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=networks)
    assert (await request(app, peer=peer, forwarded="198.51.100.1")).status_code == 200
    assert (await request(app, peer=peer, forwarded="198.51.100.2")).status_code == 200
    assert (await request(app, peer=peer, forwarded="198.51.100.1")).status_code == 429


@pytest.mark.parametrize(
    "forwarded",
    [
        "198.51.100.1",
        "malformed-private-value",
        "",
        "198.51.100.1," * 1000,
        "198.51.100.1, 127.0.0.1",
    ],
)
async def test_untrusted_peer_ignores_all_forwarding_headers(forwarded: str) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    headers = [
        ("X-Forwarded-For", forwarded),
        ("X-Forwarded-For", "198.51.100.99"),
        ("Forwarded", "for=198.51.100.100"),
        ("X-Real-IP", "198.51.100.101"),
    ]
    assert (await request(app, peer="192.0.2.1", headers=headers)).status_code == 200
    assert (await request(app, peer="192.0.2.1", forwarded="198.51.100.2")).status_code == 429


async def test_empty_trust_list_ignores_even_loopback_forwarding() -> None:
    app = RateLimitMiddleware(ok_app, rpm=1)
    assert (await request(app, forwarded="198.51.100.1")).status_code == 200
    assert (await request(app, forwarded="198.51.100.2")).status_code == 429


async def test_right_to_left_strips_trusted_hops_and_ignores_spoofed_prefix() -> None:
    app = RateLimitMiddleware(
        ok_app,
        rpm=1,
        trusted_proxy_cidrs=("127.0.0.1/32", "10.0.0.0/8", "2001:db8:1::/48"),
    )
    first = "198.51.100.1, 192.0.2.1, 10.1.1.1, 2001:db8:1::1"
    second = "198.51.100.2, 192.0.2.1, 10.1.1.2"
    assert (await request(app, forwarded=first)).status_code == 200
    assert (await request(app, forwarded=second)).status_code == 429
    assert (await request(app, forwarded="192.0.2.2, 10.1.1.1")).status_code == 200


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
        ("::ffff:192.0.2.1", "192.0.2.1"),
        ("::ffff:c000:201", "192.0.2.1"),
        (" 192.0.2.1 \t", "192.0.2.1"),
    ],
)
async def test_equivalent_client_addresses_share_bucket(first: str, second: str) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    assert (await request(app, forwarded=first)).status_code == 200
    assert (await request(app, forwarded=second)).status_code == 429


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
        ("::ffff:192.0.2.1", "192.0.2.1"),
    ],
)
async def test_equivalent_direct_peers_share_bucket(first: str, second: str) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1)
    assert (await request(app, peer=first)).status_code == 200
    assert (await request(app, peer=second)).status_code == 429


@pytest.mark.parametrize(
    "forwarded",
    [
        "",
        " ",
        "unknown",
        "hostname.example",
        "192.0.2.1:123",
        "[2001:db8::1]:443",
        "[2001:db8::1]",
        "fe80::1%lo0",
        "192.0.2.1/32",
        "192.000.002.001",
        "192.0.2.1,",
        ",192.0.2.1",
        "192.0.2.1,,10.1.1.1",
        "private-invalid-prefix, 192.0.2.1",
        "192.0.2.1\n",
        "192.0.2.1\r\nX-Spoof: private",
        "192.0.2.1\x00",
        "192.0.2.1, ::ffff:192.0.2.1",
        "x" * 4097,
        ",".join(f"192.0.2.{index}" for index in range(1, 34)),
    ],
)
async def test_malformed_trusted_chain_fails_without_echo_or_bucket_consumption(
    forwarded: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = Mock()
    monkeypatch.setattr("ark_mcp.security.http_middleware.log_warning", logger)
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    response = await request(app, forwarded=forwarded)
    assert response.status_code == 400
    assert response.text == "Invalid forwarding headers."
    assert forwarded not in str(logger.call_args_list) or not forwarded.strip()
    assert (await request(app, forwarded="192.0.2.1")).status_code == 200


async def test_duplicate_xff_fields_are_rejected_before_body_read() -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    scope: Scope = {
        "type": "http",
        "path": "/mcp",
        "client": ("127.0.0.1", 1234),
        "headers": [
            (b"x-forwarded-for", b"192.0.2.1"),
            (b"X-Forwarded-For", b"192.0.2.2"),
        ],
    }
    receive = AsyncMock(side_effect=AssertionError("Must not read body"))
    messages: list[Message] = []
    await app(scope, receive, AsyncMock(side_effect=messages.append))
    assert messages[0]["status"] == 400
    assert messages[1]["body"] == b"Invalid forwarding headers."
    receive.assert_not_called()


async def test_non_ascii_trusted_chain_is_rejected_without_echo() -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    scope: Scope = {
        "type": "http",
        "path": "/mcp",
        "client": ("127.0.0.1", 1234),
        "headers": [(b"x-forwarded-for", b"\xffprivate")],
    }
    messages: list[Message] = []
    await app(scope, AsyncMock(), AsyncMock(side_effect=messages.append))
    assert messages[0]["status"] == 400
    assert messages[1]["body"] == b"Invalid forwarding headers."


async def test_chain_limits_are_inclusive() -> None:
    app = RateLimitMiddleware(ok_app, rpm=10, trusted_proxy_cidrs=("127.0.0.1/32", "10.0.0.0/8"))
    chain = ",".join(["192.0.2.1", *(f"10.0.0.{index}" for index in range(1, 32))])
    assert (await request(app, forwarded=chain)).status_code == 200
    padded = "192.0.2.1".ljust(4096)
    assert (await request(app, forwarded=padded)).status_code == 200
    assert (await request(app, forwarded=padded + " ")).status_code == 400


async def test_all_trusted_chain_uses_leftmost_address_and_absent_header_uses_peer() -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32", "10.0.0.0/8"))
    assert (await request(app, forwarded="10.0.0.1, 10.0.0.2")).status_code == 200
    assert (await request(app, forwarded="10.0.0.1")).status_code == 429
    assert (await request(app)).status_code == 200
    assert (await request(app)).status_code == 429


@pytest.mark.parametrize("peer", [None, ("unix-peer-private", 0), ("fe80::1%lo0", 1)])
async def test_missing_or_invalid_peer_uses_fixed_bucket_and_ignores_headers(
    peer: tuple[str, int] | None,
) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    scope: Scope = {
        "type": "http",
        "path": "/mcp",
        "client": peer,
        "headers": [(b"x-forwarded-for", b"192.0.2.1")],
    }
    messages: list[Message] = []
    await app(scope, AsyncMock(), AsyncMock(side_effect=messages.append))
    assert messages[0]["status"] == 200
    scope["headers"] = [(b"x-forwarded-for", b"192.0.2.2")]
    messages.clear()
    await app(scope, AsyncMock(), AsyncMock(side_effect=messages.append))
    assert messages[0]["status"] == 429


@pytest.mark.parametrize("path", ["/health", "/ready", "/health?check=1", "/ready?check=1"])
async def test_probes_do_not_create_or_consume_buckets(path: str) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1)
    for _ in range(3):
        assert (await request(app, path=path)).status_code == 200
    assert app._buckets == {}
    assert (await request(app)).status_code == 200
    assert (await request(app)).status_code == 429
    assert (await request(app, path=path)).status_code == 200


@pytest.mark.parametrize("path", ["/health/", "/ready/", "/healthz", "/ready/extra", "/metrics"])
async def test_only_exact_probe_paths_are_exempt(path: str) -> None:
    app = RateLimitMiddleware(ok_app, rpm=1)
    assert (await request(app, path=path)).status_code == 200
    assert (await request(app, path=path)).status_code == 429


async def test_concurrent_spoofed_prefixes_share_one_burst() -> None:
    app = RateLimitMiddleware(ok_app, rpm=1, burst=7, trusted_proxy_cidrs=("127.0.0.1/32",))
    responses = await asyncio.gather(
        *(request(app, forwarded=f"198.51.100.{index}, 192.0.2.1") for index in range(1, 41))
    )
    assert sum(response.status_code == 200 for response in responses) == 7
    assert sum(response.status_code == 429 for response in responses) == 33


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_non_http_scopes_pass_through(scope_type: str) -> None:
    downstream = AsyncMock()
    app = RateLimitMiddleware(downstream, rpm=1)
    scope: Scope = {"type": scope_type}
    receive, send = AsyncMock(), AsyncMock()
    await app(scope, receive, send)
    downstream.assert_awaited_once_with(scope, receive, send)


async def test_disabled_limiter_passes_through() -> None:
    app = RateLimitMiddleware(ok_app, rpm=0)
    for _ in range(3):
        assert (await request(app)).status_code == 200
    assert app._buckets == {}


@pytest.mark.parametrize("cidr", ["*", "0.0.0.0/0", "::/0", "::ffff:0.0.0.0/96", "invalid"])
def test_direct_middleware_configuration_rejects_unsafe_networks(cidr: str) -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_TRUSTED_PROXY_CIDRS"):
        RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=(cidr,))


@pytest.mark.parametrize("mode", ["rate", "declared", "invalid_length", "streamed"])
async def test_guard_logs_do_not_contain_arbitrary_uri_or_header_values(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    logger = Mock()
    monkeypatch.setattr("ark_mcp.security.http_middleware.log_warning", logger)

    async def consume_body(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive()).get("more_body", False):
            pass
        await ok_app(scope, receive, send)

    app = (
        RateLimitMiddleware(ok_app, rpm=1)
        if mode == "rate"
        else RequestBodyLimitMiddleware(consume_body, max_bytes=2)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:

        async def chunks() -> AsyncIterator[bytes]:
            yield b"too-large"

        headers = {"X-Forwarded-For": "private-header"}
        if mode == "invalid_length":
            headers["Content-Length"] = "private-length"
        response = await client.post(
            "/private-path?key=private-query",
            headers=headers,
            content=chunks() if mode == "streamed" else b"too-large",
        )
        if mode == "rate":
            response = await client.get("/private-path?key=private-query", headers=headers)
        assert response.status_code in {400, 413, 429}
    assert logger.call_count == 1
    assert "private-" not in str(logger.call_args_list)
    assert logger.call_args.kwargs["route"] == "other"


async def test_guard_logs_exclude_even_valid_forwarded_client_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr("ark_mcp.security.http_middleware.log_warning", logger)
    app = RateLimitMiddleware(ok_app, rpm=1, trusted_proxy_cidrs=("127.0.0.1/32",))
    assert (await request(app, forwarded="192.0.2.1")).status_code == 200
    assert (await request(app, forwarded="192.0.2.1")).status_code == 429
    logger.assert_called_once_with(
        "rate_limit_exceeded", retry_after_seconds=60, capacity=1, route="mcp"
    )
