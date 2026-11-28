"""Process-lifetime services shared by tools and resources.

The FastMCP lifespan owns this container. Keeping artifact persistence,
concurrency controls, ownership, and budget state here prevents request-scoped
limiters and mutable server-module globals from leaking across test servers.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    ExitStack,
    asynccontextmanager,
    suppress,
)
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from ark_mcp.artifacts.filesystem_store import FilesystemArtifactStore
from ark_mcp.artifacts.object_storage_store import ObjectStorageArtifactStore
from ark_mcp.config.env import Settings
from ark_mcp.domain.artifacts import ArtifactRef
from ark_mcp.domain.errors import AcceptedTaskError, NormalizedProviderError, ProviderError
from ark_mcp.domain.submissions import IDENTIFIER_PATTERN
from ark_mcp.execution import (
    provider_mutation_scope,
    provider_mutation_started,
    record_accepted_receipt,
    state_cleanup_scope,
)
from ark_mcp.observability.admin import MetricsListener
from ark_mcp.observability.logger import error as log_error
from ark_mcp.observability.logger import info as log_info
from ark_mcp.observability.logger import warning as log_warning
from ark_mcp.observability.metrics import ADMISSION_REJECTIONS, BUDGET_REJECTIONS
from ark_mcp.providers.base import safe_provider_text
from ark_mcp.security.auth_context import AuthContext, PrincipalContext
from ark_mcp.security.credentials import redact_request_secrets, request_principal
from ark_mcp.security.safe_downloader import SafeDownloader
from ark_mcp.sqlite_io import drain_task
from ark_mcp.state.disabled import (
    DisabledArtifactStore,
    DisabledObjectKeyOwnershipStore,
    DisabledTaskArtifactCache,
)
from ark_mcp.state.stateless import ProviderAuthorizedTasks

if TYPE_CHECKING:
    from fastmcp import Context, FastMCP

    from ark_mcp.artifacts.store import ArtifactStore

ProviderKey = Literal["modelark", "seed-speech", "s3"]


class _StateCleanupFailed(RuntimeError):
    """An incompletely initialized state connection could not be closed."""


def _close_initializing_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.close()
    except BaseException:
        raise _StateCleanupFailed("Runtime state initialization cleanup failed.") from None


def _open_sqlite_connection(database_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection safe for thread-offloaded access.

    ``check_same_thread=False`` is required because database access is
    dispatched to worker threads via :func:`_offload`. Each store owns an
    ``asyncio.Lock`` that serializes access to its connection object, so at
    most one thread touches a given connection at a time.
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    try:
        connection.execute("PRAGMA journal_mode=WAL").fetchone()
        connection.execute("PRAGMA busy_timeout=5000")
    except BaseException:
        _close_initializing_connection(connection)
        raise
    return connection


async def _offload[T](func: Callable[..., T], *args: Any) -> T:
    """Run a synchronous callable in a worker thread, off the event loop."""
    return await asyncio.to_thread(func, *args)


async def _run_locked[T](lock: asyncio.Lock, func: Callable[[], T]) -> T:
    """Run a synchronous closure off the loop while holding ``lock``.

    The lock serializes access to a store's ``sqlite3.Connection``, and
    ``asyncio.to_thread`` moves the synchronous database call off the event
    loop so a slow commit cannot block unrelated MCP requests.
    Cancellation is delivered only after the worker finishes, before releasing
    the connection lock.
    """
    async with lock:
        return await drain_task(asyncio.create_task(_offload(func)))


@dataclass(slots=True)
class _PrincipalLimiter:
    semaphore: asyncio.Semaphore
    users: int = 0


class ProviderLimiters:
    """Shared provider and bounded per-principal concurrency controls."""

    def __init__(
        self,
        *,
        provider_limit: int = 5,
        principal_limit: int = 3,
        principal_cache_size: int = 10_000,
        admission_timeout_seconds: float = 2.0,
    ) -> None:
        if provider_limit <= 0 or principal_limit <= 0 or principal_cache_size <= 0:
            raise ValueError("Concurrency limits and owner capacity must be positive.")
        if not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds <= 0:
            raise ValueError("Admission timeout must be finite and positive.")
        self._provider = {
            "modelark": asyncio.Semaphore(provider_limit),
            "seed-speech": asyncio.Semaphore(provider_limit),
            "s3": asyncio.Semaphore(provider_limit),
        }
        self._principal_limit = principal_limit
        self._principal_capacity = principal_cache_size
        self._principals: dict[tuple[str, str], _PrincipalLimiter] = {}
        self._admission_timeout_seconds = admission_timeout_seconds

    def provider(self, provider: ProviderKey) -> asyncio.Semaphore:
        return self._provider[provider]

    @staticmethod
    def _admission_error(provider: ProviderKey, *, capacity: bool = False) -> ProviderError:
        ADMISSION_REJECTIONS.labels(
            provider=provider, reason="capacity" if capacity else "timeout"
        ).inc()
        return ProviderError(
            NormalizedProviderError(
                provider=provider,
                operation="admission",
                code="ADMISSION_CAPACITY_EXCEEDED" if capacity else "ADMISSION_TIMEOUT",
                message=(
                    "Provider admission capacity is unavailable; this attempt did not dispatch."
                    if capacity
                    else "Provider admission timed out; this attempt did not dispatch."
                ),
                retryable=True,
                ambiguous_completion=False,
            )
        )

    @asynccontextmanager
    async def acquire(
        self,
        provider: ProviderKey,
        owner: AuthContext,
    ) -> AsyncIterator[None]:
        deadline = asyncio.get_running_loop().time() + self._admission_timeout_seconds
        key = (owner.tenant_id, owner.principal_id)
        entry = None
        if not owner.is_local:
            entry = self._principals.get(key)
            if entry is None:
                if len(self._principals) >= self._principal_capacity:
                    raise self._admission_error(provider, capacity=True)
                entry = _PrincipalLimiter(asyncio.Semaphore(self._principal_limit))
                self._principals[key] = entry
            entry.users += 1
        owner_acquired = provider_acquired = False
        provider_limiter = self.provider(provider)
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    if entry is not None:
                        await entry.semaphore.acquire()
                        owner_acquired = True
                    await provider_limiter.acquire()
                    provider_acquired = True
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
            except TimeoutError:
                raise self._admission_error(provider) from None
            yield
        finally:
            if provider_acquired:
                provider_limiter.release()
            if entry is not None:
                if owner_acquired:
                    entry.semaphore.release()
                entry.users -= 1
                if entry.users == 0:
                    self._principals.pop(key)


@dataclass(frozen=True, slots=True)
class OwnedTask:
    """A provider task ID owned by one principal, with its recording time."""

    task_id: str
    created_at: datetime


class TaskOwnershipStore(Protocol):
    async def require_capacity(self) -> None: ...

    async def record(self, provider: str, task_id: str, owner: AuthContext) -> None: ...

    async def require_owner(self, provider: str, task_id: str, owner: AuthContext) -> None: ...

    async def list_owned_tasks(
        self,
        provider: str,
        owner: AuthContext,
        *,
        since: datetime,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> list[OwnedTask]: ...

    async def prune(self, max_age_days: int) -> int: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class ObjectKeyOwnershipStore(Protocol):
    """Ownership ledger for object-storage keys minted by ``media_upload``."""

    async def record(self, object_key: str, owner: AuthContext) -> None: ...

    async def require_owner(self, object_key: str, owner: AuthContext) -> None: ...

    async def prune(self, max_age_days: int) -> int: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class TaskArtifactCache(Protocol):
    async def get(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None: ...

    async def set(
        self,
        provider: str,
        task_id: str,
        artifacts: dict[str, ArtifactRef | None],
    ) -> None: ...

    async def pop(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None: ...

    async def prune_expired(self) -> int: ...

    async def clear(self) -> None: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class _TaskArtifactLockEntry:
    lock: asyncio.Lock
    users: int = 0
    artifacts: dict[str, ArtifactRef | None] | None = None


class TaskArtifactPersistenceLocks:
    """Bounded-lifetime task locks for artifact persistence single-flight."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _TaskArtifactLockEntry] = {}
        self._registry_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, provider: str, task_id: str) -> AsyncIterator[_TaskArtifactLockEntry]:
        """Serialize persistence for one provider task while leaving other tasks concurrent."""
        key = (provider, task_id)
        async with self._registry_lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _TaskArtifactLockEntry(lock=asyncio.Lock())
                self._entries[key] = entry
            entry.users += 1

        try:
            async with entry.lock:
                yield entry
        finally:
            async with self._registry_lock:
                entry.users -= 1
                if entry.users == 0:
                    self._entries.pop(key, None)


