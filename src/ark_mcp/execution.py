"""Cooperative direct calls from specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

import asyncio
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastmcp.tools import ToolResult

from ark_mcp.observability.metrics import TOOL_DEADLINES
from ark_mcp.security.credentials import redact_request_secrets
from ark_mcp.submission_store import IDENTIFIER_PATTERN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(slots=True)
class _DirectExecution:
    deadline: float
    active: bool = True
    request_started: bool = False
    side_effect_started: bool = False
    receipts: dict[str, str | None] = field(default_factory=dict)


class _DispatchExpired(BaseException):
    """Stop dispatch without being swallowed by provider exception normalization."""


_current: ContextVar[_DirectExecution | None] = ContextVar("direct_execution", default=None)
_MAX_RECEIPTS = 5


def before_provider_request(*, side_effect: bool = True) -> None:
    """Reject expired/cancelled calls and mark actual dispatch, not tool annotations."""
    current = _current.get()
    if current is None:
        return
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError
    if not current.active or asyncio.get_running_loop().time() >= current.deadline:
        raise _DispatchExpired
    current.request_started = True
    current.side_effect_started |= side_effect


def record_accepted_receipt(task_id: str, request_id: str | None) -> None:
    """Retain bounded safe IDs in the live call, shared by its variation children."""
    current = _current.get()
    if current is None or not current.active:
        return
    if not isinstance(task_id, str) or not re.fullmatch(IDENTIFIER_PATTERN, task_id):
        return
    if redact_request_secrets(task_id) != task_id:
        return
    if request_id is not None and (
        not isinstance(request_id, str)
        or not re.fullmatch(IDENTIFIER_PATTERN, request_id)
        or redact_request_secrets(request_id) != request_id
    ):
        request_id = None
    if task_id not in current.receipts and len(current.receipts) >= _MAX_RECEIPTS:
        return
    if current.receipts.get(task_id) is None:
        current.receipts[task_id] = request_id


def _deadline_result(current: _DirectExecution) -> ToolResult:
    TOOL_DEADLINES.labels(
        dispatch=(
            "mutation"
            if current.side_effect_started
            else "read"
            if current.request_started
            else "none"
        )
    ).inc()
    if current.side_effect_started:
        message = (
            "A provider mutation may have started; its outcome is uncertain. "
            "This deadline does not cancel accepted upstream work. "
            "Do not regenerate blindly; reconcile the original attempt."
        )
    elif current.request_started:
        message = "Only read-only provider requests started; no provider mutation was dispatched."
    else:
        message = "This attempt did not dispatch a provider request."
    if current.receipts:
        message += " Known accepted tasks: " + "; ".join(
            f"task_id={task_id}" + (f", request_id={request_id}" if request_id else "")
            for task_id, request_id in current.receipts.items()
        )
        message += ". Poll only where ownership is recorded; otherwise reconcile with the provider."
    return ToolResult(
        content=(
            f"TOOL_DEADLINE_EXCEEDED: {message} "
            f"[ambiguous_completion={current.side_effect_started}]"
        ),
        is_error=True,
    )


async def run_direct_call(
    call: Callable[[], Awaitable[Any]], *, timeout_seconds: float, read_only: bool
) -> Any:
    """Apply our cooperative deadline; preserve external cancellation and provider errors."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Tool timeout must be finite and positive.")
    current = _DirectExecution(deadline=asyncio.get_running_loop().time() + timeout_seconds)
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Direct execution requires an asyncio task.")
    initial_cancels = task.cancelling()
    token = _current.set(current)
    timeout = asyncio.timeout_at(current.deadline)
    try:
        try:
            async with timeout:
                result = await call()
        except TimeoutError:
            if not timeout.expired():
                raise
        except _DispatchExpired:
            pass
        else:
            if task.cancelling() > initial_cancels:
                raise asyncio.CancelledError
            if asyncio.get_running_loop().time() < current.deadline:
                return result
        if task.cancelling() > initial_cancels:
            raise asyncio.CancelledError
        return _deadline_result(current)
    finally:
        current.active = False
        current.receipts.clear()
        _current.reset(token)
