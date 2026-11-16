"""URL-only tool policy for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

from collections.abc import Sequence

from fastmcp import Context

from ark_mcp.runtime import get_runtime


def validate_http_options(
    ctx: Context,
    *,
    persist: bool = False,
    persist_field: str = "persist",
    media_references: Sequence[str] = (),
) -> None:
    """Reject server-side persistence and stored input artifacts on HTTP."""
    if get_runtime(ctx).settings.mcp_transport == "stdio":
        return
    if persist:
        raise ValueError(
            f"{persist_field}=true is not supported over HTTP; use false and download "
            "the temporary provider URLs on the client."
        )
    if any(ref.strip().lower().startswith("seed-media:") for ref in media_references):
        raise ValueError(
            "Stored artifact references are not supported over HTTP; supply public HTTPS URLs."
        )
