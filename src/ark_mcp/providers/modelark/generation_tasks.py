"""ModelArk generation task reads for Seedance video.

Every asynchronous ModelArk generation task lives behind the same
``/contents/generations/tasks`` endpoints, so retrieval, listing and deletion
use one service across supported Seedance models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ark_mcp.domain.models import TaskUsage
from ark_mcp.observability.logger import debug as log_debug
from ark_mcp.providers.base import safe_provider_text
from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.providers.modelark.schemas import GenerationTaskListResponse, GenerationTaskResponse

TASKS_PATH = "/contents/generations/tasks"


class GenerationTaskService:
    """Retrieve, list and delete ModelArk generation tasks."""

    def __init__(self, gateway: ModelArkGateway) -> None:
        self._gateway = gateway

    async def get_task(self, task_id: str) -> tuple[GenerationTaskResponse, str | None]:
        """Call ``GET /contents/generations/tasks/{id}``; returns ``(task, request_id)``."""
        log_debug("generation_get_task", task_id=task_id)
        response = await self._send("get_task", "GET", f"{TASKS_PATH}/{task_id}", side_effect=False)
        request_id = ModelArkGateway.extract_request_id(response)
        parsed = ModelArkGateway.parse_response(
            response, "get_task", GenerationTaskResponse, side_effect=False
        )
        self._sanitize_task_error(parsed)
        log_debug(
            "generation_get_task_complete",
            task_id=task_id,
            status=parsed.status,
            request_id=request_id,
        )
        return parsed, request_id

    async def list_tasks(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        task_ids: list[str] | None = None,
        model: str | None = None,
    ) -> tuple[GenerationTaskListResponse, str | None]:
        """Call ``GET /contents/generations/tasks``; returns ``(page, request_id)``."""
        params: dict[str, Any] = {"page_num": page, "page_size": page_size}
        if status:
            params["filter.status"] = status
        if task_ids:
            params["filter.task_ids"] = task_ids
        if model:
            params["filter.model"] = model
        log_debug("generation_list_tasks", page=page, page_size=page_size)
        response = await self._send(
            "list_tasks", "GET", TASKS_PATH, side_effect=False, params=params
        )
        request_id = ModelArkGateway.extract_request_id(response)
        parsed = ModelArkGateway.parse_response(
            response, "list_tasks", GenerationTaskListResponse, side_effect=False
        )
        for task in parsed.data:
            self._sanitize_task_error(task)
        log_debug(
            "generation_list_tasks_complete",
            page=page,
            returned=len(parsed.data),
            request_id=request_id,
        )
        return parsed, request_id

    async def delete_task(self, task_id: str) -> str | None:
        """Call ``DELETE /contents/generations/tasks/{id}``; returns the request ID."""
        log_debug("generation_delete_task", task_id=task_id)
        response = await self._send("delete_task", "DELETE", f"{TASKS_PATH}/{task_id}")
        return ModelArkGateway.extract_request_id(response)

    async def _send(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        side_effect: bool = True,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            if method == "DELETE":
                response = await self._gateway.delete(path)
            else:
                response = await self._gateway.get(path, params=params)
        except httpx.TransportError as exc:
            raise ModelArkGateway.normalize_transport_error(
                operation, exc, side_effect=side_effect
            ) from None
        if response.status_code >= 400:
            raise ModelArkGateway.normalize_error(response, operation)
        return response

    @staticmethod
    def _sanitize_task_error(task: GenerationTaskResponse) -> None:
        if task.error is not None:
            task.error.code = safe_provider_text(task.error.code)
            task.error.message = safe_provider_text(task.error.message)

    async def close(self) -> None:
        await self._gateway.close()


def task_timestamp(raw: int | float | str | None) -> str:
    """Format a provider task timestamp (epoch seconds or ISO-8601) as ISO-8601."""
    if raw is None:
        return datetime.now(UTC).isoformat()
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC).isoformat()
    return str(raw)


def task_usage(task: GenerationTaskResponse) -> TaskUsage | None:
    """Return the task's reported token usage, if any."""
    if task.usage is None:
        return None
    return TaskUsage(
        prompt_tokens=task.usage.prompt_tokens,
        completion_tokens=task.usage.completion_tokens,
        total_tokens=task.usage.total_tokens,
    )
