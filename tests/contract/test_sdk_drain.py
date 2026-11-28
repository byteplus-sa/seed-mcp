"""Blocking SDK lifetime contracts from specs/SPEC_DIRECT_EXECUTION.md."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from ark_mcp.providers.s3.client import S3Gateway
from ark_mcp.runtime import ProviderLimiters
from ark_mcp.security.auth_context import AuthContext


class BlockedSdk:
    def __init__(self, *, fails: bool = False) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.closed = threading.Event()
        self.calls = 0
        self.fails = fails

    def put_object(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.started.set()
        try:
            assert self.release.wait(5)
            assert not self.close_started.is_set()
            if self.fails:
                raise RuntimeError("synthetic SDK failure")
            return {}
        finally:
            self.finished.set()

    upload_file = put_object
    put_object_from_file = put_object

    def close(self) -> None:
        assert self.finished.is_set()
        self.close_started.set()
        assert self.close_release.wait(5)
        self.closed.set()


@pytest.mark.parametrize("gateway_type", [S3Gateway])
@pytest.mark.parametrize("file_upload", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_sdk_upload_holds_provider_slot_until_thread_finishes(
    gateway_type: type[S3Gateway], file_upload: bool, fails: bool
) -> None:
    sdk = BlockedSdk(fails=fails)
    gateway = gateway_type(client=sdk, bucket="synthetic-bucket")
    limiters = ProviderLimiters(provider_limit=1)
    second_entered = asyncio.Event()
    provider = "s3"

    async def upload() -> None:
        async with limiters.acquire(provider, AuthContext()):
            if file_upload:
                await gateway.upload_file(
                    key="one", file_path="/synthetic/file", mime_type="text/plain"
                )
            else:
                await gateway.upload_bytes(key="one", data=b"synthetic", mime_type="text/plain")

    async def second_upload() -> None:
        async with limiters.acquire(provider, AuthContext()):
            second_entered.set()
            await gateway.upload_bytes(key="two", data=b"synthetic", mime_type="text/plain")

    first = asyncio.create_task(upload())
    second: asyncio.Task[None] | None = None
    try:
        assert await asyncio.to_thread(sdk.started.wait, 1)
        first.cancel()
        second = asyncio.create_task(second_upload())
        await asyncio.sleep(0)
        first.cancel()
        completed, _ = await asyncio.wait({first, second}, timeout=0.02)
        assert not completed
        assert not second_entered.is_set()
        assert sdk.calls == 1
    finally:
        sdk.release.set()
        sdk.close_release.set()
        results = await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        await gateway.close()
    assert isinstance(results[0], asyncio.CancelledError)
    assert second_entered.is_set()
    assert sdk.calls == 2
    assert sdk.closed.is_set()


@pytest.mark.parametrize("gateway_type", [S3Gateway])
async def test_cancelled_sdk_close_drains_upload_and_close_through_repeated_cancellation(
    gateway_type: type[S3Gateway],
) -> None:
    sdk = BlockedSdk()
    gateway = gateway_type(client=sdk, bucket="synthetic-bucket")
    upload = asyncio.create_task(
        gateway.upload_bytes(key="one", data=b"synthetic", mime_type="text/plain")
    )
    close: asyncio.Task[None] | None = None
    try:
        assert await asyncio.to_thread(sdk.started.wait, 1)
        upload.cancel()
        close = asyncio.create_task(gateway.close())
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        close.cancel()
        completed, _ = await asyncio.wait({upload, close}, timeout=0.02)
        assert not completed
        assert not sdk.close_started.is_set()
        sdk.release.set()
        assert await asyncio.to_thread(sdk.close_started.wait, 1)
        close.cancel()
        await asyncio.sleep(0)
        assert not close.done()
        assert not sdk.closed.is_set()
    finally:
        sdk.release.set()
        sdk.close_release.set()
        results = await asyncio.gather(upload, *([close] if close else []), return_exceptions=True)
        await gateway.close()
    assert isinstance(results[0], asyncio.CancelledError)
    assert isinstance(results[1], asyncio.CancelledError)
    assert sdk.closed.is_set()


@pytest.mark.parametrize("gateway_type", [S3Gateway])
async def test_presign_is_not_a_provider_mutation(
    gateway_type: type[S3Gateway],
) -> None:
    from ark_mcp.execution import run_direct_call
    from tests.unit.test_direct_execution import deadline_text

    sdk = SimpleNamespace(
        generate_presigned_url=lambda *args, **kwargs: "https://synthetic.invalid/object",
        pre_signed_url=lambda *args, **kwargs: "https://synthetic.invalid/object",
    )
    gateway = gateway_type(client=sdk, bucket="synthetic-bucket")

    async def call() -> None:
        assert await gateway.presign_get(key="one") == "https://synthetic.invalid/object"
        await asyncio.Event().wait()

    try:
        deadline_text(
            await run_direct_call(call, timeout_seconds=0.02, read_only=False), ambiguous=False
        )
    finally:
        await gateway.close()


@pytest.mark.parametrize("gateway_type", [S3Gateway])
async def test_sdk_deadline_is_cooperative_and_reports_mutation_uncertainty(
    gateway_type: type[S3Gateway],
) -> None:
    from ark_mcp.execution import run_direct_call
    from tests.unit.test_direct_execution import deadline_text

    sdk = BlockedSdk()
    gateway = gateway_type(client=sdk, bucket="synthetic-bucket")

    async def call() -> None:
        await gateway.upload_bytes(key="one", data=b"synthetic", mime_type="text/plain")

    pending = asyncio.create_task(run_direct_call(call, timeout_seconds=0.03, read_only=True))
    try:
        assert await asyncio.to_thread(sdk.started.wait, 1)
        completed, _ = await asyncio.wait({pending}, timeout=0.05)
        assert not completed
        assert not sdk.finished.is_set()
    finally:
        sdk.release.set()
        sdk.close_release.set()
        results = await asyncio.gather(pending, return_exceptions=True)
        await gateway.close()
    deadline_text(results[0], ambiguous=True)
    assert sdk.closed.is_set()


@pytest.mark.parametrize("gateway_type", [S3Gateway])
async def test_expired_execution_cannot_schedule_sdk_upload(
    gateway_type: type[S3Gateway],
) -> None:
    import time

    from ark_mcp.execution import run_direct_call
    from tests.unit.test_direct_execution import deadline_text

    calls: list[object] = []
    sdk = SimpleNamespace(put_object=lambda **kwargs: calls.append(kwargs))
    gateway = gateway_type(client=sdk, bucket="synthetic-bucket")

    async def call() -> None:
        time.sleep(0.01)
        await gateway.upload_bytes(key="one", data=b"synthetic", mime_type="text/plain")

    try:
        deadline_text(
            await run_direct_call(call, timeout_seconds=0.001, read_only=False),
            ambiguous=False,
        )
        assert calls == []
    finally:
        await gateway.close()
