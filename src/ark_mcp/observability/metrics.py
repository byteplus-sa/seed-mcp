"""Low-cardinality Prometheus metrics and FastMCP request instrumentation."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from prometheus_client import Counter, Histogram

from ark_mcp.tools._catalog import catalog_entry

if TYPE_CHECKING:
    import mcp.types as mt
    from fastmcp.tools import ToolResult

TOOL_REQUESTS = Counter(
    "ark_mcp_tool_requests_total",
    "MCP tool requests by tool and outcome.",
    ("tool", "status"),
)
TOOL_DURATION = Histogram(
    "ark_mcp_tool_duration_seconds",
    "MCP tool execution duration.",
    ("tool",),
)
PROVIDER_REQUESTS = Counter(
    "ark_mcp_provider_requests_total",
    "Provider requests by provider, operation, and outcome.",
    ("provider", "operation", "status"),
)
PROVIDER_DURATION = Histogram(
    "ark_mcp_provider_duration_seconds",
    "Provider request duration.",
    ("provider", "operation"),
)
ARTIFACT_OPERATIONS = Counter(
    "ark_mcp_artifact_operations_total",
    "Artifact operations by operation, outcome, and media type.",
    ("operation", "status", "media_type"),
)
BUDGET_REJECTIONS = Counter(
    "ark_mcp_budget_rejections_total",
    "Budget rejections by product.",
    ("product",),
)
RETRY_ATTEMPTS = Counter(
    "ark_mcp_retry_attempts_total",
    "Safe provider retry attempts.",
    ("provider", "operation"),
)
ADMISSION_REJECTIONS = Counter(
    "ark_mcp_admission_rejections_total",
    "Provider admission rejections before dispatch of this attempt.",
    ("provider", "reason"),
)
TOOL_DEADLINES = Counter(
    "ark_mcp_tool_deadlines_total",
    "Cooperative tool deadlines by dispatch state; not provider cancellation.",
    ("dispatch",),
)


def _tool_label(tool_name: str) -> str:
    return tool_name if catalog_entry(tool_name) is not None else "unknown"


class MetricsMiddleware(Middleware):
    """Measure MCP tool calls without tenant, model, URL, or request labels."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = _tool_label(context.message.name)
        started = perf_counter()
        try:
            result = await call_next(context)
        except asyncio.CancelledError:
            TOOL_REQUESTS.labels(tool=tool_name, status="cancelled").inc()
            raise
        except Exception:
            TOOL_REQUESTS.labels(tool=tool_name, status="exception").inc()
            raise
        else:
            status = "error" if result.is_error else "success"
            TOOL_REQUESTS.labels(tool=tool_name, status=status).inc()
            return result
        finally:
            TOOL_DURATION.labels(tool=tool_name).observe(perf_counter() - started)