def _ownership_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


class SQLiteTaskOwnershipStore:
    """Small single-instance ownership database for provider task IDs."""

    def __init__(self, database_path: Path, *, max_records: int = 100_000) -> None:
        self._connection = _open_sqlite_connection(database_path)
        self._max_records = max_records
        try:
            self._ensure_schema()
            self._connection.commit()
        except BaseException:
            _close_initializing_connection(self._connection)
            raise
        self._lock = asyncio.Lock()

    def _ensure_schema(self) -> None:
        """Create fresh credential-scoped state; old ownership schemas are unsupported."""
        with self._connection:
            primary_key = {
                str(row[1])
                for row in self._connection.execute("PRAGMA table_info(task_ownership)").fetchall()
                if row[5]
            }
            if primary_key and primary_key != {"provider", "tenant_id", "task_id"}:
                raise ValueError(
                    "Ownership schema is unsupported; use a fresh Seed MCP state directory."
                )
            self._create_table()

    def _create_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_ownership (
                provider TEXT NOT NULL,
                task_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(provider, tenant_id, task_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS task_ownership_owner_created
            ON task_ownership(provider, tenant_id, principal_id, created_at, task_id)
            """
        )

    async def record(self, provider: str, task_id: str, owner: AuthContext) -> None:
        created_at = _ownership_timestamp(datetime.now(UTC))

        def _run() -> None:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT principal_id FROM task_ownership WHERE provider=? AND tenant_id=? AND task_id=?",
                    (provider, owner.tenant_id, task_id),
                ).fetchone()
                if row is not None:
                    if row[0] != owner.principal_id:
                        raise PermissionError("Task is not available to this principal.")
                    return
                self._require_capacity()
                self._connection.execute(
                    "INSERT INTO task_ownership(provider, task_id, principal_id, tenant_id, created_at) VALUES (?, ?, ?, ?, ?)",
                    (provider, task_id, owner.principal_id, owner.tenant_id, created_at),
                )

        await _run_locked(self._lock, _run)

    def _require_capacity(self) -> None:
        count = self._connection.execute("SELECT COUNT(*) FROM task_ownership").fetchone()[0]
        if count >= self._max_records:
            raise RuntimeError("Task ownership capacity reached; new submissions are unavailable.")

    async def require_capacity(self) -> None:
        await _run_locked(self._lock, self._require_capacity)

    async def require_owner(self, provider: str, task_id: str, owner: AuthContext) -> None:
        def _run() -> tuple[str, str] | None:
            return cast(
                "tuple[str, str] | None",
                self._connection.execute(
                    """
                    SELECT principal_id, tenant_id FROM task_ownership
                    WHERE provider = ? AND tenant_id = ? AND task_id = ?
                    """,
                    (provider, owner.tenant_id, task_id),
                ).fetchone(),
            )

        row = await _run_locked(self._lock, _run)
        if row is None:
            if owner.is_local:
                return
            raise PermissionError("Task is not owned by the current principal.")
        if row != (owner.principal_id, owner.tenant_id):
            raise PermissionError("Task is not owned by the current principal.")

    async def list_owned_tasks(
        self,
        provider: str,
        owner: AuthContext,
        *,
        since: datetime,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> list[OwnedTask]:
        """Return owned task IDs recorded at or after ``since``, newest first.

        ``before`` is an exclusive ``(created_at, task_id)`` keyset cursor.
        """
        query = """
            SELECT task_id, created_at FROM task_ownership
            WHERE provider = ? AND tenant_id = ? AND principal_id = ? AND created_at >= ?
        """
        params: list[str | int] = [
            provider,
            owner.tenant_id,
            owner.principal_id,
            _ownership_timestamp(since),
        ]
        if before is not None:
            query += " AND (created_at < ? OR (created_at = ? AND task_id < ?))"
            cursor_time = _ownership_timestamp(before[0])
            params.extend([cursor_time, cursor_time, before[1]])
        query += " ORDER BY created_at DESC, task_id DESC LIMIT ?"
        params.append(limit)

        def _run() -> list[tuple[str, str]]:
            return self._connection.execute(query, params).fetchall()

        rows = await _run_locked(self._lock, _run)
        return [
            OwnedTask(task_id=str(task_id), created_at=datetime.fromisoformat(str(created_at)))
            for task_id, created_at in rows
        ]

    async def prune(self, max_age_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

        def _run() -> int:
            cursor = self._connection.execute(
                "DELETE FROM task_ownership WHERE created_at < ?",
                (cutoff,),
            )
            self._connection.commit()
            return cursor.rowcount if cursor.rowcount is not None else 0

        return await _run_locked(self._lock, _run)

    async def ping(self) -> None:
        await _run_locked(self._lock, lambda: self._connection.execute("SELECT 1").fetchone())

    async def close(self) -> None:
        await _run_locked(self._lock, self._connection.close)


class SQLiteObjectKeyOwnershipStore:
    """SQLite ownership ledger for object-storage keys (``media_upload``)."""

    def __init__(self, database_path: Path) -> None:
        self._connection = _open_sqlite_connection(database_path)
        try:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS object_key_ownership (
                    object_key TEXT NOT NULL PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.commit()
        except BaseException:
            _close_initializing_connection(self._connection)
            raise
        self._lock = asyncio.Lock()

    async def record(self, object_key: str, owner: AuthContext) -> None:
        created_at = datetime.now(UTC).isoformat()

        def _run() -> None:
            self._connection.execute(
                """
                INSERT INTO object_key_ownership(
                    object_key, principal_id, tenant_id, created_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(object_key) DO UPDATE SET
                    principal_id = excluded.principal_id,
                    tenant_id = excluded.tenant_id,
                    created_at = excluded.created_at
                """,
                (
                    object_key,
                    owner.principal_id,
                    owner.tenant_id,
                    created_at,
                ),
            )
            self._connection.commit()

        await _run_locked(self._lock, _run)

    async def require_owner(self, object_key: str, owner: AuthContext) -> None:
        def _run() -> None:
            row = self._connection.execute(
                """
                SELECT principal_id, tenant_id FROM object_key_ownership
                WHERE object_key = ?
                """,
                (object_key,),
            ).fetchone()
            if row is None:
                if owner.is_local:
                    return
                raise PermissionError("Object key is not owned by the current principal.")
            if row != (owner.principal_id, owner.tenant_id):
                raise PermissionError("Object key is not owned by the current principal.")
            self._connection.execute(
                "UPDATE object_key_ownership SET created_at = ? WHERE object_key = ?",
                (datetime.now(UTC).isoformat(), object_key),
            )
            self._connection.commit()

        await _run_locked(self._lock, _run)

    async def prune(self, max_age_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

        def _run() -> int:
            cursor = self._connection.execute(
                "DELETE FROM object_key_ownership WHERE created_at < ?",
                (cutoff,),
            )
            self._connection.commit()
            return cursor.rowcount if cursor.rowcount is not None else 0

        return await _run_locked(self._lock, _run)

    async def ping(self) -> None:
        await _run_locked(self._lock, lambda: self._connection.execute("SELECT 1").fetchone())

    async def close(self) -> None:
        await _run_locked(self._lock, self._connection.close)


class SQLiteTaskArtifactCache:
    """SQLite-backed cache mapping provider task IDs to persisted artifact refs."""

    def __init__(
        self,
        database_path: Path,
        *,
        ttl_seconds: int = 86_400,
        max_size: int = 10_000,
    ) -> None:
        self._connection = _open_sqlite_connection(database_path)
        try:
            self._ensure_schema()
            self._connection.commit()
        except BaseException:
            _close_initializing_connection(self._connection)
            raise
        self._lock = asyncio.Lock()
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size

    def _ensure_schema(self) -> None:
        """Create or migrate the artifact cache to provider-scoped keys."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute("PRAGMA table_info(task_artifacts)").fetchall()
            }
            legacy_exists = self._table_exists("task_artifacts_legacy")
            if columns and "provider" not in columns:
                if legacy_exists:
                    self._connection.execute(
                        """
                        INSERT OR REPLACE INTO task_artifacts_legacy
                        SELECT task_id, artifacts_json, created_at FROM task_artifacts
                        """
                    )
                    self._connection.execute("DROP TABLE task_artifacts")
                else:
                    self._connection.execute(
                        "ALTER TABLE task_artifacts RENAME TO task_artifacts_legacy"
                    )
                legacy_exists = True
            self._create_table()
            if legacy_exists:
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO task_artifacts(
                        provider, task_id, artifacts_json, created_at
                    )
                    SELECT 'modelark', task_id, artifacts_json, created_at
                    FROM task_artifacts_legacy
                    """
                )
                self._connection.execute("DROP TABLE task_artifacts_legacy")

    def _table_exists(self, table: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            is not None
        )

    def _create_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_artifacts (
                provider TEXT NOT NULL,
                task_id TEXT NOT NULL,
                artifacts_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(provider, task_id)
            )
            """
        )

    async def get(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None:
        def _run() -> tuple[str, str] | None:
            return cast(
                "tuple[str, str] | None",
                self._connection.execute(
                    """
                    SELECT artifacts_json, created_at FROM task_artifacts
                    WHERE provider = ? AND task_id = ?
                    """,
                    (provider, task_id),
                ).fetchone(),
            )

        row = await _run_locked(self._lock, _run)
        if row is None:
            return None
        artifacts_json, created_at_str = row
        created_at = datetime.fromisoformat(created_at_str)
        if (datetime.now(UTC) - created_at).total_seconds() > self._ttl_seconds:
            return None
        return self._deserialize(artifacts_json)

    async def set(
        self,
        provider: str,
        task_id: str,
        artifacts: dict[str, ArtifactRef | None],
    ) -> None:
        artifacts_json = self._serialize(artifacts)
        now = datetime.now(UTC).isoformat()

        def _run() -> None:
            self._connection.execute(
                """
                INSERT INTO task_artifacts(provider, task_id, artifacts_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider, task_id) DO UPDATE SET
                    artifacts_json = excluded.artifacts_json,
                    created_at = excluded.created_at
                """,
                (provider, task_id, artifacts_json, now),
            )
            self._connection.commit()
            count_row = self._connection.execute("SELECT COUNT(*) FROM task_artifacts").fetchone()
            if count_row is not None and count_row[0] > self._max_size:
                self._connection.execute(
                    """
                    DELETE FROM task_artifacts
                    WHERE (provider, task_id) NOT IN (
                        SELECT provider, task_id FROM task_artifacts
                        ORDER BY created_at DESC LIMIT ?
                    )
                    """,
                    (self._max_size,),
                )
                self._connection.commit()

        await _run_locked(self._lock, _run)

    async def pop(self, provider: str, task_id: str) -> dict[str, ArtifactRef | None] | None:
        def _run() -> tuple[str, str] | None:
            row = cast(
                "tuple[str, str] | None",
                self._connection.execute(
                    """
                    SELECT artifacts_json, created_at FROM task_artifacts
                    WHERE provider = ? AND task_id = ?
                    """,
                    (provider, task_id),
                ).fetchone(),
            )
            if row is not None:
                self._connection.execute(
                    "DELETE FROM task_artifacts WHERE provider = ? AND task_id = ?",
                    (provider, task_id),
                )
                self._connection.commit()
            return row

        row = await _run_locked(self._lock, _run)
        if row is None:
            return None
        created_at = datetime.fromisoformat(row[1])
        if (datetime.now(UTC) - created_at).total_seconds() > self._ttl_seconds:
            return None
        return self._deserialize(row[0])

    async def clear(self) -> None:
        def _run() -> None:
            self._connection.execute("DELETE FROM task_artifacts")
            self._connection.commit()

        await _run_locked(self._lock, _run)

    async def prune_expired(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(seconds=self._ttl_seconds)).isoformat()

        def _run() -> int:
            cursor = self._connection.execute(
                "DELETE FROM task_artifacts WHERE created_at < ?",
                (cutoff,),
            )
            self._connection.commit()
            return cursor.rowcount if cursor.rowcount is not None else 0

        return await _run_locked(self._lock, _run)

    async def close(self) -> None:
        await _run_locked(self._lock, self._connection.close)

    @staticmethod
    def _serialize(artifacts: dict[str, ArtifactRef | None]) -> str:
        return json.dumps(
            {k: v.model_dump(mode="json") if v is not None else None for k, v in artifacts.items()}
        )

    @staticmethod
    def _deserialize(raw: str) -> dict[str, ArtifactRef | None]:
        data = json.loads(raw)
        return {
            k: ArtifactRef.model_validate(v) if v is not None else None for k, v in data.items()
        }


@dataclass(frozen=True, slots=True)
class CostEstimate:
    product: str
    amount_usd: float


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: int
    owner: AuthContext
    estimate: CostEstimate
    usage_date: date


class BudgetExceededError(ValueError):
    """Raised before dispatch when a principal's daily budget is exhausted."""


class BudgetLedger:
    """SQLite-backed daily budget reservations for one server instance."""

    def __init__(
        self,
        database_path: Path,
        *,
        daily_limit_usd: float | None = None,
        max_records: int = 100_000,
    ) -> None:
        self._connection = _open_sqlite_connection(database_path)
        self._max_records = max_records
        try:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usage_date TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    product TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved', 'committed', 'released'))
                )
                """
            )
            self._connection.commit()
        except BaseException:
            _close_initializing_connection(self._connection)
            raise
        self._daily_limit_usd = daily_limit_usd
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        owner: AuthContext,
        estimate: CostEstimate,
    ) -> BudgetReservation:
        usage_date = datetime.now(UTC).date()

        def _run() -> int:
            count = self._connection.execute("SELECT COUNT(*) FROM budget_reservations").fetchone()[
                0
            ]
            if count >= self._max_records:
                raise BudgetExceededError(
                    "Budget record capacity reached; new requests are unavailable."
                )
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0) FROM budget_reservations
                WHERE usage_date = ? AND principal_id = ? AND tenant_id = ?
                  AND status IN ('reserved', 'committed')
                """,
                (usage_date.isoformat(), owner.principal_id, owner.tenant_id),
            ).fetchone()
            current = float(row[0]) if row is not None else 0.0
            if (
                self._daily_limit_usd is not None
                and current + estimate.amount_usd > self._daily_limit_usd
            ):
                BUDGET_REJECTIONS.labels(product=estimate.product).inc()
                log_warning(
                    "budget_rejected",
                    product=estimate.product,
                    amount_usd=round(estimate.amount_usd, 6),
                    current_usd=round(current, 6),
                    daily_limit_usd=self._daily_limit_usd,
                    principal_id=owner.principal_id,
                )
                raise BudgetExceededError(
                    f"Daily budget of ${self._daily_limit_usd:.2f} would be exceeded."
                )
            cursor = self._connection.execute(
                """
                INSERT INTO budget_reservations(
                    usage_date, principal_id, tenant_id, product, amount_usd, status
                ) VALUES (?, ?, ?, ?, ?, 'reserved')
                """,
                (
                    usage_date.isoformat(),
                    owner.principal_id,
                    owner.tenant_id,
                    estimate.product,
                    estimate.amount_usd,
                ),
            )
            self._connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Budget reservation did not return an ID.")
            return cursor.lastrowid

        reservation_id = await _run_locked(self._lock, _run)
        return BudgetReservation(reservation_id, owner, estimate, usage_date)

    async def commit(self, reservation: BudgetReservation) -> None:
        await self._set_status(reservation, "committed")

    async def release(self, reservation: BudgetReservation) -> None:
        await self._set_status(reservation, "released")

    async def _set_status(
        self,
        reservation: BudgetReservation,
        status: Literal["committed", "released"],
    ) -> None:
        def _run() -> None:
            self._connection.execute(
                "UPDATE budget_reservations SET status = ? WHERE id = ?",
                (status, reservation.reservation_id),
            )
            self._connection.commit()

        await _run_locked(self._lock, _run)

    async def prune(self, max_age_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).date().isoformat()

        def _run() -> int:
            cursor = self._connection.execute(
                "DELETE FROM budget_reservations WHERE usage_date < ?",
                (cutoff,),
            )
            self._connection.commit()
            return cursor.rowcount if cursor.rowcount is not None else 0

        return await _run_locked(self._lock, _run)

    async def close(self) -> None:
        await _run_locked(self._lock, self._connection.close)

    async def ping(self) -> None:
        await _run_locked(self._lock, lambda: self._connection.execute("SELECT 1").fetchone())


