"""Outcome preservation for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest
from fastmcp import Context

from ark_mcp.config.env import Settings
from ark_mcp.domain.errors import AcceptedTaskError, NormalizedProviderError, ProviderError
from ark_mcp.execution import authorize_provider_request, before_provider_request, run_direct_call
from ark_mcp.runtime import (
    BudgetExceededError,
    BudgetReservation,
    CostEstimate,
    billed_provider_slot,
    capture_accepted_task,
    close_runtime_services,
    create_runtime_services,
    get_principal,
    get_runtime,
    record_accepted_task,
)
from ark_mcp.security.auth_context import AuthContext
from ark_mcp.security.credentials import provider_scope, request_credentials_scope
from ark_mcp.sqlite_io import drain_task
from tests.fixtures.fake_context import FakeContext
from tests.unit.test_direct_execution import deadline_text

STORAGE_DETAIL = "synthetic-private-storage-detail"


@pytest.fixture
async def billed_context(tmp_path: Path) -> AsyncIterator[Context]:
    runtime = await create_runtime_services(
        Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path), DAILY_BUDGET_USD=0.10)
    )
    try:
        yield cast("Context", FakeContext(lifespan_context={"runtime": runtime}))
    finally:
        await close_runtime_services(runtime)


def assert_finalization_error(stderr: str, *, action: str, reservation_id: int) -> None:
    events = [
        json.loads(line)
        for line in stderr.splitlines()
        if line.startswith("{") and '"msg": "budget_finalization_failed"' in line
    ]
    assert len(events) == 1
    assert events[0] == {
        "ts": events[0]["ts"],
        "level": "ERROR",
        "msg": "budget_finalization_failed",
        "provider": "modelark",
        "action": action,
        "reservation_id": reservation_id,
    }
    assert STORAGE_DETAIL not in stderr


@pytest.mark.parametrize("outcome", ["success", "uncertain", "timeout", "rejected", "unexpected"])
@pytest.mark.parametrize("finalization_fails", [False, True])
async def test_billed_slot_preserves_original_outcome_and_budget_allowance(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
    finalization_fails: bool,
) -> None:
    runtime = get_runtime(billed_context)
    ledger = runtime.budget_ledger
    commit = AsyncMock(wraps=ledger.commit)
    release = AsyncMock(wraps=ledger.release)
    action = "commit" if outcome in {"success", "uncertain", "timeout"} else "release"
    finalizer = commit if action == "commit" else release
    if finalization_fails:
        finalizer.side_effect = RuntimeError(STORAGE_DETAIL)
    monkeypatch.setattr(ledger, "commit", commit)
    monkeypatch.setattr(ledger, "release", release)
    original: Exception | None = None
    if outcome == "unexpected":
        original = ValueError("Synthetic original failure")
    elif outcome != "success":
        original = ProviderError(
            NormalizedProviderError(
                provider="modelark",
                operation="generate",
                http_status=503 if outcome == "uncertain" else 400,
                code="TIMEOUT" if outcome == "timeout" else "SYNTHETIC_PROVIDER_CODE",
                message="Synthetic provider diagnostics",
                request_id="req-original",
                retryable=outcome != "rejected",
                ambiguous_completion=outcome == "uncertain",
                retry_after_seconds=2,
            )
        )
    original_payload = original.error.model_dump() if isinstance(original, ProviderError) else None
    provider_call = AsyncMock(return_value="https://example.com/output.png", side_effect=original)

    async def generate() -> str:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            return await provider_call()

    if original is None:
        assert await generate() == "https://example.com/output.png"
    else:
        with pytest.raises(type(original)) as raised:
            await generate()
        assert raised.value is original
        if isinstance(original, ProviderError):
            assert original.error.model_dump() == original_payload
    provider_call.assert_awaited_once()
    finalizer.assert_awaited_once()
    (release if action == "commit" else commit).assert_not_awaited()
    reservation = finalizer.await_args.args[0]
    status = ledger._connection.execute(
        "SELECT status FROM budget_reservations WHERE id = ?", (reservation.reservation_id,)
    ).fetchone()[0]
    expected_status = "committed" if action == "commit" else "released"
    assert status == ("reserved" if finalization_fails else expected_status)
    if finalization_fails or action == "commit":
        with pytest.raises(BudgetExceededError):
            await ledger.reserve(get_principal(billed_context), CostEstimate("image", 0.08))
    else:
        await ledger.reserve(get_principal(billed_context), CostEstimate("image", 0.08))
    stderr = capsys.readouterr().err
    if finalization_fails:
        assert_finalization_error(stderr, action=action, reservation_id=reservation.reservation_id)
    else:
        assert "budget_finalization_failed" not in stderr


async def test_billed_slot_reservation_failure_blocks_dispatch(
    billed_context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = get_runtime(billed_context).budget_ledger
    original = RuntimeError("Synthetic reserve failure")
    monkeypatch.setattr(ledger, "reserve", AsyncMock(side_effect=original))
    commit = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(ledger, "commit", commit)
    monkeypatch.setattr(ledger, "release", release)
    provider_call = AsyncMock()
    with pytest.raises(RuntimeError) as raised:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            await provider_call()
    assert raised.value is original
    provider_call.assert_not_awaited()
    commit.assert_not_awaited()
    release.assert_not_awaited()


async def test_saturated_admission_does_not_reserve_budget(
    billed_context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = get_runtime(billed_context)
    reserve = AsyncMock(wraps=runtime.budget_ledger.reserve)
    monkeypatch.setattr(runtime.budget_ledger, "reserve", reserve)
    limiter = runtime.provider_limiters.provider("modelark")
    for _ in range(runtime.settings.provider_max_concurrency):
        await limiter.acquire()

    async def call() -> None:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            pytest.fail("Saturated provider cannot dispatch")

    pending = asyncio.create_task(call())
    try:
        completed, _ = await asyncio.wait({pending}, timeout=0.02)
        assert not completed
        reserve.assert_not_awaited()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        for _ in range(runtime.settings.provider_max_concurrency):
            limiter.release()


@pytest.mark.parametrize("reserve_fails", [False, True])
@pytest.mark.parametrize("release_fails", [False, True])
async def test_cancelled_reservation_recovers_result_and_drains_release_without_dispatch(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reserve_fails: bool,
    release_fails: bool,
) -> None:
    runtime = get_runtime(billed_context)
    ledger = runtime.budget_ledger
    reserve_started = asyncio.Event()
    finish_reserve = asyncio.Event()
    release_started = asyncio.Event()
    finish_release = asyncio.Event()
    original_reserve, original_release = ledger.reserve, ledger.release
    provider_call = AsyncMock()

    async def reserve(owner: AuthContext, estimate: CostEstimate) -> BudgetReservation:
        reservation = None if reserve_fails else await original_reserve(owner, estimate)
        reserve_started.set()
        await finish_reserve.wait()
        if reservation is None:
            raise RuntimeError(STORAGE_DETAIL)
        return reservation

    async def release(reservation: BudgetReservation) -> None:
        release_started.set()
        await finish_release.wait()
        if release_fails:
            raise RuntimeError(STORAGE_DETAIL)
        await original_release(reservation)

    monkeypatch.setattr(ledger, "reserve", reserve)
    monkeypatch.setattr(ledger, "release", release)

    async def call() -> None:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            await provider_call()

    pending = asyncio.create_task(call())
    try:
        await asyncio.wait_for(reserve_started.wait(), 1)
        pending.cancel("original cancellation")
        await asyncio.sleep(0)
        pending.cancel("repeated cancellation")
        completed, _ = await asyncio.wait({pending}, timeout=0.02)
        assert not completed
        finish_reserve.set()
        if not reserve_fails:
            await asyncio.wait_for(release_started.wait(), 1)
            pending.cancel("cancel during release")
            completed, _ = await asyncio.wait({pending}, timeout=0.02)
            assert not completed
    finally:
        finish_reserve.set()
        finish_release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    provider_call.assert_not_awaited()
    rows = ledger._connection.execute("SELECT status FROM budget_reservations").fetchall()
    assert rows == ([] if reserve_fails else [("reserved" if release_fails else "released",)])
    assert STORAGE_DETAIL not in capsys.readouterr().err


@pytest.mark.parametrize("dispatched", [False, True])
@pytest.mark.parametrize("finalization_fails", [False, True])
@pytest.mark.parametrize("cancel_again", [False, True])
async def test_billed_slot_cancellation_cleanup_is_shielded_and_logged(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    dispatched: bool,
    finalization_fails: bool,
    cancel_again: bool,
) -> None:
    runtime = get_runtime(billed_context)
    ledger = runtime.budget_ledger
    ready = asyncio.Event()
    finish_reserve = asyncio.Event()
    finalizing = asyncio.Event()
    finish_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()
    action = "commit" if dispatched else "release"
    finalizer = getattr(ledger, action)
    reserve = ledger.reserve

    async def reserve_then_signal(owner: AuthContext, estimate: CostEstimate) -> BudgetReservation:
        reservation = await reserve(owner, estimate)
        if not dispatched:
            ready.set()
            await finish_reserve.wait()
        return reservation

    async def finalize(reservation: BudgetReservation) -> None:
        finalizing.set()
        try:
            await finish_cleanup.wait()
            if finalization_fails:
                raise RuntimeError(STORAGE_DETAIL)
            await finalizer(reservation)
        finally:
            cleanup_finished.set()

    monkeypatch.setattr(ledger, "reserve", reserve_then_signal)
    cleanup = AsyncMock(side_effect=finalize)
    monkeypatch.setattr(ledger, action, cleanup)
    other_action = AsyncMock()
    monkeypatch.setattr(ledger, "release" if dispatched else "commit", other_action)
    provider_call = AsyncMock()

    async def generate() -> None:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            before_provider_request()
            await provider_call()
            ready.set()
            await asyncio.Event().wait()

    pending = asyncio.create_task(generate())
    try:
        await asyncio.wait_for(ready.wait(), 2)
        pending.cancel()
        finish_reserve.set()
        await asyncio.wait_for(finalizing.wait(), 2)
        if cancel_again:
            pending.cancel()
            completed, _ = await asyncio.wait({pending}, timeout=0.02)
            assert not completed
            assert not cleanup_finished.is_set()
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(cleanup_finished.wait(), 2)
        cleanup.assert_awaited_once()
        other_action.assert_not_awaited()
        assert provider_call.await_count == int(dispatched)
        reservation = cleanup.await_args.args[0]
        stderr = capsys.readouterr().err
        if finalization_fails:
            assert_finalization_error(
                stderr, action=action, reservation_id=reservation.reservation_id
            )
        else:
            assert "budget_finalization_failed" not in stderr
        assert STORAGE_DETAIL not in caplog.text
        assert "Task exception was never retrieved" not in caplog.text
    finally:
        finish_reserve.set()
        finish_cleanup.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if finalizing.is_set():
            await asyncio.wait_for(cleanup_finished.wait(), 2)


@pytest.mark.parametrize("provider", ["modelark"])
async def test_record_accepted_task_retains_id_with_safe_outward_text(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: Literal["modelark"],
) -> None:
    record = AsyncMock(side_effect=RuntimeError(STORAGE_DETAIL))
    monkeypatch.setattr(get_runtime(billed_context).ownership_store, "record", record)
    task_id = "accepted-synthetic-private-key https://example.com/private?token=private"
    with (
        request_credentials_scope(
            [(b"x-modelark-api-key", b"synthetic-private-key"), (b"x-mcp-client-secret", b"b" * 64)]
        ),
        pytest.raises(AcceptedTaskError) as raised,
    ):
        await record_accepted_task(billed_context, provider, task_id, None)
    error = raised.value
    assert error.task_id == task_id
    assert error.request_id is None
    assert error.code == "OWNERSHIP_RECORD_FAILED"
    assert error.retryable is False
    assert error.ambiguous_completion is True
    assert "task_id=accepted-" in error.message
    assert "synthetic-private-key" not in error.message
    assert "https://" not in error.message
    assert STORAGE_DETAIL not in error.message
    assert "do not resubmit" in error.message.lower()
    logs = capsys.readouterr().err
    assert task_id not in logs
    assert STORAGE_DETAIL not in logs


@pytest.mark.parametrize(
    ("transport", "stage"),
    [
        ("stdio", "commit"),
        ("stdio", "ownership"),
    ],
)
@pytest.mark.parametrize("external_cancel", [False, True])
async def test_accepted_receipts_survive_deadline_during_partial_batch_bookkeeping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
    stage: str,
    external_cancel: bool,
) -> None:
    settings = Settings(
        _env_file=None,
        ARTIFACT_DIR=str(tmp_path),
        MCP_TRANSPORT=transport,
        MCP_IDENTITY_HMAC_KEY="a" * 64,
    )
    runtime = await create_runtime_services(settings)
    ctx = cast("Context", FakeContext(lifespan_context={"runtime": runtime}))
    entered = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    if stage == "commit":
        target, method = runtime.budget_ledger, "commit"
    else:
        target, method = runtime.ownership_store, "record"
    original = getattr(target, method)
    calls = 0

    async def blocked(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:

            async def finish() -> None:
                entered.set()
                await release.wait()
                await original(*args, **kwargs)
                finished.set()

            await drain_task(asyncio.create_task(finish()))
        else:
            await original(*args, **kwargs)

    monkeypatch.setattr(target, method, blocked)

    async def create_batch() -> None:
        for index in range(2):
            async with billed_provider_slot(
                ctx,
                provider="modelark",
                product="video",
                estimated_cost_usd=0.01,
            ):
                before_provider_request()
                capture_accepted_task(ctx, "modelark", f"accepted-{index}", f"request-{index}")
                await record_accepted_task(ctx, "modelark", f"accepted-{index}", f"request-{index}")

    async def call() -> None:
        await create_batch()

    try:
        with (
            request_credentials_scope(
                [
                    (b"x-modelark-api-key", b"synthetic-key"),
                    (b"x-mcp-client-secret", b"b" * 64),
                ]
            ),
            provider_scope(settings, "modelark"),
        ):
            pending = asyncio.create_task(
                run_direct_call(
                    call,
                    timeout_seconds=10 if external_cancel else 0.1,
                    read_only=False,
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), 1)
                if external_cancel:
                    pending.cancel()
                    await asyncio.sleep(0)
                    pending.cancel()
                completed, _ = await asyncio.wait({pending}, timeout=0.12)
                assert not completed
            finally:
                release.set()
                results = await asyncio.gather(pending, return_exceptions=True)
            assert finished.is_set()
            if external_cancel:
                assert isinstance(results[0], asyncio.CancelledError)
            else:
                text = deadline_text(results[0], ambiguous=True)
                for index in range(2):
                    assert f"task_id=accepted-{index}" in text
                    assert f"request_id=request-{index}" in text
    finally:
        release.set()
        await close_runtime_services(runtime)


@pytest.mark.parametrize(
    "field",
    [
        "modelark_api_key",
        "seed_speech_api_key",
        "s3_access_key",
        "s3_secret_key",
    ],
)
async def test_local_deadline_receipts_omit_startup_secrets(
    billed_context: Context,
    field: str,
) -> None:
    settings = get_runtime(billed_context).settings
    setattr(settings, field, "synthetic-startup-secret")

    async def call() -> None:
        before_provider_request()
        capture_accepted_task(billed_context, "modelark", "task-synthetic-startup-secret", None)
        capture_accepted_task(
            billed_context, "modelark", "task-safe", "req-synthetic-startup-secret"
        )
        capture_accepted_task(billed_context, "modelark", "task\nmalformed", "req-safe")
        await asyncio.Event().wait()

    text = deadline_text(
        await run_direct_call(call, timeout_seconds=0.01, read_only=False),
        ambiguous=True,
    )
    assert "synthetic-startup-secret" not in text
    assert "malformed" not in text
    assert "task_id=task-safe" in text


@pytest.mark.parametrize("external_cancel", [False, True])
async def test_deadline_during_reserve_drains_then_releases_without_dispatch(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    external_cancel: bool,
) -> None:
    ledger = get_runtime(billed_context).budget_ledger
    entered, release = asyncio.Event(), asyncio.Event()
    reserve = ledger.reserve
    dispatched = False

    async def blocked(owner: AuthContext, estimate: CostEstimate) -> BudgetReservation:
        reservation = await reserve(owner, estimate)
        entered.set()
        await release.wait()
        return reservation

    monkeypatch.setattr(ledger, "reserve", blocked)

    async def call() -> None:
        nonlocal dispatched
        async with billed_provider_slot(
            billed_context,
            provider="modelark",
            product="image",
            estimated_cost_usd=0.08,
        ):
            before_provider_request()
            dispatched = True

    pending = asyncio.create_task(run_direct_call(call, timeout_seconds=0.05, read_only=False))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        completed, _ = await asyncio.wait({pending}, timeout=0.07)
        assert not completed
        if external_cancel:
            pending.cancel()
    finally:
        release.set()
        results = await asyncio.gather(pending, return_exceptions=True)
    assert not dispatched
    assert ledger._connection.execute("SELECT status FROM budget_reservations").fetchall() == [
        ("released",),
    ]
    if external_cancel:
        assert isinstance(results[0], asyncio.CancelledError)
    else:
        deadline_text(results[0], ambiguous=False)


async def test_expired_later_slot_releases_only_its_reservation_not_prior_accepted_work(
    billed_context: Context,
) -> None:
    dispatched: list[str] = []

    async def call() -> None:
        async with billed_provider_slot(
            billed_context,
            provider="modelark",
            product="video",
            estimated_cost_usd=0.04,
        ):
            before_provider_request()
            dispatched.append("first")
            capture_accepted_task(billed_context, "modelark", "accepted-first", "request-first")
        async with billed_provider_slot(
            billed_context,
            provider="modelark",
            product="video",
            estimated_cost_usd=0.04,
        ):
            time.sleep(0.03)
            before_provider_request()
            dispatched.append("second")

    text = deadline_text(
        await run_direct_call(call, timeout_seconds=0.02, read_only=False),
        ambiguous=True,
    )
    assert dispatched == ["first"]
    assert "task_id=accepted-first" in text
    assert get_runtime(billed_context).budget_ledger._connection.execute(
        "SELECT status FROM budget_reservations ORDER BY id",
    ).fetchall() == [("committed",), ("released",)]


@pytest.mark.parametrize("external_cancel", [False, True])
@pytest.mark.parametrize("prior_dispatch", [False, True])
async def test_cancelled_create_fence_releases_only_undispatched_reservation(
    billed_context: Context, external_cancel: bool, prior_dispatch: bool
) -> None:
    guarded = asyncio.Event()
    dispatches = 0

    async def guard() -> None:
        guarded.set()
        await asyncio.Event().wait()

    async def call() -> None:
        nonlocal dispatches
        if prior_dispatch:
            async with billed_provider_slot(
                billed_context,
                provider="modelark",
                product="video",
                estimated_cost_usd=0.04,
            ):
                before_provider_request()
                dispatches += 1
        async with billed_provider_slot(
            billed_context,
            provider="modelark",
            product="video",
            estimated_cost_usd=0.04,
        ):
            await authorize_provider_request()
            dispatches += 1

    pending = asyncio.create_task(
        run_direct_call(
            call,
            timeout_seconds=5 if external_cancel else 0.05,
            read_only=False,
            mutation_guard=guard,
        )
    )
    await asyncio.wait_for(guarded.wait(), 1)
    if external_cancel:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        deadline_text(await pending, ambiguous=prior_dispatch)
    assert dispatches == int(prior_dispatch)
    assert get_runtime(billed_context).budget_ledger._connection.execute(
        "SELECT status FROM budget_reservations ORDER BY id",
    ).fetchall() == ([("committed",)] if prior_dispatch else []) + [("released",)]
