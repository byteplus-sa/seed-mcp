"""HTTP asynchronous-create safety for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastmcp.tools import ToolResult

from ark_mcp.config.model_capabilities import get_capability_registry
from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
from ark_mcp.observability.logger import error as log_error
from ark_mcp.runtime import get_principal, get_runtime
from ark_mcp.security.credentials import redact_request_secrets, submission_fingerprints
from ark_mcp.submission_store import (
    IDENTIFIER_PATTERN,
    SQLiteSubmissionStore,
    SubmissionConflictError,
    SubmissionRecord,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import Context
    from pydantic import BaseModel

CREATE_PROVIDERS = {
    "seedance_create_task": "modelark",
    "omnihuman_create_task": "vision-cv",
}


@dataclass(slots=True)
class _SubmissionContext:
    store: SQLiteSubmissionStore
    submission_id: str
    provider: str
    tenant_id: str
    principal_id: str
    active: bool = True


_current: ContextVar[_SubmissionContext | None] = ContextVar("http_submission", default=None)


def _contains_secret(ctx: Context, text: str) -> bool:
    hmac_key = get_runtime(ctx).settings.identity_hmac_key.get_secret_value()
    return redact_request_secrets(text) != text or bool(hmac_key and hmac_key in text)


def validate_receipt_identifiers(
    ctx: Context, provider: str, task_id: str, request_id: str | None
) -> None:
    """Refuse unsafe provider identifiers before either HTTP persistence write."""
    if get_runtime(ctx).settings.mcp_transport != "http":
        return
    for value in (task_id, request_id):
        if value is None:
            continue
        if not re.fullmatch(IDENTIFIER_PATTERN, value) or _contains_secret(ctx, value):
            raise ProviderError(
                NormalizedProviderError(
                    provider="modelark" if provider == "modelark" else "byteplus-vision-cv",
                    operation="create_task",
                    code="UNSAFE_TASK_RECEIPT",
                    message=(
                        "The provider may have accepted the task but returned an unsafe "
                        "identifier. No identifier was persisted. Do not resubmit; "
                        "reconcile through the provider."
                    ),
                    retryable=False,
                    ambiguous_completion=True,
                )
            )


async def record_submission_task(
    ctx: Context, provider: str, task_id: str, request_id: str | None
) -> None:
    """Record a safe accepted ID while the originating HTTP invocation is live."""
    current = _current.get()
    owner = get_principal(ctx)
    if (
        current is None
        or not current.active
        or current.provider != provider
        or current.tenant_id != owner.tenant_id
        or current.principal_id != owner.principal_id
    ):
        raise RuntimeError("Live submission context is unavailable.")
    await current.store.record_task(current.submission_id, task_id, request_id)


def _canonical_input(tool_name: str, request: BaseModel) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    if tool_name == "seedance_create_task" and payload.get("model") is None:
        payload["model"] = (
            {"inherit_from_draft": payload["draft_task_id"]}
            if payload.get("draft_task_id")
            else get_capability_registry().resolve_video_model(None).model_id
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _error(code: str, message: str, record: SubmissionRecord | None = None) -> ToolResult:
    known = ""
    if record is not None and record.tasks:
        known = " Known accepted tasks: " + "; ".join(
            f"task_id={task_id}" + (f", request_id={request_id}" if request_id else "")
            for task_id, request_id in record.tasks
        )
        known += ". Poll only where ownership remains recorded; otherwise use the provider."
    return ToolResult(content=f"{code}: {message}{known}", is_error=True)


def _success_payload(
    ctx: Context, tool_name: str, request: BaseModel, result: Any, record: SubmissionRecord
) -> dict[str, Any] | None:
    from ark_mcp.tools.omnihuman_create_task import OmniHumanCreateTaskOutput
    from ark_mcp.tools.seedance_create_task import SeedanceCreateTaskOutput

    if tool_name == "seedance_create_task":
        if not isinstance(result, SeedanceCreateTaskOutput):
            return None
        count = getattr(request, "variations", 1)
        tasks = result.tasks
        if (
            result.dry_run
            or result.preview is not None
            or len(tasks) != count
            or result.submitted != count
            or result.failed != 0
            or any(task.error is not None or not task.task_id for task in tasks)
            or [task.index for task in tasks] != list(range(count))
            or len({task.task_id for task in tasks}) != count
            or {(task.task_id, task.request_id) for task in tasks} != set(record.tasks)
            or len(record.tasks) != count
        ):
            return None
        for value in (result.model, result.family):
            if not re.fullmatch(IDENTIFIER_PATTERN, value) or _contains_secret(ctx, value):
                return None
        payload = result.model_dump(mode="json")
    else:
        if not isinstance(result, OmniHumanCreateTaskOutput):
            return None
        if record.tasks != ((result.task_id, result.request_id),):
            return None
        payload = result.model_dump(mode="json")
    for task_id, request_id in record.tasks:
        validate_receipt_identifiers(ctx, CREATE_PROVIDERS[tool_name], task_id, request_id)
    if _contains_secret(ctx, json.dumps(payload)):
        return None
    return payload


async def _replay(
    ctx: Context, tool_name: str, request: BaseModel, record: SubmissionRecord
) -> ToolResult:
    if record.state != "succeeded" or record.response_json is None:
        code = "SUBMISSION_IN_PROGRESS" if record.state == "running" else "SUBMISSION_UNRESOLVED"
        return _error(
            code,
            "This key already identifies an in-progress or unresolved attempt. "
            "No new work was submitted. Do not change keys to bypass uncertain acceptance; "
            "reconcile the original attempt.",
            record,
        )
    from ark_mcp.tools.omnihuman_create_task import OmniHumanCreateTaskOutput
    from ark_mcp.tools.seedance_create_task import SeedanceCreateTaskOutput

    try:
        model = (
            SeedanceCreateTaskOutput
            if tool_name == "seedance_create_task"
            else OmniHumanCreateTaskOutput
        )
        result = model.model_validate_json(record.response_json)
        payload = _success_payload(ctx, tool_name, request, result, record)
        if payload is None:
            raise ValueError("Invalid saved receipt.")
        runtime = get_runtime(ctx)
        owner = get_principal(ctx)
        for task_id, _ in record.tasks:
            await runtime.ownership_store.require_owner(CREATE_PROVIDERS[tool_name], task_id, owner)
        return ToolResult(structured_content=payload)
    except Exception:
        return _error(
            "SUBMISSION_UNRESOLVED",
            "The saved receipt or its ownership is unavailable. No new work was submitted. "
            "Do not resubmit; reconcile the original task.",
            record,
        )


async def _unresolved(store: SQLiteSubmissionStore, submission_id: str) -> None:
    try:
        await asyncio.shield(store.mark_unresolved(submission_id))
    except Exception:
        log_error("submission_finalization_failed", action="mark_unresolved")


async def execute_submission(
    ctx: Context, tool_name: str, request: BaseModel, call: Callable[[], Awaitable[Any]]
) -> Any:
    """Claim a whole HTTP create once; only fully successful receipts are replayed."""
    if tool_name not in CREATE_PROVIDERS or getattr(request, "dry_run", False):
        return await call()
    key = getattr(request, "idempotency_key", None)
    if key is None:
        return _error(
            "IDEMPOTENCY_KEY_REQUIRED",
            "HTTP creation requires idempotency_key: use a fresh UUID per intended operation "
            "and reuse it with identical arguments only for delivery retries.",
        )
    runtime = get_runtime(ctx)
    store = runtime.submission_store
    if store is None:
        return _error(
            "SUBMISSION_UNAVAILABLE", "Submission state is unavailable; nothing submitted."
        )
    owner = get_principal(ctx)
    key_digest, request_digest = submission_fingerprints(
        runtime.settings, tool_name, key, _canonical_input(tool_name, request)
    )
    try:
        record, claimed = await store.claim(
            provider=CREATE_PROVIDERS[tool_name],
            tenant_id=owner.tenant_id,
            principal_id=owner.principal_id,
            tool_name=tool_name,
            key_digest=key_digest,
            request_digest=request_digest,
        )
    except SubmissionConflictError:
        return _error(
            "SUBMISSION_CONFLICT",
            "This key was already used with different arguments. No new work was submitted. "
            "Use the original arguments to recover the original operation.",
        )
    except Exception:
        return _error(
            "SUBMISSION_UNAVAILABLE",
            "Submission state is unavailable or full. No provider call was made.",
        )
    if not claimed:
        return await _replay(ctx, tool_name, request, record)
    context = _SubmissionContext(
        store,
        record.submission_id,
        CREATE_PROVIDERS[tool_name],
        owner.tenant_id,
        owner.principal_id,
    )
    token = _current.set(context)
    try:
        result = await call()
        try:
            recorded = await store.get(record.submission_id)
            payload = _success_payload(ctx, tool_name, request, result, recorded)
            if payload is None:
                await _unresolved(store, record.submission_id)
            else:
                await store.succeed(record.submission_id, json.dumps(payload, ensure_ascii=True))
        except Exception:
            log_error("submission_finalization_failed", action="save_receipt")
            await _unresolved(store, record.submission_id)
        return result
    except BaseException:
        await _unresolved(store, record.submission_id)
        raise
    finally:
        context.active = False
        _current.reset(token)