@dataclass(slots=True)
class RuntimeServices:
    settings: Settings
    artifact_store: ArtifactStore
    safe_downloader: SafeDownloader
    ownership_store: TaskOwnershipStore
    object_key_ownership_store: ObjectKeyOwnershipStore
    budget_ledger: BudgetLedger | None
    provider_limiters: ProviderLimiters
    task_artifact_cache: TaskArtifactCache
    task_artifact_locks: TaskArtifactPersistenceLocks
    metrics_listener: MetricsListener | None = None
    _close_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)


@dataclass(slots=True)
class RuntimeState:
    runtime: RuntimeServices | None = None


def build_state_stores(
    settings: Settings,
    database_path: Path,
) -> tuple[TaskOwnershipStore, ObjectKeyOwnershipStore, BudgetLedger, TaskArtifactCache]:
    """Build the state stores for the configured ``STATE_BACKEND``."""
    if settings.state_backend != "sqlite":
        raise ValueError(f"Unsupported STATE_BACKEND: {settings.state_backend}")
    log_warning(
        "single_instance_state_backend",
        backend=settings.state_backend,
        note="Only one replica may run with the SQLite state backend.",
    )
    with ExitStack() as cleanup:
        ownership = SQLiteTaskOwnershipStore(database_path, max_records=settings.state_max_records)
        cleanup.callback(_close_initializing_connection, ownership._connection)
        object_keys = SQLiteObjectKeyOwnershipStore(database_path)
        cleanup.callback(_close_initializing_connection, object_keys._connection)
        budget = BudgetLedger(
            database_path,
            daily_limit_usd=settings.daily_budget_usd or None,
            max_records=settings.state_max_records,
        )
        cleanup.callback(_close_initializing_connection, budget._connection)
        cache = SQLiteTaskArtifactCache(
            database_path,
            ttl_seconds=settings.persistence_cache_ttl_seconds,
            max_size=settings.persistence_cache_max_size,
        )
        cleanup.callback(_close_initializing_connection, cache._connection)
        cleanup.pop_all()
        return ownership, object_keys, budget, cache


