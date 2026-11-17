"""Bounded metrics regressions for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import respx
from fastmcp.tools import ToolResult
from prometheus_client import CollectorRegistry, Counter, Histogram

from ark_mcp.observability import metrics
from ark_mcp.tools._catalog import CATALOG
from tests.integration.test_byok_http import (
    assert_denied,
    call_tool,
    http_server,
    successful,
)


@pytest.fixture
def metric_registry(monkeypatch):
    registry = CollectorRegistry()
    for name, metric_type, labels in (
        ("TOOL_REQUESTS", Counter, ("tool", "status")),
        ("TOOL_DURATION", Histogram, ("tool",)),
    ):
        monkeypatch.setattr(
            metrics,
            name,
            metric_type(
                name.lower(),
                name,
                labels,
                registry=registry,
                unit="seconds" if metric_type is Histogram else "",
            ),
        )
    return registry


def label_values(registry, label):
    return {
        sample.labels[label]
        for metric in registry.collect()
        for sample in metric.samples
        if label in sample.labels
    }


@respx.mock
async def test_many_anonymous_unknown_tool_calls_keep_retained_metrics_bounded(
    tmp_path, metric_registry
):
    async with http_server(tmp_path) as (_, _, client):
        for index in range(200):
            assert_denied(await call_tool(client, f"unknown-tool-{index}", {}))
        assert_denied(await call_tool(client, "seedream_generate_image", {"prompt": "square"}))
        successful(await call_tool(client, "ark_list_models", {}))

    assert label_values(metric_registry, "tool") == {
        "unknown",
        "seedream_generate_image",
        "ark_list_models",
    }
    assert (
        metric_registry.get_sample_value(
            "tool_requests_total", {"tool": "ark_list_models", "status": "success"}
        )
        == 1
    )
    assert (
        metric_registry.get_sample_value("tool_duration_seconds_count", {"tool": "unknown"}) == 200
    )
    assert len(respx.calls) == 0


@pytest.mark.parametrize("outcome", ["success", "error", "exception", "cancelled"])
async def test_middleware_bounds_every_direct_outcome(metric_registry, outcome):
    middleware = metrics.MetricsMiddleware()
    result = ToolResult(content="synthetic result", is_error=outcome == "error")

    async def call_next(context):
        assert context.message.name.startswith("unknown-tool-")
        if outcome == "exception":
            raise ValueError("synthetic failure")
        if outcome == "cancelled":
            raise asyncio.CancelledError
        return result

    for index in range(200):
        context = SimpleNamespace(
            message=SimpleNamespace(name=f"unknown-tool-{index}"), fastmcp_context=None
        )
        if outcome in ("exception", "cancelled"):
            with pytest.raises(ValueError if outcome == "exception" else asyncio.CancelledError):
                await middleware.on_call_tool(context, call_next)
        else:
            assert await middleware.on_call_tool(context, call_next) is result

    assert label_values(metric_registry, "tool") == {"unknown"}
    assert (
        metric_registry.get_sample_value(
            "tool_requests_total", {"tool": "unknown", "status": outcome}
        )
        == 200
    )
    assert (
        metric_registry.get_sample_value("tool_duration_seconds_count", {"tool": "unknown"}) == 200
    )


async def test_every_catalog_name_keeps_its_direct_label(metric_registry):
    async def handler(context):
        return ToolResult(content="synthetic result")

    middleware = metrics.MetricsMiddleware()
    for entry in CATALOG:
        context = SimpleNamespace(message=SimpleNamespace(name=entry.name))
        await middleware.on_call_tool(context, handler)
        assert (
            metric_registry.get_sample_value(
                "tool_requests_total", {"tool": entry.name, "status": "success"}
            )
            == 1
        )
    assert label_values(metric_registry, "tool") == {entry.name for entry in CATALOG}
