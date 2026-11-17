"""Storage contract from plans/PLAN_SQLITE_SUBMISSION_SAFETY.md."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ark_mcp.submission_store import (
    IDENTIFIER_PATTERN,
    SQLiteSubmissionStore,
    SubmissionConflictError,
    SubmissionRecord,
)


def _scope(**changes: str) -> dict[str, str]:
    return {
        "provider": "modelark",
        "tenant_id": "synthetic-tenant",
        "principal_id": "synthetic-owner",
        "tool_name": "seedance_create_task",
        "key_digest": "synthetic-key-digest",
        "request_digest": "synthetic-request-digest",
    } | changes


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SQLiteSubmissionStore]:
    instance = await asyncio.to_thread(SQLiteSubmissionStore, tmp_path / "runtime.sqlite3")
    try:
        yield instance
    finally:
        await instance.close()


async def test_claim_returns_immutable_record_and_private_uuid(
    store: SQLiteSubmissionStore,
) -> None:
    record, created = await store.claim(**_scope())
    assert created is True
    assert UUID(record.submission_id).version == 4
    assert record == SubmissionRecord(record.submission_id, "running", None, ())
    assert await store.get(record.submission_id) == record
    assert await store.claim(**_scope()) == (record, False)
    with pytest.raises(FrozenInstanceError):
        record.__setattr__("state", "succeeded")


def test_identifier_pattern_is_available_to_coordinator() -> None:
    assert IDENTIFIER_PATTERN == r"[A-Za-z0-9._:-]{1,256}"


@pytest.mark.parametrize(
    "dimension", ["provider", "tenant_id", "principal_id", "tool_name", "key_digest"]
)
async def test_claim_scope_dimensions_are_isolated(
    store: SQLiteSubmissionStore, dimension: str
) -> None:
    original, _ = await store.claim(**_scope())
    other, created = await store.claim(**_scope(**{dimension: "other-value"}))
    assert created is True
    assert other.submission_id != original.submission_id
    await store.record_task(other.submission_id, "other-task", None)
    assert await store.get(original.submission_id) == original


async def test_conflicting_request_leaves_original_claim_unchanged(
    store: SQLiteSubmissionStore,
) -> None:
    record, _ = await store.claim(**_scope())
    with pytest.raises(SubmissionConflictError):
        await store.claim(**_scope(request_digest="different-request"))
    assert await store.claim(**_scope()) == (record, False)
    assert (await store.claim(**_scope(key_digest="another-key")))[1] is True


async def test_claim_is_atomic_across_connections(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        results = await asyncio.gather(
            *(instance.claim(**_scope()) for instance in (first, second) * 12)
        )
        assert sum(created for _, created in results) == 1
        assert len({record.submission_id for record, _ in results}) == 1
        assert {record.state for record, _ in results} == {"running"}
    finally:
        await asyncio.gather(first.close(), second.close())


async def test_conflicting_concurrent_claims_have_one_winner(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        results = await asyncio.gather(
            first.claim(**_scope()),
            second.claim(**_scope(request_digest="different-request")),
            return_exceptions=True,
        )
        assert sum(isinstance(result, SubmissionConflictError) for result in results) == 1
        winners = [result for result in results if isinstance(result, tuple)]
        assert len(winners) == 1
        assert winners[0][1] is True
    finally:
        await asyncio.gather(first.close(), second.close())


@pytest.mark.parametrize("state", ["running", "succeeded", "unresolved"])
async def test_capacity_preserves_existing_keys_and_conflicts(tmp_path: Path, state: str) -> None:
    instance = await asyncio.to_thread(
        SQLiteSubmissionStore, tmp_path / "runtime.sqlite3", max_records=1
    )
    try:
        record, _ = await instance.claim(**_scope())
        if state == "succeeded":
            await instance.succeed(record.submission_id, '{"task_id":"task-1"}')
        elif state == "unresolved":
            await instance.mark_unresolved(record.submission_id)
        with pytest.raises(RuntimeError, match="capacity"):
            await instance.claim(**_scope(key_digest="another-key"))
        with pytest.raises(SubmissionConflictError):
            await instance.claim(**_scope(request_digest="different-request"))
        repeated, created = await instance.claim(**_scope())
        assert created is False
        assert repeated.state == state
        assert repeated.submission_id == record.submission_id
    finally:
        await instance.close()


async def test_capacity_check_and_insert_are_atomic_across_connections(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database, max_records=3)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database, max_records=3)
    try:
        results = await asyncio.gather(
            *(
                instance.claim(**_scope(key_digest=f"key-{index}"))
                for index, instance in enumerate((first, second) * 8)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, tuple) for result in results) == 3
        assert sum(isinstance(result, RuntimeError) for result in results) == 13
    finally:
        await asyncio.gather(first.close(), second.close())


@pytest.mark.parametrize("max_records", [0, -1])
def test_nonpositive_capacity_is_rejected(tmp_path: Path, max_records: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        SQLiteSubmissionStore(tmp_path / "runtime.sqlite3", max_records=max_records)


async def test_tasks_are_ordered_bounded_and_duplicates_do_not_use_capacity(
    store: SQLiteSubmissionStore,
) -> None:
    record, _ = await store.claim(**_scope())
    tasks = (("z-task", None), ("a-task", "req:1"), ("task.2", None), ("task_3", "r"), ("t-4", "r"))
    for task_id, request_id in tasks:
        await store.record_task(record.submission_id, task_id, request_id)
    for task_id, request_id in tasks:
        await store.record_task(record.submission_id, task_id, request_id)
    with pytest.raises(RuntimeError, match=r"capacity|five|5"):
        await store.record_task(record.submission_id, "sixth-task", None)
    assert (await store.get(record.submission_id)).tasks == tasks
    assert (await store.claim(**_scope()))[0].tasks == tasks


async def test_task_limit_is_atomic_across_connections(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        record, _ = await first.claim(**_scope())
        results = await asyncio.gather(
            *(
                instance.record_task(record.submission_id, f"task-{index}", None)
                for index, instance in enumerate((first, second) * 8)
            ),
            return_exceptions=True,
        )
        assert results.count(None) == 5
        assert sum(isinstance(result, RuntimeError) for result in results) == 11
        assert len((await second.get(record.submission_id)).tasks) == 5
    finally:
        await asyncio.gather(first.close(), second.close())


@pytest.mark.parametrize("original, replacement", [(None, "req-2"), ("req-1", None), ("a", "b")])
async def test_duplicate_task_cannot_replace_request_id(
    store: SQLiteSubmissionStore, original: str | None, replacement: str | None
) -> None:
    record, _ = await store.claim(**_scope())
    await store.record_task(record.submission_id, "task-1", original)
    with pytest.raises(ValueError):
        await store.record_task(record.submission_id, "task-1", replacement)
    assert (await store.get(record.submission_id)).tasks == (("task-1", original),)


@pytest.mark.parametrize("identifier", ["A", "a" * 256, "Az09._:-"])
async def test_task_and_request_identifiers_accept_exact_boundaries(
    store: SQLiteSubmissionStore, identifier: str
) -> None:
    record, _ = await store.claim(**_scope())
    await store.record_task(record.submission_id, identifier, identifier)
    assert (await store.get(record.submission_id)).tasks == ((identifier, identifier),)


@pytest.mark.parametrize("field", ["task_id", "request_id"])
@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "x" * 257,
        "https://example.com/task",
        "task/name",
        "task?token=value",
        "task\n",
        " task",
        "task\x00",
        "\u00e9",
        "task'); DROP TABLE http_submissions;--",
    ],
)
async def test_invalid_identifiers_are_rejected_without_persistence(
    store: SQLiteSubmissionStore, tmp_path: Path, field: str, identifier: str
) -> None:
    record, _ = await store.claim(**_scope())
    identifiers = {"task_id": "task-1", "request_id": "request-1", field: identifier}
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob("runtime.sqlite3*")
        if path.suffix == ".sqlite3" or path.name.endswith("-wal")
    }
    with pytest.raises(ValueError):
        await store.record_task(record.submission_id, **identifiers)
    assert await store.get(record.submission_id) == record
    after = {name: (tmp_path / name).read_bytes() for name in before}
    assert after == before


@pytest.mark.parametrize("operation", ["get", "record_task", "succeed", "mark_unresolved"])
async def test_unknown_submission_ids_fail_without_mutating_other_claims(
    store: SQLiteSubmissionStore, operation: str
) -> None:
    record, _ = await store.claim(**_scope())
    unknown = str(uuid4())
    with pytest.raises(LookupError):
        if operation == "record_task":
            await store.record_task(unknown, "task-1", None)
        elif operation == "succeed":
            await store.succeed(unknown, "{}")
        elif operation == "mark_unresolved":
            await store.mark_unresolved(unknown)
        else:
            await store.get(unknown)
    assert await store.get(record.submission_id) == record


async def test_get_looks_up_only_private_submission_uuid(store: SQLiteSubmissionStore) -> None:
    record, _ = await store.claim(**_scope())
    await store.record_task(record.submission_id, "task-1", None)
    for external_id in ("task-1", _scope()["key_digest"], "' OR 1=1 --", ""):
        with pytest.raises(LookupError):
            await store.get(external_id)


async def test_success_retains_exact_receipt_and_cannot_be_demoted(
    store: SQLiteSubmissionStore,
) -> None:
    record, _ = await store.claim(**_scope())
    await store.record_task(record.submission_id, "task-1", "request-1")
    response = '{ "task_id": "task-1", "request_id": "request-1" }\n'
    await store.succeed(record.submission_id, response)
    await store.mark_unresolved(record.submission_id)
    await store.mark_unresolved(record.submission_id)
    await store.record_task(record.submission_id, "task-1", "request-1")
    with pytest.raises(RuntimeError):
        await store.record_task(record.submission_id, "new-task", None)
    expected = SubmissionRecord(
        record.submission_id, "succeeded", response, (("task-1", "request-1"),)
    )
    assert await store.get(record.submission_id) == expected
    assert await store.claim(**_scope()) == (expected, False)


@pytest.mark.parametrize("state", ["succeeded", "unresolved"])
async def test_success_requires_running_state(store: SQLiteSubmissionStore, state: str) -> None:
    record, _ = await store.claim(**_scope())
    if state == "succeeded":
        await store.succeed(record.submission_id, '{"original":true}')
    else:
        await store.mark_unresolved(record.submission_id)
    before = await store.get(record.submission_id)
    with pytest.raises(RuntimeError):
        await store.succeed(record.submission_id, '{"replacement":true}')
    assert await store.get(record.submission_id) == before


async def test_unresolved_retains_late_acceptance_receipts(store: SQLiteSubmissionStore) -> None:
    record, _ = await store.claim(**_scope())
    await store.record_task(record.submission_id, "task-1", None)
    await store.mark_unresolved(record.submission_id)
    await store.mark_unresolved(record.submission_id)
    await store.record_task(record.submission_id, "task-2", "request-2")
    assert await store.get(record.submission_id) == SubmissionRecord(
        record.submission_id, "unresolved", None, (("task-1", None), ("task-2", "request-2"))
    )


@pytest.mark.parametrize("state", ["running", "succeeded", "unresolved"])
async def test_restart_reclassifies_only_running_claims(tmp_path: Path, state: str) -> None:
    database = tmp_path / "runtime.sqlite3"
    instance = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        record, _ = await instance.claim(**_scope())
        await instance.record_task(record.submission_id, "task-1", "request-1")
        response = '{"task_id":"task-1"}'
        if state == "succeeded":
            await instance.succeed(record.submission_id, response)
        elif state == "unresolved":
            await instance.mark_unresolved(record.submission_id)
    finally:
        await instance.close()
    reopened = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        expected = SubmissionRecord(
            record.submission_id,
            "succeeded" if state == "succeeded" else "unresolved",
            response if state == "succeeded" else None,
            (("task-1", "request-1"),),
        )
        assert await reopened.get(record.submission_id) == expected
        assert await reopened.claim(**_scope()) == (expected, False)
    finally:
        await reopened.close()


@pytest.mark.parametrize("extra_bytes", [0, 1])
async def test_response_limit_is_32_kib_utf8_bytes(
    store: SQLiteSubmissionStore, extra_bytes: int
) -> None:
    record, _ = await store.claim(**_scope())
    response = '"' + "\u00e9" * 16383 + "a" * extra_bytes + '"'
    assert len(response.encode("utf-8")) == 32768 + extra_bytes
    if extra_bytes:
        with pytest.raises(ValueError, match=r"32|32768"):
            await store.succeed(record.submission_id, response)
        assert await store.get(record.submission_id) == record
    else:
        await store.succeed(record.submission_id, response)
        assert (await store.get(record.submission_id)).response_json == response


@pytest.mark.parametrize("response", ["", "{", "{} trailing", "NaN", '{"x":Infinity}'])
async def test_invalid_json_does_not_transition_claim(
    store: SQLiteSubmissionStore, response: str
) -> None:
    record, _ = await store.claim(**_scope())
    with pytest.raises(ValueError):
        await store.succeed(record.submission_id, response)
    assert await store.get(record.submission_id) == record
    await store.succeed(record.submission_id, "{}")


async def test_success_and_unresolved_race_never_overwrite_terminal_state(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        record, _ = await first.claim(**_scope())
        results = await asyncio.gather(
            first.succeed(record.submission_id, "{}"),
            second.mark_unresolved(record.submission_id),
            return_exceptions=True,
        )
        final = await first.get(record.submission_id)
        assert results[1] is None
        if final.state == "succeeded":
            assert results[0] is None
            assert final.response_json == "{}"
        else:
            assert isinstance(results[0], RuntimeError)
            assert final.state == "unresolved"
            assert final.response_json is None
    finally:
        await asyncio.gather(first.close(), second.close())


class _WriteBarrier:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = asyncio.Event()
        self.release = threading.Event()
        self.timed_out = threading.Event()
        self.thread_ids: list[int] = []
        self.statement_prefix: str | None = "INSERT INTO http_submissions"
        loop = asyncio.get_running_loop()
        original_connect = sqlite3.connect

        def trace(statement: str) -> None:
            if self.statement_prefix and statement.lstrip().startswith(self.statement_prefix):
                self.statement_prefix = None
                self.thread_ids.append(threading.get_ident())
                loop.call_soon_threadsafe(self.started.set)
                if not self.release.wait(timeout=10):
                    self.timed_out.set()

        def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection: sqlite3.Connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(trace)
            return connection

        monkeypatch.setattr(sqlite3, "connect", connect)


@pytest.mark.parametrize("cancel_close", [False, True])
@pytest.mark.parametrize("blocked_statement", ["INSERT INTO http_submissions", "COMMIT"])
async def test_cancelled_thread_operation_keeps_serialization_and_close_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_close: bool,
    blocked_statement: str,
) -> None:
    barrier = _WriteBarrier(monkeypatch)
    database = tmp_path / "runtime.sqlite3"
    instance = await asyncio.to_thread(SQLiteSubmissionStore, database)
    barrier.statement_prefix = blocked_statement
    pending = asyncio.create_task(instance.claim(**_scope()))
    following: asyncio.Task[tuple[SubmissionRecord, bool]] | None = None
    closing_task: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(barrier.started.wait(), timeout=3)
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        following = asyncio.create_task(instance.claim(**_scope()))
        await asyncio.sleep(0)
        closing_task = asyncio.create_task(instance.close())
        await asyncio.sleep(0)
        if cancel_close:
            closing_task.cancel()
            await asyncio.sleep(0)
            closing_task.cancel()
            await asyncio.sleep(0)
        assert not pending.done()
        assert not following.done()
        assert not closing_task.done()
        with pytest.raises(RuntimeError, match="closed"):
            await instance.get(str(uuid4()))
        barrier.release.set()
        results = await asyncio.wait_for(
            asyncio.gather(pending, following, closing_task, return_exceptions=True), timeout=3
        )
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[1], tuple)
        assert results[1][1] is False
        if cancel_close:
            assert isinstance(results[2], asyncio.CancelledError)
        else:
            assert results[2] is None
        assert not barrier.timed_out.is_set()
        assert threading.get_ident() not in barrier.thread_ids
    finally:
        barrier.release.set()
        await asyncio.gather(
            *(task for task in (pending, following, closing_task) if task is not None),
            return_exceptions=True,
        )
        await instance.close()
    reopened = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        record, created = await reopened.claim(**_scope())
        assert created is False
        assert record.state == "unresolved"
    finally:
        await reopened.close()


async def test_cancelled_queued_operation_does_not_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = _WriteBarrier(monkeypatch)
    instance = await asyncio.to_thread(SQLiteSubmissionStore, tmp_path / "runtime.sqlite3")
    first = asyncio.create_task(instance.claim(**_scope()))
    try:
        await asyncio.wait_for(barrier.started.wait(), timeout=3)
        queued = asyncio.create_task(instance.claim(**_scope(key_digest="queued-key")))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        barrier.release.set()
        await first
        assert (await instance.claim(**_scope(key_digest="queued-key")))[1] is True
    finally:
        barrier.release.set()
        await asyncio.gather(first, return_exceptions=True)
        await instance.close()


async def test_database_failure_rolls_back_and_preserves_original_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = _WriteBarrier(monkeypatch)
    database = tmp_path / "runtime.sqlite3"
    instance = await asyncio.to_thread(SQLiteSubmissionStore, database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            CREATE TRIGGER fail_claim BEFORE INSERT ON http_submissions
            BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END
            """
        )
    pending = asyncio.create_task(instance.claim(**_scope()))
    try:
        await asyncio.wait_for(barrier.started.wait(), timeout=3)
        pending.cancel()
        await asyncio.sleep(0)
        barrier.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=3)
        with pytest.raises(sqlite3.IntegrityError, match="synthetic write failure"):
            await instance.claim(**_scope())
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("DROP TRIGGER fail_claim")
        assert (await instance.claim(**_scope()))[1] is True
    finally:
        barrier.release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await instance.close()


