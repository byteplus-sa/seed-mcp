"""ASGI request-size policy and rate limiting for Streamable HTTP."""

from __future__ import annotations

import asyncio
import math
import time
from contextlib import ExitStack
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import TYPE_CHECKING

from starlette.responses import PlainTextResponse

from ark_mcp.config.env import Settings, parse_trusted_proxy_cidrs, settings_scope
from ark_mcp.observability.logger import warning as log_warning
from ark_mcp.security.credentials import request_credentials_scope

if TYPE_CHECKING:
    from ipaddress import IPv4Network, IPv6Network

    from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _route_label(scope: Scope) -> str:
    return {"/mcp": "mcp", "/health": "health", "/ready": "ready"}.get(
        scope.get("path", ""), "other"
    )


def _client_address(value: str) -> IPv4Address | IPv6Address:
    if "%" in value:
        raise ValueError("Scoped addresses are not supported.")
    address = ip_address(value)
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


class RequestBodyTooLarge(Exception):
    pass


class ByokHeadersMiddleware:
    """Bind validated credentials only for the lifetime of a live ASGI request."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with ExitStack() as stack:
            stack.enter_context(settings_scope(self.settings))
            try:
                stack.enter_context(request_credentials_scope(scope.get("headers", [])))
            except ValueError as exc:
                await PlainTextResponse(str(exc), status_code=400)(scope, receive, send)
                return
            await self.app(scope, receive, send)


class InFlightLimitMiddleware:
    """Reject overload before reading a body instead of growing an unbounded queue."""

    def __init__(self, app: ASGIApp, *, max_in_flight: int) -> None:
        self.app = app
        self.maximum = max_in_flight
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return
        if self.active >= self.maximum:
            await PlainTextResponse(
                "Server concurrency limit reached.",
                status_code=503,
                headers={"Retry-After": "1"},
            )(scope, receive, send)
            return
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1


class RequestBodyLimitMiddleware:
    """Reject declared and streamed HTTP request bodies above a hard limit."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    log_warning(
                        "request_body_too_large",
                        max_bytes=self.max_bytes,
                        route=_route_label(scope),
                    )
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                log_warning(
                    "request_body_invalid_content_length",
                    route=_route_label(scope),
                )
                await PlainTextResponse("Invalid Content-Length", status_code=400)(
                    scope, receive, send
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            log_warning(
                "request_body_too_large_streamed",
                received=received,
                max_bytes=self.max_bytes,
                route=_route_label(scope),
            )
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = PlainTextResponse("Request body too large", status_code=413)
        await response(scope, receive, send)


class RateLimitMiddleware:
    """Peer-validated per-process limits; no shared or durable rate state."""

    _MAX_BUCKETS = 10_000
    _MAX_FORWARDED_BYTES = 4096
    _MAX_FORWARDED_HOPS = 32

    def __init__(
        self,
        app: ASGIApp,
        *,
        rpm: int,
        burst: int | None = None,
        trusted_proxy_cidrs: tuple[str | IPv4Network | IPv6Network, ...] = (),
    ) -> None:
        self.app = app
        self.rpm = rpm
        self.capacity = burst if burst and burst > 0 else rpm
        self._rate = rpm / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()
        self.trusted_proxy_networks = parse_trusted_proxy_cidrs(
            ",".join(str(network) for network in trusted_proxy_cidrs)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.rpm <= 0 or scope.get("path") in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        try:
            ip = self._client_key(scope)
        except ValueError:
            await PlainTextResponse("Invalid forwarding headers.", status_code=400)(
                scope, receive, send
            )
            return

        retry_after = await self._consume(ip)
        if retry_after > 0:
            reset = math.ceil(retry_after)
            log_warning(
                "rate_limit_exceeded",
                retry_after_seconds=reset,
                capacity=self.capacity,
                route=_route_label(scope),
            )
            response = PlainTextResponse(
                "Rate limit exceeded",
                status_code=429,
                headers={
                    "Retry-After": str(reset),
                    "X-RateLimit-Limit": str(self.capacity),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + reset),
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _client_key(self, scope: Scope) -> str:
        client = scope.get("client")
        if not client:
            return "unknown"
        try:
            peer = _client_address(client[0])
        except ValueError:
            return "unknown"
        if not self._is_trusted(peer):
            return str(peer)
        addresses = self._forwarded_addresses(scope)
        for address in reversed(addresses):
            if not self._is_trusted(peer):
                break
            peer = address
        return str(peer)

    def _is_trusted(self, address: IPv4Address | IPv6Address) -> bool:
        return any(address in network for network in self.trusted_proxy_networks)

    def _forwarded_addresses(self, scope: Scope) -> tuple[IPv4Address | IPv6Address, ...]:
        forwarded: bytes | None = None
        for name, value in scope.get("headers", []):
            if name.lower() != b"x-forwarded-for":
                continue
            if forwarded is not None or len(value) > self._MAX_FORWARDED_BYTES:
                raise ValueError("Invalid forwarding headers.")
            forwarded = value
        if forwarded is None:
            return ()
        try:
            entries = forwarded.decode("ascii").split(",")
            if len(entries) > self._MAX_FORWARDED_HOPS:
                raise ValueError
            addresses = tuple(_client_address(entry.strip(" \t")) for entry in entries)
            if len(set(addresses)) != len(addresses):
                raise ValueError
        except ValueError:
            raise ValueError("Invalid forwarding headers.") from None
        return addresses

    async def _consume(self, ip: str) -> float:
        """Try to consume one token. Return 0 on success, or seconds to wait."""
        now = time.monotonic()
        async with self._lock:
            if ip not in self._buckets and len(self._buckets) >= self._MAX_BUCKETS:
                self._evict_expired()
                if len(self._buckets) >= self._MAX_BUCKETS:
                    return 60.0
            tokens, last_refill = self._buckets.get(ip, (self.capacity, now))
            elapsed = now - last_refill
            tokens = min(self.capacity, tokens + elapsed * self._rate)
            self._buckets[ip] = (tokens, now)
            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[ip] = (tokens, now)
                return 0.0
            deficit = 1.0 - tokens
            return deficit / self._rate if self._rate > 0 else 0.0

    def _evict_expired(self) -> None:
        """Remove buckets whose tokens have fully refilled (no active throttle)."""
        now = time.monotonic()
        expired = [
            ip
            for ip, (tokens, last_refill) in self._buckets.items()
            if tokens >= self.capacity or (now - last_refill) * self._rate >= self.capacity - tokens
        ]
        for ip in expired:
            del self._buckets[ip]
