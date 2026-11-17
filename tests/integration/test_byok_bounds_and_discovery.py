"""Bounded admission and request-local discovery for the hosted foundation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from tests.integration.test_byok_http import (
    IMAGE_MODEL,
    MODELARK,
    assert_denied,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)


@respx.mock
async def test_anonymous_discovery_uses_server_bindings_without_provider_keys(
    tmp_path: Path,
) -> None:
    async with http_server(tmp_path) as (_, _, client):
        result = successful(await call_tool(client, "ark_list_models", {}))
        models = {model["model_id"] for model in result["models"]}
        assert IMAGE_MODEL in models
        services = {service["service"]: service["enabled"] for service in result["services"]}
        assert services == {
            "modelark": True,
            "seed_audio": True,
            "omnihuman": False,
            "object_storage": False,
        }
    assert not respx.calls


@respx.mock
async def test_different_servers_keep_capability_bindings_isolated(tmp_path: Path) -> None:
    alternate = "dola-seedream-5-5-261028"
    first_settings = http_settings(tmp_path / "first")
    second_settings = http_settings(tmp_path / "second", SEEDREAM_DEFAULT_MODEL=alternate)
    async with (
        http_server(tmp_path / "first", settings=first_settings) as (_, _, first),
        http_server(tmp_path / "second", settings=second_settings) as (_, _, second),
    ):
        for client, expected in ((first, IMAGE_MODEL), (second, alternate), (first, IMAGE_MODEL)):
            result = successful(await call_tool(client, "ark_list_models", {"kind": "image"}))
            assert [model["model_id"] for model in result["models"]] == [expected]
            preview = successful(
                await call_tool(
                    client,
                    "seedream_generate_image",
                    {"prompt": "A blue square", "dry_run": True},
                    headers=credentials(),
                )
            )
            assert preview["model"] == expected
    assert not respx.calls


@respx.mock
async def test_endpoint_defaults_are_validated_and_explicit_model_wins(tmp_path: Path) -> None:
    async with http_server(tmp_path) as (_, _, client):
        headers = {**credentials(), "X-ModelArk-Seedream-Endpoint": "ep-unverified"}
        assert_denied(
            await call_tool(
                client,
                "seedream_generate_image",
                {"prompt": "A blue square", "dry_run": True},
                headers=headers,
            )
        )
        explicit = successful(
            await call_tool(
                client,
                "seedream_generate_image",
                {"prompt": "A blue square", "dry_run": True, "model": IMAGE_MODEL},
                headers=headers,
            )
        )
        assert explicit["model"] == IMAGE_MODEL
    assert not respx.calls


@respx.mock
async def test_full_ownership_store_rejects_new_calls_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = respx.post(f"{MODELARK}/contents/generations/tasks").respond(
        200, json={"id": "only-task"}
    )
    settings = http_settings(tmp_path, STATE_MAX_RECORDS=2)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        record = AsyncMock(wraps=runtime.ownership_store.record)
        capacity = AsyncMock(wraps=runtime.ownership_store.require_capacity)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        monkeypatch.setattr(runtime.ownership_store, "require_capacity", capacity)
        first = successful(
            await call_tool(
                client,
                "seedance_create_task",
                {"prompt": "scene", "idempotency_key": "ownership-capacity-first"},
                headers=credentials(),
            )
        )
        assert first["submitted"] == 1
        owner = record.await_args_list[0].args[2]
        await runtime.ownership_store.record("modelark", "already-owned-task", owner)
        denied = await call_tool(
            client,
            "seedance_create_task",
            {"prompt": "another scene", "idempotency_key": "ownership-capacity-second"},
            headers=credentials("different-key", "c" * 64),
        )
        assert_denied(denied)
        assert capacity.await_count == 2
    assert created.call_count == 1


@respx.mock
async def test_budget_row_limit_cannot_be_bypassed_by_changing_keys(tmp_path: Path) -> None:
    generated = respx.post(f"{MODELARK}/images/generations").respond(
        401, json={"error": {"code": "INVALID_KEY", "message": "Rejected"}}
    )
    settings = http_settings(tmp_path, STATE_MAX_RECORDS=1)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        for key in ("invalid-first", "invalid-second"):
            assert_denied(
                await call_tool(
                    client,
                    "seedream_generate_image",
                    {"prompt": "square"},
                    headers=credentials(key),
                )
            )
    assert generated.call_count == 1


@respx.mock
async def test_saturated_generation_rejects_waiter_but_provider_polling_stays_direct(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def generate(request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(200, json={"data": [{"url": "https://example.com/image.png"}]})

    created = respx.post(f"{MODELARK}/contents/generations/tasks").respond(
        200, json={"id": "owned-poll-task"}
    )
    generated = respx.post(f"{MODELARK}/images/generations").mock(side_effect=generate)
    polled = respx.get(f"{MODELARK}/contents/generations/tasks").respond(
        200,
        json={
            "data": [
                {
                    "id": "owned-poll-task",
                    "model": "dreamina-seedance-2-5-260628",
                    "status": "queued",
                }
            ]
        },
    )
    settings = http_settings(
        tmp_path,
        PROVIDER_MAX_CONCURRENCY=1,
        PRINCIPAL_MAX_CONCURRENCY=1,
        MCP_ADMISSION_TIMEOUT_SECONDS=0.05,
        MCP_TOOL_TIMEOUT_SECONDS=5,
    )
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        successful(
            await call_tool(
                client,
                "seedance_create_task",
                {"prompt": "scene", "idempotency_key": "direct-poll-owned-task"},
                headers=credentials(),
            )
        )
        active = asyncio.create_task(
            call_tool(
                client, "seedream_generate_image", {"prompt": "square"}, headers=credentials()
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            rejected = await call_tool(
                client, "seedream_generate_image", {"prompt": "circle"}, headers=credentials()
            )
            assert_denied(rejected)
            assert "ADMISSION_TIMEOUT" in str(rejected)
            assert "retryable=True" in str(rejected)
            assert "ambiguous_completion=False" in str(rejected)
            assert "structuredContent" not in rejected["result"]
            polled_result = successful(
                await call_tool(
                    client, "gen_task_get", {"task_ids": ["owned-poll-task"]}, headers=credentials()
                )
            )
            assert polled_result["tasks"][0]["status"] == "queued"
            assert not active.done()
        finally:
            release.set()
            successful(await asyncio.wait_for(active, timeout=5))
    assert created.call_count == generated.call_count == polled.call_count == 1


@pytest.mark.parametrize("mutation", [False, True])
@respx.mock
async def test_direct_http_deadline_distinguishes_reads_from_possible_billing(
    tmp_path: Path, mutation: bool
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    requests: list[httpx.Request] = []

    async def stalled(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Stalled provider unexpectedly resumed")

    settings = http_settings(tmp_path, MCP_TOOL_TIMEOUT_SECONDS=0.2)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        if mutation:
            respx.post(f"{MODELARK}/images/generations").mock(side_effect=stalled)
            name, arguments = "seedream_generate_image", {"prompt": "square"}
        else:
            respx.post(f"{MODELARK}/contents/generations/tasks").respond(
                200, json={"id": "owned-deadline-task"}
            )
            successful(
                await call_tool(
                    client,
                    "seedance_create_task",
                    {"prompt": "scene", "idempotency_key": "direct-deadline-owned-task"},
                    headers=credentials(),
                )
            )
            respx.get(f"{MODELARK}/contents/generations/tasks").mock(side_effect=stalled)
            name, arguments = "gen_task_get", {"task_ids": ["owned-deadline-task"]}
        result = await asyncio.wait_for(
            call_tool(client, name, arguments, headers=credentials()), timeout=5
        )
        assert_denied(result)
        assert "TOOL_DEADLINE_EXCEEDED" in str(result)
        assert f"ambiguous_completion={mutation}" in str(result)
        assert "structuredContent" not in result["result"]
        if mutation:
            assert "does not cancel accepted upstream work" in str(result)
        else:
            assert "Only read-only provider requests started" in str(result)
    assert started.is_set()
    assert cancelled.is_set()
    assert len(requests) == 1


@respx.mock
async def test_deadline_after_acceptance_keeps_safe_ids_and_blocks_same_key_redispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = respx.post(f"{MODELARK}/contents/generations/tasks").respond(
        200, json={"id": "accepted-before-deadline"}, headers={"X-Request-Id": "safe-deadline-id"}
    )
    settings = http_settings(tmp_path, MCP_TOOL_TIMEOUT_SECONDS=0.2)
    arguments = {"prompt": "scene", "idempotency_key": "direct-accepted-deadline"}

    async def blocked_record(*args, **kwargs):
        await asyncio.Event().wait()

    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        monkeypatch.setattr(runtime.ownership_store, "record", blocked_record)
        first = await call_tool(client, "seedance_create_task", arguments, headers=credentials())
        assert_denied(first)
        assert "TOOL_DEADLINE_EXCEEDED" in str(first)
        assert "accepted-before-deadline" in str(first)
        assert "safe-deadline-id" in str(first)
        replay = await call_tool(client, "seedance_create_task", arguments, headers=credentials())
        assert_denied(replay)
        assert "SUBMISSION_UNRESOLVED" in str(replay)
        assert "accepted-before-deadline" in str(replay)
    assert created.call_count == 1