async def test_close_is_idempotent_and_rejects_further_operations(
    store: SQLiteSubmissionStore,
) -> None:
    record, _ = await store.claim(**_scope())
    await asyncio.gather(store.close(), store.close())
    await store.close()
    operations = (
        store.claim(**_scope()),
        store.get(record.submission_id),
        store.record_task(record.submission_id, "task-1", None),
        store.succeed(record.submission_id, json.dumps({"task_id": "task-1"})),
        store.mark_unresolved(record.submission_id),
    )
    results = await asyncio.gather(*operations, return_exceptions=True)
    assert all(isinstance(result, RuntimeError) and "closed" in str(result) for result in results)


async def test_durability_settings_and_foreign_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    instance = await asyncio.to_thread(SQLiteSubmissionStore, tmp_path / "nested/runtime.sqlite3")
    try:
        connection = connections[0]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute(
                "INSERT INTO http_submission_tasks(submission_id, task_id) VALUES (?, ?)",
                (str(uuid4()), "task-1"),
            )
    finally:
        await instance.close()


async def test_get_returns_consistent_snapshot_during_cross_connection_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = _WriteBarrier(monkeypatch)
    barrier.statement_prefix = None
    database = tmp_path / "runtime.sqlite3"
    reader = await asyncio.to_thread(SQLiteSubmissionStore, database)
    writer = await asyncio.to_thread(SQLiteSubmissionStore, database)
    pending: asyncio.Task[SubmissionRecord] | None = None
    try:
        record, _ = await writer.claim(**_scope())
        barrier.statement_prefix = "SELECT task_id, request_id"
        pending = asyncio.create_task(reader.get(record.submission_id))
        await asyncio.wait_for(barrier.started.wait(), timeout=3)
        await writer.record_task(record.submission_id, "task-1", None)
        await writer.succeed(record.submission_id, '{"task_id":"task-1"}')
        barrier.release.set()
        assert await pending == record
        current = await reader.get(record.submission_id)
        assert current.state == "succeeded"
        assert current.tasks == (("task-1", None),)
        assert current.response_json == '{"task_id":"task-1"}'
    finally:
        barrier.release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await asyncio.gather(reader.close(), writer.close())


