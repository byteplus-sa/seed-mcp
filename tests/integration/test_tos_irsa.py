"""Live ASGI requests with mock-only STS and real offline TOS signing."""

import asyncio
import json
import threading
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ark_mcp.providers.tos.credentials import IrsaCredentialError
from tests.integration.test_byok_http import (
    OTHER_SECRET,
    assert_denied,
    call_tool,
    http_server,
    rpc,
    successful,
)
from tests.integration.test_temporary_upload import HEADERS, INPUT
from tests.unit.test_tos_irsa import (
    AK,
    SK,
    STS_TOKEN,
    TOKEN,
    irsa_settings,
    mock_exchange,
    response_body,
)


@pytest.mark.parametrize(
    "blocked",
    ["missing_secret", "unenrolled", "extra_input", "admission"],
)
async def test_blocked_http_calls_never_initialize_irsa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked: str
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Blocked requests must not exchange OIDC")

    mock_exchange(monkeypatch, forbidden)
    settings = irsa_settings(
        tmp_path, PROVIDER_MAX_CONCURRENCY=1, MCP_ADMISSION_TIMEOUT_SECONDS=0.02
    )
    headers = (
        None
        if blocked == "missing_secret"
        else {"X-MCP-Client-Secret": OTHER_SECRET}
        if blocked == "unenrolled"
        else HEADERS
    )
    data = {**INPUT, "file_path": "/tmp/forbidden"} if blocked == "extra_input" else INPUT
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        limiter = runtime.provider_limiters.provider("tos")
        if blocked == "admission":
            await limiter.acquire()
        try:
            assert_denied(await call_tool(client, "media_prepare_upload", data, headers=headers))
            assert runtime.tos_credentials is None
        finally:
            if blocked == "admission":
                limiter.release()


async def test_discovery_readiness_and_startup_do_not_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Discovery and readiness must not exchange OIDC")

    mock_exchange(monkeypatch, forbidden)
    # A nonexistent token file must not prevent startup or be read by discovery.
    async with http_server(tmp_path, settings=irsa_settings(tmp_path)) as (_, runtime, client):
        assert "media_prepare_upload" in str(await rpc(client, "tools/list"))
        discovery = successful(await call_tool(client, "ark_list_models", {}))
        storage = next(row for row in discovery["services"] if row["service"] == "object_storage")
        assert storage["enabled"] is True
        assert (await client.get("/ready")).json() == {"status": "ready"}
        assert runtime.tos_credentials is None and runtime.budget_ledger is None
    assert not list(tmp_path.rglob("*.sqlite3"))


async def test_enrolled_concurrent_calls_share_cache_until_lifespan_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_body(datetime.now(UTC).timestamp() + 3600))

    mock_exchange(monkeypatch, handler)
    async with http_server(tmp_path, settings=irsa_settings(tmp_path)) as (_, runtime, client):
        results = await asyncio.gather(
            *(call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS) for _ in range(3))
        )
        outputs = [successful(result) for result in results]
        assert len({output["object_key"] for output in outputs}) == 3
        assert len(requests) == 1
        assert parse_qs(requests[0].content.decode())["OIDCToken"] == [TOKEN]
        provider = runtime.tos_credentials
        assert provider is not None and provider._snapshot is not None
        for output in outputs:
            query = parse_qs(urlsplit(output["reference_url"]).query)
            assert query["X-Tos-Credential"][0].startswith(AK + "/")
            assert query["X-Tos-Security-Token"] == [STS_TOKEN]
            assert output["form_fields"]["x-tos-security-token"] == STS_TOKEN
            assert SK not in json.dumps(output)
    assert provider._snapshot is None
    with pytest.raises(IrsaCredentialError, match="closed"):
        provider.get_credentials()
    assert not list(tmp_path.rglob("*.sqlite3"))


async def test_each_server_owns_a_separate_irsa_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_body(datetime.now(UTC).timestamp() + 3600))

    mock_exchange(monkeypatch, handler)
    async with AsyncExitStack() as stack:
        runtimes = []
        for index in range(2):
            root = tmp_path / str(index)
            root.mkdir()
            (root / "projected-token").write_text(TOKEN)
            _, runtime, client = await stack.enter_async_context(
                http_server(root, settings=irsa_settings(root))
            )
            runtimes.append(runtime)
            successful(await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS))
        assert len(requests) == 2
        assert runtimes[0].tos_credentials is not runtimes[1].tos_credentials
        sessions = [parse_qs(request.content.decode())["RoleSessionName"] for request in requests]
        assert sessions[0] != sessions[1]
    assert all(
        runtime.tos_credentials is not None and runtime.tos_credentials._snapshot is None
        for runtime in runtimes
    )


async def test_sts_failure_is_sanitized_in_http_result_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, text=TOKEN + SK + STS_TOKEN)

    mock_exchange(monkeypatch, handler)
    async with http_server(tmp_path, settings=irsa_settings(tmp_path)) as (_, _, client):
        results = [
            await call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS)
            for _ in range(2)
        ]
    assert len(requests) == 1  # Failed exchanges are backed off across calls.
    for result in results:
        assert_denied(result)
        assert "TOS_IRSA_CREDENTIALS_UNAVAILABLE" in str(result)
    for secret in (TOKEN, SK, STS_TOKEN):
        assert secret not in json.dumps(results) + caplog.text


async def test_canceled_exchange_drains_worker_before_releasing_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    entered, release = threading.Event(), threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(5), "Test did not release the STS worker"
        return httpx.Response(200, json=response_body(datetime.now(UTC).timestamp() + 3600))

    mock_exchange(monkeypatch, handler)
    settings = irsa_settings(tmp_path, PROVIDER_MAX_CONCURRENCY=1)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        pending = asyncio.create_task(
            call_tool(client, "media_prepare_upload", INPUT, headers=HEADERS)
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            assert runtime.provider_limiters.provider("tos").locked()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, 5)
            assert not runtime.provider_limiters.provider("tos").locked()
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
