"""Outcome preservation for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest
from fastmcp import Context

from ark_mcp.config.env import Settings
from ark_mcp.domain.errors import AcceptedTaskError, NormalizedProviderError, ProviderError
from ark_mcp.runtime import (
    BudgetExceededError,
    BudgetReservation,
    CostEstimate,
    billed_provider_slot,
    close_runtime_services,
    create_runtime_services,
    get_principal,
    get_runtime,
    record_accepted_task,
)
from ark_mcp.security.auth_context import AuthContext
from ark_mcp.security.credentials import request_credentials_scope
from tests.fixtures.fake_context import FakeContext

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
    limiter = runtime.provider_limiters.provider("modelark")
    if not dispatched:
        for _ in range(runtime.settings.provider_max_concurrency):
            await limiter.acquire()
    provider_call = AsyncMock()

    async def generate() -> None:
        async with billed_provider_slot(
            billed_context, provider="modelark", product="image", estimated_cost_usd=0.08
        ):
            await provider_call()
            ready.set()
            await asyncio.Event().wait()

    pending = asyncio.create_task(generate())
    try:
        await asyncio.wait_for(ready.wait(), 2)
        pending.cancel()
        await asyncio.wait_for(finalizing.wait(), 2)
        if cancel_again:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
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
        finish_cleanup.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if finalizing.is_set():
            await asyncio.wait_for(cleanup_finished.wait(), 2)
        if not dispatched:
            for _ in range(runtime.settings.provider_max_concurrency):
                limiter.release()


@pytest.mark.parametrize("provider", ["modelark", "vision-cv"])
async def test_record_accepted_task_retains_id_with_safe_outward_text(
    billed_context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: Literal["modelark", "vision-cv"],
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
