"""Offline drain fixture contracts; real Caddy timing runs are explicit CLIs."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from scripts import hosted_drain_acceptance as drain_cli
from scripts.hosted_acceptance_support.drain import (
    KEEPALIVE_IDLE,
    PROFILES,
    REQUEST_ID,
    TASK_ID,
    Clocks,
    event,
    mark,
    mock_response,
    receipt,
)
from scripts.hosted_acceptance_support.runtime import CheckFailure
from scripts.hosted_drain_acceptance import DrainHarness, DrainOptions, exited, main, parse_options


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--caddy-bin", "/missing/synthetic-private"],
        ["--caddy-bin", sys.executable, "--profile", "live"],
        ["--caddy-bin", sys.executable, "--url", "https://synthetic-private"],
        ["--caddy-bin", sys.executable, "--duration", "1"],
        ["--caddy-bin", sys.executable, "--live-provider"],
        ["--caddy-bin", sys.executable, "--prof", "production"],
    ],
)
def test_cli_rejects_remote_or_unbounded_inputs_without_echo(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": False, "failure": "invalid_arguments"}


def test_default_short_and_explicit_production_clocks() -> None:
    assert parse_options(["--caddy-bin", sys.executable]).profile == "short"
    assert (
        parse_options(["--caddy-bin", sys.executable, "--profile", "production"]).profile
        == "production"
    )
    production = PROFILES["production"]
    assert production == Clocks(work=590, tool=600, grace=630, pod=660, lifetime=750)
    for clocks in PROFILES.values():
        assert 0 < clocks.work < clocks.tool < clocks.grace < clocks.pod
        assert clocks.lifetime > 30 + KEEPALIVE_IDLE + clocks.pod
    assert KEEPALIVE_IDLE > 5


async def test_mock_completion_requires_parent_release_and_measured_work(tmp_path: Path) -> None:
    records: list[str] = []
    clocks = Clocks(work=0.03, tool=1, grace=2, pod=3, lifetime=4)
    pending = asyncio.create_task(mock_response(tmp_path, clocks, "accepted", records.append))
    try:
        async with asyncio.timeout(1):
            while not event(tmp_path, "dispatched"):
                await asyncio.sleep(0)
        assert records == ["drain_dispatch"]
        assert not pending.done()
        assert event(tmp_path, "completed") is None
        (tmp_path / "release").touch()
        response = await asyncio.wait_for(pending, timeout=1)
        assert response.json() == {"id": TASK_ID}
        assert response.headers["X-Request-Id"] == REQUEST_ID
        assert records == ["drain_dispatch", "drain_completed"]
        assert event(tmp_path, "completed")["time"] - event(tmp_path, "dispatched")["time"] >= 0.03
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("prompt", ["stalled", "disconnected"])
async def test_uncertain_mock_cancels_once_and_never_completes_or_retries(
    tmp_path: Path, prompt: str
) -> None:
    records: list[str] = []
    pending = asyncio.create_task(
        mock_response(tmp_path, PROFILES["short"], prompt, records.append)
    )
    try:
        async with asyncio.timeout(1):
            while not event(tmp_path, "dispatched"):
                await asyncio.sleep(0)
        (tmp_path / "release").touch()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert records == ["drain_dispatch", "drain_cancelled"]
        assert event(tmp_path, "cancelled") is not None
        assert event(tmp_path, "completed") is None
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


def test_fixture_events_are_atomic_and_contain_only_safe_fields(tmp_path: Path) -> None:
    assert event(tmp_path, "absent") is None
    timestamp = mark(tmp_path, "fresh", port=12345, protocol="1.1")
    assert event(tmp_path, "fresh") == {"time": timestamp, "port": 12345, "protocol": "1.1"}
    assert not list(tmp_path.glob("*.tmp"))


def synthetic_receipt() -> dict[str, object]:
    return {
        "submitted": 1,
        "failed": 0,
        "tasks": [{"task_id": TASK_ID, "request_id": REQUEST_ID}],
    }


def test_complete_receipt_requires_exact_task_and_request_ids() -> None:
    content = synthetic_receipt()
    receipt(httpx.Response(200, json={"result": {"structuredContent": content}}))
    for field, value in (
        ("submitted", 0),
        ("failed", 1),
        ("tasks", []),
        ("tasks", [{"task_id": TASK_ID}]),
        ("tasks", [{"task_id": "wrong", "request_id": REQUEST_ID}]),
        ("tasks", [content["tasks"][0], content["tasks"][0]]),
    ):
        with pytest.raises(CheckFailure):
            receipt(
                httpx.Response(
                    200, json={"result": {"structuredContent": {**content, field: value}}}
                )
            )


@pytest.mark.parametrize(
    "changes",
    [{"forced": True}, {"timed_out": True}, {"cleanup_failed": True}, {"returncode": 1}],
)
async def test_exit_cannot_pass_after_watchdog_or_cleanup_kill(changes: dict[str, object]) -> None:
    child = Mock(forced=False, timed_out=False, cleanup_failed=False)
    child.process.poll.return_value = changes.get("returncode", 0)
    child.process.returncode = changes.pop("returncode", 0)
    for field, value in changes.items():
        setattr(child, field, value)
    with pytest.raises(CheckFailure, match="ungraceful_process_exit"):
        await exited(child, asyncio.get_running_loop().time() + 1)


async def test_exit_wait_is_bounded_and_never_calls_stop() -> None:
    child = Mock(timed_out=False)
    child.process.poll.return_value = None
    with pytest.raises(TimeoutError):
        await exited(child, asyncio.get_running_loop().time() + 0.01)
    child.stop.assert_not_called()


async def test_already_exited_process_cannot_pass_an_expired_observation_deadline() -> None:
    child = Mock(forced=False, timed_out=False, cleanup_failed=False)
    child.process.poll.return_value = 0
    child.process.returncode = 0
    with pytest.raises(CheckFailure, match="process_exit_observed_after_deadline"):
        await exited(child, time.monotonic() - 1)
    child.stop.assert_not_called()


def test_drain_uses_production_proxy_and_profile_watchdogs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.hosted_acceptance.free_ports", lambda _: [12345, 12346])
    harness = DrainHarness(tmp_path, DrainOptions(Path(sys.executable), "production"))
    prepare = Mock()
    monkeypatch.setattr(harness, "prepare_proxy", prepare)
    monkeypatch.setattr(drain_cli, "PRODUCTION_CADDYFILE", tmp_path / "Caddyfile")
    (tmp_path / "Caddyfile").write_text("synthetic")
    harness.prepare()
    prepare.assert_called_once_with(
        source=tmp_path / "Caddyfile", grace_period=630, lifetime=750, body_limit=2097152
    )
    assert harness.environment["MCP_BACKEND_HOST"] == "localhost"


def test_drain_cleanup_uses_shared_production_budget_not_eight_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.hosted_acceptance.free_ports", lambda _: [12345, 12346])
    monkeypatch.setattr("scripts.hosted_acceptance.Harness.close", lambda self: None)
    harness = DrainHarness(tmp_path, DrainOptions(Path(sys.executable), "production"))
    children = [Mock(), Mock()]
    harness.children = children
    harness.close()
    for child in children:
        child.stop.assert_called_once_with(grace=660)


async def test_protocol_matrix_has_all_orders_and_short_negative_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drain_cli.importlib.util, "find_spec", lambda _: object())
    run = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(drain_cli, "run_case", run)
    results = await drain_cli.exercise(tmp_path, DrainOptions(Path(sys.executable), "production"))
    assert len(results) == 10
    accepted = [call.args for call in run.call_args_list if call.args[-1] == "accepted"]
    assert {(args[2], args[3]) for args in accepted} == {
        (protocol, order) for protocol in drain_cli.PROTOCOLS for order in drain_cli.ORDERS
    }
    assert all(args[1].profile == "production" for args in accepted)
    assert all(
        call.args[1].profile == "short"
        for call in run.call_args_list
        if call.args[-1] != "accepted"
    )


async def test_http2_offer_dependency_is_required_even_with_h1_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drain_cli.importlib.util, "find_spec", lambda _: None)
    run = AsyncMock()
    monkeypatch.setattr(drain_cli, "run_case", run)
    with pytest.raises(CheckFailure, match="http2_dependency_missing"):
        await drain_cli.exercise(tmp_path, DrainOptions(Path(sys.executable)))
    run.assert_not_called()


@pytest.mark.parametrize(
    "defect,code",
    [
        (None, None),
        ("protocol", "protocol_negotiation_failed"),
        ("client_reuse", "client_connection_not_reused"),
        ("backend_reuse", "backend_keepalive_not_exercised"),
        ("backend_stale", "backend_keepalive_not_exercised"),
        ("interval", "keepalive_interval_too_short"),
    ],
)
async def test_keepalive_requires_h1_negotiation_reuse_and_more_than_five_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str | None, code: str | None
) -> None:
    monkeypatch.setattr("scripts.hosted_acceptance.free_ports", lambda _: [12345, 12346])
    harness = DrainHarness(tmp_path, DrainOptions(Path(sys.executable)))
    clock = Mock()
    clock.monotonic.side_effect = [10, 15 if defect == "interval" else 15.25]
    monkeypatch.setattr(drain_cli, "time", clock)
    sleep = AsyncMock()
    monkeypatch.setattr(drain_cli.asyncio, "sleep", sleep)
    ports = {
        "fresh": 123,
        "reused": 124 if defect == "backend_reuse" else 123,
        "stale": 123 if defect == "backend_stale" else 456,
    }
    monkeypatch.setattr(
        drain_cli, "event", lambda directory, name: {"port": ports[name], "protocol": "1.1"}
    )
    stream = object()
    responses = [
        httpx.Response(
            200,
            extensions={
                "http_version": b"HTTP/2" if defect == "protocol" else b"HTTP/1.1",
                "network_stream": object() if defect == "client_reuse" else stream,
            },
        )
        for _ in range(3)
    ]
    client = Mock()
    client.get = AsyncMock(side_effect=responses)
    if code:
        with pytest.raises(CheckFailure, match=code):
            await harness.keepalive(client, "HTTP/2")
    else:
        result = await harness.keepalive(client, "HTTP/2")
        assert result["idle_seconds"] == 5.25
        assert result["client_connection_reused"]
        assert result["backend_connection_reused_then_replaced"]
        assert client.get.await_count == 3
        sleep.assert_awaited_once_with(KEEPALIVE_IDLE)


@pytest.mark.parametrize("order", drain_cli.ORDERS)
async def test_case_sends_term_only_after_dispatch_and_requires_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    monkeypatch.setattr("scripts.hosted_acceptance.free_ports", lambda _: [12345, 12346])
    harness = DrainHarness(tmp_path, DrainOptions(Path(sys.executable)))
    harness.clocks = Clocks(work=0, tool=8, grace=12, pod=18, lifetime=90)
    terms: list[str] = []
    app, proxy = Mock(), Mock()
    harness.proxy = proxy

    def terminate(name: str) -> None:
        assert event(tmp_path, "dispatched") is not None
        assert not (tmp_path / "release").exists()
        terms.append(name)

    app.terminate.side_effect = lambda: terminate("app")
    proxy.terminate.side_effect = lambda: terminate("proxy")
    monkeypatch.setattr(harness, "server", Mock(return_value=app))
    monkeypatch.setattr(harness, "keepalive", AsyncMock(return_value={}))
    monkeypatch.setattr(drain_cli, "wait_healthy", AsyncMock())
    client = AsyncMock()
    monkeypatch.setattr(drain_cli.httpx, "AsyncClient", Mock(return_value=client))

    async def mock_call(*args: object) -> httpx.Response:
        (tmp_path / "dispatches.log").write_text("drain_dispatch\n")
        mark(tmp_path, "dispatched")
        while not (tmp_path / "release").exists():
            await asyncio.sleep(0.001)
        (tmp_path / "dispatches.log").write_text("drain_dispatch\ndrain_completed\n")
        mark(tmp_path, "completed")
        mark(tmp_path, "response-complete")
        return httpx.Response(
            200,
            json={"result": {"structuredContent": synthetic_receipt()}},
            extensions={"http_version": b"HTTP/1.1"},
        )

    async def mock_exit(*args: object) -> float:
        return time.monotonic()

    monkeypatch.setattr(drain_cli, "call", mock_call)
    monkeypatch.setattr(drain_cli, "exited", mock_exit)
    result = await harness.exercise_case(Mock(), "HTTP/1.1", order, "accepted")
    assert terms == (["proxy", "app"] if order == "proxy-first" else ["app", "proxy"])
    assert result["complete_receipt"]
    assert result["dispatches"] == 1
    assert result["client_offer"] == "HTTP/1.1"
    assert result["negotiated_protocol"] == "HTTP/1.1"
    assert result["ok"]
    app.stop.assert_not_called()
    proxy.stop.assert_not_called()


@pytest.mark.parametrize("failed_stage", ["prepare", "exercise", "close"])
async def test_case_failures_are_sanitized_and_always_clean_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_stage: str
) -> None:
    harness = Mock()
    harness.exercise_case = AsyncMock(return_value={"ok": True})
    target = {
        "prepare": harness.prepare,
        "exercise": harness.exercise_case,
        "close": harness.close,
    }[failed_stage]
    target.side_effect = RuntimeError("synthetic-private-detail")
    monkeypatch.setattr(drain_cli, "DrainHarness", Mock(return_value=harness))
    result = await drain_cli.run_case(
        tmp_path / "case", DrainOptions(Path(sys.executable)), "HTTP/2", "app-first", "accepted"
    )
    assert not result["ok"]
    assert "synthetic-private" not in json.dumps(result)
    harness.close.assert_called_once()


def test_main_returns_failure_for_any_failed_timing_case(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        drain_cli, "exercise", AsyncMock(return_value=[{"ok": True}, {"ok": False}])
    )
    assert main(["--caddy-bin", sys.executable]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_outer_directory_cleanup_failure_cannot_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = Mock()
    context.__enter__ = Mock(return_value=str(tmp_path))
    context.__exit__ = Mock(side_effect=OSError("synthetic-private-cleanup"))
    monkeypatch.setattr(drain_cli.tempfile, "TemporaryDirectory", Mock(return_value=context))
    monkeypatch.setattr(drain_cli, "exercise", AsyncMock(return_value=[{"ok": True}]))
    assert main(["--caddy-bin", sys.executable]) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["ok"] is False
    assert report["failure"] == "drain_harness_failed"
    assert "synthetic-private" not in str(output)
