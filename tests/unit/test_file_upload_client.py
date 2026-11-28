"""Client uploader is explicit, stream-only and independent of MCP server settings."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx

from ark_mcp import file_upload
from ark_mcp.domain.errors import ProviderError
from ark_mcp.providers.modelark.files import LocalFileUpload, ModelArkFilesGateway
from tests.contract.test_files_api import BASE, FILE, URL


def test_import_does_not_construct_settings(monkeypatch) -> None:
    settings = Mock(side_effect=AssertionError("client must not construct server settings"))
    monkeypatch.setattr("ark_mcp.config.env.Settings", settings)
    importlib.reload(file_upload)
    settings.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--file", "/tmp/synthetic"],
        ["--file", "/tmp/synthetic", "--confirm-upload", "--api-key-env", "not-a-name"],
        ["--file", "/tmp/synthetic", "--confirm-upload"],
    ],
)
@respx.mock
def test_missing_consent_or_key_fails_before_upload(monkeypatch, arguments) -> None:
    monkeypatch.setattr(sys, "argv", ["seed-mcp-upload", *arguments])
    with pytest.raises(SystemExit) as caught:
        file_upload.main()
    assert caught.value.code == 2
    assert not respx.calls


@respx.mock
def test_stdout_has_id_but_no_signed_url_or_key(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "input.png"
    path.write_bytes(b"tiny-synthetic")
    route = respx.post(BASE + "/files").respond(200, json=FILE | {"download_url": URL})
    monkeypatch.setenv("UPLOAD_TEST_KEY", "synthetic-client-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed-mcp-upload",
            "--file",
            str(path),
            "--api-key-env",
            "UPLOAD_TEST_KEY",
            "--confirm-upload",
        ],
    )
    file_upload.main()
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert data["id"] == FILE["id"] and data["next_tool"] == "ark_file_get"
    assert URL not in output.out and "synthetic-client-key" not in output.out + output.err
    assert route.calls.last.request.headers["Authorization"] == "Bearer synthetic-client-key"
    assert route.call_count == 1


@respx.mock
async def test_client_does_not_retry_mutations(tmp_path: Path) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"synthetic")
    route = respx.post(BASE + "/files").respond(500, json={"error": {"code": "InternalError"}})
    with pytest.raises(ProviderError) as caught:
        await file_upload.upload_local_file(file_path=str(path), api_key="synthetic-client-key")
    assert caught.value.ambiguous_completion
    assert route.call_count == 1


@pytest.mark.parametrize(
    "phase,observed_id",
    [
        ("before_headers", None),
        ("response_body", "provider-deadline-request"),
        ("response_body", "synthetic-client-key"),
        ("response_body", "https://example.invalid/reference?signature=private-value"),
    ],
)
@respx.mock
def test_cli_deadline_retains_safe_ids_and_closes_resources(
    tmp_path: Path, monkeypatch, capsys, phase: str, observed_id: str | None
) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"synthetic")
    deadlines = []
    real_timeout = asyncio.timeout
    sent_ids = []
    closed_files = []
    closed_clients = []
    closed_responses = []
    real_file_close = LocalFileUpload.aclose
    real_gateway_close = ModelArkFilesGateway.close

    def timeout(seconds):
        assert seconds == 600
        deadline = real_timeout(seconds)
        deadlines.append(deadline)
        return deadline

    async def stall():
        deadlines[-1].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()

    async def close_file(stream):
        await real_file_close(stream)
        closed_files.append(stream._file.closed)

    async def close_gateway(gateway):
        client = gateway._client
        await real_gateway_close(gateway)
        closed_clients.append(client.is_closed)

    class StalledResponse(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"private":"synthetic-client-key",'
            await stall()

        async def aclose(self):
            closed_responses.append(True)

    async def respond(request):
        sent_ids.append(request.headers["X-Request-Id"])
        if phase == "before_headers":
            await stall()
        return httpx.Response(
            200,
            headers={"X-Request-Id": observed_id or ""},
            stream=StalledResponse(),
        )

    route = respx.post(BASE + "/files").mock(side_effect=respond)
    monkeypatch.setattr(file_upload.asyncio, "timeout", timeout)
    monkeypatch.setattr(LocalFileUpload, "aclose", close_file)
    monkeypatch.setattr(ModelArkFilesGateway, "close", close_gateway)
    monkeypatch.setenv("UPLOAD_TEST_KEY", "synthetic-client-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed-mcp-upload",
            "--file",
            str(path),
            "--confirm-upload",
            "--api-key-env",
            "UPLOAD_TEST_KEY",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        file_upload.main()
    assert caught.value.code == 1
    output = capsys.readouterr()
    error = json.loads(output.err)
    assert error["code"] == "UPLOAD_DEADLINE_EXCEEDED"
    assert error["ambiguous_completion"] is True
    assert error["retryable"] is False
    assert "provider may have accepted" in error["message"]
    assert "Do not upload again blindly" in error["message"]
    assert sent_ids[0] in error["message"]
    expected_id = observed_id if observed_id == "provider-deadline-request" else sent_ids[0]
    assert error["request_id"] == expected_id
    assert expected_id in error["message"]
    assert output.out == ""
    assert "synthetic-client-key" not in output.err
    assert "signature=private-value" not in output.err
    assert len(sent_ids) == 1
    # RESPX does not count a call whose callback exits by cancellation.
    assert route.call_count == (0 if phase == "before_headers" else 1)
    assert closed_files == closed_clients == [True]
    assert closed_responses == ([] if phase == "before_headers" else [True])


@respx.mock
def test_local_validation_still_reports_no_uncertain_upload(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("UPLOAD_TEST_KEY", "synthetic-client-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed-mcp-upload",
            "--file",
            str(tmp_path / "missing"),
            "--confirm-upload",
            "--api-key-env",
            "UPLOAD_TEST_KEY",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        file_upload.main()
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert "validation or local I/O" in output.err
    assert "may have accepted" not in output.err
    assert not respx.calls


@pytest.mark.parametrize("cancelled", [False, True])
@respx.mock
async def test_before_dispatch_deadline_and_external_cancellation(
    tmp_path: Path, monkeypatch, cancelled: bool
) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"synthetic")
    closed_files = []
    real_close = LocalFileUpload.aclose

    async def unavailable_client(self):
        if cancelled:
            raise asyncio.CancelledError
        raise TimeoutError("synthetic-client-key must not leak")

    async def close_file(stream):
        await real_close(stream)
        closed_files.append(stream._file.closed)

    monkeypatch.setattr(ModelArkFilesGateway, "_ensure_client", unavailable_client)
    monkeypatch.setattr(LocalFileUpload, "aclose", close_file)
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await file_upload.upload_local_file(file_path=str(path), api_key="synthetic-client-key")
    else:
        with pytest.raises(ProviderError) as caught:
            await file_upload.upload_local_file(file_path=str(path), api_key="synthetic-client-key")
        assert caught.value.error.code == "UPLOAD_DEADLINE_EXCEEDED"
        assert caught.value.ambiguous_completion is False
        assert caught.value.request_id is None
        assert "before provider dispatch" in caught.value.message
        assert "synthetic-client-key" not in caught.value.error.model_dump_json()
    assert closed_files == [True]
    assert not respx.calls
