"""Removed protocol boundaries per specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import respx

from tests.integration.test_byok_http import (
    MODELARK,
    MODELARK_KEY,
    OTHER_SECRET,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    rpc,
)


@pytest.mark.parametrize(
    ("name", "input_data"),
    [
        ("ark_job_capabilities", None),
        (
            "ark_job_submit",
            {"tool_name": "seedream_generate_image", "arguments": {"input": {"prompt": "square"}}},
        ),
        ("ark_job_get", {"job_id": "synthetic-job-" + "x" * 32}),
        ("ark_job_cancel", {"job_id": "synthetic-job-" + "x" * 32}),
        ("seed_understand", {"prompt": "square"}),
        ("seed_audio_understand", {"prompt": "tone"}),
    ],
)
@respx.mock
async def test_removed_tools_unavailable_to_every_http_client_without_dispatch(
    tmp_path: Path, name: str, input_data: dict[str, Any] | None
) -> None:
    async with http_server(tmp_path) as (server, _, client):
        assert "io.modelcontextprotocol/tasks" not in server._extensions
        for headers in ({}, credentials(), credentials(MODELARK_KEY, OTHER_SECRET)):
            result = await call_tool(client, name, input_data, headers=headers)
            assert_denied(result)
            assert "unknown tool" in str(result).lower()
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    ("name", "input_data", "url", "response"),
    [
        (
            "seedream_generate_image",
            {"prompt": "square"},
            f"{MODELARK}/images/generations",
            {"data": [{"url": "https://example.com/image.png"}]},
        ),
        (
            "seedance_create_task",
            {"prompt": "scene", "idempotency_key": "native-task-rejected"},
            f"{MODELARK}/contents/generations/tasks",
            {"id": "must-not-submit"},
        ),
    ],
)
@respx.mock
async def test_native_task_opt_in_is_rejected_before_provider_dispatch(
    tmp_path: Path,
    name: str,
    input_data: dict[str, Any],
    url: str,
    response: dict[str, Any],
) -> None:
    route = respx.post(url).respond(200, json=response)
    async with http_server(tmp_path) as (server, _, client):
        assert "io.modelcontextprotocol/tasks" not in server._extensions
        result = await call_tool(client, name, input_data, headers=credentials(), task_capable=True)
    assert route.call_count == 0, "Native task opt-in dispatched provider work in the foreground."
    assert_denied(result)


@pytest.mark.parametrize("method", ["tasks/get", "tasks/update", "tasks/cancel"])
@respx.mock
async def test_native_task_methods_are_not_registered(tmp_path: Path, method: str) -> None:
    params: dict[str, Any] = {"taskId": "synthetic-task"}
    if method == "tasks/update":
        params["inputResponses"] = {}
    async with http_server(tmp_path) as (_, _, client):
        result = await rpc(
            client, method, params, headers=credentials(), task_capable=True, expected_status=404
        )
        assert result["error"]["code"] == -32601
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    "uri", ["seed-health://status", "seed-media://artifacts/5eacfd74-a1c4-42aa-bfc3-6247846abebe"]
)
@respx.mock
async def test_hidden_resources_cannot_be_read_by_uri(tmp_path: Path, uri: str) -> None:
    async with http_server(tmp_path) as (_, _, client):
        for headers in ({}, credentials()):
            result = await rpc(
                client, "resources/read", {"uri": uri}, headers=headers, expected_status=400
            )
            assert result["error"]["code"] == -32602
            assert "ModelArk configured" not in str(result)
    assert len(respx.calls) == 0


@pytest.mark.parametrize(
    "name",
    [
        "media_upload",
        "media_presign",
        "seed_media_get_artifact",
        "seed_media_export_artifact",
        "seed_media_persist_url",
    ],
)
@respx.mock
async def test_storage_and_artifact_tools_cannot_be_called(tmp_path: Path, name: str) -> None:
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(client, name, {}, headers=credentials())
        assert_denied(result)
        assert "unknown tool" in str(result).lower()
    assert len(respx.calls) == 0


async def test_http_server_has_no_oauth_or_jwks_routes(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
            "/.well-known/jwks.json",
            "/authorize",
            "/token",
            "/register",
        ):
            assert (await client.get(path)).status_code == 404
