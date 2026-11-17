"""Client diagnostics for direct tool invocations."""

from __future__ import annotations

from typing import Literal

from fastmcp import Context


async def context_log(
    ctx: Context, level: Literal["info", "warning", "error"], message: str
) -> None:
    """Send a diagnostic through the live MCP context."""
    await getattr(ctx, level)(message)
