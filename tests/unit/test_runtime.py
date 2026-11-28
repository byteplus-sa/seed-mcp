"""Runtime contracts, including specs/SPEC_HOSTED_BYOK.md ownership."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from contextlib import AsyncExitStack, closing, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.domain.artifacts import ArtifactRef, MediaType
from ark_mcp.domain.errors import ProviderError
from ark_mcp.runtime import (
    BudgetExceededError,
    BudgetLedger,
    CostEstimate,
    ProviderLimiters,
    RuntimeServices,
    SQLiteObjectKeyOwnershipStore,
    SQLiteTaskArtifactCache,
    SQLiteTaskOwnershipStore,
    TaskArtifactPersistenceLocks,
    TaskOwnershipStore,
    _state_sweeper,
    build_lifespan,
    close_runtime_services,
    create_runtime_services,
    get_principal,
)
from ark_mcp.security.auth_context import AuthContext
from ark_mcp.security.credentials import (
    provider_scope,
    request_credentials_scope,
    request_principal,
)
from tests.fixtures.fake_context import FakeContext


def _credential_owner(key: str = "synthetic-customer-a", secret: str = "b" * 64) -> AuthContext:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_AUTH_MODE="byok",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
    )
    with (
        request_credentials_scope(
            [(b"x-modelark-api-key", key.encode()), (b"x-mcp-client-secret", secret.encode())]
        ),
        provider_scope(settings, "modelark"),
    ):
        return request_principal()


def _make_ref(ref_id: str = "art-1") -> ArtifactRef:
    return ArtifactRef(
        id=ref_id,
        uri=f"seed-media://artifacts/{ref_id}",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        bytes=100,
        sha256="abc123",
        created_at=datetime.now(UTC).isoformat(),
    )


async def test_task_artifact_cache_set_and_get(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3")
    ref = _make_ref("art-get")
    await cache.set("modelark", "task-1", {"video": ref, "last_frame": None})
    result = await cache.get("modelark", "task-1")
    assert result is not None
    assert result["video"] is not None
    assert result["video"].id == "art-get"
    assert result["last_frame"] is None
    await cache.close()


async def test_task_artifact_cache_returns_none_for_missing(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3")
    assert await cache.get("modelark", "nope") is None
    await cache.close()


async def test_task_artifact_cache_upsert(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3")
    ref1 = _make_ref("art-old")
    ref2 = _make_ref("art-new")
    await cache.set("modelark", "task-up", {"video": ref1, "last_frame": None})
    await cache.set("modelark", "task-up", {"video": ref2, "last_frame": None})
    result = await cache.get("modelark", "task-up")
    assert result is not None
    assert result["video"] is not None
    assert result["video"].id == "art-new"
    await cache.close()


async def test_task_artifact_cache_pop(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3")
    ref = _make_ref("art-pop")
    await cache.set("modelark", "task-pop", {"video": ref, "last_frame": None})
    popped = await cache.pop("modelark", "task-pop")
    assert popped is not None
    assert popped["video"] is not None
    assert popped["video"].id == "art-pop"
    assert await cache.get("modelark", "task-pop") is None
    await cache.close()


async def test_task_artifact_persistence_locks_keep_different_tasks_concurrent() -> None:
    locks = TaskArtifactPersistenceLocks()
    both_entered = asyncio.Event()
    entered: set[str] = set()

    async def worker(task_id: str) -> None:
        async with locks.acquire("modelark", task_id):
            entered.add(task_id)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)

    await asyncio.gather(worker("task-1"), worker("task-2"))
    assert entered == {"task-1", "task-2"}


async def test_task_artifact_cache_clear(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3")
    await cache.set("modelark", "task-a", {"video": _make_ref("a"), "last_frame": None})
    await cache.set("modelark", "task-b", {"video": _make_ref("b"), "last_frame": None})
    await cache.clear()
    assert await cache.get("modelark", "task-a") is None
    assert await cache.get("modelark", "task-b") is None
    await cache.close()


async def test_task_artifact_cache_ttl_expiry(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3", ttl_seconds=1)
    await cache.set("modelark", "task-ttl", {"video": _make_ref("ttl"), "last_frame": None})

    fake_old = datetime.now(UTC) - timedelta(seconds=2)
    cache._connection.execute(
        "UPDATE task_artifacts SET created_at = ? WHERE task_id = ?",
        (fake_old.isoformat(), "task-ttl"),
    )
    cache._connection.commit()

    assert await cache.get("modelark", "task-ttl") is None
    await cache.close()


async def test_task_artifact_cache_max_size_eviction(tmp_path: Path) -> None:
    cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3", max_size=2)
    await cache.set("modelark", "task-1", {"video": _make_ref("r1"), "last_frame": None})
    await asyncio.sleep(0.01)
    await cache.set("modelark", "task-2", {"video": _make_ref("r2"), "last_frame": None})
    await asyncio.sleep(0.01)
    await cache.set("modelark", "task-3", {"video": _make_ref("r3"), "last_frame": None})

    assert await cache.get("modelark", "task-1") is None
    assert await cache.get("modelark", "task-2") is not None
    assert await cache.get("modelark", "task-3") is not None
    await cache.close()


async def test_task_artifact_cache_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "runtime.sqlite3"
    cache1 = SQLiteTaskArtifactCache(db)
    await cache1.set(
        "modelark", "task-survive", {"video": _make_ref("survive"), "last_frame": None}
    )
    await cache1.close()

    cache2 = SQLiteTaskArtifactCache(db)
    result = await cache2.get("modelark", "task-survive")
    assert result is not None
    assert result["video"] is not None
    assert result["video"].id == "survive"
    await cache2.close()


async def test_task_ownership_is_principal_and_tenant_scoped(tmp_path: Path) -> None:
    store = SQLiteTaskOwnershipStore(tmp_path / "runtime.sqlite3")
    alice = AuthContext(principal_id="alice", tenant_id="tenant-a")
    await store.record("modelark", "task-1", alice)

    await store.require_owner("modelark", "task-1", alice)
    assert await _owned_ids(store, "modelark", alice) == ["task-1"]

    with pytest.raises(PermissionError):
        await store.require_owner(
            "modelark", "task-1", AuthContext(principal_id="bob", tenant_id="tenant-a")
        )
    with pytest.raises(PermissionError):
        await store.require_owner(
            "modelark", "task-1", AuthContext(principal_id="alice", tenant_id="tenant-b")
        )
    await store.close()


async def test_task_ownership_and_artifacts_are_provider_scoped(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteTaskOwnershipStore(database)
    cache = SQLiteTaskArtifactCache(database)
    alice = AuthContext(principal_id="alice", tenant_id="tenant-a")
    bob = AuthContext(principal_id="bob", tenant_id="tenant-a")

    await store.record("modelark", "shared-id", alice)
    await store.record("test-provider", "shared-id", bob)
    await cache.set("modelark", "shared-id", {"video": _make_ref("modelark"), "last_frame": None})
    await cache.set("test-provider", "shared-id", {"video": _make_ref("other"), "last_frame": None})

    await store.require_owner("modelark", "shared-id", alice)
    await store.require_owner("test-provider", "shared-id", bob)
    assert await _owned_ids(store, "modelark", alice) == ["shared-id"]
    assert await _owned_ids(store, "test-provider", alice) == []
    modelark = await cache.get("modelark", "shared-id")
    other = await cache.get("test-provider", "shared-id")
    assert modelark is not None and modelark["video"] is not None
    assert other is not None and other["video"] is not None
    assert modelark["video"].id == "modelark"
    assert other["video"].id == "other"
    await cache.close()
    await store.close()


async def test_fresh_ownership_schema_is_credential_tenant_scoped(tmp_path: Path) -> None:
    store = SQLiteTaskOwnershipStore(tmp_path / "runtime.sqlite3")
    try:
        columns = store._connection.execute("PRAGMA table_info(task_ownership)").fetchall()
        primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        assert primary_key == ["provider", "tenant_id", "task_id"]
        assert {row[1] for row in columns} == {
            "provider",
            "tenant_id",
            "task_id",
            "principal_id",
            "created_at",
        }
        assert await _owned_ids(store, "modelark", _credential_owner()) == []
        await store.ping()
    finally:
        await store.close()


@pytest.mark.parametrize("provider_column", [False, True])
async def test_old_ownership_schema_is_rejected_without_migration(
    tmp_path: Path, provider_column: bool
) -> None:
    database = tmp_path / "runtime.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        if provider_column:
            connection.execute(
                "CREATE TABLE task_ownership (provider TEXT NOT NULL, task_id TEXT NOT NULL, "
                "principal_id TEXT NOT NULL, tenant_id TEXT NOT NULL, created_at TEXT NOT NULL, "
                "PRIMARY KEY(provider, task_id))"
            )
            connection.execute(
                "INSERT INTO task_ownership VALUES (?, ?, ?, ?, ?)",
                ("modelark", "old-task", "old-owner", "old-tenant", datetime.now(UTC).isoformat()),
            )
        else:
            connection.execute(
                "CREATE TABLE task_ownership (task_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
                "tenant_id TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO task_ownership VALUES (?, ?, ?, ?)",
                ("old-task", "old-owner", "old-tenant", datetime.now(UTC).isoformat()),
            )
        original_schema = connection.execute("PRAGMA table_info(task_ownership)").fetchall()
        original_rows = connection.execute("SELECT * FROM task_ownership").fetchall()

    with pytest.raises(ValueError, match="fresh"):
        SQLiteTaskOwnershipStore(database)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA table_info(task_ownership)").fetchall() == original_schema
        assert connection.execute("SELECT * FROM task_ownership").fetchall() == original_rows


async def test_identical_task_ids_are_independent_across_credential_tenants(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = _credential_owner()
    second = _credential_owner(key="synthetic-customer-b")
    assert first.tenant_id != second.tenant_id
    store = SQLiteTaskOwnershipStore(database)
    try:
        for owner in (first, second):
            await store.record("modelark", "same-provider-id", owner)
        await store.record("modelark", "first-only", first)
    finally:
        await store.close()

    reopened = SQLiteTaskOwnershipStore(database)
    try:
        for owner in (first, second):
            await reopened.require_owner("modelark", "same-provider-id", owner)
            await reopened.record("modelark", "same-provider-id", owner)
        assert await _owned_ids(reopened, "modelark", first) == ["first-only", "same-provider-id"]
        assert await _owned_ids(reopened, "modelark", second) == ["same-provider-id"]
        with pytest.raises(PermissionError):
            await reopened.require_owner("modelark", "first-only", second)
    finally:
        await reopened.close()


async def test_record_cannot_overwrite_another_owner_even_after_reopening(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    owner = _credential_owner()
    other = _credential_owner(secret="c" * 64)
    assert owner.tenant_id == other.tenant_id
    assert owner.principal_id != other.principal_id
    store = SQLiteTaskOwnershipStore(database)
    try:
        await store.record("modelark", "immutable-task", owner)
        await store.record("modelark", "immutable-task", owner)
        with pytest.raises(PermissionError):
            await store.record("modelark", "immutable-task", other)
    finally:
        await store.close()

    reopened = SQLiteTaskOwnershipStore(database)
    try:
        with pytest.raises(PermissionError):
            await reopened.record("modelark", "immutable-task", other)
        await reopened.require_owner("modelark", "immutable-task", owner)
        with pytest.raises(PermissionError):
            await reopened.require_owner("modelark", "immutable-task", other)
        assert await _owned_ids(reopened, "modelark", owner) == ["immutable-task"]
        assert await _owned_ids(reopened, "modelark", other) == []
    finally:
        await reopened.close()


async def test_concurrent_owners_cannot_record_the_same_credential_task(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    owners = [_credential_owner(), _credential_owner(secret="c" * 64)]
    stores = [SQLiteTaskOwnershipStore(database), SQLiteTaskOwnershipStore(database)]
    try:
        results = await asyncio.gather(
            *(
                store.record("modelark", "contested-task", owner)
                for store, owner in zip(stores, owners, strict=True)
            ),
            return_exceptions=True,
        )
        assert results.count(None) == 1
        winner_index = results.index(None)
        assert isinstance(results[1 - winner_index], PermissionError)
        winner, loser = owners[winner_index], owners[1 - winner_index]
    finally:
        for store in stores:
            await store.close()

    reopened = SQLiteTaskOwnershipStore(database)
    try:
        await reopened.require_owner("modelark", "contested-task", winner)
        with pytest.raises(PermissionError):
            await reopened.record("modelark", "contested-task", loser)
        assert await _owned_ids(reopened, "modelark", winner) == ["contested-task"]
        assert await _owned_ids(reopened, "modelark", loser) == []
    finally:
        await reopened.close()


async def test_budget_reservations_block_and_release(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "runtime.sqlite3", daily_limit_usd=0.10)
    owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
    first = await ledger.reserve(owner, CostEstimate(product="image", amount_usd=0.08))

    with pytest.raises(BudgetExceededError):
        await ledger.reserve(owner, CostEstimate(product="image", amount_usd=0.03))

    await ledger.release(first)
    second = await ledger.reserve(owner, CostEstimate(product="image", amount_usd=0.03))
    await ledger.commit(second)
    await ledger.close()


@pytest.mark.parametrize("runtime_transport", [None, "stdio", "http"])
async def test_default_limiters_admit_ten_and_recover_after_saturation(
    tmp_path: Path, runtime_transport: str | None
) -> None:
    runtime = None
    if runtime_transport is None:
        limiters = ProviderLimiters(admission_timeout_seconds=0.01)
    else:
        runtime = await create_runtime_services(
            Settings(
                _env_file=None,
                MCP_TRANSPORT=runtime_transport,
                MCP_IDENTITY_HMAC_KEY="a" * 64,
                MCP_ADMISSION_TIMEOUT_SECONDS=0.01,
                ARTIFACT_DIR=str(tmp_path / "artifacts"),
            )
        )
        limiters = runtime.provider_limiters
    alice = AuthContext(principal_id="alice", tenant_id="tenant", transport="http")
    bob = AuthContext(principal_id="bob", tenant_id="tenant", transport="http")
    try:
        # Repeat to prove that timeout and release restore all ten slots.
        for _ in range(2):
            async with AsyncExitStack() as held:
                for _ in range(10):
                    await held.enter_async_context(limiters.acquire("modelark", alice))
                for provider, owner in [
                    ("modelark", alice),
                    ("seed-speech", alice),  # The same owner has used all ten slots.
                    ("modelark", bob),  # Another owner still shares the provider cap.
                ]:
                    with pytest.raises(ProviderError) as raised:
                        async with limiters.acquire(provider, owner):  # type: ignore[arg-type]
                            pytest.fail("The eleventh admission must not dispatch")
                    assert raised.value.code == "ADMISSION_TIMEOUT"
                    assert raised.value.ambiguous_completion is False
                # Other owners retain independent capacity in another provider bucket.
                for _ in range(10):
                    await held.enter_async_context(limiters.acquire("seed-speech", bob))
            assert not limiters._principals
    finally:
        if runtime is not None:
            await close_runtime_services(runtime)


async def test_provider_limit_is_shared_across_principals() -> None:
    limiters = ProviderLimiters(provider_limit=2, principal_limit=2)
    active = 0
    maximum = 0
    gate = asyncio.Event()

    async def worker(index: int) -> None:
        nonlocal active, maximum
        owner = AuthContext(principal_id=f"p-{index}", tenant_id="tenant")
        async with limiters.acquire("modelark", owner):
            active += 1
            maximum = max(maximum, active)
            await gate.wait()
            active -= 1

    tasks = [asyncio.create_task(worker(index)) for index in range(4)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert maximum == 2
    gate.set()
    await asyncio.gather(*tasks)


async def test_principal_limit_is_shared_across_providers() -> None:
    limiters = ProviderLimiters(provider_limit=5, principal_limit=1)
    owner = AuthContext(principal_id="alice", tenant_id="tenant")
    active = 0
    maximum = 0

    async def worker(provider: str) -> None:
        nonlocal active, maximum
        async with limiters.acquire(provider, owner):  # type: ignore[arg-type]
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(worker("modelark"), worker("seed-speech"))
    assert maximum == 1


async def test_local_principal_is_bounded_only_by_provider_limit() -> None:
    limiters = ProviderLimiters(provider_limit=3, principal_limit=1)
    owner = AuthContext()  # local stdio principal
    active = 0
    maximum = 0

    async def worker() -> None:
        nonlocal active, maximum
        async with limiters.acquire("modelark", owner):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(worker(), worker(), worker())
    assert maximum == 3


async def test_remote_principal_is_still_bounded_by_principal_limit() -> None:
    limiters = ProviderLimiters(provider_limit=5, principal_limit=2)
    owner = AuthContext(principal_id="alice", tenant_id="tenant", transport="http")
    active = 0
    maximum = 0

    async def worker() -> None:
        nonlocal active, maximum
        async with limiters.acquire("modelark", owner):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(worker(), worker(), worker())
    assert maximum == 2


async def test_owner_backlog_does_not_hold_provider_slots_needed_by_other_owners() -> None:
    limiters = ProviderLimiters(provider_limit=2, principal_limit=1)
    alice = AuthContext(principal_id="alice", tenant_id="tenant")
    bob = AuthContext(principal_id="bob", tenant_id="tenant")
    waiting = asyncio.Event()

    async def alice_again() -> None:
        waiting.set()
        async with limiters.acquire("modelark", alice):
            pass

    async with limiters.acquire("modelark", alice):
        backlog = asyncio.create_task(alice_again())
        try:
            await waiting.wait()
            async with asyncio.timeout(0.1), limiters.acquire("modelark", bob):
                assert not backlog.done()
        finally:
            backlog.cancel()
            await asyncio.gather(backlog, return_exceptions=True)


@pytest.mark.parametrize("local", [False, True])
async def test_admission_timeout_releases_partial_owner_slot(local: bool) -> None:
    limiters = ProviderLimiters(provider_limit=1, principal_limit=1, admission_timeout_seconds=0.01)
    owner = AuthContext() if local else AuthContext(principal_id="alice", tenant_id="tenant")
    provider = limiters.provider("modelark")
    await provider.acquire()
    try:
        with pytest.raises(ProviderError) as raised:
            async with limiters.acquire("modelark", owner):
                pytest.fail("No provider slot was available")
        error = raised.value
        assert error.code == "ADMISSION_TIMEOUT"
        assert error.operation == "admission"
        assert error.retryable and error.ambiguous_completion is False
        assert "this attempt did not dispatch" in error.message.lower()
        async with limiters.acquire("seed-speech", owner):
            pass
    finally:
        provider.release()
    async with limiters.acquire("modelark", owner):
        pass
    assert len(limiters._principals) == 0


async def test_active_owner_map_is_bounded_and_never_evicts_held_or_waiting_entries() -> None:
    limiters = ProviderLimiters(
        provider_limit=2,
        principal_limit=1,
        principal_cache_size=1,
        admission_timeout_seconds=0.01,
    )
    alice = AuthContext(principal_id="alice", tenant_id="tenant")
    bob = AuthContext(principal_id="bob", tenant_id="tenant")
    async with limiters.acquire("modelark", alice):
        with pytest.raises(ProviderError) as raised:
            async with limiters.acquire("modelark", bob):
                pytest.fail("Active owner must remain pinned")
        assert raised.value.operation == "admission"
        assert raised.value.retryable and not raised.value.ambiguous_completion
        with pytest.raises(ProviderError):
            async with limiters.acquire("seed-speech", alice):
                pytest.fail("An active owner must not receive a replacement semaphore")
        assert len(limiters._principals) == 1
    assert len(limiters._principals) == 0
    async with limiters.acquire("modelark", bob):
        assert len(limiters._principals) == 1
    assert len(limiters._principals) == 0


async def test_admission_waiting_owner_is_pinned_and_cancellation_releases_it() -> None:
    limiters = ProviderLimiters(provider_limit=1, principal_cache_size=1)
    owner = AuthContext(principal_id="alice", tenant_id="tenant")
    await limiters.provider("modelark").acquire()
    waiting = asyncio.Event()

    async def blocked() -> None:
        waiting.set()
        async with limiters.acquire("modelark", owner):
            pytest.fail("Cancelled admission must not enter")

    pending = asyncio.create_task(blocked())
    await waiting.wait()
    try:
        assert len(limiters._principals) == 1
        with pytest.raises(ProviderError):
            async with limiters.acquire(
                "seed-speech", AuthContext(principal_id="bob", tenant_id="tenant")
            ):
                pytest.fail("Waiting owner must remain pinned")
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        limiters.provider("modelark").release()
    assert len(limiters._principals) == 0
    async with limiters.acquire("modelark", owner):
        pass


async def test_admission_timeout_does_not_limit_operation_after_acquisition() -> None:
    limiters = ProviderLimiters(admission_timeout_seconds=0.001)
    async with limiters.acquire("modelark", AuthContext()):
        await asyncio.sleep(0.01)


async def test_http_principal_requires_a_live_provider_credential_scope(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_AUTH_MODE="byok",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        ARTIFACT_DIR=str(tmp_path / "artifacts"),
        BYTEPLUS_MODELARK_API_KEY="sk-test-operator",  # pragma: allowlist secret
    )
    runtime = await create_runtime_services(settings)
    context = FakeContext(lifespan_context={"runtime": runtime})
    try:
        with pytest.raises(PermissionError):
            get_principal(context)
        with request_credentials_scope(
            [(b"x-modelark-api-key", b"synthetic-customer-a"), (b"x-mcp-client-secret", b"b" * 64)]
        ):
            with pytest.raises(PermissionError):
                get_principal(context)
            with provider_scope(settings, "modelark"):
                principal = get_principal(context)
                assert principal == request_principal()
                assert principal.transport == "http"
                assert not principal.is_local
                assert principal.scopes == frozenset()
                assert principal.principal_id not in {"local", "shared-team"}
            with pytest.raises(PermissionError):
                get_principal(context)
        with pytest.raises(PermissionError):
            get_principal(context)
    finally:
        await close_runtime_services(runtime)


@pytest.mark.parametrize("auth_mode", ["local", "byok"])
async def test_stdio_principal_is_local_without_bearer_context(
    tmp_path: Path, auth_mode: str
) -> None:
    runtime = await create_runtime_services(
        Settings(_env_file=None, MCP_AUTH_MODE=auth_mode, ARTIFACT_DIR=str(tmp_path))
    )
    try:
        principal = get_principal(FakeContext(lifespan_context={"runtime": runtime}))
        assert principal == AuthContext()
        assert principal.is_local
    finally:
        await close_runtime_services(runtime)


class TestStateSweeper:
    """The background sweeper prunes artifacts, ownership, budget, and cache."""

    async def test_sweeper_invokes_all_prune_steps(self) -> None:
        events: list[str] = []

        async def _delete_expired(now: datetime) -> int:
            events.append("artifact")
            return 1

        async def _prune_ownership(max_age_days: int) -> int:
            events.append("ownership")
            return 1

        async def _prune_budget(max_age_days: int) -> int:
            events.append("budget")
            return 1

        async def _prune_cache() -> int:
            events.append("cache")
            return 1

        runtime = SimpleNamespace(
            artifact_store=SimpleNamespace(delete_expired=_delete_expired),
            ownership_store=SimpleNamespace(prune=_prune_ownership),
            budget_ledger=SimpleNamespace(prune=_prune_budget),
            task_artifact_cache=SimpleNamespace(prune_expired=_prune_cache),
        )
        settings = SimpleNamespace(
            artifact_sweep_interval_seconds=0.01,
            state_prune_max_age_days=30,
        )
        task = asyncio.create_task(_state_sweeper(runtime, settings))
        await asyncio.sleep(0.05)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        expected = ["artifact", "ownership", "budget", "cache"]
        assert events[: len(expected)] == expected
        assert all(events[index] == expected[index % 4] for index in range(len(events)))

    async def test_lifespan_spawns_and_cancels_sweeper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def _fake_sweeper(_runtime: RuntimeServices, _settings: Settings) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(
            "ark_mcp.runtime._state_sweeper",
            _fake_sweeper,
        )

        class _FakeArtifactStore:
            async def close(self) -> None:
                return None

        class _FakeOwnershipStore:
            async def close(self) -> None:
                return None

        class _FakeObjectKeyOwnershipStore:
            async def close(self) -> None:
                return None

        class _FakeBudgetLedger:
            async def close(self) -> None:
                return None

        class _FakeTaskArtifactCache:
            async def close(self) -> None:
                return None

        services = RuntimeServices(
            settings=Settings(_env_file=None),
            artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
            safe_downloader=_FakeArtifactStore(),  # type: ignore[arg-type]
            ownership_store=_FakeOwnershipStore(),  # type: ignore[arg-type]
            object_key_ownership_store=_FakeObjectKeyOwnershipStore(),  # type: ignore[arg-type]
            budget_ledger=_FakeBudgetLedger(),  # type: ignore[arg-type]
            provider_limiters=SimpleNamespace(),  # type: ignore[arg-type]
            task_artifact_cache=_FakeTaskArtifactCache(),  # type: ignore[arg-type]
            task_artifact_locks=TaskArtifactPersistenceLocks(),
        )

        async def _factory(_settings: Settings) -> RuntimeServices:
            return services

        lifespan = build_lifespan(Settings(_env_file=None), _factory)
        async with lifespan(None) as context:  # type: ignore[arg-type]
            assert context == {"runtime": services}
            await asyncio.wait_for(started.wait(), timeout=1.0)

        assert cancelled.is_set()


class TestPruneMethods:
    """Prune methods delete only rows older than the configured threshold."""

    async def test_ownership_store_prune_deletes_only_aged_rows(self, tmp_path: Path) -> None:
        store = SQLiteTaskOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("modelark", "fresh-task", owner)
        await store.record("modelark", "aged-task", owner)
        aged = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        store._connection.execute(
            "UPDATE task_ownership SET created_at = ? WHERE task_id = ?",
            (aged, "aged-task"),
        )
        store._connection.commit()

        pruned = await store.prune(30)

        assert pruned == 1
        assert await _owned_ids(store, "modelark", owner) == ["fresh-task"]
        await store.close()

    async def test_task_artifact_cache_prune_expired_deletes_only_expired(
        self, tmp_path: Path
    ) -> None:
        cache = SQLiteTaskArtifactCache(tmp_path / "runtime.sqlite3", ttl_seconds=60)
        await cache.set("modelark", "fresh", {"video": _make_ref("fresh"), "last_frame": None})
        await cache.set("modelark", "expired", {"video": _make_ref("expired"), "last_frame": None})
        old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
        cache._connection.execute(
            "UPDATE task_artifacts SET created_at = ? WHERE task_id = ?",
            (old, "expired"),
        )
        cache._connection.commit()

        pruned = await cache.prune_expired()

        assert pruned == 1
        assert await cache.get("modelark", "fresh") is not None
        assert await cache.get("modelark", "expired") is None
        await cache.close()

    async def test_budget_ledger_prune_deletes_only_aged_rows(self, tmp_path: Path) -> None:
        ledger = BudgetLedger(tmp_path / "runtime.sqlite3", daily_limit_usd=None)
        ledger._connection.execute(
            "INSERT INTO budget_reservations(usage_date, principal_id, tenant_id, product, amount_usd, status) "
            "VALUES (?, ?, ?, ?, ?, 'committed')",
            ("2099-01-01", "alice", "tenant-a", "video", 0.07),
        )
        ledger._connection.execute(
            "INSERT INTO budget_reservations(usage_date, principal_id, tenant_id, product, amount_usd, status) "
            "VALUES (?, ?, ?, ?, ?, 'committed')",
            ("2020-01-01", "alice", "tenant-a", "video", 0.07),
        )
        ledger._connection.commit()

        pruned = await ledger.prune(30)

        assert pruned == 1
        remaining = ledger._connection.execute(
            "SELECT COUNT(*) FROM budget_reservations"
        ).fetchone()
        assert remaining is not None and remaining[0] == 1
        await ledger.close()


class TestObjectKeyOwnershipStore:
    """Object-storage key ownership ledger: record, require, prune."""

    async def test_record_then_require_owner_succeeds(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("references/video/abc", owner)
        await store.require_owner("references/video/abc", owner)
        await store.close()

    async def test_require_owner_rejects_different_principal(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("references/video/abc", owner)
        other = AuthContext(principal_id="mallory", tenant_id="tenant-a")
        with pytest.raises(PermissionError, match="not owned"):
            await store.require_owner("references/video/abc", other)
        await store.close()

    async def test_unknown_key_allowed_for_local_owner(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        await store.require_owner("references/video/unknown", AuthContext())
        await store.close()

    async def test_unknown_key_rejected_for_remote_owner(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        remote = AuthContext(principal_id="alice", tenant_id="tenant-a", transport="http")
        with pytest.raises(PermissionError, match="not owned"):
            await store.require_owner("references/video/unknown", remote)
        await store.close()

    async def test_prune_deletes_only_aged_rows(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("references/video/fresh", owner)
        await store.record("references/video/aged", owner)
        aged = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        store._connection.execute(
            "UPDATE object_key_ownership SET created_at = ? WHERE object_key = ?",
            (aged, "references/video/aged"),
        )
        store._connection.commit()

        pruned = await store.prune(30)

        assert pruned == 1
        await store.require_owner("references/video/fresh", owner)
        with pytest.raises(PermissionError, match="not owned"):
            await store.require_owner(
                "references/video/aged",
                AuthContext(principal_id="alice", tenant_id="tenant-a", transport="http"),
            )
        await store.close()

    async def test_require_owner_refreshes_created_at(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("references/video/abc", owner)
        aged = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        store._connection.execute(
            "UPDATE object_key_ownership SET created_at = ? WHERE object_key = ?",
            (aged, "references/video/abc"),
        )
        store._connection.commit()

        await store.require_owner("references/video/abc", owner)

        refreshed = store._connection.execute(
            "SELECT created_at FROM object_key_ownership WHERE object_key = ?",
            ("references/video/abc",),
        ).fetchone()
        assert refreshed is not None
        assert (datetime.now(UTC) - datetime.fromisoformat(refreshed[0])).total_seconds() < 5
        await store.close()

    async def test_record_upsert_refreshes_created_at(self, tmp_path: Path) -> None:
        store = SQLiteObjectKeyOwnershipStore(tmp_path / "runtime.sqlite3")
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        await store.record("references/video/abc", owner)
        aged = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        store._connection.execute(
            "UPDATE object_key_ownership SET created_at = ? WHERE object_key = ?",
            (aged, "references/video/abc"),
        )
        store._connection.commit()

        await store.record("references/video/abc", owner)

        refreshed = store._connection.execute(
            "SELECT created_at FROM object_key_ownership WHERE object_key = ?",
            ("references/video/abc",),
        ).fetchone()
        assert refreshed is not None
        assert (datetime.now(UTC) - datetime.fromisoformat(refreshed[0])).total_seconds() < 5
        await store.close()


class TestArtifactBackendSelection:
    """``create_runtime_services`` selects the artifact store from settings."""

    async def test_filesystem_backend_yields_filesystem_store(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            ARTIFACT_DIR=str(tmp_path / "artifacts"),
            ARTIFACT_BACKEND="filesystem",
        )
        runtime = await create_runtime_services(settings)
        try:
            from ark_mcp.artifacts.filesystem_store import FilesystemArtifactStore

            assert isinstance(runtime.artifact_store, FilesystemArtifactStore)
        finally:
            await close_runtime_services(runtime)

    async def test_object_storage_backend_yields_object_storage_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ark_mcp.artifacts.object_storage_store import ObjectStorageArtifactStore

        fake_gateway = SimpleNamespace(
            upload_bytes=_async_noop(),
            presign_get=_async_noop(),
            close=_async_noop(),
        )
        monkeypatch.setattr(
            "ark_mcp.artifacts.object_storage_store.make_object_storage_gateway",
            lambda _settings: fake_gateway,
        )
        settings = Settings(
            _env_file=None,
            ARTIFACT_DIR=str(tmp_path / "artifacts"),
            ARTIFACT_BACKEND="object_storage",
            TOS_ACCESS_KEY="ak-tos",
            TOS_SECRET_KEY="sk-tos",  # pragma: allowlist secret
            TOS_BUCKET="bucket",
        )
        runtime = await create_runtime_services(settings)
        try:
            assert isinstance(runtime.artifact_store, ObjectStorageArtifactStore)
        finally:
            await close_runtime_services(runtime)


def _async_noop() -> object:
    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    return _noop


class _FakeObjectGateway:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str) -> None:
        del mime_type
        self.objects[key] = data

    async def presign_get(self, *, key: str, expires: int | None = None) -> str:
        del expires
        return f"presigned://{key}"

    async def close(self) -> None:
        return None


class _FakeObjectDownloader:
    def __init__(self, gateway: _FakeObjectGateway) -> None:
        self._gateway = gateway

    async def download(
        self,
        url: str,
        *,
        trusted_hosts: object,
        max_bytes: int,
        max_redirects: int = 5,
    ) -> object:
        del trusted_hosts, max_bytes, max_redirects
        from ark_mcp.security.safe_downloader import DownloadedMedia

        return DownloadedMedia(
            body=self._gateway.objects[url.removeprefix("presigned://")],
            content_type=None,
            final_url=url,
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def object_store(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, _FakeObjectGateway]:
    from ark_mcp.artifacts.object_storage_store import ObjectStorageArtifactStore

    gateway = _FakeObjectGateway()
    downloader = _FakeObjectDownloader(gateway)
    monkeypatch.setattr(
        "ark_mcp.artifacts.object_storage_store.make_object_storage_gateway",
        lambda _settings: gateway,
    )
    store = ObjectStorageArtifactStore(
        settings=Settings(_env_file=None),
        ttl_seconds=3600,
        downloader=downloader,  # type: ignore[arg-type]
    )
    return store, gateway


class TestObjectStorageArtifactStore:
    """The object-storage store preserves bytes, MIME, and ownership."""

    async def test_put_get_round_trip_preserves_bytes_mime_and_ownership(
        self, object_store: tuple[object, _FakeObjectGateway]
    ) -> None:
        store, _gateway = object_store
        raw = b"fake image payload"
        owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
        ref = await store.put_base64(  # type: ignore[attr-defined]
            data=base64.b64encode(raw).decode(),
            media_type="image",
            mime_type="image/png",
            auth=owner,
        )

        stored = await store.get(ref.id, auth=owner)  # type: ignore[attr-defined]

        assert stored.data == raw
        assert stored.media_type == "image"
        assert stored.mime_type == "image/png"
        assert stored.artifact_id == ref.id

    async def test_cross_tenant_get_raises_permission_error(
        self, object_store: tuple[object, _FakeObjectGateway]
    ) -> None:
        store, _gateway = object_store
        ref = await store.put_base64(  # type: ignore[attr-defined]
            data=base64.b64encode(b"alice bytes").decode(),
            media_type="audio",
            mime_type="audio/wav",
            auth=AuthContext(principal_id="alice", tenant_id="tenant-a"),
        )

        with pytest.raises(PermissionError):
            await store.get(  # type: ignore[attr-defined]
                ref.id,
                auth=AuthContext(principal_id="alice", tenant_id="tenant-b"),
            )

    async def test_delete_expired_returns_zero(
        self, object_store: tuple[object, _FakeObjectGateway]
    ) -> None:
        store, _gateway = object_store
        assert await store.delete_expired(datetime.now(UTC)) == 0  # type: ignore[attr-defined]


def test_task_ownership_no_longer_exposes_execution_claim_api() -> None:
    assert not hasattr(TaskOwnershipStore, "claim")
    assert not hasattr(SQLiteTaskOwnershipStore, "claim")


async def test_task_record_is_idempotent_and_survives_reopening(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    owner = AuthContext(principal_id="alice", tenant_id="tenant-a")
    store = SQLiteTaskOwnershipStore(database)
    try:
        await asyncio.gather(*(store.record("modelark", "task-one", owner) for _ in range(8)))
        await store.record("modelark", "task-two", owner)
        assert await _owned_ids(store, "modelark", owner) == ["task-two", "task-one"]
    finally:
        await store.close()
    reopened = SQLiteTaskOwnershipStore(database)
    try:
        await reopened.record("modelark", "task-one", owner)
        await reopened.require_owner("modelark", "task-one", owner)
        assert await _owned_ids(reopened, "modelark", owner) == ["task-two", "task-one"]
    finally:
        await reopened.close()


async def _owned_ids(
    store: SQLiteTaskOwnershipStore, provider: str, owner: AuthContext
) -> list[str]:
    since = datetime.now(UTC) - timedelta(days=3650)
    rows = await store.list_owned_tasks(provider, owner, since=since, before=None, limit=1000)
    return [row.task_id for row in rows]


async def test_owned_tasks_are_listed_newest_first_with_keyset_cursor(tmp_path: Path) -> None:
    store = SQLiteTaskOwnershipStore(tmp_path / "runtime.sqlite3")
    alice = AuthContext(principal_id="alice", tenant_id="tenant-a")
    for task_id in ("t-1", "t-2", "t-3", "t-4"):
        await store.record("modelark", task_id, alice)
    await store.record("modelark", "bob-1", AuthContext(principal_id="bob", tenant_id="tenant-a"))
    since = datetime.now(UTC) - timedelta(days=1)

    first = await store.list_owned_tasks("modelark", alice, since=since, before=None, limit=2)
    assert [row.task_id for row in first] == ["t-4", "t-3"]
    cursor = (first[-1].created_at, first[-1].task_id)
    second = await store.list_owned_tasks("modelark", alice, since=since, before=cursor, limit=2)
    assert [row.task_id for row in second] == ["t-2", "t-1"]
    last = (second[-1].created_at, second[-1].task_id)
    assert await store.list_owned_tasks("modelark", alice, since=since, before=last, limit=2) == []
    await store.close()


async def test_owned_tasks_respect_since_and_tie_break_on_task_id(tmp_path: Path) -> None:
    store = SQLiteTaskOwnershipStore(tmp_path / "runtime.sqlite3")
    alice = AuthContext(principal_id="alice", tenant_id="tenant-a")
    same_time = datetime(2026, 10, 17, 12, 0, tzinfo=UTC).isoformat(timespec="microseconds")
    old = datetime(2026, 9, 1, tzinfo=UTC).isoformat(timespec="microseconds")
    store._connection.executemany(
        "INSERT INTO task_ownership VALUES (?, ?, ?, ?, ?)",
        [
            ("modelark", "a", "alice", "tenant-a", same_time),
            ("modelark", "b", "alice", "tenant-a", same_time),
            ("modelark", "old", "alice", "tenant-a", old),
        ],
    )
    since = datetime(2026, 10, 1, tzinfo=UTC)
    rows = await store.list_owned_tasks("modelark", alice, since=since, before=None, limit=10)
    assert [row.task_id for row in rows] == ["b", "a"]
    cursor = (rows[0].created_at, rows[0].task_id)
    after_b = await store.list_owned_tasks("modelark", alice, since=since, before=cursor, limit=10)
    assert [row.task_id for row in after_b] == ["a"]
    await store.close()


async def test_ownership_index_exists_and_reopening_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    SQLiteTaskOwnershipStore(database)._connection.close()
    store = SQLiteTaskOwnershipStore(database)
    indexes = {
        row[1] for row in store._connection.execute("PRAGMA index_list(task_ownership)").fetchall()
    }
    assert "task_ownership_owner_created" in indexes
    await store.close()
