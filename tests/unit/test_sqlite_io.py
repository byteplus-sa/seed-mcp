"""Cancellation must not release SQLite connection locks before worker completion."""

import asyncio
import threading

import pytest

from ark_mcp.runtime import _run_locked
from ark_mcp.sqlite_io import drain_task


@pytest.mark.parametrize("worker_fails", [False, True])
async def test_cancelled_database_operation_keeps_lock_until_thread_finishes(
    worker_fails: bool,
) -> None:
    lock = asyncio.Lock()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_write() -> None:
        started.set()
        try:
            assert release.wait(5)
            if worker_fails:
                raise ValueError("Synthetic database failure")
        finally:
            finished.set()

    first = asyncio.create_task(_run_locked(lock, blocked_write))
    assert await asyncio.to_thread(started.wait, 2)
    first.cancel()
    second = asyncio.create_task(_run_locked(lock, finished.is_set))
    try:
        completed, _ = await asyncio.wait({second}, timeout=0.05)
        assert not completed, "Another SQLite operation ran before the cancelled worker finished"
        first.cancel()
    finally:
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert results[1] is True


async def test_database_worker_failure_is_preserved_and_releases_lock() -> None:
    lock = asyncio.Lock()

    def fail() -> None:
        raise ValueError("Synthetic database failure")

    with pytest.raises(ValueError, match="Synthetic database failure"):
        await _run_locked(lock, fail)
    assert await _run_locked(lock, lambda: 7) == 7


async def test_cancelled_drain_preserves_independent_task_result_for_reservation_recovery() -> None:
    release = asyncio.Event()
    result = object()

    async def reserve() -> object:
        await release.wait()
        return result

    reservation = asyncio.create_task(reserve())
    caller = asyncio.create_task(drain_task(reservation))
    try:
        await asyncio.sleep(0)
        caller.cancel()
        await asyncio.sleep(0)
        caller.cancel()
        completed, _ = await asyncio.wait({caller}, timeout=0.01)
        assert not completed
        assert not reservation.cancelled()
    finally:
        release.set()
        outcomes = await asyncio.gather(caller, return_exceptions=True)
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert reservation.result() is result


async def test_database_close_waits_for_cancelled_worker_before_closing_connection() -> None:
    import sqlite3

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    lock = asyncio.Lock()
    started, release = threading.Event(), threading.Event()

    def query() -> int:
        started.set()
        assert release.wait(5)
        return connection.execute("SELECT 1").fetchone()[0]

    worker = asyncio.create_task(_run_locked(lock, query))
    assert await asyncio.to_thread(started.wait, 1)
    worker.cancel()
    close = asyncio.create_task(_run_locked(lock, connection.close))
    try:
        completed, _ = await asyncio.wait({close}, timeout=0.01)
        assert not completed
        worker.cancel()
    finally:
        release.set()
        outcomes = await asyncio.gather(worker, close, return_exceptions=True)
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert outcomes[1] is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
