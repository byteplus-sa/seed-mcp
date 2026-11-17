"""Offline BYOE workflows for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client

from ark_mcp.config.env import Settings, settings_scope
from ark_mcp.server import create_server
from tests.integration.test_byok_http import (
    CLIENT_SECRET,
    IMAGE_MODEL,
    MODELARK,
    MODELARK_KEY,
    OPERATOR_KEY,
    OTHER_SECRET,
    SPEECH_KEY,
    VIDEO_MODEL,
    assert_denied,
    assert_no_canaries,
    call_tool,
    credentials,
    http_server,
    http_settings,
    successful,
)
from tests.integration.test_task_security import provider_task

IMAGE_TOOL = "seedream_generate_image"
VIDEO_TOOL = "seedance_create_task"
IMAGE_HEADER = "X-ModelArk-Seedream-Endpoint"
VIDEO_HEADER = "X-ModelArk-Seedance-Endpoint"
IMAGE_ENDPOINT = "ep-byoe-image-primary"
OTHER_IMAGE_ENDPOINT = "ep-byoe-image-secondary"
VIDEO_ENDPOINT = "ep-byoe-video-primary"
FLASH_ENDPOINT = "ep-byoe-video-secondary"
IMAGES_URL = f"{MODELARK}/images/generations"
TASKS_URL = f"{MODELARK}/contents/generations/tasks"
IMAGE_URL = "https://example.com/byoe-image.png"
VIDEO_URL = "https://example.com/byoe-video.mp4"
provider_mock = respx.MockRouter(assert_all_mocked=True, assert_all_called=True)


def byoe_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return http_settings(
        tmp_path,
        **{
            "SEEDREAM_MODEL_BINDINGS": [
                {"model_id": IMAGE_MODEL, "family": "pro"},
                {"model_id": IMAGE_ENDPOINT, "family": "seedream_5_5"},
                {"model_id": OTHER_IMAGE_ENDPOINT, "family": "pro"},
            ],
            "SEEDANCE_MODEL_BINDINGS": [
                {"model_id": VIDEO_MODEL, "family": "seedance_2_5"},
                {"model_id": VIDEO_ENDPOINT, "family": "seedance_2_5"},
                {"model_id": FLASH_ENDPOINT, "family": "seedance_2_5_flash"},
            ],
            **overrides,
        },
    )


def endpoint_headers(
    *,
    image: str = IMAGE_ENDPOINT,
    video: str = VIDEO_ENDPOINT,
) -> dict[str, str]:
    return {IMAGE_HEADER: image, VIDEO_HEADER: video}


def configured_route(
    tool: str, model_id: str, family: str, *, source: str = "request_header"
) -> dict[str, Any]:
    return {
        "tool": tool,
        "source": source,
        "configured": True,
        "model_id": model_id,
        "family": family,
        "issue": None,
    }


def assert_connection(
    result: dict[str, Any],
    routes: list[dict[str, Any]],
    *,
    key_present: bool = True,
    secret_present: bool = True,
) -> None:
    connection = result["connection"]
    issues = []
    if not key_present:
        issues.append("missing_modelark_key")
    if not secret_present:
        issues.append("missing_client_secret")
    assert connection == {
        "configuration_valid": key_present
        and secret_present
        and all(route["configured"] for route in routes),
        "modelark_key_present": key_present,
        "client_secret_present": secret_present,
        "authentication_verified": False,
        "provider_calls_made": False,
        "issues": issues,
        "routes": connection["routes"],
    }
    assert sorted(connection["routes"], key=lambda route: route["tool"]) == sorted(
        routes, key=lambda route: route["tool"]
    )
    assert_no_canaries(json.dumps(result))


def state_counts(tmp_path: Path) -> dict[str, int]:
    database = tmp_path / "artifacts" / "runtime.sqlite3"
    assert database.is_file()
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        return dict(
            connection.execute(
                """
                SELECT 'task_ownership', COUNT(*) FROM task_ownership
                UNION ALL SELECT 'object_key_ownership', COUNT(*) FROM object_key_ownership
                UNION ALL SELECT 'task_artifacts', COUNT(*) FROM task_artifacts
                UNION ALL SELECT 'budget_reservations', COUNT(*) FROM budget_reservations
                UNION ALL SELECT 'http_submissions', COUNT(*) FROM http_submissions
                UNION ALL SELECT 'http_submission_tasks', COUNT(*) FROM http_submission_tasks
                """
            ).fetchall()
        )


def assert_empty_state(tmp_path: Path) -> None:
    assert state_counts(tmp_path) == {
        "task_ownership": 0,
        "object_key_ownership": 0,
        "task_artifacts": 0,
        "budget_reservations": 0,
        "http_submissions": 0,
        "http_submission_tasks": 0,
    }


def assert_forwarded(request: httpx.Request, key: str, *, model: str | None = None) -> None:
    assert request.headers["Authorization"] == f"Bearer {key}"
    for header in (
        "X-ModelArk-Api-Key",
        "X-MCP-Client-Secret",
        IMAGE_HEADER,
        VIDEO_HEADER,
        "X-Seed-Speech-Api-Key",
    ):
        assert header not in request.headers
    assert OPERATOR_KEY not in str(request.headers)
    assert_no_canaries(request.content.decode())
    if model is not None:
        body = json.loads(request.content)
        assert body["model"] == model
        assert "idempotency_key" not in body


@pytest.mark.parametrize("operator_key", [None, OPERATOR_KEY])
@provider_mock
async def test_custom_endpoints_preflight_image_video_poll_and_recovery(
    tmp_path: Path, operator_key: str | None
) -> None:
    image_route = provider_mock.post(IMAGES_URL).respond(
        200, json={"data": [{"url": IMAGE_URL, "size": "2048x2048"}]}
    )
    create_route = provider_mock.post(TASKS_URL).respond(
        200, json={"id": "byoe-workflow-video"}, headers={"X-Request-Id": "byoe-create-request"}
    )
    poll_route = provider_mock.get(TASKS_URL).respond(
        200,
        json={
            "data": [
                provider_task(
                    "byoe-workflow-video",
                    "succeeded",
                    model=VIDEO_ENDPOINT,
                    content={"video_url": VIDEO_URL},
                )
            ]
        },
    )
    settings = byoe_settings(tmp_path, BYTEPLUS_MODELARK_API_KEY=operator_key or "")
    headers = {**credentials(), **endpoint_headers()}
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        preflight = successful(
            await call_tool(client, "ark_list_models", {"check_connection": True}, headers=headers)
        )
        assert_connection(
            preflight,
            [
                configured_route(IMAGE_TOOL, IMAGE_ENDPOINT, "seedream_5_5"),
                configured_route(VIDEO_TOOL, VIDEO_ENDPOINT, "seedance_2_5"),
            ],
        )
        assert not provider_mock.calls
        assert_empty_state(tmp_path)
        image = successful(
            await call_tool(
                client, IMAGE_TOOL, {"prompt": "A blue square", "size": "2K"}, headers=headers
            )
        )
        assert image["model"] == IMAGE_ENDPOINT
        assert image["artifacts"][0]["uri"] == IMAGE_URL
        video_input = {
            "prompt": "Rotate the blue square",
            "images": [image["artifacts"][0]["uri"]],
            "resolution": "4k",
            "duration": 30,
            "idempotency_key": "byoe-workflow-video-create",
        }
        created = successful(await call_tool(client, VIDEO_TOOL, video_input, headers=headers))
        assert created["model"] == VIDEO_ENDPOINT
        assert created["family"] == "seedance_2_5"
        assert created["submitted"] == 1
        assert created["failed"] == 0
        assert created["tasks"][0]["task_id"] == "byoe-workflow-video"
        assert created["tasks"][0]["request_id"] == "byoe-create-request"
        after_create = state_counts(tmp_path)
        recovered = successful(await call_tool(client, VIDEO_TOOL, video_input, headers=headers))
        assert recovered == created
        assert state_counts(tmp_path) == after_create
        assert create_route.call_count == 1
        polled = successful(
            await call_tool(
                client,
                "gen_task_get",
                {"task_ids": [recovered["tasks"][0]["task_id"]]},
                headers=credentials(),
            )
        )
        assert polled["errors"] == []
        task = polled["tasks"][0]
        assert task["task_id"] == "byoe-workflow-video"
        assert task["model"] == VIDEO_ENDPOINT
        assert task["status"] == "succeeded"
        assert task["outputs"][0]["source_url"] == VIDEO_URL
        assert_no_canaries(json.dumps([preflight, image, created, recovered, polled]))
        counts = state_counts(tmp_path)
        assert counts["task_ownership"] == counts["http_submissions"] == 1
        assert counts["http_submission_tasks"] == 1
        assert counts["object_key_ownership"] == counts["task_artifacts"] == 0
    assert image_route.call_count == create_route.call_count == poll_route.call_count == 1
    assert len(provider_mock.calls) == 3
    assert_forwarded(image_route.calls[0].request, MODELARK_KEY, model=IMAGE_ENDPOINT)
    assert_forwarded(create_route.calls[0].request, MODELARK_KEY, model=VIDEO_ENDPOINT)
    body = json.loads(create_route.calls[0].request.content)
    assert body["resolution"] == "4k"
    assert body["duration"] == 30
    assert any(part.get("image_url", {}).get("url") == IMAGE_URL for part in body["content"])
    assert_forwarded(poll_route.calls[0].request, MODELARK_KEY)
    assert poll_route.calls[0].request.url.params.get_list("filter.task_ids") == [
        "byoe-workflow-video"
    ]


@pytest.mark.parametrize("kind", [None, "image", "video"])
@pytest.mark.parametrize("source", ["server_default", "request_header"])
@provider_mock
async def test_preflight_filters_only_selected_routes_and_never_writes_state(
    tmp_path: Path, kind: str | None, source: str
) -> None:
    headers = credentials()
    if source == "request_header":
        headers.update(endpoint_headers())
    if kind == "image":
        headers[VIDEO_HEADER] = "ep-unconfigured-unselected-video"
    elif kind == "video":
        headers[IMAGE_HEADER] = "ep-unconfigured-unselected-image"
    expected = []
    if kind in (None, "image"):
        expected.append(
            configured_route(
                IMAGE_TOOL,
                IMAGE_ENDPOINT if source == "request_header" else IMAGE_MODEL,
                "seedream_5_5" if source == "request_header" else "seedream_pro",
                source=source,
            )
        )
    if kind in (None, "video"):
        expected.append(
            configured_route(
                VIDEO_TOOL,
                VIDEO_ENDPOINT if source == "request_header" else VIDEO_MODEL,
                "seedance_2_5",
                source=source,
            )
        )
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        result = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": kind, "check_connection": True},
                headers=headers,
            )
        )
        assert_connection(result, expected)
        if kind is not None:
            assert {model["kind"] for model in result["models"]} == {kind}
        assert_empty_state(tmp_path)
    assert not provider_mock.calls


@pytest.mark.parametrize("supplied", ["none", "key_only", "secret_only", "wrong_provider"])
@provider_mock
async def test_preflight_missing_live_credentials_never_uses_startup_or_previous_keys(
    tmp_path: Path, supplied: str
) -> None:
    supplied_headers = {
        "none": {},
        "key_only": {"X-ModelArk-Api-Key": MODELARK_KEY},
        "secret_only": {"X-MCP-Client-Secret": CLIENT_SECRET},
        "wrong_provider": credentials(SPEECH_KEY, header="X-Seed-Speech-Api-Key"),
    }[supplied]
    routes = [
        configured_route(IMAGE_TOOL, IMAGE_ENDPOINT, "seedream_5_5"),
        configured_route(VIDEO_TOOL, VIDEO_ENDPOINT, "seedance_2_5"),
    ]
    settings = byoe_settings(tmp_path, BYTEPLUS_MODELARK_API_KEY=OPERATOR_KEY)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        configured = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"check_connection": True},
                headers={**credentials(), **endpoint_headers()},
            )
        )
        assert_connection(configured, routes)
        headers = {**supplied_headers, **endpoint_headers()}
        missing = successful(
            await call_tool(client, "ark_list_models", {"check_connection": True}, headers=headers)
        )
        assert_connection(
            missing,
            routes,
            key_present=supplied == "key_only",
            secret_present=supplied in ("secret_only", "wrong_provider"),
        )
        assert_empty_state(tmp_path)
        for tool in (IMAGE_TOOL, VIDEO_TOOL):
            denied = await call_tool(
                client, tool, {"prompt": "A square", "dry_run": True}, headers=headers
            )
            assert_denied(denied)
            assert "Configure" in str(denied)
            assert_no_canaries(json.dumps(denied))
        assert_empty_state(tmp_path)
    assert not provider_mock.calls


@provider_mock
async def test_default_discovery_ignores_endpoint_selection_and_preflight_excludes_understanding(
    tmp_path: Path,
) -> None:
    headers = {**credentials(), **endpoint_headers(image="ep-private-unknown")}
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        for input_data in ({}, {"check_connection": False}):
            anonymous = successful(await call_tool(client, "ark_list_models", input_data))
            authenticated = successful(
                await call_tool(client, "ark_list_models", input_data, headers=headers)
            )
            assert anonymous == authenticated
            assert anonymous["connection"] is None
            assert_no_canaries(json.dumps(authenticated))
        for check_connection in (False, True):
            denied = await call_tool(
                client,
                "ark_list_models",
                {"kind": "understanding", "check_connection": check_connection},
                headers=headers,
            )
            assert_denied(denied)
            assert "understanding" in str(denied)
        assert_empty_state(tmp_path)
    assert not provider_mock.calls


@pytest.mark.parametrize("transport", ["stdio", "http"])
@provider_mock
async def test_preflight_requires_live_http_even_with_configured_operator_key(
    tmp_path: Path,
    transport: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(Client, "_auto_internal_extensions", False)
    settings = byoe_settings(
        tmp_path,
        MCP_TRANSPORT=transport,
        MCP_AUTH_MODE="local" if transport == "stdio" else "byok",
        BYTEPLUS_MODELARK_API_KEY=OPERATOR_KEY,
    )
    with settings_scope(settings):
        async with Client(create_server(settings)) as client:
            default = await client.call_tool("ark_list_models", {"input": {}})
            assert default.structured_content is not None
            assert default.structured_content["connection"] is None
            checked = await client.call_tool(
                "ark_list_models", {"input": {"check_connection": True}}, raise_on_error=False
            )
            assert checked.is_error
            assert checked.structured_content is None
            expected = "not available on stdio" if transport == "stdio" else "current HTTP request"
            assert expected in checked.content[0].text
            assert "tasks extension" not in caplog.text
            assert_no_canaries(str(checked) + caplog.text)
    assert not provider_mock.calls


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("selection", ["unknown_endpoint", "unknown_model", "wrong_product"])
@provider_mock
async def test_unknown_and_wrong_product_routes_fail_closed_without_echoing_connection_ids(
    tmp_path: Path, kind: str, selection: str
) -> None:
    tool = IMAGE_TOOL if kind == "image" else VIDEO_TOOL
    header = IMAGE_HEADER if kind == "image" else VIDEO_HEADER
    requested = {
        "unknown_endpoint": "ep-unregistered-private-canary",
        "unknown_model": "unregistered-model-private-canary",
        "wrong_product": VIDEO_ENDPOINT if kind == "image" else IMAGE_ENDPOINT,
    }[selection]
    headers = {**credentials(), **endpoint_headers(), header: requested}
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        preflight = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": kind, "check_connection": True},
                headers=headers,
            )
        )
        assert_connection(
            preflight,
            [
                {
                    "tool": tool,
                    "source": "request_header",
                    "configured": False,
                    "model_id": None,
                    "family": None,
                    "issue": "endpoint_not_configured",
                }
            ],
        )
        assert requested not in json.dumps(preflight["connection"])
        assert_empty_state(tmp_path)
        input_data = {"prompt": "A square"}
        if kind == "video":
            input_data["idempotency_key"] = "byoe-invalid-endpoint-create"
        denied = await call_tool(client, tool, input_data, headers=headers)
        assert_denied(denied)
        if selection != "unknown_model":
            assert "ENDPOINT_NOT_CONFIGURED" in str(denied)
        if selection == "unknown_endpoint":
            assert requested not in json.dumps(denied)
        assert_no_canaries(json.dumps(denied))
        counts = state_counts(tmp_path)
        assert counts["budget_reservations"] == counts["task_ownership"] == 0
        assert counts["http_submission_tasks"] == 0
    assert not provider_mock.calls


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("selection", ["registered", "unknown", "wrong_product"])
@provider_mock
async def test_explicit_custom_model_overrides_endpoint_header_before_dispatch(
    tmp_path: Path, kind: str, selection: str
) -> None:
    tool = IMAGE_TOOL if kind == "image" else VIDEO_TOOL
    header = IMAGE_HEADER if kind == "image" else VIDEO_HEADER
    requested = {
        "registered": IMAGE_ENDPOINT if kind == "image" else VIDEO_ENDPOINT,
        "unknown": "ep-unregistered-default",
        "wrong_product": VIDEO_ENDPOINT if kind == "image" else IMAGE_ENDPOINT,
    }[selection]
    explicit = OTHER_IMAGE_ENDPOINT if kind == "image" else FLASH_ENDPOINT
    response = {"data": [{"url": IMAGE_URL}]} if kind == "image" else {"id": "explicit-video"}
    route = provider_mock.post(IMAGES_URL if kind == "image" else TASKS_URL).respond(
        200, json=response
    )
    input_data: dict[str, Any] = {"prompt": "A square", "model": explicit}
    if kind == "video":
        input_data.update(
            resolution="720p", duration=30, idempotency_key="byoe-explicit-model-create"
        )
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        result = successful(
            await call_tool(client, tool, input_data, headers={**credentials(), header: requested})
        )
        assert result["model"] == explicit
        assert_no_canaries(json.dumps(result))
    assert route.call_count == len(provider_mock.calls) == 1
    assert_forwarded(route.calls[0].request, MODELARK_KEY, model=explicit)


@provider_mock
async def test_overlapping_clients_keep_endpoint_key_preflight_and_replay_isolated(
    tmp_path: Path,
) -> None:
    first_entered = asyncio.Event()
    both_entered = asyncio.Event()
    second_key = "synthetic-byoe-second-client"
    keys = (MODELARK_KEY, second_key)
    images = (IMAGE_ENDPOINT, OTHER_IMAGE_ENDPOINT)
    videos = (VIDEO_ENDPOINT, FLASH_ENDPOINT)
    headers = (
        {**credentials(), **endpoint_headers()},
        {
            **credentials(second_key, OTHER_SECRET),
            **endpoint_headers(image=images[1], video=videos[1]),
        },
    )
    seen: list[tuple[str, str]] = []

    async def generate(request: httpx.Request) -> httpx.Response:
        index = keys.index(request.headers["Authorization"].removeprefix("Bearer "))
        assert_forwarded(request, keys[index], model=images[index])
        seen.append((keys[index], json.loads(request.content)["model"]))
        first_entered.set()
        if len(seen) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), 5)
        return httpx.Response(
            200, json={"data": [{"url": f"https://example.com/byoe-client-{index}.png"}]}
        )

    def create(request: httpx.Request) -> httpx.Response:
        index = keys.index(request.headers["Authorization"].removeprefix("Bearer "))
        assert_forwarded(request, keys[index], model=videos[index])
        return httpx.Response(200, json={"id": f"byoe-client-{index}"})

    def poll(request: httpx.Request) -> httpx.Response:
        index = keys.index(request.headers["Authorization"].removeprefix("Bearer "))
        assert_forwarded(request, keys[index])
        assert request.url.params.get_list("filter.task_ids") == [f"byoe-client-{index}"]
        return httpx.Response(
            200,
            json={
                "data": [
                    provider_task(
                        f"byoe-client-{index}",
                        "succeeded",
                        model=videos[index],
                        content={"video_url": f"https://example.com/byoe-client-{index}.mp4"},
                    )
                ]
            },
        )

    image_route = provider_mock.post(IMAGES_URL).mock(side_effect=generate)
    create_route = provider_mock.post(TASKS_URL).mock(side_effect=create)
    poll_route = provider_mock.get(TASKS_URL).mock(side_effect=poll)
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        for index in (0, 1, 0):
            checked = successful(
                await call_tool(
                    client, "ark_list_models", {"check_connection": True}, headers=headers[index]
                )
            )
            assert_connection(
                checked,
                [
                    configured_route(
                        IMAGE_TOOL, images[index], ("seedream_5_5", "seedream_pro")[index]
                    ),
                    configured_route(
                        VIDEO_TOOL, videos[index], ("seedance_2_5", "seedance_2_5_flash")[index]
                    ),
                ],
            )
            assert second_key not in json.dumps(checked)
            assert OTHER_SECRET not in json.dumps(checked)
        assert_empty_state(tmp_path)
        assert not provider_mock.calls
        pending = asyncio.create_task(
            call_tool(client, IMAGE_TOOL, {"prompt": "First square"}, headers=headers[0])
        )
        try:
            await asyncio.wait_for(first_entered.wait(), 5)
            second = successful(
                await call_tool(client, IMAGE_TOOL, {"prompt": "Second square"}, headers=headers[1])
            )
            first = successful(await asyncio.wait_for(pending, 5))
        finally:
            both_entered.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        for index, image in enumerate((first, second)):
            assert image["model"] == images[index]
            assert image["artifacts"][0]["uri"] == f"https://example.com/byoe-client-{index}.png"
        input_data = {
            "prompt": "Rotate the square",
            "resolution": "720p",
            "idempotency_key": "same-key-two-byoe-clients",
        }
        created = [
            successful(await call_tool(client, VIDEO_TOOL, input_data, headers=client_headers))
            for client_headers in headers
        ]
        for index in (1, 0, 1):
            replay = successful(
                await call_tool(client, VIDEO_TOOL, input_data, headers=headers[index])
            )
            assert replay == created[index]
            assert replay["model"] == videos[index]
            assert replay["tasks"][0]["task_id"] == f"byoe-client-{index}"
        for index in (1, 0):
            result = successful(
                await call_tool(
                    client,
                    "gen_task_get",
                    {"task_ids": [f"byoe-client-{index}"]},
                    headers=credentials(keys[index], (CLIENT_SECRET, OTHER_SECRET)[index]),
                )
            )
            assert result["errors"] == []
            assert result["tasks"][0]["model"] == videos[index]
    assert seen == [(keys[0], images[0]), (keys[1], images[1])]
    assert image_route.call_count == create_route.call_count == poll_route.call_count == 2
    assert len(provider_mock.calls) == 6


@pytest.mark.parametrize("kind", ["image", "video"])
@provider_mock
async def test_configuration_valid_is_not_authentication_even_when_provider_rejects_key(
    tmp_path: Path, kind: str
) -> None:
    tool = IMAGE_TOOL if kind == "image" else VIDEO_TOOL
    model = IMAGE_ENDPOINT if kind == "image" else VIDEO_ENDPOINT
    family = "seedream_5_5" if kind == "image" else "seedance_2_5"
    route = provider_mock.post(IMAGES_URL if kind == "image" else TASKS_URL).respond(
        401,
        json={"error": {"code": "INVALID_API_KEY", "message": "Synthetic rejected credential"}},
    )
    headers = {**credentials(), **endpoint_headers()}
    input_data: dict[str, Any] = {"prompt": "A square"}
    if kind == "video":
        input_data["idempotency_key"] = "byoe-rejected-key-create"
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        before = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": kind, "check_connection": True},
                headers=headers,
            )
        )
        assert_connection(before, [configured_route(tool, model, family)])
        assert_empty_state(tmp_path)
        assert not provider_mock.calls
        denied = await call_tool(client, tool, input_data, headers=headers)
        assert_denied(denied)
        assert "INVALID_API_KEY" in str(denied)
        assert_no_canaries(json.dumps(denied))
        after_failure = state_counts(tmp_path)
        after = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": kind, "check_connection": True},
                headers=headers,
            )
        )
        assert after == before
        assert_connection(after, [configured_route(tool, model, family)])
        assert state_counts(tmp_path) == after_failure
        assert after_failure["task_ownership"] == after_failure["http_submission_tasks"] == 0
        if kind == "video":
            repeated = await call_tool(client, tool, input_data, headers=headers)
            assert_denied(repeated)
            assert "SUBMISSION_UNRESOLVED" in str(repeated)
    assert route.call_count == len(provider_mock.calls) == 1
    assert_forwarded(route.calls[0].request, MODELARK_KEY, model=model)


@pytest.mark.parametrize(
    ("kind", "extra", "message"),
    [
        ("image", {"size": "4K"}, "size"),
        ("image", {"size": "1x1"}, "pixel count"),
        ("image", {"max_images": 2}, "batch generation"),
        ("image", {"prompt_optimization": "fast"}, "prompt_optimization"),
        ("video", {"resolution": "4k"}, "resolution"),
        ("video", {"draft": True}, "Draft mode"),
        ("video", {"images": [IMAGE_URL] * 11}, "reference images"),
        ("video", {"videos": [VIDEO_URL] * 6}, "reference videos"),
    ],
)
@provider_mock
async def test_configured_endpoint_still_enforces_its_bound_family_capabilities(
    tmp_path: Path, kind: str, extra: dict[str, Any], message: str
) -> None:
    tool = IMAGE_TOOL if kind == "image" else VIDEO_TOOL
    model = IMAGE_ENDPOINT if kind == "image" else FLASH_ENDPOINT
    family = "seedream_5_5" if kind == "image" else "seedance_2_5_flash"
    headers = {**credentials(), **endpoint_headers(video=FLASH_ENDPOINT)}
    input_data = {"prompt": "A square", **extra}
    if kind == "video":
        input_data["idempotency_key"] = "byoe-capability-rejected"
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        preflight = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": kind, "check_connection": True},
                headers=headers,
            )
        )
        assert_connection(preflight, [configured_route(tool, model, family)])
        assert_empty_state(tmp_path)
        denied = await call_tool(client, tool, input_data, headers=headers)
        assert_denied(denied)
        assert message in str(denied)
        assert model in str(denied)
        assert family in str(denied)
        assert_no_canaries(json.dumps(denied))
        counts = state_counts(tmp_path)
        assert counts["budget_reservations"] == counts["task_ownership"] == 0
    assert not provider_mock.calls


@provider_mock
async def test_changed_endpoint_conflicts_but_explicit_original_model_recovers_receipt(
    tmp_path: Path,
) -> None:
    route = provider_mock.post(TASKS_URL).respond(200, json={"id": "byoe-replay-original"})
    input_data = {"prompt": "A square", "idempotency_key": "byoe-endpoint-replay"}
    headers = {**credentials(), **endpoint_headers()}
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        first = successful(await call_tool(client, VIDEO_TOOL, input_data, headers=headers))
        changed_headers = {**headers, VIDEO_HEADER: FLASH_ENDPOINT}
        conflict = await call_tool(client, VIDEO_TOOL, input_data, headers=changed_headers)
        assert_denied(conflict)
        assert "SUBMISSION_CONFLICT" in str(conflict)
        recovered = successful(
            await call_tool(
                client,
                VIDEO_TOOL,
                {**input_data, "model": VIDEO_ENDPOINT},
                headers=changed_headers,
            )
        )
        assert recovered == first
        assert state_counts(tmp_path)["http_submissions"] == 1
    assert route.call_count == len(provider_mock.calls) == 1
    assert_forwarded(route.calls[0].request, MODELARK_KEY, model=VIDEO_ENDPOINT)


@pytest.mark.parametrize("identity_change", ["provider_key", "client_secret"])
@provider_mock
async def test_valid_endpoint_preflight_does_not_grant_another_clients_task_ownership(
    tmp_path: Path, identity_change: str
) -> None:
    create_route = provider_mock.post(TASKS_URL).respond(200, json={"id": "byoe-private-draft"})
    poll_route = provider_mock.get(TASKS_URL).respond(
        200,
        json={
            "data": [
                provider_task(
                    "byoe-private-draft",
                    "succeeded",
                    model=VIDEO_ENDPOINT,
                    draft=True,
                    content={"video_url": VIDEO_URL},
                )
            ]
        },
    )
    owner = {**credentials(), **endpoint_headers()}
    stranger = {
        **(
            credentials("synthetic-byoe-foreign-key")
            if identity_change == "provider_key"
            else credentials(MODELARK_KEY, OTHER_SECRET)
        ),
        **endpoint_headers(),
    }
    async with http_server(tmp_path, settings=byoe_settings(tmp_path)) as (_, _, client):
        created = successful(
            await call_tool(
                client,
                VIDEO_TOOL,
                {"prompt": "A square", "draft": True, "idempotency_key": "byoe-private-draft-key"},
                headers=owner,
            )
        )
        assert created["tasks"][0]["task_id"] == "byoe-private-draft"
        before = state_counts(tmp_path)
        check = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": "video", "check_connection": True},
                headers=stranger,
            )
        )
        assert_connection(check, [configured_route(VIDEO_TOOL, VIDEO_ENDPOINT, "seedance_2_5")])
        assert state_counts(tmp_path) == before
        got = successful(
            await call_tool(
                client, "gen_task_get", {"task_ids": ["byoe-private-draft"]}, headers=stranger
            )
        )
        assert got["tasks"] == []
        assert [(error["task_id"], error["code"]) for error in got["errors"]] == [
            ("byoe-private-draft", "NOT_OWNED")
        ]
        listed = successful(await call_tool(client, "gen_task_list", {}, headers=stranger))
        assert listed == {"tasks": [], "next_cursor": None}
        for tool, input_data in (
            (
                "gen_task_cancel_or_delete",
                {"task_id": "byoe-private-draft", "mode": "cancel", "expected_status": "queued"},
            ),
            (
                VIDEO_TOOL,
                {
                    "draft_task_id": "byoe-private-draft",
                    "idempotency_key": "byoe-foreign-promotion",
                },
            ),
        ):
            denied = await call_tool(client, tool, input_data, headers=stranger)
            assert_denied(denied)
            assert_no_canaries(json.dumps(denied))
        assert len(provider_mock.calls) == 1
        owned = successful(
            await call_tool(
                client, "gen_task_get", {"task_ids": ["byoe-private-draft"]}, headers=owner
            )
        )
        assert owned["errors"] == []
        assert owned["tasks"][0]["model"] == VIDEO_ENDPOINT
    assert create_route.call_count == poll_route.call_count == 1
    assert len(provider_mock.calls) == 2
    assert_forwarded(create_route.calls[0].request, MODELARK_KEY, model=VIDEO_ENDPOINT)
    assert_forwarded(poll_route.calls[0].request, MODELARK_KEY)


@provider_mock
async def test_custom_endpoint_draft_inherits_model_and_replays_without_another_draft_lookup(
    tmp_path: Path,
) -> None:
    create_route = provider_mock.post(TASKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"id": "byoe-source-draft"}),
            httpx.Response(200, json={"id": "byoe-promoted-final"}),
        ]
    )
    draft_route = provider_mock.get(f"{TASKS_URL}/byoe-source-draft").mock(
        side_effect=[
            httpx.Response(
                200,
                json=provider_task(
                    "byoe-source-draft", "succeeded", model=VIDEO_ENDPOINT, draft=True
                ),
            )
        ]
    )
    promotion = {
        "draft_task_id": "byoe-source-draft",
        "idempotency_key": "byoe-draft-promotion-key",
    }
    settings = byoe_settings(tmp_path, SEEDANCE_DEFAULT_MODEL=FLASH_ENDPOINT)
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        headers = {**credentials(), **endpoint_headers()}
        check = successful(
            await call_tool(
                client,
                "ark_list_models",
                {"kind": "video", "check_connection": True},
                headers=headers,
            )
        )
        assert_connection(check, [configured_route(VIDEO_TOOL, VIDEO_ENDPOINT, "seedance_2_5")])
        assert_empty_state(tmp_path)
        assert not provider_mock.calls
        draft = successful(
            await call_tool(
                client,
                VIDEO_TOOL,
                {"prompt": "A square", "draft": True, "idempotency_key": "byoe-source-draft-key"},
                headers=headers,
            )
        )
        assert draft["model"] == VIDEO_ENDPOINT
        final = successful(await call_tool(client, VIDEO_TOOL, promotion, headers=credentials()))
        assert final["model"] == VIDEO_ENDPOINT
        assert final["family"] == "seedance_2_5"
        assert final["tasks"][0]["task_id"] == "byoe-promoted-final"
        assert final["submitted"] == 1
        assert final["failed"] == 0
    async with http_server(tmp_path, settings=settings) as (_, _, client):
        before = state_counts(tmp_path)
        replay = successful(await call_tool(client, VIDEO_TOOL, promotion, headers=credentials()))
        assert replay == final
        assert state_counts(tmp_path) == before
        assert before["http_submissions"] == before["http_submission_tasks"] == 2
        assert before["task_ownership"] == 2
    assert create_route.call_count == 2
    assert draft_route.call_count == 1
    assert len(provider_mock.calls) == 3
    for call in create_route.calls:
        assert_forwarded(call.request, MODELARK_KEY, model=VIDEO_ENDPOINT)
    preview_body = json.loads(create_route.calls[0].request.content)
    assert preview_body["draft"] is True
    assert preview_body["resolution"] == "480p"
    final_body = json.loads(create_route.calls[1].request.content)
    assert final_body["resolution"] == "1080p"
    assert final_body["content"] == [
        {"type": "draft_task", "draft_task": {"id": "byoe-source-draft"}}
    ]
    assert_forwarded(draft_route.calls[0].request, MODELARK_KEY)
