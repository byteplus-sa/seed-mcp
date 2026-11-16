"""HTTP has no shared jobs or snapshots: specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import respx
from docket import Docket
from fastmcp_tasks.context import TaskContextSnapshot

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


@pytest.fixture
def background_spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    spies: dict[str, Mock] = {
        "capture": Mock(wraps=TaskContextSnapshot.capture),
        "save": AsyncMock(),
        "create": AsyncMock(),
        "bridge_create": AsyncMock(),
        "enqueue": AsyncMock(),
        "docket_add": Mock(),
    }
    monkeypatch.setattr(TaskContextSnapshot, "capture", spies["capture"])
    monkeypatch.setattr(TaskContextSnapshot, "save", spies["save"])
    monkeypatch.setattr("fastmcp_tasks.creation.create_task", spies["create"])
    monkeypatch.setattr("fastmcp_tasks.extension.create_task", spies["create"])
    monkeypatch.setattr("ark_mcp.background_jobs.create_task", spies["bridge_create"])
    monkeypatch.setattr("fastmcp_tasks.creation.add_component_to_docket", spies["enqueue"])
    monkeypatch.setattr(Docket, "add", spies["docket_add"])
    return spies


def assert_no_background_activity(spies: dict[str, Mock]) -> None:
    for spy in spies.values():
        spy.assert_not_called()


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
    ],
)
@respx.mock
async def test_ordinary_jobs_unavailable_to_every_http_client_before_snapshot_or_queue(
    tmp_path: Path, background_spies: dict[str, Mock], name: str, input_data: dict[str, Any] | None
) -> None:
    async with http_server(tmp_path) as (server, _, client):
        assert server._docket is None
        for headers in ({}, credentials(), credentials(MODELARK_KEY, OTHER_SECRET)):
            result = await call_tool(client, name, input_data, headers=headers)
            assert_denied(result)
            assert "unknown tool" in str(result).lower()
    assert_no_background_activity(background_spies)
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
            {"prompt": "scene"},
            f"{MODELARK}/contents/generations/tasks",
            {"id": "must-not-submit"},
        ),
    ],
)
@respx.mock
async def test_native_task_opt_in_is_rejected_before_snapshot_queue_or_provider(
    tmp_path: Path,
    background_spies: dict[str, Mock],
    name: str,
    input_data: dict[str, Any],
    url: str,
    response: dict[str, Any],
) -> None:
    route = respx.post(url).respond(200, json=response)
    async with http_server(tmp_path) as (server, _, client):
        assert server._docket is None
        result = await call_tool(client, name, input_data, headers=credentials(), task_capable=True)
    assert_no_background_activity(background_spies)
    assert route.call_count == 0, "Native task opt-in dispatched provider work in the foreground."
    assert_denied(result)


@pytest.mark.parametrize("method", ["tasks/get", "tasks/update", "tasks/cancel"])
@respx.mock
async def test_native_task_methods_are_not_registered(
    tmp_path: Path, background_spies: dict[str, Mock], method: str
) -> None:
    params: dict[str, Any] = {"taskId": "synthetic-task"}
    if method == "tasks/update":
        params["inputResponses"] = {}
    async with http_server(tmp_path) as (_, _, client):
        result = await rpc(
            client, method, params, headers=credentials(), task_capable=True, expected_status=404
        )
        assert result["error"]["code"] == -32601
    assert_no_background_activity(background_spies)
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
