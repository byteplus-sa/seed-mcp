"""Safe provider receipts and explicitly rejected legacy replay keys."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

if TYPE_CHECKING:
    from fastmcp import Context

IDENTIFIER_PATTERN = r"[A-Za-z0-9._:-]{1,256}"

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
    "Unsupported legacy field; omit it. The stateless server rejects supplied keys "
    "and does not provide deduplication or saved-response replay. Never automatically "
    "repeat an uncertain create; retain task IDs and poll instead."
)


def validate_receipt_identifiers(
    ctx: Context, provider: str, task_id: str, request_id: str | None
) -> None:
    """Reject unsafe HTTP provider identifiers before exposing them to clients."""
    from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
    from ark_mcp.runtime import get_runtime
    from ark_mcp.security.credentials import redact_request_secrets

    settings = get_runtime(ctx).settings
    if settings.mcp_transport != "http":
        return
    secret = settings.identity_hmac_key.get_secret_value()
    for value in (task_id, request_id):
        if value is None:
            continue
        if (
            not re.fullmatch(IDENTIFIER_PATTERN, value)
            or redact_request_secrets(value) != value
            or (secret and secret in value)
        ):
            raise ProviderError(
                NormalizedProviderError(
                    provider="modelark" if provider == "modelark" else "byteplus-vision-cv",
                    operation="create_task",
                    code="UNSAFE_TASK_RECEIPT",
                    message=(
                        "The provider may have accepted the task but returned an unsafe "
                        "identifier. Do not resubmit; reconcile through the provider."
                    ),
                    retryable=False,
                    ambiguous_completion=True,
                )
            )
