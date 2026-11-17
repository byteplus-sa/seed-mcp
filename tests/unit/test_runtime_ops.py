"""Runtime ownership from specs/SPEC_VKE_DEPLOYMENT.md."""

from __future__ import annotations

import asyncio
import gc
import os
import select
import sqlite3
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.runtime import close_runtime_services, create_runtime_services
from ark_mcp.runtime_lock import RuntimeStateLease


def http_settings(path: Path, **values: object) -> Settings:
    return Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        ARTIFACT_DIR=str(path),
        **values,
    )


async def test_http_overlap_does_not_open_stores_or_recover_running_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    assert stat.S_IMODE((tmp_path / "runtime.sqlite3.lock").stat().st_mode) == 0o600
    assert runtime.submission_store is not None
    record, _ = await runtime.submission_store.claim(
        provider="modelark",
        tenant_id="tenant",
        principal_id="owner",
        tool_name="seedance_create_task",
        key_digest="digest",
        request_digest="input",
    )
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob("runtime.sqlite3*")
        if not path.name.endswith((".lock", "-shm"))
    }
    try:
        with monkeypatch.context() as patch:

            def forbidden(*args: object, **kwargs: object) -> None:
                pytest.fail("Overlapping runtime opened state")

            patch.setattr("ark_mcp.runtime.build_state_stores", forbidden)
            with pytest.raises(RuntimeError, match="Runtime state is already in use"):
                await create_runtime_services(http_settings(tmp_path))
        assert (await runtime.submission_store.get(record.submission_id)).state == "running"
        assert before == {
            path.name: path.read_bytes()
            for path in tmp_path.glob("runtime.sqlite3*")
            if not path.name.endswith((".lock", "-shm"))
        }
    finally:
        await close_runtime_services(runtime)
    assert (tmp_path / "runtime.sqlite3.lock").is_file()
    restarted = await create_runtime_services(http_settings(tmp_path))
    try:
        assert restarted.submission_store is not None
        assert (await restarted.submission_store.get(record.submission_id)).state == "unresolved"
    finally:
        await close_runtime_services(restarted)


async def test_stdio_does_not_acquire_lease_or_start_metrics(tmp_path: Path) -> None:
    first = await create_runtime_services(Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path)))
    second = await create_runtime_services(Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path)))
    try:
        assert first.state_lease is None and second.state_lease is None
        assert first.metrics_listener is None and second.metrics_listener is None
        assert not (tmp_path / "runtime.sqlite3.lock").exists()
    finally:
        await close_runtime_services(first)
        await close_runtime_services(second)


