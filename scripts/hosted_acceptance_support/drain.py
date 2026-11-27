"""Private bounded fixtures for specs/SPEC_VKE_DEPLOYMENT.md."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from scripts.hosted_acceptance_support.runtime import require

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

TASK_ID = "cgt-acceptance-drain"
REQUEST_ID = "req-acceptance-drain"
KEEPALIVE_IDLE = 5.25
PRODUCTION_BODY_LIMIT = 2 * 1024 * 1024


@dataclass(frozen=True)
class Clocks:
    work: float
    tool: float
    grace: float
    pod: float
    lifetime: float


PROFILES = {
    "short": Clocks(work=3, tool=8, grace=12, pod=18, lifetime=90),
    "production": Clocks(work=590, tool=600, grace=630, pod=660, lifetime=750),
}


def mark(directory: Path, name: str, **fields: Any) -> float:
    """Atomically publish a safe fixture event; never include request values."""
    path = directory / f"drain-{name}.json"
    pending = path.with_suffix(".tmp")
    timestamp = time.monotonic()
    pending.write_text(json.dumps({"time": timestamp, **fields}))
    pending.replace(path)
    return timestamp


def event(directory: Path, name: str) -> dict[str, Any] | None:
    path = directory / f"drain-{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


async def mock_response(
    directory: Path, clocks: Clocks, prompt: str, record: Callable[[str], None]
) -> httpx.Response:
    started = mark(directory, "dispatched")
    record("drain_dispatch")
    try:
        if prompt in {"stalled", "disconnected"}:
            await asyncio.Event().wait()
        # Completion requires both the elapsed workload and the parent's TERM barrier.
        async with asyncio.timeout(clocks.tool):
            while not (directory / "release").exists():
                await asyncio.sleep(0.01)
            await asyncio.sleep(max(0, started + clocks.work - time.monotonic()))
        record("drain_completed")
        mark(directory, "completed")
        return httpx.Response(200, json={"id": TASK_ID}, headers={"X-Request-Id": REQUEST_ID})
    except asyncio.CancelledError:
        record("drain_cancelled")
        mark(directory, "cancelled")
        raise


def receipt(response: httpx.Response) -> None:
    from scripts.hosted_acceptance_support.runtime import successful

    content = successful(response)
    tasks = content.get("tasks", [])
    require(
        content.get("submitted") == 1
        and content.get("failed") == 0
        and len(tasks) == 1
        and tasks[0].get("task_id") == TASK_ID
        and tasks[0].get("request_id") == REQUEST_ID,
        "incomplete_synthetic_receipt",
    )
