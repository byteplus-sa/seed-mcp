"""Request-scoped gateway factories for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import httpx
import pytest
from fastmcp import Context

from ark_mcp.config.env import Settings
from ark_mcp.providers.modelark.seedance import SeedanceService


@pytest.mark.parametrize(
    ("factory_name", "provider", "header", "prefix", "base_field"),
    [
        ("modelark_gateway", "modelark", "Authorization", "Bearer ", "modelark_base_url"),
        ("seed_speech_gateway", "seed-speech", "X-Api-Key", "", "seed_audio_base_url"),
    ],
)
async def test_factories_use_selected_request_key_and_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
    factory_name: str,
    provider: str,
    header: str,
    prefix: str,
    base_field: str,
) -> None:
    from ark_mcp.providers import factory

    settings = Settings(
        _env_file=None, BYTEPLUS_REQUEST_TIMEOUT_MS=34000, BYTEPLUS_CONNECT_TIMEOUT_MS=7000
    )
    ctx = cast("Context", object())
    runtime = Mock(return_value=SimpleNamespace(settings=settings))
    credentials = Mock(return_value="synthetic-request-key")
    monkeypatch.setattr(factory, "get_runtime", runtime)
    monkeypatch.setattr(factory, "provider_api_key", credentials)
    for module in ("modelark", "seed_speech"):
        monkeypatch.setattr(
            f"ark_mcp.providers.{module}.client.get_settings",
            Mock(side_effect=AssertionError("Factory must use runtime settings.")),
        )
    gateway = getattr(factory, factory_name)(ctx)
    seen: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = await gateway._ensure_client()
    client._transport = httpx.MockTransport(dispatch)
    try:
        await gateway.post("/test", {})
        assert seen[0].headers[header] == prefix + "synthetic-request-key"
        assert str(seen[0].url) == getattr(settings, base_field) + "/test"
        assert seen[0].extensions["timeout"] == {
            "connect": 7.0,
            "read": 34.0,
            "write": 34.0,
            "pool": 34.0,
        }
        credentials.assert_called_once_with(ctx, provider)
        runtime.assert_called_once_with(ctx)
    finally:
        await gateway.close()


@pytest.mark.parametrize("factory_name", ["modelark_gateway", "seed_speech_gateway"])
def test_factory_refuses_to_fall_back_when_request_key_is_missing(
    monkeypatch: pytest.MonkeyPatch, factory_name: str
) -> None:
    from ark_mcp.providers import factory

    settings = Settings(
        _env_file=None,
        BYTEPLUS_MODELARK_API_KEY="synthetic-startup-key",  # pragma: allowlist secret
        BYTEPLUS_SEED_SPEECH_API_KEY="synthetic-startup-key",  # pragma: allowlist secret
    )
    monkeypatch.setattr(factory, "get_runtime", lambda _ctx: SimpleNamespace(settings=settings))
    monkeypatch.setattr(
        factory, "provider_api_key", Mock(side_effect=PermissionError("Request key required."))
    )
    with pytest.raises(PermissionError, match="Request key required"):
        getattr(factory, factory_name)(cast("Context", object()))


async def test_separate_services_isolate_headers_and_close_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ark_mcp.providers import factory

    settings = Settings(_env_file=None)
    monkeypatch.setattr(factory, "get_runtime", lambda _ctx: SimpleNamespace(settings=settings))
    monkeypatch.setattr(factory, "provider_api_key", lambda ctx, _provider: ctx.api_key)
    first = factory.modelark_gateway(
        cast("Context", SimpleNamespace(api_key="synthetic-first-key"))  # pragma: allowlist secret
    )
    second = factory.modelark_gateway(
        cast("Context", SimpleNamespace(api_key="synthetic-second-key"))  # pragma: allowlist secret
    )
    clients = [await gateway._ensure_client() for gateway in (first, second)]
    entered = asyncio.Event()
    seen: list[str] = []

    async def dispatch(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        if len(seen) == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), timeout=1)
        return httpx.Response(200, json={"id": "task-created"})

    for client in clients:
        client._transport = httpx.MockTransport(dispatch)
    services = [SeedanceService(first), SeedanceService(second)]
    request = SeedanceService.build_request(model="test", content=[])
    try:
        await asyncio.gather(*(service.create_task(request) for service in services))
        assert set(seen) == {"Bearer synthetic-first-key", "Bearer synthetic-second-key"}
        await services[0].close()
        assert clients[0].is_closed
        assert not clients[1].is_closed
        await services[1].create_task(request)
    finally:
        await services[0].close()
        await services[1].close()
    assert clients[1].is_closed
