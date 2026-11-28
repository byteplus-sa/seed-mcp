"""Files tools use live ModelArk credentials, not operator storage or local state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx

from tests.contract.test_files_api import FILE, URL
from tests.integration.test_byok_http import (
    MODELARK,
    MODELARK_KEY,
    OTHER_SECRET,
    assert_denied,
    assert_no_canaries,
    call_tool,
    credentials,
    http_server,
    rpc,
    successful,
)


@respx.mock
async def test_files_discovery_and_live_url_workflow(tmp_path: Path) -> None:
    post = respx.post(MODELARK + "/files").respond(200, json=FILE)
    get = respx.get(MODELARK + "/files/file-synthetic").respond(
        200, json=FILE | {"download_url": URL}
    )
    listing = respx.get(MODELARK + "/files").respond(200, json={"data": [FILE], "has_more": False})
    delete = respx.delete(MODELARK + "/files/file-synthetic").respond(
        200, json={"id": FILE["id"], "deleted": True}
    )
    async with http_server(tmp_path) as (_, runtime, client):
        tools = (await rpc(client, "tools/list"))["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert {"ark_file_upload", "ark_file_get", "ark_file_list", "ark_file_delete"} <= names
        assert "media_prepare_upload" not in names
        uploaded = successful(
            await call_tool(client, "ark_file_upload", {"url": URL}, headers=credentials())
        )
        assert uploaded["id"] == FILE["id"] and uploaded["download_url"] is None
        # Same provider key with another client secret retains provider-authorized access.
        retrieved = successful(
            await call_tool(
                client,
                "ark_file_get",
                {"file_id": FILE["id"]},
                headers=credentials(secret=OTHER_SECRET),
            )
        )
        assert retrieved["download_url"] == URL
        successful(await call_tool(client, "ark_file_list", {}, headers=credentials()))
        successful(
            await call_tool(
                client,
                "ark_file_delete",
                {"file_id": FILE["id"], "confirm": True},
                headers=credentials(),
            )
        )
        assert runtime.budget_ledger is None
        assert_no_canaries(json.dumps(uploaded))
    assert not list(tmp_path.rglob("*"))
    for route in (post, get, listing, delete):
        assert route.call_count == 1
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {MODELARK_KEY}"


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-ModelArk-Api-Key": MODELARK_KEY}, credentials(header="X-Seed-Speech-Api-Key")],
)
@respx.mock
async def test_files_require_selected_live_credentials(tmp_path: Path, headers: dict) -> None:
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(await call_tool(client, "ark_file_list", {}, headers=headers))
    assert not respx.calls


@pytest.mark.parametrize(
    "payload",
    [
        {"file_path": "/tmp/client-file.mp4"},
        {"url": "https://127.0.0.1/file"},
        {"url": URL, "tos": {"bucket": "ignored"}},
        {"url": "tos://bucket/file"},
        {"data": "AAAA"},
        {"url": URL, "idempotency_key": "legacy"},
    ],
)
@respx.mock
async def test_hosted_upload_rejects_local_and_legacy_inputs(tmp_path: Path, payload: dict) -> None:
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(await call_tool(client, "ark_file_upload", payload, headers=credentials()))
    assert not respx.calls


@respx.mock
async def test_delete_requires_explicit_confirmation(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        assert_denied(
            await call_tool(
                client, "ark_file_delete", {"file_id": FILE["id"]}, headers=credentials()
            )
        )
    assert not respx.calls


@respx.mock
async def test_uncertain_upload_is_error_not_repeat(tmp_path: Path) -> None:
    route = respx.post(MODELARK + "/files").respond(
        500, json={"error": {"code": "InternalError", "message": URL}}
    )
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(client, "ark_file_upload", {"url": URL}, headers=credentials())
        assert_denied(result)
        assert "ambiguous_completion=True" in str(result)
        assert URL not in str(result)
        assert_no_canaries(json.dumps(result))
    assert route.call_count == 1


@respx.mock
async def test_stdio_local_file_uses_configured_modelark_key(fake_ctx, tmp_path: Path) -> None:
    from ark_mcp.domain.files import FileUploadInput
    from ark_mcp.tools.ark_files import ark_file_upload

    path = tmp_path / "reference.png"
    path.write_bytes(b"synthetic-local-reference")
    route = respx.post("https://ark.test.example.com/api/v3/files").respond(200, json=FILE)
    result = await ark_file_upload(FileUploadInput(file_path=str(path)), fake_ctx)
    assert result.id == FILE["id"]
    assert b"synthetic-local-reference" in route.calls.last.request.content
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test-modelark"


@respx.mock
async def test_files_admission_timeout_does_not_dispatch(tmp_path: Path) -> None:
    from tests.integration.test_byok_http import http_settings

    settings = http_settings(tmp_path, MCP_ADMISSION_TIMEOUT_SECONDS=0.01)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        slot = runtime.provider_limiters.provider("modelark")
        for _ in range(settings.provider_max_concurrency):
            await slot.acquire()
        try:
            result = await call_tool(client, "ark_file_list", {}, headers=credentials())
            assert_denied(result)
            assert "ADMISSION_TIMEOUT" in str(result)
            assert "ambiguous_completion=False" in str(result)
        finally:
            for _ in range(settings.provider_max_concurrency):
                slot.release()
    assert not respx.calls
