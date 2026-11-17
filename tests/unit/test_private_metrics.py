"""Private aggregate telemetry for specs/SPEC_VKE_DEPLOYMENT.md."""

from __future__ import annotations

import asyncio
import http.client
import socket
import threading
from pathlib import Path

import pytest
import pytest_socket
from prometheus_client import REGISTRY

from ark_mcp.config.env import Settings
from ark_mcp.domain.errors import ProviderError
from ark_mcp.execution import before_provider_request, run_direct_call
from ark_mcp.observability.admin import MetricsListener
from ark_mcp.runtime import ProviderLimiters, close_runtime_services, create_runtime_services
from ark_mcp.security.auth_context import AuthContext
from tests.unit.test_runtime_ops import http_settings


@pytest.fixture
def loopback(socket_enabled: None) -> None:
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)


def scrape(port: int, path: str = "/metrics") -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.mark.usefixtures("loopback")
async def test_listener_serves_registry_only_on_loopback_and_releases_port() -> None:
    listener = MetricsListener(0)
    port = listener.port
    try:
        assert listener._server.server_address == ("127.0.0.1", port)
        status, body = await asyncio.to_thread(scrape, port)
        assert status == 200
        assert b"ark_mcp_tool_requests" in body
        for path in ("/", "/ready", "/metrics?token=canary", "/canary-secret"):
            status, body = await asyncio.to_thread(scrape, port, path)
            assert status == 404 and body == b""
    finally:
        await listener.close()
        await listener.close()
    assert not listener._thread.is_alive()
    assert listener._server.socket.fileno() == -1
    replacement = MetricsListener(port)
    await replacement.close()


@pytest.mark.usefixtures("loopback")
async def test_metrics_runtime_port_conflict_fails_startup_and_releases_state(
    tmp_path: Path,
) -> None:
    listener = MetricsListener(0)
    try:
        settings = http_settings(tmp_path, MCP_METRICS_PORT=listener.port)
        with pytest.raises(RuntimeError, match="Private metrics listener could not bind"):
            await create_runtime_services(settings)
    finally:
        await listener.close()
    runtime = await create_runtime_services(settings)
    try:
        assert runtime.metrics_listener is not None
        assert (await asyncio.to_thread(scrape, runtime.metrics_listener.port))[0] == 200
    finally:
        await close_runtime_services(runtime)


@pytest.mark.usefixtures("loopback")
async def test_listener_thread_start_failure_closes_bound_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = MetricsListener(0)
    port = probe.port
    await probe.close()

    def fail_start(self: threading.Thread) -> None:
        raise RuntimeError("synthetic thread failure")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail_start)
        with pytest.raises(RuntimeError, match="synthetic thread failure"):
            MetricsListener(port)
    replacement = MetricsListener(port)
    await replacement.close()


async def test_disabled_metrics_and_stdio_never_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("Metrics must remain disabled")

    monkeypatch.setattr("ark_mcp.runtime.MetricsListener", forbidden)
    for settings in (
        http_settings(tmp_path),
        Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path), MCP_METRICS_PORT=19381),
    ):
        runtime = await create_runtime_services(settings)
        assert runtime.metrics_listener is None
        await close_runtime_services(runtime)


@pytest.mark.usefixtures("loopback")
async def test_incomplete_scrape_is_interrupted_and_repeated_close_cancellation_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = MetricsListener(0)
    entered, finish = threading.Event(), threading.Event()
    original = listener._close

    def delayed() -> None:
        entered.set()
        assert finish.wait(5)
        original()

    monkeypatch.setattr(listener, "_close", delayed)
    connection = socket.create_connection(("127.0.0.1", listener.port), timeout=2)
    connection.sendall(b"GET /metrics HTTP/1.1\r\n")
    pending = asyncio.create_task(listener.close())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(3):
            pending.cancel()
            await asyncio.sleep(0)
        assert not pending.done()
    finally:
        finish.set()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 3)
    finally:
        connection.close()
    assert not listener._thread.is_alive()
    await listener.close()


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


async def test_admission_metrics_use_only_provider_and_fixed_reason() -> None:
    name = "ark_mcp_admission_rejections_total"
    before_timeout = sample(name, provider="modelark", reason="timeout")
    before_capacity = sample(name, provider="modelark", reason="capacity")
    limiters = ProviderLimiters(
        provider_limit=1,
        principal_limit=1,
        principal_cache_size=1,
        admission_timeout_seconds=0.001,
    )
    owner = AuthContext(principal_id="private-owner-canary", tenant_id="private-tenant-canary")
    async with limiters.acquire("modelark", owner):
        with pytest.raises(ProviderError):
            async with limiters.acquire("modelark", owner):
                pytest.fail("Admission must time out")
        with pytest.raises(ProviderError):
            async with limiters.acquire("modelark", AuthContext(principal_id="other")):
                pytest.fail("Owner registry must be full")
    assert sample(name, provider="modelark", reason="timeout") == before_timeout + 1
    assert sample(name, provider="modelark", reason="capacity") == before_capacity + 1
    for metric in REGISTRY.collect():
        if metric.name == name.removesuffix("_total"):
            for point in metric.samples:
                assert set(point.labels) == {"provider", "reason"}
                assert "canary" not in repr(point.labels)


@pytest.mark.parametrize("dispatch", ["none", "read", "mutation"])
async def test_tool_deadline_metrics_use_only_fixed_dispatch_state(dispatch: str) -> None:
    name = "ark_mcp_tool_deadlines_total"
    before = sample(name, dispatch=dispatch)

    async def delayed() -> None:
        if dispatch != "none":
            before_provider_request(side_effect=dispatch == "mutation")
        await asyncio.Event().wait()

    result = await run_direct_call(delayed, timeout_seconds=0.001, read_only=False)
    assert result.is_error
    assert sample(name, dispatch=dispatch) == before + 1


async def test_external_cancellation_and_provider_timeout_are_not_tool_deadlines() -> None:
    name = "ark_mcp_tool_deadlines_total"
    before = sample(name, dispatch="none")
    entered = asyncio.Event()

    async def delayed() -> None:
        entered.set()
        await asyncio.Event().wait()

    pending = asyncio.create_task(run_direct_call(delayed, timeout_seconds=10, read_only=False))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    async def timeout() -> None:
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await run_direct_call(timeout, timeout_seconds=10, read_only=False)
    assert sample(name, dispatch="none") == before
