"""Cancellation-safe completion for thread-offloaded SQLite operations."""

import asyncio


async def drain_task[T](task: asyncio.Task[T]) -> T:
    """Keep connection locks held until the worker finishes, then deliver cancellation."""
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            cancellation = exc
        except Exception:
            if cancellation is not None:
                raise cancellation from None
            raise
    if cancellation is not None:
        raise cancellation
    return result