async def test_same_provider_task_id_does_not_modify_another_submission(
    store: SQLiteSubmissionStore,
) -> None:
    first, _ = await store.claim(**_scope())
    second, _ = await store.claim(**_scope(tenant_id="another-tenant"))
    await store.record_task(first.submission_id, "task-1", "first-request")
    await store.record_task(second.submission_id, "task-1", "second-request")
    assert (await store.get(first.submission_id)).tasks == (("task-1", "first-request"),)
    assert (await store.get(second.submission_id)).tasks == (("task-1", "second-request"),)


@pytest.mark.parametrize("request_id", ["request-1", "request-2"])
async def test_concurrent_duplicate_tasks_remain_one_immutable_receipt(
    tmp_path: Path, request_id: str
) -> None:
    database = tmp_path / "runtime.sqlite3"
    first = await asyncio.to_thread(SQLiteSubmissionStore, database)
    second = await asyncio.to_thread(SQLiteSubmissionStore, database)
    try:
        record, _ = await first.claim(**_scope())
        results = await asyncio.gather(
            first.record_task(record.submission_id, "task-1", "request-1"),
            second.record_task(record.submission_id, "task-1", request_id),
            return_exceptions=True,
        )
        if request_id == "request-1":
            assert all(result is None for result in results)
        else:
            assert sum(isinstance(result, ValueError) for result in results) == 1
            assert results.count(None) == 1
        tasks = (await first.get(record.submission_id)).tasks
        assert len(tasks) == 1
        assert tasks[0][0] == "task-1"
        assert tasks[0][1] in ("request-1", request_id)
    finally:
        await asyncio.gather(first.close(), second.close())


async def test_initialization_failure_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "runtime.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE http_submissions(incompatible_column TEXT)")
    connections: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError):
        await asyncio.to_thread(SQLiteSubmissionStore, database)
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
