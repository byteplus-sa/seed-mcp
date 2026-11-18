"""Read-only aggregate inspection from specs/SPEC_VKE_DEPLOYMENT.md.

See specs/SPEC_HOSTED_BYOK.md for state ownership and retention. This standalone
stdlib command never imports application startup, Settings, or recovery code.
Capacity applies independently to ownership, budgets, and submission claims.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

_SCHEMAS = {
    "task_ownership": (
        ("provider", "TEXT", 1, 1),
        ("task_id", "TEXT", 1, 3),
        ("principal_id", "TEXT", 1, 0),
        ("tenant_id", "TEXT", 1, 2),
        ("created_at", "TEXT", 1, 0),
    ),
    "object_key_ownership": (
        ("object_key", "TEXT", 1, 1),
        ("principal_id", "TEXT", 1, 0),
        ("tenant_id", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "budget_reservations": (
        ("id", "INTEGER", 0, 1),
        ("usage_date", "TEXT", 1, 0),
        ("principal_id", "TEXT", 1, 0),
        ("tenant_id", "TEXT", 1, 0),
        ("product", "TEXT", 1, 0),
        ("amount_usd", "REAL", 1, 0),
        ("status", "TEXT", 1, 0),
    ),
    "task_artifacts": (
        ("provider", "TEXT", 1, 1),
        ("task_id", "TEXT", 1, 2),
        ("artifacts_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "http_submissions": (
        ("submission_id", "TEXT", 1, 1),
        ("provider", "TEXT", 1, 0),
        ("tenant_id", "TEXT", 1, 0),
        ("principal_id", "TEXT", 1, 0),
        ("tool_name", "TEXT", 1, 0),
        ("key_digest", "TEXT", 1, 0),
        ("request_digest", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("response_json", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "http_submission_tasks": (
        ("submission_id", "TEXT", 1, 1),
        ("task_id", "TEXT", 1, 2),
        ("request_id", "TEXT", 0, 0),
    ),
}
_COUNT_QUERIES = {
    "task_ownership": "SELECT COUNT(*) FROM task_ownership",
    "object_key_ownership": "SELECT COUNT(*) FROM object_key_ownership",
    "budget_reservations": "SELECT COUNT(*) FROM budget_reservations",
    "task_artifacts": "SELECT COUNT(*) FROM task_artifacts",
    "http_submissions": "SELECT COUNT(*) FROM http_submissions",
    "http_submission_tasks": "SELECT COUNT(*) FROM http_submission_tasks",
}
_CAPPED_TABLES = {"task_ownership", "budget_reservations", "http_submissions"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("Invalid inspection arguments.")


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table, expected in _SCHEMAS.items():
        row = connection.execute(
            "SELECT type FROM sqlite_schema WHERE name=? AND sql LIKE 'CREATE TABLE %'",
            (table,),
        ).fetchone()
        if row != ("table",):
            raise ValueError("Unsupported runtime schema.")
        rows = connection.execute(
            'SELECT name, type, "notnull", pk, dflt_value, hidden FROM pragma_table_xinfo(?)',
            (table,),
        ).fetchmany(len(expected) + 1)
        if tuple(row[:4] for row in rows) != expected or any(
            row[4] is not None or row[5] != 0 for row in rows
        ):
            raise ValueError("Unsupported runtime schema.")


def inspect_state(
    database: Path,
    *,
    capacity: int,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    """Read one consistent SQLite snapshot with fixed-size aggregate output."""
    if not 1 <= capacity <= 2**63 - 1:
        raise ValueError("Invalid capacity.")
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
        raise ValueError("Invalid timeout.")
    deadline = time.monotonic() + timeout_seconds
    database = database.expanduser().resolve(strict=True)
    if not database.is_file():
        raise ValueError("Runtime database must be a regular file.")
    uri = database.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=timeout_seconds)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        connection.execute("BEGIN")
        _validate_schema(connection)
        tables: dict[str, dict[str, int | float]] = {}
        for table, query in _COUNT_QUERIES.items():
            count = int(connection.execute(query).fetchone()[0])
            tables[table] = {"rows": count}
            if table in _CAPPED_TABLES:
                tables[table]["capacity_ratio"] = count / capacity
        running, succeeded, unresolved, invalid_dates, age = connection.execute(
            """
            SELECT COALESCE(SUM(state='running'), 0),
                   COALESCE(SUM(state='succeeded'), 0),
                   COALESCE(SUM(state='unresolved'), 0),
                   COALESCE(SUM(state='unresolved' AND julianday(created_at) IS NULL), 0),
                   MAX(0, (julianday(?) -
                       MIN(CASE WHEN state='unresolved' THEN julianday(created_at) END)) * 86400)
            FROM http_submissions
            """,
            (datetime.now(UTC).isoformat(),),
        ).fetchone()
        reserved, committed, released = connection.execute(
            """
            SELECT COALESCE(SUM(status='reserved'), 0),
                   COALESCE(SUM(status='committed'), 0),
                   COALESCE(SUM(status='released'), 0)
            FROM budget_reservations
            """
        ).fetchone()
        if (
            running + succeeded + unresolved != tables["http_submissions"]["rows"]
            or reserved + committed + released != tables["budget_reservations"]["rows"]
            or invalid_dates
            or time.monotonic() >= deadline
        ):
            raise ValueError("Runtime aggregate validation failed.")
        return {
            "schema_version": 1,
            "capacity": capacity,
            "tables": tables,
            "submission_states": {
                "running": running,
                "succeeded": succeeded,
                "unresolved": unresolved,
            },
            "budget_states": {"reserved": reserved, "committed": committed, "released": released},
            "oldest_unresolved_age_seconds": round(age, 3) if age is not None else None,
        }


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Inspect aggregate runtime state without repair or recovery.")
    parser.add_argument("--database", "--path", required=True, type=Path)
    parser.add_argument("--capacity", required=True, type=int)
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    try:
        args = parser.parse_args(argv)
        if not 1 <= args.capacity <= 2**63 - 1:
            raise ValueError
        if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 30:
            raise ValueError
    except ValueError:
        print(json.dumps({"error": "Invalid inspection arguments."}))
        return 2
    try:
        result = inspect_state(
            args.database,
            capacity=args.capacity,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        print(json.dumps({"error": "Runtime state inspection failed."}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
