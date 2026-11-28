"""Direct execution contracts from specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial

import httpx
import pytest
from fastmcp.tools import ToolResult

from ark_mcp.domain.errors import ProviderError
from ark_mcp.execution import (
    before_provider_request,
    record_accepted_receipt,
    run_direct_call,
)
from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.providers.seed_speech.client import SeedSpeechGateway
from ark_mcp.security.credentials import request_credentials_scope
from ark_mcp.sqlite_io import drain_task


def deadline_text(result: object, *, ambiguous: bool) -> str:
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert result.structured_content is None
    text = " ".join(block.text for block in result.content if block.type == "text")
    assert "TOOL_DEADLINE_EXCEEDED" in text
    assert f"ambiguous_completion={ambiguous}" in text
    return text


async def test_success_is_returned_unchanged_and_unscoped_dispatch_is_supported() -> None:
    value = object()

    async def call() -> object:
        before_provider_request()
        return value

    assert await run_direct_call(call, timeout_seconds=1, read_only=False) is value
    before_provider_request()
    record_accepted_receipt("unscoped-task", None)


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan")])
async def test_invalid_deadline_rejects_before_handler_entry(timeout_seconds: float) -> None:
    entered = False

    async def call() -> None:
        nonlocal entered
        entered = True

    with pytest.raises(ValueError, match="finite and positive"):
        await run_direct_call(call, timeout_seconds=timeout_seconds, read_only=False)
    assert not entered


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("side_effect", [None, False, True])
async def test_deadline_tracks_actual_dispatch_not_root_annotations(
    read_only: bool, side_effect: bool | None
) -> None:
    async def call() -> None:
        if side_effect is not None:
            before_provider_request(side_effect=side_effect)
        await asyncio.Event().wait()

    result = await run_direct_call(call, timeout_seconds=0.01, read_only=read_only)
    text = deadline_text(result, ambiguous=side_effect is True)
    if side_effect is None:
        assert "did not dispatch" in text
    if side_effect is True:
        assert "Do not" in text


async def test_inner_provider_timeout_remains_a_provider_error() -> None:
    original = ModelArkGateway.normalize_timeout("create_task")

    async def call() -> None:
        before_provider_request()
        raise original

    with pytest.raises(ProviderError) as raised:
        await run_direct_call(call, timeout_seconds=1, read_only=False)
    assert raised.value is original


async def test_inner_timeout_error_is_not_relabelled_as_our_deadline() -> None:
    async def call() -> None:
        async with asyncio.timeout(0.01):
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await run_direct_call(call, timeout_seconds=1, read_only=True)


@pytest.mark.parametrize("external_cancel", [False, True])
async def test_own_deadline_and_external_cancel_race_preserves_client_cancellation(
    external_cancel: bool,
) -> None:
    finalizing = asyncio.Event()
    release = asyncio.Event()

    async def cleanup() -> None:
        finalizing.set()
        await release.wait()

    async def call() -> None:
        before_provider_request()
        try:
            await asyncio.Event().wait()
        finally:
            await drain_task(asyncio.create_task(cleanup()))

    pending = asyncio.create_task(run_direct_call(call, timeout_seconds=0.01, read_only=False))
    try:
        await asyncio.wait_for(finalizing.wait(), 1)
        if external_cancel:
            pending.cancel("client disconnected")
            await asyncio.sleep(0)
            pending.cancel("client disconnected again")
        assert not pending.done()
    finally:
        release.set()
    if external_cancel:
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        deadline_text(await pending, ambiguous=True)


@pytest.mark.parametrize("suppress_cancel", [False, True])
async def test_external_cancellation_never_becomes_deadline_or_success(
    suppress_cancel: bool,
) -> None:
    entered = asyncio.Event()

    async def call() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not suppress_cancel:
                raise
        return "must not be delivered"

    pending = asyncio.create_task(run_direct_call(call, timeout_seconds=1, read_only=True))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.parametrize("dispatch_after", [False, True])
async def test_suppressed_deadline_cannot_dispatch_or_return_success(dispatch_after: bool) -> None:
    dispatched = False

    async def call() -> str:
        nonlocal dispatched
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if dispatch_after:
                before_provider_request()
                dispatched = True
        return "late success"

    result = await run_direct_call(call, timeout_seconds=0.01, read_only=False)
    deadline_text(result, ambiguous=False)
    assert not dispatched


async def test_expiry_before_timeout_callback_prevents_dispatch() -> None:
    dispatched = False

    async def call() -> None:
        nonlocal dispatched
        time.sleep(0.02)
        before_provider_request()
        dispatched = True

    deadline_text(
        await run_direct_call(call, timeout_seconds=0.005, read_only=False), ambiguous=False
    )
    assert not dispatched


async def test_children_share_safe_bounded_receipts_and_invocations_are_isolated() -> None:
    async def child(index: int) -> None:
        before_provider_request()
        record_accepted_receipt(f"task-{index}", f"request-{index}")
        record_accepted_receipt(f"task-{index}", f"request-{index}")

    async def call() -> None:
        await asyncio.gather(*(child(index) for index in range(20)))
        record_accepted_receipt("https://private.invalid/?credential=secret", None)
        record_accepted_receipt("task\nunsafe", None)
        record_accepted_receipt("x" * 257, None)
        await asyncio.Event().wait()

    text = deadline_text(
        await run_direct_call(call, timeout_seconds=0.02, read_only=False), ambiguous=True
    )
    assert text.count("task_id=") == 5
    assert "task-0" in text and "request-0" in text
    assert "private.invalid" not in text and "unsafe" not in text
    assert len(text) < 4000
    result = await run_direct_call(asyncio.Event().wait, timeout_seconds=0.01, read_only=True)
    assert "task-0" not in deadline_text(result, ambiguous=False)


async def test_live_request_credentials_are_never_captured_as_receipts() -> None:
    async def call() -> None:
        before_provider_request()
        record_accepted_receipt("task-synthetic-private-key", "req-safe")
        record_accepted_receipt("task-safe", "req-synthetic-private-key")
        await asyncio.Event().wait()

    with request_credentials_scope([(b"x-modelark-api-key", b"synthetic-private-key")]):
        result = await run_direct_call(call, timeout_seconds=0.01, read_only=False)
    text = deadline_text(result, ambiguous=True)
    assert "synthetic-private-key" not in text


async def test_file_receipts_are_reported_separately_and_bounded() -> None:
    async def child(index: int) -> None:
        before_provider_request()
        record_accepted_receipt(f"file-{index}", f"request-{index}", resource="file")
        record_accepted_receipt(f"file-{index}", f"request-{index}", resource="file")

    async def call() -> None:
        before_provider_request()
        for invalid in (
            "",
            "x" * 257,
            "unsafe\nfile",
            "https://private.invalid/",
            "file-private-key",
        ):
            record_accepted_receipt(invalid, None, resource="file")
        record_accepted_receipt("f" * 256, "r" * 256, resource="file")
        await asyncio.gather(*(child(index) for index in range(20)))
        await asyncio.Event().wait()

    with request_credentials_scope([(b"x-modelark-api-key", b"private-key")]):
        result = await run_direct_call(call, timeout_seconds=0.02, read_only=False)
    text = deadline_text(result, ambiguous=True)
    assert "Known accepted files" in text
    assert text.count("request_id=") == 5
    assert "file_id=" + "f" * 256 in text
    assert "request_id=request-0" in text
    assert "request_id=request-4" not in text
    assert "private" not in text and "unsafe" not in text
    assert "task_id=" not in text and "Known accepted tasks" not in text
    assert len(text) < 1500


async def test_inherited_context_cannot_dispatch_after_root_finishes() -> None:
    release = asyncio.Event()
    child: asyncio.Task[None] | None = None
    dispatched = False

    async def later() -> None:
        nonlocal dispatched
        await release.wait()
        before_provider_request()
        dispatched = True

    async def call() -> None:
        nonlocal child
        child = asyncio.create_task(later())

    await run_direct_call(call, timeout_seconds=1, read_only=False)
    assert child is not None
    release.set()
    result = await asyncio.gather(child, return_exceptions=True)
    assert isinstance(result[0], BaseException)
    assert not dispatched


@pytest.mark.parametrize(
    "operation",
    ["modelark-get", "modelark-post", "modelark-delete", "speech"],
)
async def test_http_gateways_mark_semantic_mutations(
    operation: str,
) -> None:
    received = asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        received.set()
        await asyncio.Event().wait()
        return httpx.Response(200)

    gateway: ModelArkGateway | SeedSpeechGateway
    call: Callable[[], Awaitable[object]]
    if operation.startswith("modelark"):
        gateway = modelark = ModelArkGateway(api_key="synthetic-key")
        if operation == "modelark-get":
            call = partial(modelark.get, "/tasks")
        elif operation == "modelark-post":
            call = partial(modelark.post, "/tasks", {})
        else:
            call = partial(modelark.delete, "/tasks/task-1")
    else:
        gateway = speech = SeedSpeechGateway(api_key="synthetic-key")
        call = partial(speech.post, "/audio", {})
    gateway._client = httpx.AsyncClient(transport=httpx.MockTransport(blocked))
    try:
        result = await run_direct_call(call, timeout_seconds=0.02, read_only=False)
        assert received.is_set()
        deadline_text(result, ambiguous=operation not in {"modelark-get"})
    finally:
        await gateway.close()


async def test_modelark_read_does_not_wait_for_saturated_generation_slots() -> None:
    from ark_mcp.runtime import ProviderLimiters
    from ark_mcp.security.auth_context import AuthContext

    limiters = ProviderLimiters(provider_limit=1)
    gateway = ModelArkGateway(api_key="synthetic-key")
    gateway._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []})),
    )
    try:
        async with limiters.acquire("modelark", AuthContext()):
            response = await run_direct_call(
                partial(gateway.get, "/tasks"),
                timeout_seconds=0.1,
                read_only=True,
            )
            assert response.status_code == 200
    finally:
        await gateway.close()