async def _create_stateless_runtime(settings: Settings) -> RuntimeServices:
    """HTTP has no database, task ledger, artifact directory or filesystem lease."""
    async with AsyncExitStack() as cleanup:
        downloader = SafeDownloader(
            timeout=settings.artifact_download_timeout_seconds,
            connect_timeout=settings.connect_timeout_ms / 1000,
            max_attempts=settings.artifact_download_max_attempts,
        )
        cleanup.push_async_callback(downloader.close)
        listener = None
        if settings.metrics_port:
            listener = MetricsListener(settings.metrics_port)
            cleanup.push_async_callback(listener.close)
        runtime = RuntimeServices(
            settings=settings,
            artifact_store=DisabledArtifactStore(),
            safe_downloader=downloader,
            ownership_store=ProviderAuthorizedTasks(),
            object_key_ownership_store=DisabledObjectKeyOwnershipStore(),
            budget_ledger=None,
            provider_limiters=ProviderLimiters(
                provider_limit=settings.provider_max_concurrency,
                principal_limit=settings.principal_max_concurrency,
                admission_timeout_seconds=settings.admission_timeout_seconds,
            ),
            task_artifact_cache=DisabledTaskArtifactCache(),
            task_artifact_locks=TaskArtifactPersistenceLocks(),
            metrics_listener=listener,
        )
        cleanup.pop_all()
        return runtime


