"""HTTPS contract checks and bounded synthetic load, with no remote-target CLI."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from typing import TYPE_CHECKING, Any

import httpx
from scripts.hosted_acceptance_support.runtime import (
    BODY_LIMIT,
    IMAGE_MODEL,
    PUBLIC_TOOLS,
    VIDEO_MODEL,
    Sample,
    aggregate,
    classify,
    expected_error,
    protocol_request,
    require,
    result_of,
    successful,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from scripts.hosted_acceptance_support.runtime import ManagedProcess


async def rpc(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    protocol_headers, body = protocol_request(method, params)
    return await client.post(
        url + "/mcp", headers={**protocol_headers, **(headers or {})}, json=body
    )


async def call(
    client: httpx.AsyncClient,
    url: str,
    name: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    return await rpc(
        client, url, "tools/call", {"name": name, "arguments": {"input": arguments}}, headers
    )


def credentials(values: dict[str, str], *, other: bool = False) -> dict[str, str]:
    return {
        "X-ModelArk-Api-Key": values["key"],
        "X-MCP-Client-Secret": values["other_secret" if other else "secret"],
        "X-ModelArk-Seedream-Endpoint": IMAGE_MODEL,
        "X-ModelArk-Seedance-Endpoint": VIDEO_MODEL,
    }


def dispatches(directory: Path) -> Counter[str]:
    path = directory / "dispatches.log"
    return Counter(path.read_text().splitlines()) if path.exists() else Counter()


async def wait_dispatch(directory: Path, label: str, previous: int) -> None:
    async with asyncio.timeout(5):
        while dispatches(directory)[label] == previous:
            await asyncio.sleep(0.01)


async def wait_healthy(client: httpx.AsyncClient, url: str, process: ManagedProcess) -> None:
    async with asyncio.timeout(30):
        while True:
            require(process.healthy(), "process_startup_failed")
            try:
                response = await client.get(url + "/health", timeout=1)
                if response.status_code == 200:
                    require(response.json() == {"status": "healthy"}, "health_contract")
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)


async def surface(client: httpx.AsyncClient, url: str) -> None:
    tools = result_of(await rpc(client, url, "tools/list"))["tools"]
    expected = PUBLIC_TOOLS
    require(
        len(tools) == len(expected) and {tool["name"] for tool in tools} == expected,
        "tool_inventory",
    )
    require(
        result_of(await rpc(client, url, "resources/list"))["resources"] == [], "http_resources"
    )
    require(
        result_of(await rpc(client, url, "resources/templates/list"))["resourceTemplates"] == [],
        "http_resource_templates",
    )


async def credential_checks(
    client: httpx.AsyncClient, url: str, values: dict[str, str], directory: Path
) -> None:
    before = dispatches(directory)
    for headers in (
        {},
        {"X-ModelArk-Api-Key": values["key"]},
        {"X-MCP-Client-Secret": values["secret"]},
        {"X-Seed-Speech-Api-Key": values["speech_key"], "X-MCP-Client-Secret": values["secret"]},
    ):
        expected_error(
            await call(client, url, "seedream_generate_image", {"prompt": "unused"}, headers),
            "Configure",
        )
    protocol_headers, body = protocol_request(
        "tools/call",
        {"name": "seedream_generate_image", "arguments": {"input": {"prompt": "unused"}}},
    )
    for malformed in (
        [("X-ModelArk-Api-Key", "bad key")],
        [("X-ModelArk-Api-Key", "")],
        [("X-ModelArk-Api-Key", values["key"] * 100)],
        [("X-MCP-Client-Secret", "A" * 64)],
        [("Authorization", "Bearer " + values["key"])],
        [("X-ModelArk-Api-Key", values["key"]), ("X-ModelArk-Api-Key", values["key"])],
    ):
        response = await client.post(
            url + "/mcp", headers=[*protocol_headers.items(), *malformed], json=body
        )
        require(response.status_code == 400, "malformed_headers")
        require(values["key"] not in response.text, "credential_response_leak")
    require(dispatches(directory) == before, "rejected_credentials_dispatched")
    response = await call(
        client,
        url,
        "seedream_generate_image",
        {"prompt": "unused"},
        {**credentials(values), "X-ModelArk-Api-Key": values["invalid_key"]},
    )
    expected_error(response, "SYNTHETIC_INVALID_KEY")
    require(values["invalid_key"] not in response.text, "invalid_key_response_leak")
    require(
        dispatches(directory)["invalid_key"] == before["invalid_key"] + 1, "invalid_key_dispatch"
    )


async def edge_checks(
    client: httpx.AsyncClient, url: str, backend: str, values: dict[str, str]
) -> None:
    for path in ("/metrics", "/ready", "/unknown"):
        require((await client.get(url + path)).status_code == 404, "public_private_route")
    require(
        (await client.get(backend + "/ready")).json() == {"status": "ready"}, "private_readiness"
    )
    protocol_headers, body = protocol_request(
        "tools/call", {"name": "ark_list_models", "arguments": {"input": {}}}
    )
    body["padding"] = "x" * BODY_LIMIT
    raw = json.dumps(body).encode()
    response = await client.post(url + "/mcp", headers=protocol_headers, content=raw)
    require(response.status_code == 413, "declared_body_cap")

    async def chunks() -> AsyncIterator[bytes]:
        for offset in range(0, len(raw), 4096):
            yield raw[offset : offset + 4096]

    response = await client.post(url + "/mcp", headers=protocol_headers, content=chunks())
    require(response.status_code == 413, "streamed_body_cap")
    response = await rpc(
        client, backend, "tools/list", headers={"X-Forwarded-For": values["forwarded"]}
    )
    require(
        response.status_code == 400 and values["forwarded"] not in response.text,
        "trusted_malformed_forwarding",
    )
    response = await rpc(
        client,
        url,
        "tools/list",
        headers={
            "X-Forwarded-For": values["forwarded"],
            "Forwarded": values["forwarded"],
            "X-Forwarded-Proto": "http",
            "X-Forwarded-Host": "spoof.invalid",
            "X-Acceptance-Probe": "1",
        },
    )
    require("tools" in result_of(response), "proxy_overwrite")


async def bounded_generation(
    client: httpx.AsyncClient, url: str, values: dict[str, str], directory: Path, task_id: str
) -> None:
    headers = credentials(values)
    previous = dispatches(directory)["slow"]
    pending = asyncio.create_task(
        call(client, url, "seedream_generate_image", {"prompt": "slow"}, headers)
    )
    try:
        await wait_dispatch(directory, "slow", previous)
        expected_error(
            await call(
                client, url, "seedream_generate_image", {"prompt": "must-not-dispatch"}, headers
            ),
            "ADMISSION_TIMEOUT",
        )
        successful(await call(client, url, "ark_list_models", {}, {}))
        successful(await call(client, url, "gen_task_get", {"task_ids": [task_id]}, headers))
        require(not pending.done(), "polling_blocked_by_generation")
        text = expected_error(await pending, "TOOL_DEADLINE_EXCEEDED")
        require("ambiguous_completion=True" in text, "deadline_mutation_uncertainty")
        successful(
            await call(
                client, url, "seedream_generate_image", {"prompt": values["prompt"]}, headers
            )
        )
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


def disconnected_input(values: dict[str, str]) -> dict[str, Any]:
    return {
        "prompt": "disconnect",
        "duration": 4,
    }


async def disconnect_check(
    client: httpx.AsyncClient, url: str, values: dict[str, str], directory: Path
) -> None:
    before = dispatches(directory)["disconnect"]
    pending = asyncio.create_task(
        call(client, url, "seedance_create_task", disconnected_input(values), credentials(values))
    )
    try:
        await wait_dispatch(directory, "disconnect", before)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    # The client must not repeat an uncertain create. Probe liveness only.
    response = await client.get(url + "/health")
    require(response.status_code == 200, "disconnect_health")
    require(dispatches(directory)["disconnect"] == before + 1, "disconnect_redispatched")


async def run_load(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    task_id: str,
    max_requests: int,
    concurrency: int,
) -> dict[str, Any]:
    require(1 <= max_requests <= 1000 and 1 <= concurrency <= min(32, max_requests), "load_bounds")
    indices = iter(range(max_requests))
    samples: list[Sample] = []

    async def worker() -> None:
        for index in indices:
            choices: list[tuple[str, dict[str, Any]]] = [
                ("ark_list_models", {}),
                ("seedream_generate_image", {"prompt": "load"}),
                ("gen_task_get", {"task_ids": [task_id]}),
                (
                    "seedance_create_task",
                    {
                        "prompt": "load",
                        "duration": 4,
                    },
                ),
            ]
            name, arguments = choices[index % len(choices)]
            started = time.perf_counter()
            try:
                response = await call(client, url, name, arguments, headers)
                samples.append(
                    Sample(
                        (time.perf_counter() - started) * 1000,
                        response.status_code,
                        classify(response),
                    )
                )
            except httpx.TransportError:
                samples.append(Sample((time.perf_counter() - started) * 1000, 0, "error"))

    started = time.perf_counter()
    async with asyncio.timeout(90), asyncio.TaskGroup() as group:
        for _ in range(concurrency):
            group.create_task(worker())
    return aggregate(samples, time.perf_counter() - started, concurrency)


async def inflight_checks(
    client: httpx.AsyncClient, url: str, values: dict[str, str], directory: Path
) -> None:
    before = dispatches(directory)["slow"]
    pending = asyncio.create_task(
        call(client, url, "seedream_generate_image", {"prompt": "slow"}, credentials(values))
    )
    try:
        await wait_dispatch(directory, "slow", before)
        response = await rpc(client, url, "tools/list")
        require(response.status_code == 503 and classify(response) == "overload", "http_admission")
        for _ in range(3):
            require(
                (await client.get(url + "/health")).status_code == 200, "inflight_health_exemption"
            )
        expected_error(await pending, "TOOL_DEADLINE_EXCEEDED")
        require("tools" in result_of(await rpc(client, url, "tools/list")), "http_slot_recovery")
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def rate_checks(client: httpx.AsyncClient, url: str) -> None:
    for _ in range(3):
        require((await client.get(url + "/health")).status_code == 200, "rate_health_exemption")
    for index in range(2):
        require(
            "tools"
            in result_of(
                await rpc(
                    client, url, "tools/list", headers={"X-Forwarded-For": f"192.0.2.{index + 1}"}
                )
            ),
            "rate_burst",
        )
    rejected = await rpc(client, url, "tools/list", headers={"X-Forwarded-For": "198.51.100.9"})
    require(
        rejected.status_code == 429 and "Retry-After" in rejected.headers, "spoof_bypassed_rate"
    )
    require((await client.get(url + "/health")).status_code == 200, "rate_health_exemption")
