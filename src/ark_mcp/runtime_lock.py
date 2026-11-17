"""HTTP state ownership from specs/SPEC_VKE_DEPLOYMENT.md.

The durable single-instance contract is specs/SPEC_HOSTED_BYOK.md.
This is a local filesystem lease, not distributed fencing.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, ClassVar

from filelock import FileLock, Timeout

from ark_mcp.sqlite_io import drain_task

if TYPE_CHECKING:
    from pathlib import Path


class RuntimeStateLease:
    """Hold a hard lock until explicit release, including after failed cleanup.

    Strong ownership prevents FileLock finalization from unlocking failed
    runtimes whose callers have already discarded their startup exception.
    """

    _held: ClassVar[set[RuntimeStateLease]] = set()

    def __init__(self, database_path: Path) -> None:
        self._lock = FileLock(
            str(database_path) + ".lock",
            timeout=0,
            mode=0o600,
            thread_local=False,
            fallback_to_soft=False,
            preserve_lock_file=True,
        )

    def _acquire(self) -> None:
        try:
            self._lock.acquire(timeout=0)
            self._held.add(self)
        except Timeout:
            raise RuntimeError("Runtime state is already in use by another HTTP runtime.") from None
        except (OSError, NotImplementedError):
            raise RuntimeError(
                "Runtime state requires an available exclusive filesystem lock."
            ) from None

    async def acquire(self) -> None:
        """Drain acquisition and release any acquired lease before delivering cancellation."""
        pending = asyncio.create_task(asyncio.to_thread(self._acquire))
        try:
            await drain_task(pending)
        except asyncio.CancelledError:
            with suppress(asyncio.CancelledError):
                await self.close()
            raise

    async def close(self) -> None:
        """Release only after the owner has drained all of its state users."""
        await drain_task(asyncio.create_task(asyncio.to_thread(self._release)))

    def _release(self) -> None:
        self._lock.release()
        if not self._lock.is_locked:
            self._held.discard(self)
