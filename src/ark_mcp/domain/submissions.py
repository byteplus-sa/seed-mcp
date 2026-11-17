"""Caller operation identifiers for the HTTP submission-safety contract."""

from typing import Annotated

from pydantic import Field

IdempotencyKey = Annotated[
    str,
    Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        json_schema_extra={"not": {"pattern": r"[^A-Za-z0-9_-]"}},
    ),
]

IDEMPOTENCY_KEY_DESCRIPTION = (
    "Caller-generated operation ID (16-128 ASCII letters, digits, underscores or hyphens; "
    "a fresh UUID is recommended). Required for HTTP creation except Seedance dry runs. "
    "Reuse identical arguments and this key only to recover delivery of the same operation, "
    "never to start another generation. Local stdio rejects this field; omit it there."
)