async def create_runtime_services(settings: Settings) -> RuntimeServices:
    """Create stateless HTTP services or local stdio persistence."""
    if settings.mcp_transport == "http":
        return await _create_stateless_runtime(settings)
    artifact_dir = Path(settings.artifact_dir).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    database_path = artifact_dir / "runtime.sqlite3"
    cleanup = AsyncExitStack()
    state_cleanup_failed = False
    try:
        downloader = SafeDownloader(
            timeout=settings.artifact_download_timeout_seconds,
            connect_timeout=settings.connect_timeout_ms / 1000,
            max_attempts=settings.artifact_download_max_attempts,
        )
        cleanup.push_async_callback(downloader.close)
        if settings.artifact_backend == "object_storage":
            artifact_store: ArtifactStore = ObjectStorageArtifactStore(
                settings=settings,
                downloader=downloader,
            )
        else:
            artifact_store = FilesystemArtifactStore(
                artifact_dir=str(artifact_dir),
                ttl_seconds=settings.artifact_ttl_seconds,
                downloader=downloader,
            )
        cleanup.push_async_callback(artifact_store.close)

        async def open_stores() -> tuple[
            TaskOwnershipStore, ObjectKeyOwnershipStore, BudgetLedger, TaskArtifactCache
        ]:
            nonlocal state_cleanup_failed
            try:
                stores = await asyncio.to_thread(build_state_stores, settings, database_path)
            except _StateCleanupFailed:
                state_cleanup_failed = True
                raise
            for store in stores:
                cleanup.push_async_callback(store.close)
            return stores

        (
            ownership_store,
            object_key_ownership_store,
            budget_ledger,
            task_artifact_cache,
        ) = await drain_task(asyncio.create_task(open_stores()))

        runtime = RuntimeServices(
            settings=settings,
            artifact_store=artifact_store,
            safe_downloader=downloader,
            ownership_store=ownership_store,
            object_key_ownership_store=object_key_ownership_store,
            budget_ledger=budget_ledger,
            provider_limiters=ProviderLimiters(
                provider_limit=settings.provider_max_concurrency,
                principal_limit=settings.principal_max_concurrency,
                admission_timeout_seconds=settings.admission_timeout_seconds,
            ),
            task_artifact_cache=task_artifact_cache,
            task_artifact_locks=TaskArtifactPersistenceLocks(),
        )
    except BaseException:

        async def close_partial() -> None:
            await cleanup.aclose()
            if state_cleanup_failed:
                raise _StateCleanupFailed("Runtime state initialization cleanup failed.")

        cleanup_task = asyncio.create_task(close_partial())
        try:
            await drain_task(cleanup_task)
        except (Exception, asyncio.CancelledError):
            if cleanup_task.cancelled() or cleanup_task.exception() is not None:
                log_error("runtime_startup_cleanup_failed")
        raise
    cleanup.pop_all()
    return runtime


