"""Read-only diagnostics for specs/SPEC_VKE_DEPLOYMENT.md."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ark_mcp.runtime import close_runtime_services, create_runtime_services
from tests.unit.test_runtime_ops import http_settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect_runtime_state.py"
CANARY = "private-key-owner-payload-canary"


def inspect(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(SCRIPT),
            "--database",
            str(database),
            "--capacity",
            "100",
            *arguments,
        ],
        cwd=database.parent,
        env={"PATH": os.defpath},
        text=True,
        capture_output=True,
        timeout=10,
    )


async def test_live_inspection_reports_aggregates_without_recovery_or_disclosure(
    tmp_path: Path,
) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    database = tmp_path / "runtime.sqlite3"
    try:
        with closing(sqlite3.connect(database)) as connection, connection:
            for index, state in enumerate(("running", "succeeded", "unresolved")):
                connection.execute(
                    "INSERT INTO http_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{CANARY}-{index}",
                        CANARY,
                        CANARY,
                        CANARY,
                        CANARY,
                        f"{CANARY}-{index}",
                        CANARY,
                        state,
                        CANARY,
                        (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    ),
                )
            connection.execute(
                "INSERT INTO task_ownership VALUES (?, ?, ?, ?, ?)",
                (CANARY, CANARY, CANARY, CANARY, CANARY),
            )
            connection.execute(
                "INSERT INTO budget_reservations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, "2026-11-17", CANARY, CANARY, CANARY, 1.0, "reserved"),
            )
        before = {
            path.name: path.read_bytes()
            for path in tmp_path.glob("runtime.sqlite3*")
            if not path.name.endswith("-shm")
        }
        result = inspect(database)
        assert result.returncode == 0, result.stderr
        assert CANARY not in result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["tables"]["http_submissions"]["rows"] == 3
        assert report["tables"]["http_submissions"]["capacity_ratio"] == 0.03
        assert report["submission_states"] == {"running": 1, "succeeded": 1, "unresolved": 1}
        assert 3590 <= report["oldest_unresolved_age_seconds"] <= 3620
        assert report["budget_states"] == {"reserved": 1, "committed": 0, "released": 0}
        assert result.stderr == ""
        assert before == {
            path.name: path.read_bytes()
            for path in tmp_path.glob("runtime.sqlite3*")
            if not path.name.endswith("-shm")
        }
        with closing(sqlite3.connect(database)) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM http_submissions WHERE state='running'"
                ).fetchone()[0]
                == 1
            )
    finally:
        await close_runtime_services(runtime)


@pytest.mark.parametrize("failure", ["missing", "corrupt", "schema", "view"])
def test_missing_corrupt_and_unexpected_schema_fail_without_disclosure_or_creation(
    tmp_path: Path,
    failure: str,
) -> None:
    database = tmp_path / f"{CANARY}.sqlite3"
    if failure == "corrupt":
        database.write_bytes(CANARY.encode())
    elif failure in {"schema", "view"}:
        with closing(sqlite3.connect(database)) as connection:
            if failure == "schema":
                connection.execute("CREATE TABLE http_submissions(private TEXT)")
            else:
                connection.execute("CREATE VIEW http_submissions AS SELECT 'private' AS state")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = inspect(database)
    assert result.returncode == 1
    assert CANARY not in result.stdout + result.stderr
    assert json.loads(result.stdout) == {"error": "Runtime state inspection failed."}
    assert result.stderr == ""
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


async def test_empty_stopped_runtime_and_uri_metacharacters(tmp_path: Path) -> None:
    root = tmp_path / "state ? #"
    runtime = await create_runtime_services(http_settings(root))
    await close_runtime_services(runtime)
    result = inspect(root / "runtime.sqlite3")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["oldest_unresolved_age_seconds"] is None
    assert report["submission_states"] == {"running": 0, "succeeded": 0, "unresolved": 0}
    assert all(table["rows"] == 0 for table in report["tables"].values())


async def test_large_payloads_and_capacity_overflow_have_fixed_size_output(tmp_path: Path) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    database = tmp_path / "runtime.sqlite3"
    try:
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executemany(
                "INSERT INTO task_ownership VALUES (?, ?, ?, ?, ?)",
                (("modelark", f"task-{index}", CANARY, CANARY, CANARY) for index in range(20_000)),
            )
            connection.execute(
                "INSERT INTO task_artifacts VALUES (?, ?, ?, ?)",
                ("modelark", CANARY, CANARY * 100_000, CANARY),
            )
        result = inspect(database)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout) < 2000
        assert CANARY not in result.stdout
        assert json.loads(result.stdout)["tables"]["task_ownership"]["capacity_ratio"] == 200
    finally:
        await close_runtime_services(runtime)


@pytest.mark.parametrize(
    "arguments",
    [
        ("--capacity", "0"),
        ("--capacity", "-1"),
        ("--capacity", CANARY),
        ("--timeout-seconds", "nan"),
        ("--timeout-seconds", "inf"),
        ("--timeout-seconds", "0"),
        ("--timeout-seconds", "31"),
        ("--sql", CANARY),
    ],
)
def test_invalid_arguments_fail_closed_without_echo(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    result = inspect(tmp_path / "missing.sqlite3", *arguments)
    assert result.returncode == 2
    assert CANARY not in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


async def test_invalid_state_and_unresolved_timestamp_fail_closed(tmp_path: Path) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    database = tmp_path / "runtime.sqlite3"
    try:
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "INSERT INTO http_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (CANARY, CANARY, CANARY, CANARY, CANARY, CANARY, CANARY, CANARY, CANARY, CANARY),
            )
        assert inspect(database).returncode == 1
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE http_submissions SET state='unresolved'")
        result = inspect(database)
        assert result.returncode == 1
        assert CANARY not in result.stdout + result.stderr
    finally:
        await close_runtime_services(runtime)


async def test_busy_read_only_database_fails_with_bounded_wait(tmp_path: Path) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    await close_runtime_services(runtime)
    database = tmp_path / "runtime.sqlite3"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=DELETE")
        before = database.read_bytes()
        writer.execute("BEGIN EXCLUSIVE")
        try:
            started = time.monotonic()
            result = inspect(database, "--timeout-seconds", "0.05")
            assert time.monotonic() - started < 3
            assert result.returncode == 1
            assert result.stderr == ""
        finally:
            writer.rollback()
        assert database.read_bytes() == before


def test_symlink_loop_fails_without_path_echo(tmp_path: Path) -> None:
    database = tmp_path / CANARY
    database.symlink_to(database.name)
    result = inspect(database)
    assert result.returncode == 1
    assert result.stderr == ""
    assert CANARY not in result.stdout
