"""Offline contracts for specs/SPEC_VKE_DEPLOYMENT.md acceptance tooling."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import ssl
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from scripts.hosted_acceptance import Harness, main, parse_options
from scripts.hosted_acceptance_support.runtime import (
    CheckFailure,
    ManagedProcess,
    Sample,
    aggregate,
    classify,
    cleanup_signals,
    fixtures,
    isolated_environment,
    loopback_config,
    scan_files,
    verify_untrusted_certificate,
)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--caddy-bin", "/missing/synthetic-private-path"],
        ["--caddy-bin", sys.executable, "--max-requests", "0"],
        ["--caddy-bin", sys.executable, "--max-requests", "1001"],
        ["--caddy-bin", sys.executable, "--concurrency", "0"],
        ["--caddy-bin", sys.executable, "--concurrency", "33"],
        ["--caddy-bin", sys.executable, "--concurrency", "nan"],
        ["--caddy-bin", sys.executable, "--max-requests", "1", "--concurrency", "2"],
        ["--caddy-bin", sys.executable, "--url", "https://synthetic-private.example"],
        ["--caddy-bin", sys.executable, "--live-provider"],
        ["--caddy-bin", sys.executable, "--max-requests", "1_0"],
        ["--caddy-bin", sys.executable, "--max-requests", "\uff11"],
    ],
)
def test_invalid_inputs_do_not_echo_values(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": False, "failure": "invalid_arguments"}


def test_default_is_full_acceptance_and_small_bounded_load() -> None:
    options = parse_options(["--caddy-bin", sys.executable])
    assert options.max_requests == 40
    assert options.concurrency == 4
    assert options.caddy_bin == Path(sys.executable).resolve()


@pytest.mark.parametrize("count,concurrency", [(1, 1), (1000, 32)])
def test_load_bounds_are_inclusive(count: int, concurrency: int) -> None:
    options = parse_options(
        [
            "--caddy-bin",
            sys.executable,
            "--max-requests",
            str(count),
            "--concurrency",
            str(concurrency),
        ]
    )
    assert options.max_requests == count
    assert options.concurrency == concurrency


def test_environment_is_allowlisted_and_home_is_private(tmp_path: Path) -> None:
    synthetic_value = "synthetic-parent-key"
    environment = isolated_environment(
        tmp_path,
        {
            "PATH": "/usr/bin:/bin",
            "BYTEPLUS_MODELARK_API_KEY": synthetic_value,
            "HTTP_PROXY": "https://synthetic-parent-proxy",
            "SSL_CERT_FILE": "/synthetic-parent-ca",
            "PYTHONPATH": "/synthetic-parent-imports",
            "MCP_IDENTITY_HMAC_KEY": "synthetic-parent-identity",
        },
    )
    assert environment["HOME"] == str(tmp_path)
    assert environment["ARK_MCP_ENV_FILE"] == str(tmp_path / "absent.env")
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert "BYTEPLUS_MODELARK_API_KEY" not in environment
    assert "HTTP_PROXY" not in environment
    assert "SSL_CERT_FILE" not in environment
    assert "MCP_IDENTITY_HMAC_KEY" not in environment
    assert "synthetic-parent" not in json.dumps(environment)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, {"result": {"structuredContent": {"failed": 0}}}, "success"),
        (200, {"result": {"structuredContent": {"failed": 1}}}, "error"),
        (200, {"result": {"structuredContent": {"errors": [{"code": "NOT_OWNED"}]}}}, "error"),
        (200, {"result": {"isError": True, "content": [{"text": "bad"}]}}, "error"),
        (
            200,
            {"result": {"isError": True, "content": [{"text": "code=ADMISSION_TIMEOUT"}]}},
            "overload",
        ),
        (200, {"error": {"code": -32603}}, "error"),
        (200, {}, "error"),
        (200, {"result": {}}, "error"),
        (500, {}, "error"),
        (401, {}, "error"),
        (413, {}, "error"),
        (429, {}, "overload"),
        (503, {}, "error"),
    ],
)
def test_load_classification_does_not_hide_unexpected_errors(
    status: int, body: dict[str, object], expected: str
) -> None:
    response = httpx.Response(status, json=body)
    assert classify(response) == expected


def test_only_known_http_admission_rejection_is_overload() -> None:
    response = httpx.Response(
        503, text="Server concurrency limit reached.", headers={"Retry-After": "1"}
    )
    assert classify(response) == "overload"
    assert classify(httpx.Response(200, text="not JSON")) == "error"


def test_aggregate_reports_latency_statuses_and_separate_expected_overload() -> None:
    report = aggregate(
        [
            Sample(10, 200, "success"),
            Sample(20, 200, "overload"),
            Sample(30, 503, "overload"),
            Sample(40, 500, "error"),
            Sample(50, 0, "error"),
        ],
        duration=2.0,
        concurrency=2,
    )
    assert report["requests"] == 5
    assert report["latency_ms"] == {"p50": 30, "p95": 50, "p99": 50}
    assert report["throughput_rps"] == 2.5
    assert report["success_count"] == 1
    assert report["overload_count"] == 2
    assert report["error_count"] == 2
    assert report["statuses"] == {"200": 2, "503": 1, "500": 1, "transport_error": 1}
    assert "URL" not in json.dumps(report)


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_aggregate_rejects_invalid_duration(duration: float) -> None:
    with pytest.raises(ValueError):
        aggregate([Sample(1, 200, "success")], duration, 1)


def test_aggregate_rejects_empty_sample_set() -> None:
    with pytest.raises(ValueError):
        aggregate([], 1, 1)


def test_proxy_adaptation_changes_only_listener_addresses() -> None:
    config = {
        "admin": {"disabled": True},
        "apps": {"http": {"servers": {"srv0": {"listen": [":8443"], "routes": ["retained"]}}}},
    }
    narrowed = loopback_config(config, 8443)
    assert narrowed["apps"]["http"]["servers"]["srv0"]["listen"] == ["127.0.0.1:8443"]
    assert narrowed["apps"]["http"]["servers"]["srv0"]["routes"] == ["retained"]
    assert config["apps"]["http"]["servers"]["srv0"]["listen"] == [":8443"]


def test_proxy_adaptation_fails_closed_on_unexpected_listener() -> None:
    config = {"apps": {"http": {"servers": {"srv0": {"listen": [":443", ":80"]}}}}}
    with pytest.raises(CheckFailure, match="proxy_listener_contract"):
        loopback_config(config, 8443)


@pytest.mark.parametrize("encoding", ["raw", "url", "json"])
def test_canary_scan_checks_all_logs_and_never_echoes_contents(
    tmp_path: Path, encoding: str
) -> None:
    from urllib.parse import quote

    canary = 'synthetic-private+/"canary'
    value = {"raw": canary, "url": quote(canary, safe=""), "json": json.dumps(canary)}[encoding]
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "stderr.log").write_text(value)
    with pytest.raises(CheckFailure, match="canary_leak") as error:
        scan_files(tmp_path, [canary])
    assert canary not in str(error.value)


def test_clean_file_scan_succeeds(tmp_path: Path) -> None:
    (tmp_path / "stdout.log").write_text("safe aggregate event")
    scan_files(tmp_path, ["synthetic-private"])


def test_process_cleanup_is_idempotent_and_threadsafe(tmp_path: Path) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=30,
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: child.stop(), range(4)))
    assert child.process.poll() is not None
    assert not child.timed_out
    assert not child.forced
    assert not child._timer.is_alive()


def test_process_deadline_kills_and_reaps_child(tmp_path: Path) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=0.05,
    )
    try:
        child.process.wait(timeout=5)
        assert child.timed_out
    finally:
        child.stop()
    assert child.process.poll() is not None
    assert not child._timer.is_alive()


def test_exited_child_is_not_signalled_after_its_pid_can_be_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "pass"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=30,
    )
    try:
        assert child.process.wait(timeout=5) == 0
        signal_group = Mock()
        monkeypatch.setattr(os, "killpg", signal_group)
        child._signal(signal.SIGTERM)
        child.stop()
        signal_group.assert_not_called()
        assert not child.cleanup_failed
        assert not child._timer.is_alive()
    finally:
        child.stop()


@pytest.mark.parametrize("operation", ["connect", "getaddrinfo", "sendto"])
@pytest.mark.parametrize("mode", ["normal", "drain-short", "drain-production"])
def test_worker_rejects_unmocked_network_before_socket_dispatch(
    tmp_path: Path, operation: str, mode: str
) -> None:
    program = """
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from scripts.hosted_acceptance_support.worker import serve