async def close_runtime_services(runtime: RuntimeServices) -> None:
    """Drain lifespan cleanup, including repeated cancellation."""

    async def close() -> None:
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(runtime.safe_downloader.close)
            cleanup.push_async_callback(runtime.task_artifact_cache.close)
            if runtime.budget_ledger is not None:
                cleanup.push_async_callback(runtime.budget_ledger.close)
            cleanup.push_async_callback(runtime.object_key_ownership_store.close)
            cleanup.push_async_callback(runtime.ownership_store.close)
            cleanup.push_async_callback(runtime.artifact_store.close)
            if runtime.metrics_listener is not None:
                cleanup.push_async_callback(runtime.metrics_listener.close)

    if runtime._close_task is None:
        runtime._close_task = asyncio.create_task(close())
    await drain_task(runtime._close_task)


RuntimeFactory = Callable[[Settings], Awaitable[RuntimeServices]]


def get_runtime(ctx: Context) -> RuntimeServices:
    runtime = ctx.lifespan_context.get("runtime")
    if not isinstance(runtime, RuntimeServices):
        raise RuntimeError("Runtime services are unavailable outside the server lifespan.")
    return runtime


def get_principal(ctx: Context) -> PrincipalContext:
    """Resolve trusted local ownership or the selected live HTTP provider scope."""
    settings = get_runtime(ctx).settings
    if settings.mcp_transport == "stdio":
        return PrincipalContext()
    return request_principal()


