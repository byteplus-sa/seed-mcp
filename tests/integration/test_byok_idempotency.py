"""HTTP submission contract from plans/PLAN_SQLITE_SUBMISSION_SAFETY.md."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from jsonschema import validate
from pydantic import BaseModel, ValidationError

from ark_mcp.tools.omnihuman_create_task import (
    OmniHumanCreateTaskInput,
    OmniHumanCreateTaskOutput,
    omnihuman_create_task,
)
from ark_mcp.tools.seedance_create_task import (
    SeedanceCreateTaskInput,
    SeedanceCreateTaskOutput,
    seedance_create_task,
)
from tests.fixtures.fake_context import FakeContext
from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    HMAC_KEY,
    MODELARK,
    MODELARK_KEY,
    OTHER_SECRET,
    SPEECH_KEY,
    VIDEO_MODEL,
    VISION,
    VISION_KEY,
    assert_denied,
    assert_no_canaries,
    call_tool,
    credentials,
    http_server,
    http_settings,
    rpc,
    successful,
)
from tests.integration.test_task_security import provider_task

TASKS_URL = f"{MODELARK}/contents/generations/tasks"
AVATAR_URL = f"{VISION}/api/common/v3/submit_task_v2"
PRIVATE_DETAIL = "synthetic-private-submission-detail"


@dataclass(frozen=True)
class CreateCase:
    tool: str
    url: str
    headers: dict[str, str]
    input_data: dict[str, Any]
    input_model: type[BaseModel]
    output_model: type[BaseModel]


@pytest.fixture(params=["seedance", "omnihuman"])
def create_case(request: pytest.FixtureRequest) -> CreateCase:
    if request.param == "seedance":
        return CreateCase(
            "seedance_create_task",
            TASKS_URL,
            credentials(),
            {"prompt": "A synthetic scene"},
            SeedanceCreateTaskInput,
            SeedanceCreateTaskOutput,
        )
    return CreateCase(
        "omnihuman_create_task",
        AVATAR_URL,
        credentials(VISION_KEY, header="X-OmniHuman-Api-Key"),
        {"image": "https://example.com/face.png", "audio": "https://example.com/audio.wav"},
        OmniHumanCreateTaskInput,
        OmniHumanCreateTaskOutput,
    )


def accepted_response(
    case: CreateCase, task_id: str = "task-accepted", request_id: str | None = "req-accepted"
) -> httpx.Response:
    if case.tool == "seedance_create_task":
        return httpx.Response(
            200,
            json={"id": task_id},
            headers={"X-Request-Id": request_id} if request_id is not None else {},
        )
    return httpx.Response(
        200,
        json={"code": 10000, "data": {"task_id": task_id}, "request_id": request_id},
    )


def submission_error(response: dict[str, Any], *codes: str) -> str:
    assert_denied(response)
    result = response["result"]
    assert result["isError"] is True
    assert result.get("structuredContent") is None
    assert all(block["type"] == "text" for block in result["content"])
    text = "\n".join(block["text"] for block in result["content"])
    assert any(code in text for code in codes), text
    assert_no_canaries(text)
    return text


def state_rows(tmp_path: Path, query: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(tmp_path / "artifacts" / "runtime.sqlite3")) as connection:
        return connection.execute(query).fetchall()


def assert_private_state(tmp_path: Path, *private_values: str) -> None:
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert any(path.name == "runtime.sqlite3" for path in files)
    for path in files:
        text = path.read_bytes().decode("latin-1")
        assert_no_canaries(text)
        for value in private_values:
            assert value not in text, path.name


def test_idempotency_key_schema_is_described_optional_and_bounded(
    create_case: CreateCase,
) -> None:
    schema = create_case.input_model.model_json_schema()
    field = schema["properties"]["idempotency_key"]
    assert field["description"]
    assert field["default"] is None
    assert "idempotency_key" not in schema.get("required", [])
    string_schema = next(item for item in field["anyOf"] if item.get("type") == "string")
    assert "pattern" in string_schema
    for key in ("a" * 16, "Z9_-" * 32):
        assert re.fullmatch(string_schema["pattern"], key)
        parsed = create_case.input_model.model_validate(
            {**create_case.input_data, "idempotency_key": key}
        )
        assert parsed.idempotency_key == key
    assert create_case.input_model.model_validate(create_case.input_data).idempotency_key is None


@pytest.mark.parametrize(
    "key",
    [
        "",
        "a" * 15,
        "a" * 129,
        "valid-key-but.dot",
        "white space-key-123",
        "a" * 16 + "\n",
        "\u00e9" * 16,
        123,
    ],
)
def test_invalid_key_fails_input_validation(create_case: CreateCase, key: object) -> None:
    with pytest.raises(ValidationError, match="idempotency_key"):
        create_case.input_model.model_validate({**create_case.input_data, "idempotency_key": key})


@pytest.mark.parametrize("key", ["omitted", None, "", "a" * 15, "a" * 129, "invalid/key-123456"])
@respx.mock
async def test_http_requires_valid_key_before_dispatch(
    tmp_path: Path, create_case: CreateCase, key: str | None
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    input_data = dict(create_case.input_data)
    if key != "omitted":
        input_data["idempotency_key"] = key
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        response = await call_tool(
            client, create_case.tool, input_data, headers=create_case.headers
        )
        assert_denied(response)
        assert "idempotency_key" in str(response)
        if key in ("omitted", None):
            submission_error(response, "IDEMPOTENCY_KEY_REQUIRED")
    assert route.call_count == 0


@respx.mock
async def test_http_discovery_advertises_key_without_requiring_it_globally(
    tmp_path: Path, create_case: CreateCase
) -> None:
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        tools = (await rpc(client, "tools/list"))["result"]["tools"]
        tool = next(item for item in tools if item["name"] == create_case.tool)
        schema = tool["inputSchema"]
        for key in (None, "a" * 16, "Z9_-" * 32):
            validate(
                {"input": {**create_case.input_data, "idempotency_key": key}},
                schema,
            )
        assert "idempotency_key" in json.dumps(schema)
    assert not respx.calls


@pytest.mark.parametrize("dry_run", [False, True])
@respx.mock
async def test_local_seedance_rejects_supplied_key_before_dispatch(
    fake_ctx: FakeContext, dry_run: bool
) -> None:
    input_data = SeedanceCreateTaskInput.model_validate(
        {"prompt": "scene", "dry_run": dry_run, "idempotency_key": "local-key-is-rejected"}
    )
    with pytest.raises(ValueError, match=r"idempotency|[Ll]ocal|stdio"):
        await seedance_create_task(input_data, fake_ctx)
    assert not respx.calls


@respx.mock
async def test_local_omnihuman_rejects_supplied_key_before_dispatch(
    fake_ctx: FakeContext,
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    runtime.settings = runtime.settings.model_copy(
        update={"omnihuman_enabled": True, "cv_api_key": VISION_KEY}
    )
    input_data = OmniHumanCreateTaskInput.model_validate(
        {
            "image": "https://example.com/face.png",
            "audio": "https://example.com/audio.wav",
            "idempotency_key": "local-avatar-rejected",
        }
    )
    with pytest.raises(ValueError, match=r"idempotency|[Ll]ocal|stdio"):
        await omnihuman_create_task(input_data, fake_ctx)
    assert not respx.calls


@respx.mock
async def test_keyless_local_creates_and_dry_run_keep_existing_behavior(
    fake_ctx: FakeContext,
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    assert runtime.submission_store is None
    route = respx.post(f"{runtime.settings.modelark_base_url}/contents/generations/tasks").mock(
        side_effect=[
            httpx.Response(200, json={"id": "local-first"}),
            httpx.Response(200, json={"id": "local-second"}),
        ]
    )
    preview = await seedance_create_task(
        SeedanceCreateTaskInput(prompt="scene", dry_run=True), fake_ctx
    )
    assert isinstance(preview, SeedanceCreateTaskOutput)
    assert preview.dry_run
    assert not route.called
    for task_id in ("local-first", "local-second"):
        result = await seedance_create_task(SeedanceCreateTaskInput(prompt="scene"), fake_ctx)
        assert isinstance(result, SeedanceCreateTaskOutput)
        assert result.tasks[0].task_id == task_id
    assert route.call_count == 2


@respx.mock
async def test_keyless_local_omnihuman_creates_keep_existing_behavior(
    fake_ctx: FakeContext,
) -> None:
    runtime = fake_ctx.lifespan_context["runtime"]
    runtime.settings = runtime.settings.model_copy(
        update={"omnihuman_enabled": True, "cv_api_key": VISION_KEY}
    )
    assert runtime.submission_store is None
    route = respx.post(f"{runtime.settings.cv_base_url}/api/common/v3/submit_task_v2").mock(
        side_effect=[
            httpx.Response(200, json={"code": 10000, "data": {"task_id": task_id}})
            for task_id in ("local-avatar-first", "local-avatar-second")
        ]
    )
    for task_id in ("local-avatar-first", "local-avatar-second"):
        result = await omnihuman_create_task(
            OmniHumanCreateTaskInput(
                image="https://example.com/face.png", audio="https://example.com/audio.wav"
            ),
            fake_ctx,
        )
        assert isinstance(result, OmniHumanCreateTaskOutput)
        assert result.task_id == task_id
    assert route.call_count == 2


@respx.mock
async def test_http_dry_run_does_not_claim_or_consume_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx.post(TASKS_URL).respond(200, json={"id": "after-preview"})
    key = "preview-is-not-a-claim"
    async with http_server(tmp_path) as (_, runtime, client):
        assert runtime.submission_store is not None
        claim = AsyncMock(wraps=runtime.submission_store.claim)
        monkeypatch.setattr(runtime.submission_store, "claim", claim)
        for extra in ({}, {"idempotency_key": key}):
            preview = successful(
                await call_tool(
                    client,
                    "seedance_create_task",
                    {"prompt": "preview scene", "dry_run": True, **extra},
                    headers=credentials(),
                )
            )
            assert preview["dry_run"] is True
            assert preview["tasks"] == []
        claim.assert_not_awaited()
        assert not route.called
        result = successful(
            await call_tool(
                client,
                "seedance_create_task",
                {"prompt": "different real scene", "idempotency_key": key},
                headers=credentials(),
            )
        )
        assert result["tasks"][0]["task_id"] == "after-preview"
        claim.assert_awaited_once()
    assert route.call_count == 1


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("request_id", [None, "req-replayed"])
@respx.mock
async def test_success_replays_identical_receipt_without_provider_or_budget_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_case: CreateCase,
    restart: bool,
    request_id: str | None,
) -> None:
    route = respx.post(create_case.url).mock(
        return_value=accepted_response(create_case, request_id=request_id)
    )
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    input_data = {**create_case.input_data, "idempotency_key": "successful-replay-key"}

    async def replay(runtime: Any, client: httpx.AsyncClient, first: dict[str, Any]) -> None:
        reserve = AsyncMock(side_effect=AssertionError("Replay must not reserve budget"))
        record = AsyncMock(side_effect=AssertionError("Replay must not repair ownership"))
        monkeypatch.setattr(runtime.budget_ledger, "reserve", reserve)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        again = successful(
            await call_tool(
                client,
                create_case.tool,
                input_data,
                headers={**create_case.headers, "X-Seed-Speech-Api-Key": SPEECH_KEY},
            )
        )
        assert again == first
        validate(again, create_case.output_model.model_json_schema())
        reserve.assert_not_awaited()
        record.assert_not_awaited()

    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        first = successful(
            await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        if not restart:
            await replay(runtime, client, first)
    if restart:
        async with http_server(tmp_path, settings=settings) as (_, runtime, client):
            await replay(runtime, client, first)
    assert route.call_count == len(respx.calls) == 1
    assert input_data["idempotency_key"] not in route.calls[0].request.content.decode()


@respx.mock
async def test_changed_arguments_conflict_without_provider_dispatch(
    tmp_path: Path, create_case: CreateCase
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    input_data = {**create_case.input_data, "idempotency_key": "changed-payload-conflict"}
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        first = successful(
            await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        response = await call_tool(
            client,
            create_case.tool,
            {**input_data, "prompt": "A changed synthetic scene"},
            headers=create_case.headers,
        )
        submission_error(response, "SUBMISSION_CONFLICT")
        assert (
            successful(
                await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
            )
            == first
        )
    assert route.call_count == 1


@respx.mock
async def test_running_duplicate_is_in_progress_and_never_dispatches(
    tmp_path: Path, create_case: CreateCase
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def accept(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return accepted_response(create_case)

    route = respx.post(create_case.url).mock(side_effect=accept)
    input_data = {**create_case.input_data, "idempotency_key": "concurrent-same-key"}
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        pending = asyncio.create_task(
            call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            duplicate = await asyncio.wait_for(
                call_tool(client, create_case.tool, input_data, headers=create_case.headers), 5
            )
            submission_error(duplicate, "SUBMISSION_IN_PROGRESS")
            conflict = await call_tool(
                client,
                create_case.tool,
                {**input_data, "prompt": "changed while running"},
                headers=create_case.headers,
            )
            submission_error(conflict, "SUBMISSION_CONFLICT")
            release.set()
            first = successful(await asyncio.wait_for(pending, 5))
            assert (
                successful(
                    await call_tool(
                        client, create_case.tool, input_data, headers=create_case.headers
                    )
                )
                == first
            )
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    assert route.call_count == 1


@pytest.mark.parametrize("identity_change", ["provider_key", "client_secret"])
@respx.mock
async def test_same_key_is_isolated_by_credential_tenant_and_owner(
    tmp_path: Path, create_case: CreateCase, identity_change: str
) -> None:
    route = respx.post(create_case.url).mock(
        side_effect=[
            accepted_response(create_case, "owner-first"),
            accepted_response(create_case, "owner-second"),
        ]
    )
    input_data = {**create_case.input_data, "idempotency_key": "isolated-caller-key"}
    other_headers = dict(create_case.headers)
    header = (
        next(name for name in other_headers if name != "X-MCP-Client-Secret")
        if identity_change == "provider_key"
        else "X-MCP-Client-Secret"
    )
    other_headers[header] = (
        "synthetic-other-provider" if identity_change == "provider_key" else OTHER_SECRET
    )
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        results = [
            successful(await call_tool(client, create_case.tool, input_data, headers=headers))
            for headers in (create_case.headers, other_headers)
        ]
        assert "owner-first" in json.dumps(results[0])
        assert "owner-second" not in json.dumps(results[0])
        assert "owner-second" in json.dumps(results[1])
        assert "owner-first" not in json.dumps(results[1])
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        for headers, expected in zip((create_case.headers, other_headers), results, strict=True):
            assert (
                successful(await call_tool(client, create_case.tool, input_data, headers=headers))
                == expected
            )
    assert route.call_count == 2


@respx.mock
async def test_same_key_is_isolated_between_provider_tools(tmp_path: Path) -> None:
    video = respx.post(TASKS_URL).respond(200, json={"id": "provider-overlap"})
    avatar = respx.post(AVATAR_URL).respond(
        200, json={"code": 10000, "data": {"task_id": "provider-overlap"}}
    )
    key = "same-key-across-products"
    headers = {
        **credentials(),
        "X-OmniHuman-Api-Key": MODELARK_KEY,
    }
    requests = [
        ("seedance_create_task", {"prompt": "scene", "idempotency_key": key}),
        (
            "omnihuman_create_task",
            {
                "image": "https://example.com/face.png",
                "audio": "https://example.com/audio.wav",
                "idempotency_key": key,
            },
        ),
    ]
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        first = [
            successful(await call_tool(client, name, input_data, headers=headers))
            for name, input_data in requests
        ]
        for (name, input_data), expected in zip(requests, first, strict=True):
            assert (
                successful(await call_tool(client, name, input_data, headers=headers)) == expected
            )
    assert video.call_count == avatar.call_count == 1


@respx.mock
async def test_replay_still_requires_live_credentials(
    tmp_path: Path, create_case: CreateCase
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    input_data = {**create_case.input_data, "idempotency_key": "replay-needs-live-identity"}
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, _, client):
        first = successful(
            await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        for headers in ({}, *({name: value} for name, value in create_case.headers.items())):
            response = await call_tool(client, create_case.tool, input_data, headers=headers)
            assert_denied(response)
            assert "task-accepted" not in json.dumps(response)
        assert (
            successful(
                await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
            )
            == first
        )
    assert route.call_count == 1


@respx.mock
async def test_fingerprint_uses_validated_defaults_and_effective_model(tmp_path: Path) -> None:
    alternate = "dreamina-seedance-2-5-flash-261115"
    route = respx.post(TASKS_URL).respond(200, json={"id": "effective-model-task"})
    input_data = {"prompt": "scene", "idempotency_key": "effective-model-replay"}
    async with http_server(tmp_path) as (_, _, client):
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["model"] == VIDEO_MODEL
        explicit_defaults = {
            **input_data,
            "model": VIDEO_MODEL,
            "variations": 1,
            "watermark": False,
            "dry_run": False,
        }
        assert (
            successful(
                await call_tool(
                    client, "seedance_create_task", explicit_defaults, headers=credentials()
                )
            )
            == first
        )
        assert (
            successful(
                await call_tool(
                    client,
                    "seedance_create_task",
                    input_data,
                    headers={**credentials(), "X-ModelArk-Seedance-Endpoint": VIDEO_MODEL},
                )
            )
            == first
        )
        changed = await call_tool(
            client,
            "seedance_create_task",
            input_data,
            headers={**credentials(), "X-ModelArk-Seedance-Endpoint": alternate},
        )
        submission_error(changed, "SUBMISSION_CONFLICT")
        assert (
            successful(
                await call_tool(
                    client,
                    "seedance_create_task",
                    explicit_defaults,
                    headers={**credentials(), "X-ModelArk-Seedance-Endpoint": alternate},
                )
            )
            == first
        )
    assert route.call_count == 1


@pytest.mark.parametrize("duplicate_prompts", [False, True])
@respx.mock
async def test_whole_variation_batch_replays_once_in_original_order(
    tmp_path: Path, duplicate_prompts: bool
) -> None:
    count = 0

    def accept(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(
            200, json={"id": f"batch-task-{count}"}, headers={"X-Request-Id": f"batch-req-{count}"}
        )

    route = respx.post(TASKS_URL).mock(side_effect=accept)
    input_data = {
        "variation_prompts": ["same"] * 5
        if duplicate_prompts
        else [f"scene-{i}" for i in range(5)],
        "variations": 5,
        "idempotency_key": "whole-variation-batch",
    }
    async with http_server(tmp_path) as (_, _, client):
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["submitted"] == 5
        assert first["failed"] == 0
        assert [task["index"] for task in first["tasks"]] == list(range(5))
        assert {task["task_id"] for task in first["tasks"]} == {
            f"batch-task-{index}" for index in range(1, 6)
        }
        assert all(task["error"] is None for task in first["tasks"])
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM http_submissions") == [(1,)]
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM http_submission_tasks") == [(5,)]
    async with http_server(tmp_path) as (_, _, client):
        assert (
            successful(
                await call_tool(client, "seedance_create_task", input_data, headers=credentials())
            )
            == first
        )
    assert route.call_count == 5


@pytest.mark.parametrize("restart", [False, True])
@respx.mock
async def test_partial_batch_is_unresolved_and_never_resumes(tmp_path: Path, restart: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["content"][0]["text"]
        if prompt == "rejected":
            return httpx.Response(
                400, json={"error": {"code": "SYNTHETIC_REJECTED", "message": PRIVATE_DETAIL}}
            )
        return httpx.Response(
            200, json={"id": f"accepted-{prompt}"}, headers={"X-Request-Id": f"req-{prompt}"}
        )

    route = respx.post(TASKS_URL).mock(side_effect=respond)
    input_data = {
        "variation_prompts": ["first", "rejected", "last"],
        "variations": 3,
        "idempotency_key": "partial-batch-no-resume",
    }

    async def repeat(client: httpx.AsyncClient) -> None:
        response = await call_tool(
            client, "seedance_create_task", input_data, headers=credentials()
        )
        text = submission_error(response, "SUBMISSION_UNRESOLVED")
        for task_id in ("accepted-first", "accepted-last", "req-first", "req-last"):
            assert task_id in text
        assert PRIVATE_DETAIL not in text

    async with http_server(tmp_path) as (_, _, client):
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["submitted"] == 2
        assert first["failed"] == 1
        assert [task["task_id"] for task in first["tasks"]] == [
            "accepted-first",
            None,
            "accepted-last",
        ]
        assert PRIVATE_DETAIL in json.dumps(first)
        assert_private_state(tmp_path, PRIVATE_DETAIL, input_data["idempotency_key"])
        if not restart:
            await repeat(client)
    if restart:
        async with http_server(tmp_path) as (_, _, client):
            await repeat(client)
    assert route.call_count == 3


@respx.mock
async def test_draft_promotion_replays_after_restart_without_second_draft_read(
    tmp_path: Path,
) -> None:
    route = respx.post(TASKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"id": "source-draft"}),
            httpx.Response(200, json={"id": "promoted-final"}),
        ]
    )
    draft = respx.get(f"{TASKS_URL}/source-draft").respond(
        200, json=provider_task("source-draft", "succeeded", draft=True)
    )
    input_data = {"draft_task_id": "source-draft", "idempotency_key": "promote-draft-once"}
    async with http_server(tmp_path) as (_, _, client):
        successful(
            await call_tool(
                client,
                "seedance_create_task",
                {"prompt": "scene", "draft": True, "idempotency_key": "create-source-draft"},
                headers=credentials(),
            )
        )
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["tasks"][0]["task_id"] == "promoted-final"
        assert first["model"] == VIDEO_MODEL
        draft.respond(404, json={"error": {"code": "NOT_FOUND", "message": "Draft expired"}})
    settings = http_settings(tmp_path, SEEDANCE_DEFAULT_MODEL="dreamina-seedance-2-5-flash-261115")
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        assert (
            successful(
                await call_tool(client, "seedance_create_task", input_data, headers=credentials())
            )
            == first
        )
    assert draft.call_count == 1
    assert route.call_count == 2


@pytest.mark.parametrize("failure", ["rejection", "uncertain_503", "transport", "malformed"])
@respx.mock
async def test_failed_attempts_are_unresolved_even_after_restart(
    tmp_path: Path, create_case: CreateCase, failure: str
) -> None:
    route = respx.post(create_case.url)
    if failure == "transport":
        route.mock(side_effect=httpx.ReadError(PRIVATE_DETAIL))
    elif failure == "malformed":
        route.respond(200, json={"unexpected": PRIVATE_DETAIL})
    else:
        route.respond(
            400 if failure == "rejection" else 503,
            json={"error": {"code": "SYNTHETIC_FAILURE", "message": PRIVATE_DETAIL}},
        )
    input_data = {**create_case.input_data, "idempotency_key": "failed-attempt-no-retry"}
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        first = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        assert_denied(first)
        again = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        text = submission_error(again, "SUBMISSION_UNRESOLVED")
        assert PRIVATE_DETAIL not in text
        assert_private_state(tmp_path, PRIVATE_DETAIL, input_data["idempotency_key"])
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        response = await call_tool(
            client, create_case.tool, input_data, headers=create_case.headers
        )
        submission_error(response, "SUBMISSION_UNRESOLVED")
    assert route.call_count == 1


@respx.mock
async def test_claim_database_failure_blocks_provider_budget_and_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_case: CreateCase
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, runtime, client):
        assert runtime.submission_store is not None
        claim = AsyncMock(side_effect=RuntimeError(f"{PRIVATE_DETAIL} {CLIENT_SECRET}"))
        reserve = AsyncMock(wraps=runtime.budget_ledger.reserve)
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.submission_store, "claim", claim)
        monkeypatch.setattr(runtime.budget_ledger, "reserve", reserve)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        response = await call_tool(
            client,
            create_case.tool,
            {**create_case.input_data, "idempotency_key": "claim-database-failed"},
            headers=create_case.headers,
        )
        submission_error(response, "SUBMISSION_UNAVAILABLE")
        claim.assert_awaited_once()
        reserve.assert_not_awaited()
        record.assert_not_awaited()
        assert PRIVATE_DETAIL not in json.dumps(response)
        assert_no_canaries(json.dumps(response))
    assert route.call_count == 0


@pytest.mark.parametrize("failure", ["ownership", "record_task", "succeed", "get"])
@respx.mock
async def test_post_acceptance_failures_retain_claim_and_never_resubmit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_case: CreateCase,
    failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    input_data = {**create_case.input_data, "idempotency_key": "post-acceptance-failure"}
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        store = runtime.submission_store
        assert store is not None
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        failed_write = AsyncMock(side_effect=RuntimeError(f"{PRIVATE_DETAIL} {CLIENT_SECRET}"))
        if failure == "ownership":
            record.side_effect = failed_write.side_effect
        else:
            monkeypatch.setattr(store, failure, failed_write)
        first = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        if failure in ("succeed", "get"):
            successful(first)
        else:
            submission_error(
                first,
                "OWNERSHIP_RECORD_FAILED" if failure == "ownership" else "SUBMISSION_RECORD_FAILED",
            )
        assert "task-accepted" in json.dumps(first)
        assert "req-accepted" in json.dumps(first)
        record.assert_awaited_once()
        if failure != "ownership":
            failed_write.assert_awaited_once()
        count = 0 if failure == "record_task" else 1
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM http_submission_tasks") == [(count,)]
        again = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        text = submission_error(again, "SUBMISSION_UNRESOLVED", "SUBMISSION_IN_PROGRESS")
        if count:
            assert "task-accepted" in text
            assert "req-accepted" in text
        record.assert_awaited_once()
        assert_private_state(tmp_path, PRIVATE_DETAIL, input_data["idempotency_key"])
        output = json.dumps(first) + text + capsys.readouterr().err
        assert PRIVATE_DETAIL not in output
        assert_no_canaries(output)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        again = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        text = submission_error(again, "SUBMISSION_UNRESOLVED")
        if count:
            assert "task-accepted" in text
    assert route.call_count == 1


@respx.mock
async def test_accepted_task_is_journaled_before_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_case: CreateCase
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, runtime, client):
        record = runtime.ownership_store.record

        async def verify_receipt(provider: str, task_id: str, owner: Any) -> None:
            assert state_rows(
                tmp_path, "SELECT task_id, request_id FROM http_submission_tasks"
            ) == [("task-accepted", "req-accepted")]
            await record(provider, task_id, owner)

        checked = AsyncMock(side_effect=verify_receipt)
        monkeypatch.setattr(runtime.ownership_store, "record", checked)
        successful(
            await call_tool(
                client,
                create_case.tool,
                {**create_case.input_data, "idempotency_key": "journal-before-ownership"},
                headers=create_case.headers,
            )
        )
        checked.assert_awaited_once()
    assert route.call_count == 1


@pytest.mark.parametrize("variations", [1, 2])
@respx.mock
async def test_budget_admission_failure_is_not_retried_with_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variations: int
) -> None:
    async with http_server(tmp_path) as (_, runtime, client):
        reserve = AsyncMock(side_effect=RuntimeError(PRIVATE_DETAIL))
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.budget_ledger, "reserve", reserve)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        input_data = {
            "prompt": "scene",
            "variations": variations,
            "idempotency_key": "budget-rejected-no-retry",
        }
        first = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        if variations == 1:
            assert_denied(first)
        else:
            output = successful(first)
            assert output["submitted"] == 0
            assert output["failed"] == variations
        assert reserve.await_count == variations
        again = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        submission_error(again, "SUBMISSION_UNRESOLVED")
        assert reserve.await_count == variations
        record.assert_not_awaited()
        assert_private_state(tmp_path, PRIVATE_DETAIL)
    assert not respx.calls


@respx.mock
async def test_budget_commit_failure_still_allows_success_receipt_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx.post(TASKS_URL).respond(200, json={"id": "budget-accepted"})
    async with http_server(tmp_path) as (_, runtime, client):
        commit = AsyncMock(side_effect=RuntimeError(PRIVATE_DETAIL))
        monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
        input_data = {"prompt": "scene", "idempotency_key": "budget-commit-replay"}
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["failed"] == 0
        assert (
            successful(
                await call_tool(client, "seedance_create_task", input_data, headers=credentials())
            )
            == first
        )
        commit.assert_awaited_once()
    assert route.call_count == 1


@pytest.mark.parametrize("cleanup_fails", [False, True])
@respx.mock
async def test_cancelled_create_remains_non_resubmittable_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_case: CreateCase,
    cleanup_fails: bool,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    dispatched = 0

    async def accept(request: httpx.Request) -> httpx.Response:
        nonlocal dispatched
        dispatched += 1
        entered.set()
        await release.wait()
        return accepted_response(create_case)

    respx.post(create_case.url).mock(side_effect=accept)
    input_data = {**create_case.input_data, "idempotency_key": "cancelled-submission-key"}
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        if cleanup_fails:
            assert runtime.submission_store is not None
            monkeypatch.setattr(
                runtime.submission_store,
                "mark_unresolved",
                AsyncMock(side_effect=RuntimeError(PRIVATE_DETAIL)),
            )
        pending = asyncio.create_task(
            call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            release.set()
            again = await call_tool(
                client, create_case.tool, input_data, headers=create_case.headers
            )
            submission_error(again, "SUBMISSION_UNRESOLVED", "SUBMISSION_IN_PROGRESS")
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        again = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        submission_error(again, "SUBMISSION_UNRESOLVED")
    assert dispatched == 1


@respx.mock
async def test_running_and_cancelled_batch_expose_known_ids_without_partial_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = asyncio.Event()
    blocked = asyncio.Event()
    release = asyncio.Event()
    dispatched: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["content"][0]["text"]
        dispatched.append(prompt)
        if prompt == "blocked":
            blocked.set()
            await release.wait()
        return httpx.Response(
            200, json={"id": f"task-{prompt}"}, headers={"X-Request-Id": f"req-{prompt}"}
        )

    respx.post(TASKS_URL).mock(side_effect=respond)
    input_data = {
        "variation_prompts": ["accepted", "blocked"],
        "variations": 2,
        "idempotency_key": "cancelled-partial-batch",
    }
    async with http_server(tmp_path) as (_, runtime, client):
        record = runtime.ownership_store.record

        async def record_then_signal(provider: str, task_id: str, owner: Any) -> None:
            await record(provider, task_id, owner)
            accepted.set()

        monkeypatch.setattr(runtime.ownership_store, "record", record_then_signal)
        pending = asyncio.create_task(
            call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        try:
            await asyncio.wait_for(asyncio.gather(accepted.wait(), blocked.wait()), 5)
            duplicate = await call_tool(
                client, "seedance_create_task", input_data, headers=credentials()
            )
            text = submission_error(duplicate, "SUBMISSION_IN_PROGRESS")
            assert "task-accepted" in text
            assert "req-accepted" in text
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with http_server(tmp_path) as (_, _, client):
        again = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        text = submission_error(again, "SUBMISSION_UNRESOLVED")
        assert "task-accepted" in text
        assert "req-accepted" in text
    assert sorted(dispatched) == ["accepted", "blocked"]


@pytest.mark.parametrize("identifier", ["task_id", "request_id"])
@pytest.mark.parametrize(
    "unsafe_kind", ["url", "oversized", "provider_key", "client_secret", "hmac"]
)
@respx.mock
async def test_unsafe_accepted_ids_never_reach_journal_or_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_case: CreateCase,
    identifier: str,
    unsafe_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_key = "synthetic-safe-grammar-provider-canary"
    unsafe = {
        "url": "https://example.com/private-task?signature=synthetic-receipt-token",
        "oversized": "oversized-private-id-" + "x" * 300,
        "provider_key": provider_key,
        "client_secret": CLIENT_SECRET,
        "hmac": HMAC_KEY,
    }[unsafe_kind]
    headers = {
        name: value if name == "X-MCP-Client-Secret" else provider_key
        for name, value in create_case.headers.items()
    }
    task_id = unsafe if identifier == "task_id" else "safe-task"
    request_id = unsafe if identifier == "request_id" else "safe-request"
    route = respx.post(create_case.url).mock(
        return_value=accepted_response(create_case, task_id, request_id)
    )
    input_data = {**create_case.input_data, "idempotency_key": "unsafe-receipt-no-storage"}
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, runtime, client):
        assert runtime.submission_store is not None
        journal = AsyncMock(wraps=runtime.submission_store.record_task)
        ownership = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.submission_store, "record_task", journal)
        monkeypatch.setattr(runtime.ownership_store, "record", ownership)
        first = await call_tool(client, create_case.tool, input_data, headers=headers)
        submission_error(first, "UNSAFE_TASK_RECEIPT")
        text = json.dumps(first)
        assert "ambiguous_completion=True" in text
        assert "retryable=False" in text
        assert unsafe not in text
        journal.assert_not_awaited()
        ownership.assert_not_awaited()
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM http_submission_tasks") == [(0,)]
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM task_ownership") == [(0,)]
        again = await call_tool(client, create_case.tool, input_data, headers=headers)
        submission_error(again, "SUBMISSION_UNRESOLVED")
        assert_private_state(tmp_path, unsafe, provider_key)
        logs = capsys.readouterr().err
        assert unsafe not in logs
        assert_no_canaries(text + logs)
    assert route.call_count == 1
    assert_private_state(tmp_path, unsafe, provider_key)


@respx.mock
async def test_journal_does_not_persist_prompts_media_keys_or_raw_provider_body(
    tmp_path: Path,
) -> None:
    key = "private-raw-idempotency-key"
    prompt = "synthetic private cinematic prompt never stored"
    media = "https://example.com/private-input.png?signature=synthetic-private-media"
    provider_extra = "synthetic-provider-body-never-stored"
    route = respx.post(TASKS_URL).respond(
        200,
        json={"id": "safe-persisted-task", "unused_metadata": provider_extra},
        headers={"X-Request-Id": "safe-persisted-request"},
    )
    input_data = {"prompt": prompt, "images": [media], "idempotency_key": key}
    async with http_server(tmp_path) as (_, _, client):
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        assert first["tasks"][0]["task_id"] == "safe-persisted-task"
        assert_private_state(
            tmp_path, key, prompt, media, "synthetic-private-media", provider_extra
        )
        assert (
            successful(
                await call_tool(client, "seedance_create_task", input_data, headers=credentials())
            )
            == first
        )
        assert state_rows(tmp_path, "SELECT task_id, request_id FROM http_submission_tasks") == [
            ("safe-persisted-task", "safe-persisted-request")
        ]
    assert route.call_count == 1
    assert_private_state(tmp_path, key, prompt, media, "synthetic-private-media", provider_extra)


@pytest.mark.parametrize("failure", ["expired", "unavailable"])
@respx.mock
async def test_replay_fails_closed_without_repair_when_ownership_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    create_case: CreateCase,
    failure: str,
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    input_data = {**create_case.input_data, "idempotency_key": "expired-owner-no-repair"}
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        successful(
            await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        if failure == "expired":
            assert await runtime.ownership_store.prune(max_age_days=0) == 1
        else:
            monkeypatch.setattr(
                runtime.ownership_store,
                "require_owner",
                AsyncMock(side_effect=RuntimeError(PRIVATE_DETAIL)),
            )
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        again = await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        assert_denied(again)
        assert again["result"].get("structuredContent") is None
        assert PRIVATE_DETAIL not in json.dumps(again)
        record.assert_not_awaited()
    if failure == "expired":
        async with http_server(tmp_path, settings=settings) as (_, runtime, client):
            record = AsyncMock(wraps=runtime.ownership_store.record)
            monkeypatch.setattr(runtime.ownership_store, "record", record)
            assert_denied(
                await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
            )
            record.assert_not_awaited()
    assert route.call_count == 1


@respx.mock
async def test_capacity_rejects_new_keys_but_allows_existing_success_replay(
    tmp_path: Path, create_case: CreateCase
) -> None:
    route = respx.post(create_case.url).mock(return_value=accepted_response(create_case))
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True, STATE_MAX_RECORDS=1)
    input_data = {**create_case.input_data, "idempotency_key": "first-capacity-claim"}
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        first = successful(
            await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
        )
        assert (
            successful(
                await call_tool(client, create_case.tool, input_data, headers=create_case.headers)
            )
            == first
        )
        assert await runtime.ownership_store.prune(max_age_days=0) == 1
        response = await call_tool(
            client,
            create_case.tool,
            {**input_data, "idempotency_key": "second-capacity-claim"},
            headers=create_case.headers,
        )
        submission_error(response, "SUBMISSION_UNAVAILABLE")
        assert state_rows(tmp_path, "SELECT COUNT(*) FROM http_submissions") == [(1,)]
    assert route.call_count == 1


@respx.mock
async def test_duplicate_provider_task_ids_are_not_cached_as_full_batch_success(
    tmp_path: Path,
) -> None:
    route = respx.post(TASKS_URL).respond(
        200, json={"id": "duplicate-provider-id"}, headers={"X-Request-Id": "duplicate-request"}
    )
    input_data = {
        "prompt": "scene",
        "variations": 2,
        "idempotency_key": "duplicate-provider-receipts",
    }
    async with http_server(tmp_path) as (_, _, client):
        first = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        assert "duplicate-provider-id" in json.dumps(first)
        again = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        text = submission_error(again, "SUBMISSION_UNRESOLVED")
        assert "duplicate-provider-id" in text
    assert route.call_count == 2


@pytest.mark.parametrize("expired_index", [0, 4])
@respx.mock
async def test_batch_replay_requires_ownership_of_every_accepted_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired_index: int
) -> None:
    route = respx.post(TASKS_URL).mock(
        side_effect=[httpx.Response(200, json={"id": f"owned-batch-{index}"}) for index in range(5)]
    )
    input_data = {
        "prompt": "scene",
        "variations": 5,
        "idempotency_key": "batch-replay-all-owners",
    }
    async with http_server(tmp_path) as (_, runtime, client):
        first = successful(
            await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        )
        expired_id = first["tasks"][expired_index]["task_id"]
        with closing(sqlite3.connect(tmp_path / "artifacts" / "runtime.sqlite3")) as connection:
            connection.execute(
                "UPDATE task_ownership SET created_at=? WHERE task_id=?",
                ("2000-01-01T00:00:00+00:00", expired_id),
            )
            connection.commit()
        assert await runtime.ownership_store.prune(max_age_days=30) == 1
        record = AsyncMock(wraps=runtime.ownership_store.record)
        require_owner = AsyncMock(wraps=runtime.ownership_store.require_owner)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        monkeypatch.setattr(runtime.ownership_store, "require_owner", require_owner)
        again = await call_tool(client, "seedance_create_task", input_data, headers=credentials())
        submission_error(again, "SUBMISSION_UNRESOLVED")
        assert expired_id in {call.args[1] for call in require_owner.await_args_list}
        record.assert_not_awaited()
    assert route.call_count == 5


@respx.mock
async def test_missing_http_journal_fails_closed_and_lifespan_closes_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_case: CreateCase
) -> None:
    async with http_server(
        tmp_path, settings=http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    ) as (_, runtime, client):
        store = runtime.submission_store
        assert store is not None
        close = AsyncMock(wraps=store.close)
        monkeypatch.setattr(store, "close", close)
        with monkeypatch.context() as patch:
            patch.setattr(runtime, "submission_store", None)
            response = await call_tool(
                client,
                create_case.tool,
                {**create_case.input_data, "idempotency_key": "journal-missing-create"},
                headers=create_case.headers,
            )
            submission_error(response, "SUBMISSION_UNAVAILABLE")
        close.assert_not_awaited()
    close.assert_awaited_once()
    assert not respx.calls