class NetworkProbe:
    def run(self, **kwargs):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as outbound:
            try:
                if sys.argv[2] == "getaddrinfo":
                    socket.getaddrinfo("localhost", 9)
                elif sys.argv[2] == "connect":
                    outbound.connect(("127.0.0.1", 9))
                else:
                    outbound.sendto(b"synthetic", ("127.0.0.1", 9))
            except RuntimeError as error:
                assert str(error) == "Unexpected mock dispatch."
            else:
                raise AssertionError("Worker allowed an unmocked socket operation.")

with patch("ark_mcp.server.create_server", return_value=NetworkProbe()):
    serve(Path(sys.argv[1]), 9, sys.argv[3])
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path), operation, mode],
        cwd=tmp_path,
        env={**isolated_environment(tmp_path), "ACCEPTANCE_FIXTURES": json.dumps(fixtures())},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "dispatches.log").read_text() == "mock_violation\n"


def test_watchdog_errors_are_contained_and_cleanup_remains_possible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=30,
    )

    def denied_signal(number: int) -> None:
        raise PermissionError("synthetic-private-detail")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(child, "_signal", denied_signal)
            child._expire()
        assert child.cleanup_failed
        assert child.timed_out
    finally:
        child.stop()
    assert child.process.poll() is not None
    assert not child._timer.is_alive()


