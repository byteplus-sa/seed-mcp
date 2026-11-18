"""Database-free multi-instance BYOK behavior and explicit loss of durable replay."""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path

import httpx
import pytest
import respx

from tests.integration.test_byok_http import (
    MODELARK,
    OTHER_SECRET,
    VISION,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)
from tests.integration.test_task_security import provider_task

TASKS = f"{MODELARK}/contents/generations/tasks"


@pytest.mark.parametrize("replicas", [2, 4])
@respx.mock
async def test_tasks_follow_provider_credentials_across_instances_and_restart(
    tmp_path: Path, replicas: int
) -> None:
    creates = respx.post(TASKS).respond(200, json={"id": "provider-authorized-task"})
    task = provider_task("provider-authorized-task")
    reads = respx.get(TASKS).respond(200, json={"data": [task], "has_more": False})
    async with AsyncExitStack() as stack:
        clients = [
            (await stack.enter_async_context(http_server(tmp_path / str(index))))[2]
            for index in range(replicas)
        ]
        output = successful(
            await call_tool(
                clients[0], "seedance_create_task", {"prompt": "Synthetic"}, headers=credentials()
            )
        )
        assert output["tasks"][0]["task_id"] == task["id"]
        for client in clients:
            polled = successful(
                await call_tool(
                    client,
                    "gen_task_get",
                    {"task_ids": [task["id"]]},
                    headers=credentials(secret=OTHER_SECRET),
                )
            )
            assert polled["tasks"][0]["task_id"] == task["id"]
            listed = successful(await call_tool(client, "gen_task_list", {}, headers=credentials()))
            assert listed["tasks"][0]["task_id"] == task["id"]
            assert (await client.get("/ready")).json() == {"status": "ready"}
    async with http_server(tmp_path / "restart") as (_, _, client):
        assert (
            successful(
                await call_tool(
                    client, "gen_task_get", {"task_ids": [task["id"]]}, headers=credentials()
                )
            )["tasks"][0]["task_id"]
            == task["id"]
        )
    assert creates.call_count == 1 and reads.call_count >= replicas
    assert not list(tmp_path.rglob("*.sqlite3"))
    assert not list(tmp_path.rglob("*.lock"))


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("seedance_create_task", {"prompt": "Synthetic"}),
        ("seedance_create_task", {"prompt": "Synthetic", "dry_run": True}),
        (
            "omnihuman_create_task",
            {"image": "https://example.com/face.png", "audio": "https://example.com/audio.wav"},
        ),
    ],
)
@respx.mock
async def test_legacy_replay_key_is_rejected_before_dispatch(
    tmp_path: Path, tool: str, arguments: dict
) -> None:
    config = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=config) as (_, _, client):
        result = await call_tool(
            client,
            tool,
            {**arguments, "idempotency_key": "legacy-operation-0001"},
            headers=credentials(
                header="X-OmniHuman-Api-Key"
                if tool.startswith("omnihuman")
                else "X-ModelArk-Api-Key"
            ),
        )
        assert_denied(result)
        assert "unsupported" in str(result)
    assert not respx.calls


@respx.mock
async def test_identical_mock_creates_are_independent_not_saved_replays(tmp_path: Path) -> None:
    route = respx.post(TASKS).mock(
        side_effect=[
            httpx.Response(200, json={"id": "first-task"}),
            httpx.Response(200, json={"id": "second-task"}),
        ]
    )
    async with http_server(tmp_path) as (_, runtime, client):
        results = [
            successful(
                await call_tool(
                    client, "seedance_create_task", {"prompt": "Synthetic"}, headers=credentials()
                )
            )
            for _ in range(2)
        ]
        assert runtime.budget_ledger is None
    assert results[0]["tasks"][0]["task_id"] != results[1]["tasks"][0]["task_id"]
    assert route.call_count == 2


@respx.mock
async def test_provider_denial_is_not_bypassed_by_client_secret(tmp_path: Path) -> None:
    route = respx.get(TASKS).respond(
        403, json={"error": {"code": "AccessDenied", "message": "Denied"}}
    )
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(
            client, "gen_task_get", {"task_ids": ["unknown-task"]}, headers=credentials()
        )
        assert_denied(result)
        assert "AccessDenied" in str(result)
        assert route.call_count == 1


@respx.mock
async def test_uncertain_create_is_not_automatically_retried(tmp_path: Path) -> None:
    route = respx.post(TASKS).mock(side_effect=httpx.ReadTimeout("synthetic"))
    async with http_server(tmp_path) as (_, _, client):
        result = await call_tool(
            client, "seedance_create_task", {"prompt": "Synthetic"}, headers=credentials()
        )
        assert_denied(result)
        assert "ambiguous_completion=True" in str(result)
    assert route.call_count == 1


@respx.mock
async def test_omnihuman_works_without_journal_or_local_storage(tmp_path: Path) -> None:
    route = respx.post(f"{VISION}/api/common/v3/submit_task_v2").respond(
        200,
        json={"code": 10000, "data": {"task_id": "avatar-task"}, "request_id": "request-avatar"},
    )
    config = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=config) as (_, _, client):
        result = successful(
            await call_tool(
                client,
                "omnihuman_create_task",
                {"image": "https://example.com/face.png", "audio": "https://example.com/audio.wav"},
                headers=credentials(header="X-OmniHuman-Api-Key"),
            )
        )
        assert result["task_id"] == "avatar-task"
    assert route.call_count == 1
    assert not (tmp_path / "artifacts").exists()