async def test_acquisition_result_race_drains_repeated_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = RuntimeStateLease(tmp_path / "runtime.sqlite3")
    acquired = threading.Event()
    finish = threading.Event()
    original = lease._lock.acquire

    def delayed_acquire(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        acquired.set()
        assert finish.wait(5)
        return result

    monkeypatch.setattr(lease._lock, "acquire", delayed_acquire)
    pending = asyncio.create_task(lease.acquire())
    try:
        assert await asyncio.to_thread(acquired.wait, 5)
        for _ in range(3):
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
        contender = RuntimeStateLease(tmp_path / "runtime.sqlite3")
        with pytest.raises(RuntimeError, match="already in use"):
            await contender.acquire()
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await contender.acquire()
    await contender.close()


@pytest.mark.parametrize("failure", [OSError("private-path-canary"), NotImplementedError])
async def test_hard_lock_failure_is_fixed_and_never_opens_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException | type[BaseException]
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("filelock.FileLock.acquire", fail)
    with pytest.raises(RuntimeError) as raised:
        await create_runtime_services(http_settings(tmp_path))
    assert str(raised.value) == "Runtime state requires an available exclusive filesystem lock."
    assert not (tmp_path / "runtime.sqlite3").exists()


async def test_partial_store_initialization_closes_every_connection_and_releases_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ark_mcp.runtime as module

    connections: list[sqlite3.Connection] = []
    original = module._open_sqlite_connection

    def tracked(path: Path) -> sqlite3.Connection:
        connection = original(path)
        connections.append(connection)
        return connection

    def fail_schema(self: object) -> None:
        raise ValueError("synthetic schema failure")

    with monkeypatch.context() as patch:
        patch.setattr(module, "_open_sqlite_connection", tracked)
        patch.setattr(module.SQLiteTaskArtifactCache, "_ensure_schema", fail_schema)
        with pytest.raises(ValueError, match="synthetic schema"):
            await create_runtime_services(http_settings(tmp_path))
    assert len(connections) == 4
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    restarted = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(restarted)


@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_constructor_close_failure_keeps_runtime_fenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    import ark_mcp.runtime as module

    connections: list[sqlite3.Connection] = []
    entered, finish = threading.Event(), threading.Event()

    class RefusingClose(sqlite3.Connection):
        refuse = True

        def close(self) -> None:
            if self.refuse:
                entered.set()
                assert finish.wait(5)
                raise OSError("synthetic constructor close failure")
            super().close()

    def tracked(path: Path) -> sqlite3.Connection:
        factory = RefusingClose if len(connections) == 3 else sqlite3.Connection
        connection = sqlite3.connect(path, check_same_thread=False, factory=factory)
        connections.append(connection)
        return connection

    def fail_schema(self: object) -> None:
        raise ValueError("synthetic schema failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "_open_sqlite_connection", tracked)
            patch.setattr(module.SQLiteTaskArtifactCache, "_ensure_schema", fail_schema)
            pending = asyncio.create_task(create_runtime_services(http_settings(tmp_path)))
            assert await asyncio.to_thread(entered.wait, 5)
            if cancel:
                for _ in range(3):
                    pending.cancel()
                    await asyncio.sleep(0)
            finish.set()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await pending
        assert connections[-1].execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(RuntimeError, match="already in use"):
            await create_runtime_services(http_settings(tmp_path))
    finally:
        finish.set()
        RefusingClose.refuse = False
        for connection in connections:
            connection.close()
        for lease in tuple(RuntimeStateLease._held):
            if lease._lock.lock_file == str(tmp_path / "runtime.sqlite3.lock"):
                await lease.close()
    restarted = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(restarted)


async def test_shutdown_holds_lease_through_failure_and_repeated_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    assert runtime.submission_store is not None
    entered, finish = asyncio.Event(), asyncio.Event()
    original = runtime.submission_store.close

    async def delayed_close() -> None:
        entered.set()
        await finish.wait()
        raise RuntimeError("synthetic close failure")

    monkeypatch.setattr(runtime.submission_store, "close", delayed_close)
    pending = asyncio.create_task(close_runtime_services(runtime))
    await entered.wait()
    try:
        for _ in range(3):
            pending.cancel()
            await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="already in use"):
            await create_runtime_services(http_settings(tmp_path))
        assert not pending.done()
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    for store in (
        runtime.ownership_store,
        runtime.object_key_ownership_store,
        runtime.budget_ledger,
        runtime.task_artifact_cache,
    ):
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            store._connection.execute("SELECT 1")
    assert not runtime.submission_store._closed
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            await create_runtime_services(http_settings(tmp_path))
    finally:
        await original()
        assert runtime.state_lease is not None
        await runtime.state_lease.close()
    restarted = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(restarted)


@pytest.mark.parametrize("phase", ["startup_failure", "startup_cancel", "shutdown"])
async def test_release_failure_keeps_lease_after_all_cleanup_and_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import ark_mcp.runtime as module

    acquired: list[RuntimeStateLease] = []
    connections: list[sqlite3.Connection] = []
    original_open = module._open_sqlite_connection
    original_submission = module.SQLiteSubmissionStore
    started, finish = threading.Event(), threading.Event()

    def tracked_open(path: Path) -> sqlite3.Connection:
        connection = original_open(path)
        connections.append(connection)
        return connection

    def release_failure(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic release failure")

    def lease_factory(path: Path) -> RuntimeStateLease:
        lease = RuntimeStateLease(path)
        acquired.append(lease)
        patch.setattr(lease._lock, "release", release_failure)
        return lease

    def fail_limiters(*args: object, **kwargs: object) -> None:
        raise ValueError("synthetic startup failure")

    def delayed_submission(*args: object, **kwargs: object) -> object:
        result = original_submission(*args, **kwargs)
        started.set()
        assert finish.wait(5)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(module, "RuntimeStateLease", lease_factory)
        patch.setattr(module, "_open_sqlite_connection", tracked_open)
        if phase == "startup_failure":
            patch.setattr(module, "ProviderLimiters", fail_limiters)
            with pytest.raises(ValueError, match="synthetic startup"):
                await create_runtime_services(http_settings(tmp_path))
        elif phase == "startup_cancel":
            patch.setattr(module, "SQLiteSubmissionStore", delayed_submission)
            pending = asyncio.create_task(create_runtime_services(http_settings(tmp_path)))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                for _ in range(3):
                    pending.cancel()
                    await asyncio.sleep(0)
                assert not pending.done()
            finally:
                finish.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            runtime = await create_runtime_services(http_settings(tmp_path))
            with pytest.raises(OSError, match="synthetic release"):
                await close_runtime_services(runtime)
    assert len(acquired) == 1 and len(connections) == 4
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    lease = acquired.pop()
    assert lease in RuntimeStateLease._held
    del lease
    gc.collect()
    with pytest.raises(RuntimeError, match="already in use"):
        await create_runtime_services(http_settings(tmp_path))
    retained = next(
        lease
        for lease in RuntimeStateLease._held
        if lease._lock.lock_file == str(tmp_path / "runtime.sqlite3.lock")
    )
    await retained.close()
    restarted = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(restarted)


async def test_cancelled_submission_constructor_result_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ark_mcp.runtime as module

    started, finish = threading.Event(), threading.Event()
    original = module.SQLiteSubmissionStore
    stores: list[object] = []

    def delayed(*args: object, **kwargs: object) -> object:
        store = original(*args, **kwargs)
        stores.append(store)
        started.set()
        assert finish.wait(5)
        return store

    with monkeypatch.context() as patch:
        patch.setattr(module, "SQLiteSubmissionStore", delayed)
        pending = asyncio.create_task(create_runtime_services(http_settings(tmp_path)))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            for _ in range(3):
                pending.cancel()
                await asyncio.sleep(0)
            assert not pending.done()
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert stores[0]._closed
    restarted = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(restarted)


_CHILD = """
import asyncio, sys
from pathlib import Path
from ark_mcp.config.env import Settings
from ark_mcp.runtime import create_runtime_services, close_runtime_services
Settings.model_config["env_file"] = None
async def main():
    settings = Settings(_env_file=None, MCP_TRANSPORT="http",
        MCP_IDENTITY_HMAC_KEY="a"*64, ARTIFACT_DIR=sys.argv[1])
    runtime = await create_runtime_services(settings)
    try:
        record, created = await runtime.submission_store.claim(
            provider="modelark", tenant_id="tenant", principal_id="owner",
            tool_name="seedance_create_task", key_digest="key", request_digest="input")
        if sys.argv[2] == "hold":
            assert created
            await runtime.submission_store.record_task(record.submission_id, "task-safe", None)
            print("ready", flush=True)
            await asyncio.Event().wait()
        else:
            assert not created and record.state == "unresolved"
            assert record.tasks == (("task-safe", None),)
            print("recovered", flush=True)
    finally:
        await close_runtime_services(runtime)
asyncio.run(main())
"""


def test_separate_process_contention_crash_and_restart(tmp_path: Path) -> None:
    environment = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
    }
    command = [sys.executable, "-c", _CHILD, str(tmp_path), "hold"]
    child = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        ready, _, _ = select.select([child.stdout], [], [], 15)
        assert ready and child.stdout.readline().strip() == "ready"
        before = {
            path.name: path.read_bytes()
            for path in tmp_path.glob("runtime.sqlite3*")
            if not path.name.endswith((".lock", "-shm"))
        }
        conflict = subprocess.run(
            command,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert conflict.returncode != 0
        assert "Runtime state is already in use" in conflict.stderr
        assert before == {
            path.name: path.read_bytes()
            for path in tmp_path.glob("runtime.sqlite3*")
            if not path.name.endswith((".lock", "-shm"))
        }
    finally:
        child.kill()
        child.communicate(timeout=10)
    assert (tmp_path / "runtime.sqlite3.lock").exists()
    recovered = subprocess.run(
        [*command[:-1], "recover"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip() == "recovered"
