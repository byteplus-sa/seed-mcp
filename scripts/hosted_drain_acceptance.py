"""Mock-only TERM acceptance for specs/SPEC_VKE_DEPLOYMENT.md.

Run ``uv run python scripts/hosted_drain_acceptance.py --caddy-bin PATH``.
The explicit production profile runs six parallel 590-second calls, not paid
generation. It consumes the production Caddyfile but never contacts APIG/VKE.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import signal
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.hosted_acceptance import Harness, Options, SafeParser
from scripts.hosted_acceptance import parse_options as base_options
from scripts.hosted_acceptance_support.checks import (
    call,
    credentials,
    dispatches,
    wait_dispatch,
    wait_healthy,
)
from scripts.hosted_acceptance_support.drain import (
    KEEPALIVE_IDLE,
    PRODUCTION_BODY_LIMIT,
    PROFILES,
    event,
    receipt,
)
from scripts.hosted_acceptance_support.runtime import (
    ROOT,
    CheckFailure,
    cleanup_signals,
    expected_error,
    require,
)

if TYPE_CHECKING:
    import ssl

    from scripts.hosted_acceptance_support.runtime import ManagedProcess

PRODUCTION_CADDYFILE = ROOT / "deploy/helm/seed-mcp/files/Caddyfile.apig-production"
ORDERS = ("app-first", "proxy-first", "simultaneous")
# Both client offers must negotiate the production listener's deliberate H1 policy.
PROTOCOLS = ("HTTP/1.1", "HTTP/2")


@dataclass(frozen=True)
class DrainOptions:
    caddy_bin: Path
    profile: str = "short"


def parse_options(arguments: list[str] | None = None) -> DrainOptions:
    parser = SafeParser(
        description="Bounded mock-only TLS drain with H1 and H2-capable clients negotiating H1.",
        allow_abbrev=False,
    )
    parser.add_argument("--caddy-bin", required=True, help="Explicit reviewed Caddy executable.")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="short")
    values = parser.parse_args(arguments)
    binary = base_options(["--caddy-bin", values.caddy_bin]).caddy_bin
    return DrainOptions(binary, values.profile)


async def exited(child: ManagedProcess, deadline: float) -> float:
    async with asyncio.timeout_at(deadline):
        while child.process.poll() is None:
            require(not child.timed_out, "process_watchdog_expired")
            await asyncio.sleep(0.02)
    require(
        not (child.forced or child.timed_out or child.cleanup_failed)
        and child.process.returncode in (0, -signal.SIGTERM),
        "ungraceful_process_exit",
    )
    observed = time.monotonic()
    require(observed <= deadline, "process_exit_observed_after_deadline")
    return observed


class DrainHarness(Harness):
    def __init__(self, directory: Path, options: DrainOptions) -> None:
        super().__init__(directory, Options(options.caddy_bin))
        self.profile = options.profile
        self.clocks = PROFILES[options.profile]
        self.environment["MCP_BACKEND_HOST"] = "localhost"

    def prepare(self) -> ssl.SSLContext:
        require(PRODUCTION_CADDYFILE.is_file(), "production_caddyfile_missing")
        return self.prepare_proxy(
            source=PRODUCTION_CADDYFILE,
            grace_period=self.clocks.grace,
            lifetime=self.clocks.lifetime,
            body_limit=PRODUCTION_BODY_LIMIT,
        )

    def close(self) -> None:
        # Both containers share a pod budget; never wait two sequential grace periods.
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda child: child.stop(grace=self.clocks.pod), self.children))
        super().close()

    async def keepalive(self, client: httpx.AsyncClient, protocol: str) -> dict[str, Any]:
        responses = []
        for probe in ("fresh", "reused", "stale"):
            if probe == "stale":
                started = time.monotonic()
                await asyncio.sleep(KEEPALIVE_IDLE)
                idle = time.monotonic() - started
                require(idle > 5, "keepalive_interval_too_short")
            response = await client.get(
                self.url + "/health", headers={"X-Acceptance-Keepalive": probe}
            )
            require(response.status_code == 200, "keepalive_http_failure")
            require(response.http_version == "HTTP/1.1", "protocol_negotiation_failed")
            responses.append(response)
        streams = [response.extensions.get("network_stream") for response in responses]
        require(
            streams[0] is not None and all(stream is streams[0] for stream in streams),
            "client_connection_not_reused",
        )
        probes = [event(self.directory, name) for name in ("fresh", "reused", "stale")]
        require(all(probes), "keepalive_probe_missing")
        fresh, reused, stale = probes
        assert fresh is not None and reused is not None and stale is not None
        require(
            fresh["port"] == reused["port"] and fresh["port"] != stale["port"],
            "backend_keepalive_not_exercised",
        )
        require(
            all(probe["protocol"] == "1.1" for probe in (fresh, reused, stale)), "backend_protocol"
        )
        return {
            "idle_seconds": round(idle, 3),
            "client_connection_reused": True,
            "backend_connection_reused_then_replaced": True,
            "backend_protocol": "HTTP/1.1",
        }

    async def exercise_case(
        self, context: ssl.SSLContext, protocol: str, order: str, scenario: str
    ) -> dict[str, Any]:
        app = self.server("drain-" + self.profile, lifetime=self.clocks.lifetime)
        proxy = self.proxy
        require(proxy is not None, "proxy_not_started")
        assert proxy is not None
        signals: dict[str, float] = {}
        async with (
            asyncio.timeout(self.clocks.lifetime - 10),
            httpx.AsyncClient(
                verify=context,
                trust_env=False,
                http2=protocol == "HTTP/2",
                timeout=self.clocks.pod,
                limits=httpx.Limits(
                    max_connections=1, max_keepalive_connections=1, keepalive_expiry=30
                ),
            ) as client,
        ):
            await wait_healthy(client, self.url, app)
            keepalive = await self.keepalive(client, protocol)
            require(not dispatches(self.directory), "startup_dispatched")
            pending = asyncio.create_task(
                call(
                    client,
                    self.url,
                    "seedance_create_task",
                    {
                        "prompt": self.values["prompt"] if scenario == "accepted" else scenario,
                        "duration": 4,
                    },
                    credentials(self.values),
                )
            )
            try:
                await wait_dispatch(self.directory, "drain_dispatch", 0)
                dispatched = event(self.directory, "dispatched")
                require(dispatched is not None and not pending.done(), "dispatch_barrier_failed")
                assert dispatched is not None
                if scenario == "disconnected":
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    await client.aclose()

                children = (
                    (("proxy", proxy), ("app", app))
                    if order == "proxy-first"
                    else (("app", app), ("proxy", proxy))
                )
                for index, (name, child) in enumerate(children):
                    if index and order != "simultaneous":
                        await asyncio.sleep(0.15)
                    require(child.healthy(), "process_exited_before_term")
                    signals[name] = time.monotonic()
                    child.terminate()
                if scenario == "accepted":
                    require(
                        app.healthy() and proxy.healthy() and not pending.done(),
                        "request_lost_at_term",
                    )
                    (self.directory / "release").touch()

                response_time: float | None = None
                if scenario != "disconnected":
                    response = await pending
                    response_time = time.monotonic()
                    require(response.http_version == "HTTP/1.1", "response_protocol_changed")
                    if scenario == "accepted":
                        receipt(response)
                    else:
                        text = expected_error(response, "TOOL_DEADLINE_EXCEEDED")
                        require("ambiguous_completion=True" in text, "lost_mutation_uncertainty")

                # Observe ordinary process exit BEFORE cleanup can kill anything.
                deadline = min(signals.values()) + self.clocks.pod
                app_exit, proxy_exit = await asyncio.gather(
                    exited(app, deadline), exited(proxy, deadline)
                )
                counts = dispatches(self.directory)
                require(counts["drain_dispatch"] == 1, "create_redispatched")
                completed = event(self.directory, "completed")
                if scenario == "accepted":
                    sent = event(self.directory, "response-complete")
                    require(
                        counts["drain_completed"] == 1
                        and counts["drain_cancelled"] == 0
                        and completed is not None
                        and sent is not None,
                        "accepted_call_incomplete",
                    )
                    assert completed is not None and sent is not None
                    require(
                        self.clocks.work
                        <= completed["time"] - dispatched["time"]
                        < self.clocks.tool,
                        "work_duration_outside_profile",
                    )
                    require(
                        dispatched["time"] <= min(signals.values())
                        and max(signals.values()) < completed["time"] <= sent["time"] <= app_exit
                        and response_time is not None
                        and completed["time"] <= response_time <= max(app_exit, proxy_exit),
                        "drain_event_order",
                    )
                else:
                    require(
                        counts["drain_completed"] == 0 and counts["drain_cancelled"] == 1,
                        "uncertain_call_retried_or_unbounded",
                    )
                return {
                    "ok": True,
                    "profile": self.profile,
                    "scenario": scenario,
                    "term_order": order,
                    "client_offer": protocol,
                    "negotiated_protocol": "HTTP/1.1",
                    "keepalive": keepalive,
                    "dispatches": counts["drain_dispatch"],
                    "complete_receipt": scenario == "accepted",
                    "mutation_uncertain": scenario != "accepted",
                    "provider_elapsed_seconds": (
                        round(completed["time"] - dispatched["time"], 3) if completed else None
                    ),
                    "term_after_dispatch_seconds": {
                        name: round(stamp - dispatched["time"], 3)
                        for name, stamp in signals.items()
                    },
                    "exit_after_first_term_seconds": {
                        "app": round(app_exit - min(signals.values()), 3),
                        "proxy": round(proxy_exit - min(signals.values()), 3),
                    },
                }
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def run_case(
    directory: Path, options: DrainOptions, protocol: str, order: str, scenario: str
) -> dict[str, Any]:
    directory.mkdir(mode=0o700)
    harness = DrainHarness(directory, options)
    report: dict[str, Any] = {
        "ok": False,
        "profile": options.profile,
        "scenario": scenario,
        "term_order": order,
        "client_offer": protocol,
    }
    try:
        context = await asyncio.to_thread(harness.prepare)
        report = await harness.exercise_case(context, protocol, order, scenario)
    except Exception as error:
        if isinstance(error, CheckFailure):
            report["failure"] = str(error)
        elif isinstance(error, httpx.RemoteProtocolError):
            report["failure"] = "client_remote_protocol_error"
        elif isinstance(error, TimeoutError):
            report["failure"] = "case_deadline_exceeded"
        else:
            report["failure"] = "drain_case_failed"
    finally:
        try:
            await asyncio.to_thread(harness.close)
        except Exception as error:
            report["ok"] = False
            report["cleanup_failure"] = (
                str(error) if isinstance(error, CheckFailure) else "cleanup_failed"
            )
    return report


async def exercise(directory: Path, options: DrainOptions) -> list[dict[str, Any]]:
    require(importlib.util.find_spec("h2") is not None, "http2_dependency_missing")
    results = await asyncio.gather(
        *(
            run_case(directory / f"{index}-{order}", options, protocol, order, "accepted")
            for index, protocol in enumerate(PROTOCOLS)
            for order in ORDERS
        )
    )
    # Failure/disconnect controls always use short clocks, even in the production run.
    results.extend(
        await asyncio.gather(
            *(
                run_case(
                    directory / f"{index}-{scenario}",
                    DrainOptions(options.caddy_bin),
                    protocol,
                    "simultaneous",
                    scenario,
                )
                for index, protocol in enumerate(PROTOCOLS)
                for scenario in ("stalled", "disconnected")
            )
        )
    )
    return results


def main(arguments: list[str] | None = None) -> int:
    try:
        options = parse_options(arguments)
    except (ValueError, OSError):
        print(json.dumps({"ok": False, "failure": "invalid_arguments"}))
        return 2
    report: dict[str, Any] = {
        "ok": False,
        "profile": options.profile,
        "clocks_seconds": asdict(PROFILES[options.profile]),
        "cases": [],
        "limitations": [
            "Mock-only loopback app/Caddy; no provider, APIG, VKE, rollout or node-drain acceptance.",
            "Production uses 590s mock work and 600/630/660s clocks; short is timing-scaled.",
            "H1 and H2-capable clients must negotiate HTTP/1.1 on the private production listener.",
            "Public APIG TLS/protocol behavior is independent and untested here.",
            "Disconnect and stalled controls use short clocks and never resubmit.",
            "One synthetic receipt is not exactly-once provider billing or durable recovery.",
        ],
    }
    try:
        with (
            cleanup_signals(),
            tempfile.TemporaryDirectory(prefix="seed-hosted-drain-") as temporary,
        ):
            report["cases"] = asyncio.run(exercise(Path(temporary), options))
            report["ok"] = all(case["ok"] for case in report["cases"])
    except (Exception, KeyboardInterrupt) as error:
        report["ok"] = False
        report["failure"] = (
            str(error) if isinstance(error, CheckFailure) else "drain_harness_failed"
        )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