def _safe_receipt_identifier(settings: Settings, value: str | None) -> bool:
    if not isinstance(value, str) or not re.fullmatch(IDENTIFIER_PATTERN, value):
        return False
    if redact_request_secrets(value) != value:
        return False
    secrets = (
        settings.identity_hmac_key.get_secret_value(),
        settings.modelark_api_key,
        settings.seed_speech_api_key,
        settings.s3_access_key,
        settings.s3_secret_key,
    )
    return not any(secret and secret in value for secret in secrets)


def capture_accepted_task(
    ctx: Context,
    provider: Literal["modelark"],
    task_id: str,
    request_id: str | None,
) -> None:
    """Capture safe transient receipts synchronously, before leaving the provider slot."""
    from ark_mcp.domain.submissions import validate_receipt_identifiers

    validate_receipt_identifiers(ctx, provider, task_id, request_id)
    settings = get_runtime(ctx).settings
    if _safe_receipt_identifier(settings, task_id):
        record_accepted_receipt(
            task_id, request_id if _safe_receipt_identifier(settings, request_id) else None
        )


async def record_accepted_task(
    ctx: Context,
    provider: Literal["modelark"],
    task_id: str,
    request_id: str | None,
) -> None:
    """Never report an accepted but unrecorded task as safe to resubmit."""
    capture_accepted_task(ctx, provider, task_id, request_id)
    if get_runtime(ctx).settings.mcp_transport == "http":
        return

    async def persist() -> None:
        try:
            await get_runtime(ctx).ownership_store.record(provider, task_id, get_principal(ctx))
        except Exception:
            log_error("ownership_record_failed", provider=provider, action="record")
            raise AcceptedTaskError(
                NormalizedProviderError(
                    provider=provider,
                    operation="create_task",
                    code="OWNERSHIP_RECORD_FAILED",
                    message=(
                        f"The provider accepted task_id={safe_provider_text(task_id)}, "
                        "but its ownership could not be recorded. Do not resubmit. "
                        "Reconcile through the provider using the accepted task ID and any "
                        "diagnostic request ID; polling through MCP requires recorded ownership."
                    ),
                    request_id=safe_provider_text(request_id) or None,
                    retryable=False,
                    ambiguous_completion=True,
                ),
                task_id=task_id,
            ) from None

    # Keep the receipt and ownership sequence together across caller cancellation.
    with state_cleanup_scope():
        await drain_task(asyncio.create_task(persist(), name="seed-mcp-accepted-task"))


