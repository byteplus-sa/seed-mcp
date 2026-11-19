"""Mock-only HTTPS acceptance for specs/SPEC_VKE_DEPLOYMENT.md.

Run with ``uv run python scripts/hosted_acceptance.py --caddy-bin /path/to/caddy``.
No client configuration, system trust, external providers or cloud resources change.
Latency percentiles use nearest rank across all load outcomes, including rejections.
This loopback harness is not a deployed capacity or live-provider certification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import httpx

if TYPE_CHECKING:
    import ssl

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.hosted_acceptance_support.checks import (
    bounded_generation,
    call,
    credential_checks,
    credentials,
    disconnect_check,
    dispatches,
    edge_checks,
    inflight_checks,
    rate_checks,
    run_load,
    surface,
    wait_healthy,
)
from scripts.hosted_acceptance_support.runtime import (
    BODY_LIMIT,
    ROOT,
    CheckFailure,
    ManagedProcess,
    cleanup_signals,
    expected_error,
    fixtures,
    free_ports,
    isolated_environment,
    loopback_config,
    require,
    scan_files,
    successful,
    tls_context,
    verify_untrusted_certificate,
)


@dataclass(frozen=True)
class Options:
    caddy_bin: Path
    max_requests: int = 40
    concurrency: int = 4


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("Invalid arguments.")


def positive_integer(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,4}", value):
        raise ValueError("Invalid integer.")
    return int(value)


def parse_options(arguments: list[str] | None = None) -> Options:
    parser = SafeParser(
        description="Full mock-only loopback HTTPS acceptance and bounded mixed synthetic load.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--caddy-bin", required=True, help="Explicit path to an installed Caddy executable."
    )
    parser.add_argument(
        "--max-requests",
        type=positive_integer,
        default=40,
        help="Load requests, 1-1000 (default 40).",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_integer,
        default=4,
        help="Load workers, 1-32 and <= requests (default 4).",
    )
    values = parser.parse_args(arguments)
    binary = Path(values.caddy_bin).resolve()
    if (
        not binary.is_file()
        or not os.access(binary, os.X_OK)
        or not 1 <= values.max_requests <= 1000
        or not 1 <= values.concurrency <= min(32, values.max_requests)
    ):
        raise ValueError("Invalid arguments.")
    return Options(binary, values.max_requests, values.concurrency)


class Harness:
    def __init__(self, directory: Path, options: Options) -> None:
        self.directory = directory
        self.options = options
        self.values = fixtures()
        self.environment = isolated_environment(directory)
        self.children: list[ManagedProcess] = []
        self.checks: list[str] = []
        self.load: dict[str, Any] | None = None
        self.backend_port, self.proxy_port = free_ports(2)
        self.url = f"https://127.0.0.1:{self.proxy_port}"
        self.backend = f"http://127.0.0.1:{self.backend_port}"

    def launch(
        self,
        command: list[str],
        label: str,
        *,
        env: dict[str, str] | None = None,
        lifetime: float = 240,
        output: Path | None = None,
    ) -> ManagedProcess:
        child = ManagedProcess(
            command,
            home=self.directory,
            env=env or self.environment,
            log=self.directory / f"{len(self.children)}-{label}.log",
            lifetime=lifetime,
            output=output,
        )
        self.children.append(child)
        return child

    def command(self, arguments: list[str], label: str, output: Path | None = None) -> None:
        child = self.launch(arguments, label, lifetime=20, output=output)
        try:
            child.process.wait(timeout=22)
        finally:
            child.stop()
        require(child.process.returncode == 0 and not child.timed_out, "local_command_failed")

    def prepare_proxy(self) -> ssl.SSLContext:
        openssl = shutil.which("openssl")
        require(openssl, "openssl_unavailable")
        certificate = self.directory / "certificate.pem"
        key = self.directory / "certificate-key.pem"
        config = self.directory / "openssl.cnf"
        config.write_text(
            "[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=extensions\n"
            "[dn]\nCN=localhost\n[extensions]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n"
            "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
            "extendedKeyUsage=serverAuth\n"
        )
        self.command(
            [
                str(openssl),
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-config",
                str(config),
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ],
            "openssl",
        )
        self.environment.update(
            {
                "MCP_PUBLIC_HOST": "127.0.0.1",
                "MCP_PROXY_PORT": str(self.proxy_port),
                "MCP_PORT": str(self.backend_port),
                "MCP_TLS_CERT_FILE": str(certificate),
                "MCP_TLS_KEY_FILE": str(key),
                "MCP_HTTP_MAX_BODY_BYTES": str(BODY_LIMIT),
                "MCP_PROXY_GRACE_PERIOD": "8s",
            }
        )
        shared = ROOT / "deploy" / "helm" / "seed-mcp" / "files" / "Caddyfile"
        adapted = self.directory / "adapted.json"
        self.command(
            [
                str(self.options.caddy_bin),
                "adapt",
                "--adapter",
                "caddyfile",
                "--config",
                str(shared),
            ],
            "caddy-adapt",
            adapted,
        )
        narrowed = loopback_config(json.loads(adapted.read_text()), self.proxy_port)
        adapted.write_text(json.dumps(narrowed))
        self.command(
            [str(self.options.caddy_bin), "validate", "--config", str(adapted)], "caddy-validate"
        )
        self.launch([str(self.options.caddy_bin), "run", "--config", str(adapted)], "caddy")
        self.checks.append("shared_caddy_validated_loopback_tls")
        return tls_context(certificate)

    def server(self, mode: str = "normal") -> ManagedProcess:
        from scripts.hosted_acceptance_support import worker

        return self.launch(
            [
                sys.executable,
                "-B",
                "-m",
                worker.__name__,
                str(self.directory),
                str(self.backend_port),
                mode,
            ],
            "server",
            env={**self.environment, "ACCEPTANCE_FIXTURES": json.dumps(self.values)},
        )

    @staticmethod
    def stop_server(child: ManagedProcess) -> None:
        require(child.healthy(), "server_exited_early")
        child.stop()
        require(
            not child.forced and child.process.returncode in (0, -signal.SIGTERM),
            "server_shutdown_failed",
        )

    async def exercise(self, context: ssl.SSLContext) -> None:
        async with (
            asyncio.timeout(180),
            httpx.AsyncClient(
                verify=context,
                trust_env=False,
                timeout=10,
                limits=httpx.Limits(max_connections=40, max_keepalive_connections=40),
            ) as client,
        ):
            child = self.server()
            await wait_healthy(client, self.url, child)
            await verify_untrusted_certificate(self.proxy_port)
            self.checks.append("client_only_tls_trust")
            await surface(client, self.url)
            require(not dispatches(self.directory), "discovery_dispatched")
            self.checks.append("exact_seven_tools_no_resources")
            await credential_checks(client, self.url, self.values, self.directory)
            self.checks.append("missing_malformed_invalid_credentials")
            await edge_checks(client, self.url, self.backend, self.values)
            require(dispatches(self.directory)["proxy_verified"] == 1, "forwarding_not_overwritten")
            self.checks.append("proxy_forwarding_body_caps_private_routes")
            await self.workflows(client)
            self.stop_server(child)
            response = await client.post(
                self.url + "/mcp?probe=" + self.values["forwarded"],
                headers={**credentials(self.values), "Forwarded": self.values["forwarded"]},
                content=b"{}",
            )
            require(response.status_code == 502, "proxy_upstream_failure")
            self.checks.append("proxy_upstream_failure")
            child = self.server()
            await wait_healthy(client, self.url, child)
            await surface(client, self.url)
            await self.ownership_checks(client)
            self.checks.append("exact_seven_tools_restart_provider_authorized_polling")
            self.stop_server(child)
            child = self.server("rate")
            await wait_healthy(client, self.url, child)
            await rate_checks(client, self.url)
            self.checks.append("spoof_resistant_rate_health_exemption")
            self.stop_server(child)
            child = self.server("inflight")
            await wait_healthy(client, self.url, child)
            await inflight_checks(client, self.url, self.values, self.directory)
            self.checks.append("http_inflight_health_exemption_recovery")
            self.stop_server(child)

    def video_input(self) -> dict[str, Any]:
        return {
            "prompt": self.values["prompt"],
            "duration": 4,
        }

    async def replays(self, client: httpx.AsyncClient) -> None:
        before = dispatches(self.directory)
        for other, original in zip((False, True), self.receipts, strict=True):
            replay = successful(
                await call(
                    client,
                    self.url,
                    "seedance_create_task",
                    self.video_input(),
                    credentials(self.values, other=other),
                )
            )
            require(
                replay["tasks"][0]["task_id"] != original["tasks"][0]["task_id"],
                "stateless_create_must_not_replay",
            )
        require(
            dispatches(self.directory)["video"] == before["video"] + 2, "new_creates_dispatched"
        )
        await self.ownership_checks(client)

    async def ownership_checks(self, client: httpx.AsyncClient) -> None:
        for index, other in enumerate((False, True)):
            own = self.receipts[index]["tasks"][0]["task_id"]
            foreign = self.receipts[1 - index]["tasks"][0]["task_id"]
            headers = credentials(self.values, other=other)
            visible = successful(
                await call(client, self.url, "gen_task_get", {"task_ids": [foreign]}, headers)
            )
            require(visible["tasks"][0]["task_id"] == foreign, "provider_authorized_poll")
            owned = successful(
                await call(client, self.url, "gen_task_get", {"task_ids": [own]}, headers)
            )
            require(owned["tasks"][0]["task_id"] == own and owned["all_terminal"], "owned_poll")

    async def workflows(self, client: httpx.AsyncClient) -> None:
        headers = credentials(self.values)
        before = dispatches(self.directory)
        check = successful(
            await call(client, self.url, "ark_list_models", {"check_connection": True}, headers)
        )["connection"]
        require(
            check["configuration_valid"]
            and not check["provider_calls_made"]
            and not check["authentication_verified"],
            "static_preflight",
        )
        require(dispatches(self.directory) == before, "preflight_dispatched")
        image = successful(
            await call(
                client,
                self.url,
                "seedream_generate_image",
                {"prompt": self.values["prompt"]},
                headers,
            )
        )
        require(
            image["artifacts"][0]["uri"] == "https://example.com/acceptance.png", "image_result"
        )
        self.receipts = [
            successful(
                await call(
                    client,
                    self.url,
                    "seedance_create_task",
                    self.video_input(),
                    credentials(self.values, other=other),
                )
            )
            for other in (False, True)
        ]
        require(
            self.receipts[0]["tasks"][0]["task_id"] != self.receipts[1]["tasks"][0]["task_id"],
            "distinct_owners_shared_key",
        )
        await self.replays(client)
        self.checks.append("preflight_image_video_poll_no_replay_two_client_secrets")
        for prompt, code in (
            ("provider-failure", "SYNTHETIC_FAILURE"),
            ("transport-failure", "ambiguous_completion=True"),
        ):
            response = await call(
                client, self.url, "seedream_generate_image", {"prompt": prompt}, headers
            )
            expected_error(response, code)
            require(
                not any(self.values[name] in response.text for name in ("key", "secret", "media")),
                "provider_error_leak",
            )
        require(
            dispatches(self.directory)["provider_failure"] == 1
            and dispatches(self.directory)["transport_failure"] == 1,
            "mutation_failure_retried",
        )
        self.checks.append("provider_error_transport_uncertainty_redaction")
        task_id = self.receipts[0]["tasks"][0]["task_id"]
        await bounded_generation(client, self.url, self.values, self.directory, task_id)
        self.checks.append("admission_deadline_polling_slot_recovery")
        await disconnect_check(client, self.url, self.values, self.directory)
        self.checks.append("disconnect_no_automatic_redispatch")
        self.load = await run_load(
            client, self.url, headers, task_id, self.options.max_requests, self.options.concurrency
        )
        require(self.load["error_count"] == 0, "unexpected_load_errors")
        self.checks.append("bounded_mixed_synthetic_load")

    def close(self) -> None:
        failures = False
        for child in reversed(self.children):
            try:
                child.stop()
                failures |= (
                    child.timed_out
                    or child.forced
                    or child.cleanup_failed
                    or child.process.returncode not in (0, -signal.SIGTERM)
                )
            except Exception:
                failures = True
        scan_files(self.directory, list(self.values.values()))
        require(not (self.directory / "state").exists(), "unexpected_persistent_state")
        require(not dispatches(self.directory)["mock_violation"], "unexpected_provider_dispatch")
        require(not failures, "process_cleanup_failed")
        self.checks.append("all_logs_state_canary_scan_cleanup")

    def report(self, failure: str | None = None) -> dict[str, Any]:
        return {
            "ok": failure is None,
            **({"failure": failure} if failure else {}),
            "checks": self.checks,
            "load": self.load,
            "limitations": [
                "Mocked providers; single local app and Caddy; no paid calls or cloud validation.",
                "Synthetic 20ms provider delay; 32KiB body cap; 2s tool deadline; not production defaults.",
                "Nearest-rank latency across all outcomes; throughput includes expected overload.",
                "No universal capacity threshold, real-client, VKE source-IP or failover certification.",
            ],
        }


def main(arguments: list[str] | None = None) -> int:
    try:
        options = parse_options(arguments)
    except (ValueError, OSError):
        print(json.dumps({"ok": False, "failure": "invalid_arguments"}))
        return 2
    failure: str | None = None
    report: dict[str, Any] = {"ok": False, "failure": "harness_failed"}
    try:
        with (
            cleanup_signals(),
            tempfile.TemporaryDirectory(prefix="seed-hosted-acceptance-") as temporary,
        ):
            harness = Harness(Path(temporary), options)
            try:
                context = harness.prepare_proxy()
                asyncio.run(harness.exercise(context))
            except (Exception, KeyboardInterrupt) as error:
                failure = str(error) if isinstance(error, CheckFailure) else "harness_failed"
            finally:
                try:
                    harness.close()
                except Exception as error:
                    failure = str(error) if isinstance(error, CheckFailure) else "cleanup_failed"
            report = harness.report(failure)
    except (Exception, KeyboardInterrupt):
        failure = "harness_failed"
        report = {**report, "ok": False, "failure": failure}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
