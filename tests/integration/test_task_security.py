"""Provider ownership over HTTP, per specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from tests.integration.test_byok_http import (
    MODELARK,
    VIDEO_MODEL,
    call_tool,
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


async def create_video(
    client: httpx.AsyncClient, headers: dict[str, str], *, idempotency_key: str
) -> str:
    result = successful(
        await call_tool(
            client,
            "seedance_create_task",
            {"prompt": "A synthetic scene"},
            headers=headers,
        )
    )
    assert result["submitted"] == 1
    return str(result["tasks"][0]["task_id"])