@asynccontextmanager
async def billed_provider_slot(
    ctx: Context,
    *,
    provider: ProviderKey,
    product: str,
    estimated_cost_usd: float,
) -> AsyncIterator[None]:
    """Acquire shared limits before reserving budget for one billable call.

    Each slot covers one billable operation and its explicitly safe retries.
    The reservation is committed when the call succeeds, when the provider
    error is ambiguous, or when it is a ``TIMEOUT`` (a timed-out completion may
    still have consumed billable tokens). It is released for other errors.
    Cancellation during reservation drains and recovers a known reservation,
    then releases it without dispatch. Cancellation commits only if this slot
    dispatched a provider mutation; waiting on the create fence releases it.
    Finalization and SDK draining hold admission
    through repeated cancellation; failures never replace a provider outcome.
    """
    runtime = get_runtime(ctx)
    owner = get_principal(ctx)
    if runtime.settings.mcp_transport == "http":
        async with runtime.provider_limiters.acquire(provider, owner):
            yield
        return
    ledger = runtime.budget_ledger
    if ledger is None:
        raise RuntimeError("Local budget ledger is unavailable.")

    async def finalize(
        reservation: BudgetReservation, action: Literal["commit", "release"]
    ) -> None:
        try:
            with state_cleanup_scope():
                if action == "commit":
                    await ledger.commit(reservation)
                else:
                    await ledger.release(reservation)
        except Exception:
            log_error(
                "budget_finalization_failed",
                provider=provider,
                action=action,
                reservation_id=reservation.reservation_id,
            )

    async with runtime.provider_limiters.acquire(provider, owner):
        reserve_task = asyncio.create_task(
            ledger.reserve(owner, CostEstimate(product=product, amount_usd=estimated_cost_usd))
        )
        try:
            reservation = await asyncio.shield(reserve_task)
        except asyncio.CancelledError:
            with suppress(Exception, asyncio.CancelledError):
                await drain_task(reserve_task)
            try:
                reservation = reserve_task.result()
            except (Exception, asyncio.CancelledError):
                log_error("budget_reservation_failed", provider=provider)
            else:
                with suppress(asyncio.CancelledError):
                    await drain_task(asyncio.create_task(finalize(reservation, "release")))
            raise

        async def finish(action: Literal["commit", "release"]) -> None:
            await drain_task(asyncio.create_task(finalize(reservation, action)))

        task = asyncio.current_task()
        if task is not None and task.cancelling():
            with suppress(asyncio.CancelledError):
                await finish("release")
            raise asyncio.CancelledError
        with provider_mutation_scope():
            try:
                yield
            except ProviderError as exc:
                await finish(
                    "commit" if exc.ambiguous_completion or exc.code == "TIMEOUT" else "release"
                )
                raise
            except asyncio.CancelledError:
                with suppress(asyncio.CancelledError):
                    await finish("commit" if provider_mutation_started() else "release")
                raise
            except BaseException:
                await finish("commit" if provider_mutation_started() else "release")
                raise
            else:
                await finish("commit")


async def _state_sweeper(runtime: RuntimeServices, settings: Settings) -> None:
    """Periodically sweep expired artifacts and prune aged state rows."""
    while True:
        await asyncio.sleep(settings.artifact_sweep_interval_seconds)
        try:
            deleted = await runtime.artifact_store.delete_expired(datetime.now(UTC))
            log_info("state_sweep_artifacts", deleted=deleted)
        except Exception as exc:
            log_warning("state_sweep_artifact_error", error=str(exc))
        try:
            pruned = await runtime.ownership_store.prune(settings.state_prune_max_age_days)
            log_info("state_sweep_ownership", pruned=pruned)
        except Exception as exc:
            log_warning("state_sweep_ownership_error", error=str(exc))
        try:
            pruned = await runtime.object_key_ownership_store.prune(
                settings.state_prune_max_age_days
            )
            log_info("state_sweep_object_keys", pruned=pruned)
        except Exception as exc:
            log_warning("state_sweep_object_keys_error", error=str(exc))
        try:
            pruned = (
                await runtime.budget_ledger.prune(settings.state_prune_max_age_days)
                if runtime.budget_ledger is not None
                else 0
            )
            log_info("state_sweep_budget", pruned=pruned)
        except Exception as exc:
            log_warning("state_sweep_budget_error", error=str(exc))
        try:
            pruned = await runtime.task_artifact_cache.prune_expired()
            log_info("state_sweep_cache", pruned=pruned)
        except Exception as exc:
            log_warning("state_sweep_cache_error", error=str(exc))


def build_lifespan(
    settings: Settings,
    runtime_factory: RuntimeFactory = create_runtime_services,
    state: RuntimeState | None = None,
) -> Callable[
    [FastMCP[dict[str, object]]],
    AbstractAsyncContextManager[dict[str, object]],
]:
    @asynccontextmanager
    async def server_lifespan(
        _server: FastMCP[dict[str, object]],
    ) -> AsyncIterator[dict[str, object]]:
        runtime = await runtime_factory(settings)
        if state is not None:
            state.runtime = runtime
        sweeper = (
            asyncio.create_task(_state_sweeper(runtime, settings))
            if settings.mcp_transport == "stdio"
            else None
        )
        try:
            yield {"runtime": runtime}
        finally:
            if state is not None:
                state.runtime = None

            async def shutdown() -> None:
                try:
                    if sweeper is not None:
                        sweeper.cancel()
                        with suppress(asyncio.CancelledError):
                            await sweeper
                finally:
                    await close_runtime_services(runtime)

            await drain_task(asyncio.create_task(shutdown()))

    return server_lifespan
