"""Bounded admission and request-local discovery for the hosted foundation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

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
