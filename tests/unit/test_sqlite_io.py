"""Cancellation must not release SQLite connection locks before worker completion."""

import asyncio
import threading

import pytest

from ark_mcp.runtime import _run_locked


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