def test_term_is_sent_once_without_disarming_watchdog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=30,
    )
    try:
        with monkeypatch.context() as patch:
            send = Mock()
            patch.setattr(child, "_signal", send)
            child.terminate()
            child.terminate()
            send.assert_called_once_with(signal.SIGTERM)
            assert child._timer.is_alive()
        # Restore the unsent signal so ordinary cleanup can reap this unit fixture.
        child._terminated = False
    finally:
        child.stop()


@pytest.mark.parametrize("grace", [-1, float("nan"), float("inf")])
def test_stop_rejects_unbounded_or_negative_grace(tmp_path: Path, grace: float) -> None:
    child = ManagedProcess(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        home=tmp_path,
        env=isolated_environment(tmp_path),
        log=tmp_path / "child.log",
        lifetime=30,
    )
    try:
        with pytest.raises(ValueError, match="Invalid process grace"):
            child.stop(grace=grace)
        assert child._timer.is_alive()
    finally:
        child.stop()


def test_signal_handler_allows_cleanup_and_restores_previous_handlers() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    with cleanup_signals():
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
        handler(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == previous


async def test_tls_negative_control_requires_certificate_failure_not_connection_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect = AsyncMock(side_effect=ssl.SSLCertVerificationError(1, "synthetic-private"))
    monkeypatch.setattr(asyncio, "open_connection", connect)
    await verify_untrusted_certificate(1)
    connect.side_effect = ConnectionRefusedError("synthetic-private")
    with pytest.raises(ConnectionRefusedError):
        await verify_untrusted_certificate(1)


@pytest.mark.parametrize(
    "failure", [ValueError("synthetic-private"), CheckFailure("fixed_failure")]
)
def test_unexpected_failure_returns_nonzero_safe_json_and_runs_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    closed: list[bool] = []
    monkeypatch.setattr("scripts.hosted_acceptance.free_ports", lambda _: [1, 2])

    def fail(self: Harness) -> ssl.SSLContext:
        raise failure

    def close(self: Harness) -> None:
        closed.append(True)

    monkeypatch.setattr(Harness, "prepare_proxy", fail)
    monkeypatch.setattr(Harness, "close", close)
    assert main(["--caddy-bin", sys.executable]) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert "synthetic-private" not in output.out
    assert not json.loads(output.out)["ok"]
    assert closed == [True]


def test_launch_failure_does_not_leave_log_open(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        ManagedProcess(
            [str(tmp_path / "missing")],
            home=tmp_path,
            env=isolated_environment(tmp_path),
            log=tmp_path / "child.log",
        )
    (tmp_path / "child.log").unlink()


async def test_load_uses_fixed_worker_count_and_records_transport_failures() -> None:
    from scripts.hosted_acceptance_support.checks import run_load

    active = 0
    peak = 0
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, calls
        active += 1
        peak = max(peak, active)
        calls += 1
        current = calls
        try:
            await asyncio.sleep(0)
            if current == 2:
                raise httpx.ReadTimeout("synthetic-private-url")
            return httpx.Response(200, json={"result": {"structuredContent": {"failed": 0}}})
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        report = await run_load(client, "https://127.0.0.1:1", {}, "synthetic-task", 12, 3)
    assert calls == 12
    assert peak <= 3
    assert report["requests"] == 12
    assert report["error_count"] == 1
    assert "synthetic-private" not in json.dumps(report)


def test_cli_help_does_not_start_processes(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "hosted_acceptance.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "--caddy-bin" in result.stdout
    assert "mock" in result.stdout.lower()
    assert result.stderr == ""
