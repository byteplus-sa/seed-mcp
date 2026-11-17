"""Acceptance regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from jsonschema import validate

from ark_mcp.tools.seedance_create_task import SeedanceCreateTaskOutput
from ark_mcp.tools.seedream_generate_image import SeedreamGenerateOutput
from tests.integration.test_byok_http import (
    CANARIES,
    MODELARK,
    VISION,
    VISION_KEY,
    assert_denied,
    assert_no_canaries,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)
from tests.integration.test_task_security import provider_task

TASKS_URL = f"{MODELARK}/contents/generations/tasks"
STORAGE_DETAIL = "synthetic-private-storage-detail"


def assert_budget_events(stderr: str, reservation_ids: set[int]) -> None:
    events = [
        json.loads(line)
        for line in stderr.splitlines()
        if line.startswith("{") and '"msg": "budget_finalization_failed"' in line
    ]
    assert len(events) == len(reservation_ids)
    assert {event["reservation_id"] for event in events} == reservation_ids
    for event in events:
        assert event["level"] == "ERROR"
        assert event["action"] == "commit"
        assert event["provider"] == "modelark"
        assert "task_id" not in event
    assert STORAGE_DETAIL not in stderr
    assert_no_canaries(stderr)


def accepted_response(request: httpx.Request) -> httpx.Response:
    prompt = json.loads(request.content)["content"][0]["text"]
    return httpx.Response(
        200,
        json={"id": f"task-{prompt}"},
        headers={"X-Request-Id": f"req-{prompt}"},
    )


def assert_uncertain(error: dict[str, Any], *, request_id: str) -> None:
    assert error["request_id"] == request_id
    assert error["retryable"] is False
    assert error["ambiguous_completion"] is True
    assert "do not resubmit" in error["message"].lower()


@pytest.mark.parametrize("variations", [1, 2])
@pytest.mark.parametrize("budget_fails", [False, True])
@pytest.mark.parametrize("ownership_fails", [False, True])
@respx.mock
async def test_accepted_tasks_survive_bookkeeping_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variations: int,
    budget_fails: bool,
    ownership_fails: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    route = respx.post(TASKS_URL).mock(side_effect=accepted_response)
    task_ids = [f"task-scene-{index}" for index in range(variations)]
    respx.get(TASKS_URL).respond(
        200, json={"data": [provider_task(task_id) for task_id in task_ids]}
    )
    async with http_server(tmp_path) as (_, runtime, client):
        commit = AsyncMock(wraps=runtime.budget_ledger.commit)
        record = AsyncMock(wraps=runtime.ownership_store.record)
        release = AsyncMock(wraps=runtime.budget_ledger.release)
        if budget_fails:
            commit.side_effect = RuntimeError(STORAGE_DETAIL)
        if ownership_fails:
            record.side_effect = RuntimeError(STORAGE_DETAIL)
        monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
        monkeypatch.setattr(runtime.budget_ledger, "release", release)
        monkeypatch.setattr(runtime.ownership_store, "record", record)

        response = await call_tool(
            client,
            "seedance_create_task",
            {
                "variation_prompts": [f"scene-{index}" for index in range(variations)],
                "variations": variations,
                "idempotency_key": f"accepted-bookkeeping-{variations}-{budget_fails}-{ownership_fails}",
            },
            headers=credentials(),
        )

        assert route.call_count == variations
        assert commit.await_count == variations
        assert record.await_count == variations
        release.assert_not_awaited()
        assert {call.args[1] for call in record.await_args_list} == set(task_ids)
        owner = record.await_args_list[0].args[2]
        owned = await runtime.ownership_store.list_owned_tasks(
            "modelark", owner, since=datetime.min.replace(tzinfo=UTC), before=None, limit=10
        )
        assert {task.task_id for task in owned} == (set() if ownership_fails else set(task_ids))
        has_error = ownership_fails
        if variations == 1 and has_error:
            assert_denied(response)
            text = response["result"]["content"][0]["text"]
            assert task_ids[0] in text
            assert "req-scene-0" in text
            assert "retryable=False" in text
            assert "ambiguous_completion=True" in text
            assert "do not resubmit" in text.lower()
        else:
            output = successful(response)
            validate(output, SeedanceCreateTaskOutput.model_json_schema())
            assert output["submitted"] == variations
            assert output["failed"] == (variations if has_error else 0)
            for index, task in enumerate(output["tasks"]):
                assert task["task_id"] == task_ids[index]
                assert task["request_id"] == f"req-scene-{index}"
                if has_error:
                    assert_uncertain(task["error"], request_id=f"req-scene-{index}")
                else:
                    assert task["error"] is None
        text = json.dumps(response)
        assert "BUDGET_FINALIZATION_FAILED" not in text
        if ownership_fails:
            assert "OWNERSHIP_RECORD_FAILED" in text
        assert STORAGE_DETAIL not in text
        assert_no_canaries(text)

        polled = successful(
            await call_tool(client, "gen_task_get", {"task_ids": task_ids}, headers=credentials())
        )
        if ownership_fails:
            assert polled["tasks"] == []
            assert {error["code"] for error in polled["errors"]} == {"NOT_OWNED"}
        else:
            assert polled["errors"] == []
            assert {task["task_id"] for task in polled["tasks"]} == set(task_ids)
        assert route.call_count == variations
        assert_budget_events(
            capsys.readouterr().err,
            {call.args[0].reservation_id for call in commit.await_args_list}
            if budget_fails
            else set(),
        )


@respx.mock
async def test_mixed_accepted_and_rejected_variations_keep_ids_and_error_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["content"][0]["text"]
        if prompt == "rejected":
            return httpx.Response(
                400,
                json={"error": {"code": "INVALID_PARAM", "message": "Synthetic rejection"}},
                headers={"X-Request-Id": "req-rejected"},
            )
        return accepted_response(request)

    route = respx.post(TASKS_URL).mock(side_effect=respond)
    async with http_server(tmp_path) as (_, runtime, client):
        commit = AsyncMock(side_effect=RuntimeError(STORAGE_DETAIL))
        record = AsyncMock(wraps=runtime.ownership_store.record)
        release = AsyncMock(wraps=runtime.budget_ledger.release)
        monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        monkeypatch.setattr(runtime.budget_ledger, "release", release)
        output = successful(
            await call_tool(
                client,
                "seedance_create_task",
                {
                    "variation_prompts": ["first", "rejected", "last"],
                    "variations": 3,
                    "idempotency_key": "accepted-mixed-variations",
                },
                headers=credentials(),
            )
        )
        validate(output, SeedanceCreateTaskOutput.model_json_schema())
        assert route.call_count == 3
        assert commit.await_count == record.await_count == 2
        assert release.await_count == 1
        assert output["submitted"] == 2
        assert output["failed"] == 1
        assert [task["task_id"] for task in output["tasks"]] == ["task-first", None, "task-last"]
        for index, prompt in ((0, "first"), (2, "last")):
            assert output["tasks"][index]["error"] is None
            assert output["tasks"][index]["request_id"] == f"req-{prompt}"
        rejected = output["tasks"][1]["error"]
        assert rejected["code"] == "INVALID_PARAM"
        assert rejected["request_id"] == "req-rejected"
        assert rejected["retryable"] is False
        assert rejected["ambiguous_completion"] is False
        assert_budget_events(
            capsys.readouterr().err,
            {call.args[0].reservation_id for call in commit.await_args_list},
        )


@pytest.mark.parametrize("variations", [1, 2])
@respx.mock
async def test_budget_admission_failure_never_dispatches_or_records_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variations: int
) -> None:
    async with http_server(tmp_path) as (_, runtime, client):
        reserve = AsyncMock(side_effect=RuntimeError("Synthetic budget unavailable"))
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.budget_ledger, "reserve", reserve)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        response = await call_tool(
            client,
            "seedance_create_task",
            {
                "prompt": "scene",
                "variations": variations,
                "idempotency_key": f"budget-admission-failure-{variations}",
            },
            headers=credentials(),
        )
        if variations == 1:
            assert_denied(response)
        else:
            output = successful(response)
            assert output["submitted"] == 0
            assert output["failed"] == variations
            assert all(task["task_id"] is None for task in output["tasks"])
        record.assert_not_awaited()
    assert len(respx.calls) == 0


@pytest.mark.parametrize("variations", [1, 2])
@respx.mock
async def test_seedream_commit_failure_preserves_urls_and_request_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variations: int,
) -> None:
    output_url = "https://example.com/generated.png?signature=synthetic-delivery-token"
    route = respx.post(f"{MODELARK}/images/generations").respond(
        200,
        json={"data": [{"url": output_url}]},
        headers={"X-Request-Id": "req-image"},
    )
    async with http_server(tmp_path) as (_, runtime, client):
        commit = AsyncMock(side_effect=RuntimeError(" ".join((STORAGE_DETAIL, *CANARIES))))
        release = AsyncMock(wraps=runtime.budget_ledger.release)
        monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
        monkeypatch.setattr(runtime.budget_ledger, "release", release)
        output = successful(
            await call_tool(
                client,
                "seedream_generate_image",
                {"prompt": "square", "variations": variations},
                headers=credentials(),
            )
        )
        validate(output, SeedreamGenerateOutput.model_json_schema())
        assert route.call_count == len(respx.calls) == commit.await_count == variations
        release.assert_not_awaited()
        if variations == 1:
            assert output["artifacts"][0]["uri"] == output_url
            assert output["item_errors"] == []
        else:
            assert output["summary"]["succeeded"] == variations
            assert output["summary"]["failed"] == 0
            for variation in output["summary"]["variations"]:
                assert variation["artifact"]["uri"] == output_url
                assert variation["request_id"] == "req-image"
                assert variation["error"] is None
        assert len(output["generations"]) == variations
        assert all(item["request_id"] == "req-image" for item in output["generations"])
        assert STORAGE_DETAIL not in json.dumps(output)
        assert_no_canaries(json.dumps(output))
        assert_budget_events(
            capsys.readouterr().err,
            {call.args[0].reservation_id for call in commit.await_args_list},
        )


@pytest.mark.parametrize("tool", ["seedance_create_task", "seedream_generate_image"])
@pytest.mark.parametrize("variations", [1, 2])
@respx.mock
async def test_uncertain_503_survives_budget_commit_failure_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool: str,
    variations: int,
) -> None:
    url = TASKS_URL if tool == "seedance_create_task" else f"{MODELARK}/images/generations"
    route = respx.post(url).respond(
        503,
        json={"error": {"code": "SERVICE_UNAVAILABLE", "message": "Synthetic uncertainty"}},
        headers={"X-Request-Id": "req-uncertain"},
    )
    async with http_server(tmp_path) as (_, runtime, client):
        commit = AsyncMock(side_effect=RuntimeError(" ".join((STORAGE_DETAIL, *CANARIES))))
        release = AsyncMock(wraps=runtime.budget_ledger.release)
        record = AsyncMock(wraps=runtime.ownership_store.record)
        monkeypatch.setattr(runtime.budget_ledger, "commit", commit)
        monkeypatch.setattr(runtime.budget_ledger, "release", release)
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        input_data = {"prompt": "scene", "variations": variations}
        if tool == "seedance_create_task":
            input_data["idempotency_key"] = f"uncertain-budget-commit-{variations}"
        response = await call_tool(client, tool, input_data, headers=credentials())
        assert route.call_count == len(respx.calls) == commit.await_count == variations
        release.assert_not_awaited()
        record.assert_not_awaited()
        if variations == 1:
            assert_denied(response)
            text = response["result"]["content"][0]["text"]
            assert "http_status=503" in text
            assert "code=SERVICE_UNAVAILABLE" in text
            assert "request_id=req-uncertain" in text
            assert "retryable=True" in text
            assert "ambiguous_completion=True" in text
        else:
            output = successful(response)
            if tool == "seedance_create_task":
                assert output["submitted"] == 0
                assert output["failed"] == variations
                results = output["tasks"]
                assert all(item["task_id"] is None for item in results)
            else:
                assert output["summary"]["succeeded"] == 0
                assert output["summary"]["failed"] == variations
                results = output["summary"]["variations"]
            for item in results:
                error = item["error"]
                assert error["code"] == "SERVICE_UNAVAILABLE"
                assert error["request_id"] == "req-uncertain"
                assert error["retryable"] is True
                assert error["ambiguous_completion"] is True
        assert "Synthetic uncertainty" in json.dumps(response)
        assert STORAGE_DETAIL not in json.dumps(response)
        assert_no_canaries(json.dumps(response))
        assert_budget_events(
            capsys.readouterr().err,
            {call.args[0].reservation_id for call in commit.await_args_list},
        )


@pytest.mark.parametrize("request_id", [None, "req-avatar"])
@respx.mock
async def test_omnihuman_record_failure_retains_accepted_id_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request_id: str | None,
) -> None:
    task_id = "accepted-avatar"
    route = respx.post(f"{VISION}/api/common/v3/submit_task_v2").respond(
        200,
        json={"code": 10000, "data": {"task_id": task_id}, "request_id": request_id},
    )
    settings = http_settings(tmp_path, BYTEPLUS_OMNIHUMAN_ENABLED=True)
    async with http_server(tmp_path, settings=settings) as (_, runtime, client):
        record = AsyncMock(side_effect=RuntimeError(" ".join((STORAGE_DETAIL, *CANARIES))))
        monkeypatch.setattr(runtime.ownership_store, "record", record)
        response = await call_tool(
            client,
            "omnihuman_create_task",
            {
                "image": "https://example.com/face.png",
                "audio": "https://example.com/audio.wav",
                "idempotency_key": f"avatar-record-failure-{request_id}",
            },
            headers=credentials(VISION_KEY, header="X-OmniHuman-Api-Key"),
        )
        assert_denied(response)
        text = response["result"]["content"][0]["text"]
        assert f"task_id={task_id}" in text
        assert "OWNERSHIP_RECORD_FAILED" in text
        assert "retryable=False" in text
        assert "ambiguous_completion=True" in text
        assert "do not resubmit" in text.lower()
        if request_id:
            assert f"request_id={request_id}" in text
        record.assert_awaited_once()
        assert route.call_count == len(respx.calls) == 1
        logs = capsys.readouterr().err
        assert task_id not in logs
        assert STORAGE_DETAIL not in text + logs
        assert_no_canaries(text + logs)
