"""Provider ownership over HTTP, per specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    MODELARK,
    MODELARK_KEY,
    OTHER_SECRET,
    SPEECH_KEY,
    VIDEO_MODEL,
    VISION,
    VISION_KEY,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)

TASKS_URL = f"{MODELARK}/contents/generations/tasks"


def provider_task(task_id: str, status: str = "queued", **extra: Any) -> dict[str, Any]:
    return {
        "id": task_id,
        "model": VIDEO_MODEL,
        "status": status,
        "created_at": int(datetime.now(UTC).timestamp()),
        **extra,
    }


async def create_video(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    result = successful(
        await call_tool(
            client, "seedance_create_task", {"prompt": "A synthetic scene"}, headers=headers
        )
    )
    assert result["submitted"] == 1
    return str(result["tasks"][0]["task_id"])


@pytest.mark.parametrize("other", ["different_key", "different_secret"])
@pytest.mark.parametrize("restart", [False, True])
@respx.mock
async def test_cross_owner_get_list_cancel_and_draft_are_denied_before_outbound(
    tmp_path: Path, other: str, restart: bool
) -> None:
    respx.post(TASKS_URL).respond(200, json={"id": "task-private"})
    owner = credentials()
    stranger = (
        credentials("synthetic-other-modelark", CLIENT_SECRET)
        if other == "different_key"
        else credentials(MODELARK_KEY, OTHER_SECRET)
    )

    async def check_denied(client: httpx.AsyncClient) -> None:
        before = len(respx.calls)
        got = successful(
            await call_tool(
                client, "gen_task_get", {"task_ids": ["task-private"]}, headers=stranger
            )
        )
        assert got["tasks"] == []
        assert [(error["task_id"], error["code"]) for error in got["errors"]] == [
            ("task-private", "NOT_OWNED")
        ]
        for filters in ({}, {"task_ids": ["task-private"]}):
            listed = successful(await call_tool(client, "gen_task_list", filters, headers=stranger))
            assert listed == {"tasks": [], "next_cursor": None}
        for name, input_data in (
            (
                "gen_task_cancel_or_delete",
                {"task_id": "task-private", "mode": "cancel", "expected_status": "queued"},
            ),
            ("seedance_create_task", {"draft_task_id": "task-private"}),
            ("seedance_create_task", {"draft_task_id": "task-private", "dry_run": True}),
        ):
            assert_denied(await call_tool(client, name, input_data, headers=stranger))
        assert len(respx.calls) == before

    async with http_server(tmp_path) as (_, _, client):
        assert await create_video(client, owner) == "task-private"
        if not restart:
            await check_denied(client)
    if restart:
        async with http_server(tmp_path) as (_, _, client):
            await check_denied(client)


@pytest.mark.parametrize("restart", [False, True])
@respx.mock
async def test_owner_survives_restart_and_unrelated_provider_key_addition(
    tmp_path: Path, restart: bool
) -> None:
    respx.post(TASKS_URL).respond(200, json={"id": "task-owned"})
    get_route = respx.get(TASKS_URL).respond(200, json={"data": [provider_task("task-owned")]})
    headers = {**credentials(), "X-Seed-Speech-Api-Key": SPEECH_KEY}

    async def check_owner(client: httpx.AsyncClient) -> None:
        got = successful(
            await call_tool(client, "gen_task_get", {"task_ids": ["task-owned"]}, headers=headers)
        )
        assert got["errors"] == []
        assert [task["task_id"] for task in got["tasks"]] == ["task-owned"]
        listed = successful(await call_tool(client, "gen_task_list", {}, headers=headers))
        assert [task["task_id"] for task in listed["tasks"]] == ["task-owned"]

    async with http_server(tmp_path) as (_, _, client):
        assert await create_video(client, credentials()) == "task-owned"
        if not restart:
            await check_owner(client)
    if restart:
        async with http_server(tmp_path) as (_, _, client):
            await check_owner(client)
    assert get_route.call_count == 2
    for call in get_route.calls:
        assert call.request.headers["Authorization"] == f"Bearer {MODELARK_KEY}"
        assert call.request.url.params.get_list("filter.task_ids") == ["task-owned"]


@respx.mock
async def test_distinct_keys_may_own_identical_provider_task_ids_after_restart(
    tmp_path: Path,
) -> None:
    keys = ["synthetic-tenant-first", "synthetic-tenant-second"]
    respx.post(TASKS_URL).respond(200, json={"id": "provider-reused-id"})

    def poll(request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        index = keys.index(key)
        return httpx.Response(
            200,
            json={
                "data": [
                    provider_task(
                        "provider-reused-id",
                        "succeeded",
                        content={"video_url": f"https://example.com/owner-{index}.mp4"},
                    )
                ]
            },
        )

    respx.get(TASKS_URL).mock(side_effect=poll)
    async with http_server(tmp_path) as (_, _, client):
        ids = await asyncio.gather(*(create_video(client, credentials(key)) for key in keys))
        assert ids == ["provider-reused-id", "provider-reused-id"]
    async with http_server(tmp_path) as (_, _, client):
        for index, key in enumerate(keys):
            result = successful(
                await call_tool(
                    client,
                    "gen_task_get",
                    {"task_ids": ["provider-reused-id"]},
                    headers=credentials(key),
                )
            )
            assert result["errors"] == []
            assert (
                result["tasks"][0]["outputs"][0]["source_url"]
                == f"https://example.com/owner-{index}.mp4"
            )


@respx.mock
async def test_conflicting_same_key_submissions_never_reassign_owner(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    count = 0

    async def accepted(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), 5)
        return httpx.Response(200, json={"id": "provider-collision"})

    respx.post(TASKS_URL).mock(side_effect=accepted)
    respx.get(TASKS_URL).respond(200, json={"data": [provider_task("provider-collision")]})
    owners = [credentials(), credentials(MODELARK_KEY, OTHER_SECRET)]
    async with http_server(tmp_path) as (_, _, client):
        results = await asyncio.gather(
            *(
                call_tool(client, "seedance_create_task", {"prompt": "scene"}, headers=headers)
                for headers in owners
            )
        )
        winners = [
            index
            for index, result in enumerate(results)
            if not result.get("result", {}).get("isError", True)
        ]
        assert len(winners) == 1, results
        winner = winners[0]
        denied = results[1 - winner]
        assert_denied(denied)
    assert count == 2
    async with http_server(tmp_path) as (_, _, client):
        for index, headers in enumerate(owners):
            before = len(respx.calls)
            result = successful(
                await call_tool(
                    client, "gen_task_get", {"task_ids": ["provider-collision"]}, headers=headers
                )
            )
            if index == winner:
                assert [task["task_id"] for task in result["tasks"]] == ["provider-collision"]
            else:
                assert result["tasks"] == []
                assert result["errors"][0]["code"] == "NOT_OWNED"
                assert len(respx.calls) == before
    assert any(word in str(denied).lower() for word in ("unknown", "ambiguous", "reconcile")), (
        denied
    )


@respx.mock
async def test_owner_can_cancel_but_spoofed_identity_headers_cannot(
    tmp_path: Path,
) -> None:
    respx.post(TASKS_URL).respond(200, json={"id": "task-cancel"})
    respx.get(f"{TASKS_URL}/task-cancel").respond(200, json=provider_task("task-cancel"))
    deleted = respx.delete(f"{TASKS_URL}/task-cancel").respond(204)
    input_data = {"task_id": "task-cancel", "mode": "cancel", "expected_status": "queued"}
    async with http_server(tmp_path) as (_, _, client):
        await create_video(client, credentials())
        before = len(respx.calls)
        spoofed = {
            **credentials(MODELARK_KEY, OTHER_SECRET),
            "X-Tenant-Id": "local",
            "X-Principal-Id": "local",
            "X-Forwarded-User": "shared-team",
        }
        assert_denied(
            await call_tool(client, "gen_task_cancel_or_delete", input_data, headers=spoofed)
        )
        assert len(respx.calls) == before
        result = successful(
            await call_tool(client, "gen_task_cancel_or_delete", input_data, headers=credentials())
        )
        assert result["task_id"] == "task-cancel"
        assert result["mode"] == "cancel"
    assert deleted.call_count == 1
    assert deleted.calls[0].request.headers["Authorization"] == f"Bearer {MODELARK_KEY}"


@respx.mock
async def test_mixed_owned_and_foreign_get_filters_before_upstream(
    tmp_path: Path,
) -> None:
    respx.post(TASKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"id": "mine"}),
            httpx.Response(200, json={"id": "foreign"}),
        ]
    )
    get_route = respx.get(TASKS_URL).respond(
        200, json={"data": [provider_task("mine"), provider_task("foreign")]}
    )
    async with http_server(tmp_path) as (_, _, client):
        await create_video(client, credentials())
        await create_video(client, credentials(MODELARK_KEY, OTHER_SECRET))
        result = successful(
            await call_tool(
                client,
                "gen_task_get",
                {"task_ids": ["mine", "foreign", "unknown"]},
                headers=credentials(),
            )
        )
        assert [task["task_id"] for task in result["tasks"]] == ["mine"]
        assert {error["task_id"] for error in result["errors"]} == {"foreign", "unknown"}
        assert all(error["code"] == "NOT_OWNED" for error in result["errors"])
    assert get_route.call_count == 1
    assert get_route.calls[0].request.url.params.get_list("filter.task_ids") == ["mine"]


@respx.mock
async def test_ownership_database_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with http_server(tmp_path) as (_, runtime, client):
        failure = AsyncMock(side_effect=RuntimeError("synthetic storage unavailable"))
        monkeypatch.setattr(runtime.ownership_store, "require_owner", failure)
        for name, input_data in (
            ("gen_task_get", {"task_ids": ["unknown"]}),
            (
                "gen_task_cancel_or_delete",
                {"task_id": "unknown", "mode": "cancel", "expected_status": "queued"},
            ),
            ("seedance_create_task", {"draft_task_id": "unknown"}),
        ):
            assert_denied(await call_tool(client, name, input_data, headers=credentials()))
        assert failure.await_count == 3
    assert len(respx.calls) == 0


@respx.mock
async def test_omnihuman_ownership_denied_before_get_or_cancel(
    tmp_path: Path,
) -> None:
    respx.post(f"{VISION}/api/common/v3/submit_task_v2").respond(
        200, json={"code": 10000, "data": {"task_id": "avatar-private"}}
    )
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        result = successful(
            await call_tool(
                client,
                "omnihuman_create_task",
                {"image": "https://example.com/face.png", "audio": "https://example.com/a.wav"},
                headers=credentials(VISION_KEY, header="X-OmniHuman-Api-Key"),
            )
        )
        assert result["task_id"] == "avatar-private"
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        before = len(respx.calls)
        for name in ("omnihuman_get_task", "omnihuman_cancel_task"):
            for key, secret in (
                (VISION_KEY, OTHER_SECRET),
                ("synthetic-other-vision", CLIENT_SECRET),
            ):
                assert_denied(
                    await call_tool(
                        client,
                        name,
                        {"task_id": "avatar-private"},
                        headers=credentials(key, secret, header="X-OmniHuman-Api-Key"),
                    )
                )
        assert len(respx.calls) == before
