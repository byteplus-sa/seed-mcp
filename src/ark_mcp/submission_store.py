"""Durable HTTP claims for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from ark_mcp.sqlite_io import drain_task

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

IDENTIFIER_PATTERN = r"[A-Za-z0-9._:-]{1,256}"
_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)
_MAX_TASKS = 5
_MAX_RESPONSE_BYTES = 32 * 1024
type SubmissionState = Literal["running", "succeeded", "unresolved"]


@dataclass(frozen=True)
class SubmissionRecord:
    submission_id: str
    state: SubmissionState
    response_json: str | None
    tasks: tuple[tuple[str, str | None], ...]


class SubmissionConflictError(ValueError):
    """An existing scoped key has a different request fingerprint."""


def _reject_json_constant(value: str) -> None:
    raise ValueError("Submission response must be valid JSON.")


class SQLiteSubmissionStore:
    """Single-instance submission journal; construct off the event loop."""

    def __init__(self, database_path: Path, *, max_records: int = 100_000) -> None:
        if max_records <= 0:
            raise ValueError("Submission capacity must be positive.")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False, timeout=5)
        self._max_records = max_records
        self._lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False
        try:
            self._connection.execute("PRAGMA busy_timeout=5000")
            self._connection.execute("PRAGMA journal_mode=WAL").fetchone()
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._initialize()
        except BaseException:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS http_submissions (
                    submission_id TEXT PRIMARY KEY NOT NULL,
                    provider TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    key_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('running', 'succeeded', 'unresolved')),
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, tenant_id, principal_id, tool_name, key_digest)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS http_submission_tasks (
                    submission_id TEXT NOT NULL REFERENCES http_submissions(submission_id),
                    task_id TEXT NOT NULL,
                    request_id TEXT,
                    PRIMARY KEY(submission_id, task_id)
                )
                """
            )
            self._connection.execute(
                "UPDATE http_submissions SET state = 'unresolved' WHERE state = 'running'"
            )

    async def _run[T](self, operation: Callable[[], T]) -> T:
        if self._close_task is not None:
            raise RuntimeError("Submission store is closed or closing.")
        async with self._lock:
            if self._closed:
                raise RuntimeError("Submission store is closed.")
            return await drain_task(asyncio.create_task(asyncio.to_thread(operation)))

    def _get(self, submission_id: str) -> SubmissionRecord:
        row = self._connection.execute(
            "SELECT state, response_json FROM http_submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Submission is unavailable.")
        tasks = self._connection.execute(
            """
            SELECT task_id, request_id FROM http_submission_tasks
            WHERE submission_id = ? ORDER BY rowid
            """,
            (submission_id,),
        ).fetchall()
        return SubmissionRecord(
            submission_id=submission_id,
            state=cast("SubmissionState", row[0]),
            response_json=cast("str | None", row[1]),
            tasks=tuple(cast("list[tuple[str, str | None]]", tasks)),
        )

    async def get(self, submission_id: str) -> SubmissionRecord:
        """Read a consistent receipt snapshot by its private submission UUID."""

        def read() -> SubmissionRecord:
            with self._connection:
                self._connection.execute("BEGIN")
                return self._get(submission_id)

        return await self._run(read)

    async def claim(
        self,
        *,
        provider: str,
        tenant_id: str,
        principal_id: str,
        tool_name: str,
        key_digest: str,
        request_digest: str,
    ) -> tuple[SubmissionRecord, bool]:
        """Commit a new claim or return the matching claim without dispatching."""

        def claim_record() -> tuple[SubmissionRecord, bool]:
            scope = (provider, tenant_id, principal_id, tool_name, key_digest)
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    """
                    SELECT submission_id, request_digest FROM http_submissions
                    WHERE provider = ? AND tenant_id = ? AND principal_id = ?
                        AND tool_name = ? AND key_digest = ?
                    """,
                    scope,
                ).fetchone()
                if existing is not None:
                    if existing[1] != request_digest:
                        raise SubmissionConflictError(
                            "Submission key was already used with different arguments."
                        )
                    return self._get(existing[0]), False
                count = self._connection.execute(
                    "SELECT COUNT(*) FROM http_submissions"
                ).fetchone()[0]
                if count >= self._max_records:
                    raise RuntimeError(
                        "Submission capacity reached; new submissions are unavailable."
                    )
                submission_id = str(uuid4())
                self._connection.execute(
                    """
                    INSERT INTO http_submissions(
                        submission_id, provider, tenant_id, principal_id, tool_name,
                        key_digest, request_digest, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)
                    """,
                    (
                        submission_id,
                        *scope,
                        request_digest,
                        datetime.now(UTC).isoformat(timespec="microseconds"),
                    ),
                )
                return SubmissionRecord(submission_id, "running", None, ()), True

        return await self._run(claim_record)

    async def record_task(self, submission_id: str, task_id: str, request_id: str | None) -> None:
        """Retain up to five immutable accepted task receipts, including late receipts."""
        if _IDENTIFIER.fullmatch(task_id) is None or (
            request_id is not None and _IDENTIFIER.fullmatch(request_id) is None
        ):
            raise ValueError(
                "Task and request identifiers must match the bounded identifier grammar."
            )

        def record() -> None:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._get(submission_id)
                for recorded_task, recorded_request in existing.tasks:
                    if recorded_task == task_id:
                        if recorded_request != request_id:
                            raise ValueError("Accepted task receipt cannot be replaced.")
                        return
                if existing.state == "succeeded":
                    raise RuntimeError("Succeeded submission receipts cannot be changed.")
                if len(existing.tasks) >= _MAX_TASKS:
                    raise RuntimeError("Submission task receipt capacity reached.")
                self._connection.execute(
                    """
                    INSERT INTO http_submission_tasks(submission_id, task_id, request_id)
                    VALUES (?, ?, ?)
                    """,
                    (submission_id, task_id, request_id),
                )

        await self._run(record)

    async def succeed(self, submission_id: str, response_json: str) -> None:
        """Save a bounded JSON receipt only while the claim is running."""
        if len(response_json.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise ValueError("Submission response exceeds the 32 KiB limit.")
        try:
            json.loads(response_json, parse_constant=_reject_json_constant)
        except (ValueError, RecursionError):
            raise ValueError("Submission response must be valid JSON.") from None

        def complete() -> None:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                if self._get(submission_id).state != "running":
                    raise RuntimeError("Only running submissions can succeed.")
                self._connection.execute(
                    """
                    UPDATE http_submissions SET state = 'succeeded', response_json = ?
                    WHERE submission_id = ?
                    """,
                    (response_json, submission_id),
                )

        await self._run(complete)

    async def mark_unresolved(self, submission_id: str) -> None:
        """Retain an interrupted claim without demoting a saved success."""

        def mark() -> None:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                self._get(submission_id)
                self._connection.execute(
                    """
                    UPDATE http_submissions SET state = 'unresolved'
                    WHERE submission_id = ? AND state = 'running'
                    """,
                    (submission_id,),
                )

        await self._run(mark)

    async def _close(self) -> None:
        async with self._lock:
            await drain_task(asyncio.create_task(asyncio.to_thread(self._connection.close)))
            self._closed = True

    async def close(self) -> None:
        """Drain admitted operations and close, even if a waiting caller is cancelled."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await drain_task(self._close_task)
