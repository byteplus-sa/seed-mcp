"""Offline Files wire, streaming, response-bound and uncertainty contracts."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import respx

from ark_mcp.domain.errors import ProviderError
from ark_mcp.domain.files import FileDeleteInput, FileListInput, FileUploadInput
from ark_mcp.execution import run_direct_call
from ark_mcp.providers.modelark.files import LocalFileUpload, ModelArkFilesGateway

BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
FILE = {
    "id": "file-synthetic",
    "object": "file",
    "purpose": "agent",
    "filename": "sample.png",
    "status": "active",
    "bytes": 4,
    "created_at": 1795854853,
    "expire_at": 1796459653,
}
URL = "https://media.example.com/sample.png?signature=synthetic"


@pytest.fixture
async def service():
    gateway = ModelArkFilesGateway(
        api_key="synthetic-file-key",  # pragma: allowlist secret
        base_url=BASE,
        timeout=5,
        connect_timeout=2,
    )
    yield gateway
    await gateway.close()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"url": URL, "file_path": "/tmp/a"},
        {"url": "tos://bucket/a"},
        {"url": "http://example.com/a"},
        {"url": "https://user:password@example.com/a"},  # pragma: allowlist secret
        {"url": URL, "tos": {"bucket": "forbidden"}},
        {"url": URL, "expire_at": 1},
        {"url": URL, "data": "AAAA"},
        {"file_path": ""},
    ],
)
def test_invalid_upload_inputs(data) -> None:
    with pytest.raises(ValueError):
        FileUploadInput.model_validate(data)


def test_delete_requires_confirmation_and_valid_id() -> None:
    for payload in (
        {"file_id": "file-synthetic"},
        {"file_id": "../secrets", "confirm": True},
        {"file_id": "file-synthetic", "confirm": False},
        {"file_id": "file-synthetic", "confirm": 1},
    ):
        with pytest.raises(ValueError):
            FileDeleteInput.model_validate(payload)


@respx.mock
async def test_url_upload_is_multipart_agent_without_tos(service) -> None:
    route = respx.post(BASE + "/files").respond(200, json=FILE)
    result = await service.upload(url=URL)
    assert result.id == FILE["id"] and result.download_url is None
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer synthetic-file-key"
    assert request.headers["Content-Type"].startswith("multipart/form-data;")
    assert b'name="purpose"\r\n\r\nagent' in request.content
    assert URL.encode() in request.content
    assert b"tos" not in request.content
    assert route.call_count == 1


@respx.mock
async def test_file_upload_streams_regular_file(service, tmp_path: Path) -> None:
    path = tmp_path / "sample.png"
    path.write_bytes(b"synthetic-content")
    route = respx.post(BASE + "/files").respond(200, json=FILE)
    await service.upload(file_path=str(path))
    request = route.calls.last.request
    assert b'filename="sample.png"' in request.content
    assert b"synthetic-content" in request.content
    assert int(request.headers["Content-Length"]) == len(request.content)


async def test_stream_bounds_and_file_changes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"12345678")
    monkeypatch.setattr("ark_mcp.providers.modelark.files.CHUNK_BYTES", 3)
    stream = LocalFileUpload(str(path), {"purpose": "agent"})
    try:
        chunks = [chunk async for chunk in stream]
        assert list(map(len, chunks[1:-1])) == [3, 3, 2]
        assert stream.length == sum(map(len, chunks))
    finally:
        await stream.aclose()
    stream = LocalFileUpload(str(path), {"purpose": "agent"})
    path.write_bytes(b"short")
    try:
        with pytest.raises(ValueError, match="changed"):
            _ = [chunk async for chunk in stream]
    finally:
        await stream.aclose()


def test_reject_unsafe_local_sources(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"abc")
    link = tmp_path / "link"
    link.symlink_to(path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for source in ("relative", str(link), str(fifo), str(tmp_path)):
        with pytest.raises((OSError, ValueError)):
            LocalFileUpload(source, {"purpose": "agent"})
    monkeypatch.setattr("ark_mcp.providers.modelark.files.MAX_FILE_BYTES", 2)
    with pytest.raises(ValueError, match="512"):
        LocalFileUpload(str(path), {"purpose": "agent"})


@respx.mock
async def test_get_list_delete_and_no_download_or_refresh(service) -> None:
    get = respx.get(BASE + "/files/file-synthetic").respond(200, json=FILE | {"download_url": URL})
    listing = respx.get(BASE + "/files").respond(
        200,
        json={
            "data": [FILE | {"download_url": URL}],
            "first_id": FILE["id"],
            "last_id": FILE["id"],
            "has_more": True,
        },
    )
    delete = respx.delete(BASE + "/files/file-synthetic").respond(
        200,
        json={
            "id": FILE["id"],
            "object": "file",
            "deleted": True,
        },
    )
    assert (await service.get_file(FILE["id"])).download_url == URL
    page = await service.list_files(FileListInput(limit=1))
    assert page.has_more and page.last_id == FILE["id"]
    assert dict(listing.calls.last.request.url.params) == {
        "limit": "1",
        "order": "desc",
        "purpose": "agent",
    }
    assert (await service.delete_file(FILE["id"])).deleted
    assert get.call_count == listing.call_count == delete.call_count == 1
    assert len(respx.calls) == 3


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {"error": {"code": "InternalError", "message": f"failed {URL} synthetic-file-key"}}),
        (200, {"invalid": True}),
        (302, {}),
    ],
)
@respx.mock
async def test_failed_upload_never_retries_or_leaks(service, status, body) -> None:
    route = respx.post(BASE + "/files").respond(status, json=body)
    with pytest.raises(ProviderError) as caught:
        await service.upload(url=URL)
    assert route.call_count == 1
    assert URL not in str(caught.value) and "synthetic-file-key" not in str(caught.value)
    assert caught.value.ambiguous_completion is (status in (200, 500))
    assert not caught.value.retryable


@pytest.mark.parametrize("mutation", [True, False])
@respx.mock
async def test_response_bound(service, monkeypatch, mutation: bool) -> None:
    monkeypatch.setattr("ark_mcp.providers.modelark.files.MAX_RESPONSE_BYTES", 10)
    respx.route().respond(200, content=b"x" * 11)
    with pytest.raises(ProviderError) as caught:
        if mutation:
            await service.upload(url=URL)
        else:
            await service.get_file(FILE["id"])
    assert caught.value.code == "INVALID_RESPONSE"
    assert caught.value.ambiguous_completion is mutation


@respx.mock
async def test_upload_cancellation_and_receipt_on_deadline(service) -> None:
    respx.post(BASE + "/files").respond(200, json=FILE)

    async def delayed_return():
        await service.upload(url=URL)
        await asyncio.sleep(1)

    result = await run_direct_call(delayed_return, timeout_seconds=0.05, read_only=False)
    assert result.is_error
    assert "file_id=file-synthetic" in str(result.content)
    assert "ambiguous_completion=True" in str(result.content)
    assert len(respx.calls) == 1


@pytest.mark.parametrize("method", ["POST", "GET", "DELETE"])
@pytest.mark.parametrize("phase", ["headers", "body"])
@respx.mock
async def test_deadline_retains_dispatched_and_observed_request_ids(
    service, method: str, phase: str
) -> None:
    sent_ids: list[str] = []
    closed = asyncio.Event()

    class WaitingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"unused"

        async def aclose(self):
            closed.set()

    async def respond(request: httpx.Request) -> httpx.Response:
        sent_ids.append(request.headers["X-Request-Id"])
        if phase == "headers":
            await asyncio.Event().wait()
        return httpx.Response(
            200, headers={"X-Request-Id": "provider-request"}, stream=WaitingBody()
        )

    respx.route(method=method).mock(side_effect=respond)
    await service._ensure_client()

    async def call():
        if method == "POST":
            return await service.upload(url=URL)
        if method == "DELETE":
            return await service.delete_file(FILE["id"])
        return await service.get_file(FILE["id"])

    result = await run_direct_call(call, timeout_seconds=0.05, read_only=method == "GET")
    text = result.content[0].text
    assert result.is_error
    assert len(sent_ids) == 1
    assert f"request_id={sent_ids[0]}" in text
    assert f"ambiguous_completion={method != 'GET'}" in text
    assert "file_id=" not in text and "task_id=" not in text
    if phase == "body":
        assert "request_id=provider-request" in text
        assert closed.is_set()
    else:
        assert "provider-request" not in text


@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.ReadTimeout, OSError, ValueError])
@pytest.mark.parametrize(
    "provider_id", ["provider-request", None, "unsafe/id", "synthetic-file-key"]
)
@respx.mock
async def test_body_failure_preserves_safe_provider_id_or_sent_fallback(
    service, failure, provider_id: str | None
) -> None:
    closed = asyncio.Event()

    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise failure("synthetic body failure")
            yield b"unused"

        async def aclose(self):
            closed.set()

    route = respx.post(BASE + "/files").mock(
        return_value=httpx.Response(
            200,
            headers={"X-Request-Id": provider_id} if provider_id is not None else {},
            stream=BrokenBody(),
        )
    )
    with pytest.raises(ProviderError) as caught:
        await service.upload(url=URL)
    sent_id = route.calls.last.request.headers["X-Request-Id"]
    expected_id = provider_id if provider_id == "provider-request" else sent_id
    assert caught.value.request_id == expected_id
    assert caught.value.ambiguous_completion
    assert not caught.value.retryable
    assert "synthetic-file-key" not in caught.value.error.model_dump_json()
    assert route.call_count == 1
    assert closed.is_set()


@respx.mock
async def test_deadline_before_authorization_does_not_record_request_id(
    service, monkeypatch
) -> None:
    async def blocked_authorization(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "ark_mcp.providers.modelark.files.authorize_provider_request", blocked_authorization
    )
    result = await run_direct_call(
        lambda: service.upload(url=URL), timeout_seconds=0.05, read_only=False
    )
    assert "ambiguous_completion=False" in result.content[0].text
    assert "request_id=" not in result.content[0].text
    assert not respx.calls


@respx.mock
async def test_mismatched_file_and_unusable_cursor_fail(service) -> None:
    respx.get(BASE + "/files/file-synthetic").respond(200, json=FILE | {"id": "file-other"})
    respx.get(BASE + "/files").respond(200, json={"data": [], "has_more": True})
    with pytest.raises(ProviderError):
        await service.get_file(FILE["id"])
    with pytest.raises(ProviderError):
        await service.list_files(FileListInput())


@pytest.mark.parametrize("status", [200, 500])
@pytest.mark.parametrize("encoded", [True, False])
@respx.mock
async def test_credential_echoes_are_never_returned(status: int, encoded: bool) -> None:
    key = 'synthetic/file+key"with\\escapes'
    echoed = quote(key, safe="") if encoded else key
    body = FILE | {"filename": echoed} if status == 200 else {"error": {"message": echoed}}
    route = respx.post(BASE + "/files").respond(status, json=body)
    gateway = ModelArkFilesGateway(api_key=key, base_url=BASE, timeout=5, connect_timeout=2)
    try:
        with pytest.raises(ProviderError) as caught:
            await gateway.upload(url=URL)
        assert key not in caught.value.message
        assert echoed not in caught.value.message
        assert caught.value.ambiguous_completion
        assert not caught.value.retryable
        assert route.call_count == 1
    finally:
        await gateway.close()


@pytest.mark.parametrize("method", ["POST", "GET", "DELETE"])
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.DecodingError])
@respx.mock
async def test_interrupted_requests_are_bounded_and_not_retried(service, method, error) -> None:
    route = respx.route(method=method).mock(side_effect=error("synthetic-file-key"))
    with pytest.raises(ProviderError) as caught:
        if method == "POST":
            await service.upload(url=URL)
        elif method == "DELETE":
            await service.delete_file(FILE["id"])
        else:
            await service.get_file(FILE["id"])
    assert caught.value.ambiguous_completion is (method != "GET")
    assert caught.value.retryable is (method == "GET")
    assert caught.value.request_id
    assert "synthetic-file-key" not in str(caught.value)
    assert route.call_count == 1


@respx.mock
async def test_external_cancellation_closes_response_without_retry(service) -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    class DelayedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unused"

        async def aclose(self):
            closed.set()

    route = respx.post(BASE + "/files").mock(return_value=httpx.Response(200, stream=DelayedBody()))
    task = asyncio.create_task(service.upload(url=URL))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert route.call_count == 1


async def test_cancelled_local_read_drains_before_file_close(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"synthetic")
    stream = LocalFileUpload(str(path), {"purpose": "agent"})
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_read = stream._file.read

    def delayed_read(size):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        return original_read(size)

    monkeypatch.setattr(stream._file, "read", delayed_read)

    async def consume():
        try:
            return [chunk async for chunk in stream]
        finally:
            await stream.aclose()

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not stream._file.closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream._file.closed
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@respx.mock
async def test_pagination_filters_and_requested_limit(service) -> None:
    route = respx.get(BASE + "/files").respond(
        200, json={"data": [FILE, FILE | {"id": "file-other"}], "has_more": False}
    )
    with pytest.raises(ProviderError) as caught:
        await service.list_files(
            FileListInput(after="file-before", purpose=None, order="asc", limit=1)
        )
    assert caught.value.code == "INVALID_RESPONSE"
    assert dict(route.calls.last.request.url.params) == {
        "after": "file-before",
        "order": "asc",
        "limit": "1",
    }
