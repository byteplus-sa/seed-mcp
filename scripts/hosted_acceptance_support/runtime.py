"""Isolated process, protocol and report primitives for hosted acceptance."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import secrets
import signal
import socket
import ssl
import subprocess
import threading
from collections import Counter
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, quote_plus

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from types import FrameType

    import httpx

ROOT = Path(__file__).resolve().parents[2]
BODY_LIMIT = 32768
TOOL_TIMEOUT = 2.0
PUBLIC_TOOLS = {
    "ark_list_models",
    "seed_audio_generate",
    "seedream_generate_image",
    "seedance_create_task",
    "gen_task_get",
    "gen_task_list",
    "gen_task_cancel_or_delete",
}
AVATAR_TOOLS = {"omnihuman_create_task", "omnihuman_get_task", "omnihuman_cancel_task"}
IMAGE_MODEL = "ep-acceptance-image"
VIDEO_MODEL = "ep-acceptance-video"
MODELARK = "https://ark.ap-southeast.bytepluses.com/api/v3"


class CheckFailure(Exception):
    """Carry only a fixed, value-free check identifier."""


def require(condition: object, code: str) -> None:
    if not condition:
        raise CheckFailure(code)


@contextmanager
def cleanup_signals() -> Iterator[None]:
    interrupted = False

    def interrupt(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        for number in previous:
            signal.signal(number, interrupt)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


async def verify_untrusted_certificate(port: int) -> None:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                "127.0.0.1",
                port,
                ssl=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                server_hostname="127.0.0.1",
                ssl_handshake_timeout=3,
            ),
            timeout=5,
        )
    except ssl.SSLCertVerificationError:
        return
    writer.close()
    await asyncio.wait_for(writer.wait_closed(), timeout=3)
    raise CheckFailure("certificate_trusted_without_test_ca")


def fixtures() -> dict[str, str]:
    return {
        "key": "synthetic-" + secrets.token_hex(24),
        "invalid_key": "synthetic-rejected-" + secrets.token_hex(24),
        "speech_key": "synthetic-speech-" + secrets.token_hex(24),
        "vision_key": "synthetic-vision-" + secrets.token_hex(24),
        "secret": secrets.token_hex(32),
        "other_secret": secrets.token_hex(32),
        "hmac": secrets.token_hex(32),
        "prompt": "synthetic-private-prompt-" + secrets.token_hex(16),
        "media": "https://example.com/synthetic.png?signature=" + secrets.token_hex(16),
        "operation": "synthetic-operation-" + secrets.token_hex(16),
        "forwarded": "synthetic-forwarded-" + secrets.token_hex(16),
    }


def isolated_environment(home: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    return {
        **{name: source[name] for name in ("PATH", "SYSTEMROOT") if name in source},
        "HOME": str(home),
        "TMPDIR": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "ARK_MCP_ENV_FILE": str(home / "absent.env"),
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_ENV_FILE": str(home / "absent.env"),
        "DO_NOT_TRACK": "1",
        "OTEL_SDK_DISABLED": "true",
        "LANG": "C",
    }


class ManagedProcess:
    """Own one process group with serialized, bounded shutdown and a watchdog."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        home: Path,
        env: Mapping[str, str],
        log: Path,
        lifetime: float = 240,
        output: Path | None = None,
    ) -> None:
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise ValueError("Invalid process lifetime.")
        self._lock = threading.RLock()
        self.timed_out = False
        self.forced = False
        self.cleanup_failed = False
        self._stopped = False
        with ExitStack() as stack:
            error_stream = stack.enter_context(log.open("wb"))
            output_stream = stack.enter_context(output.open("wb")) if output else error_stream
            self.process = subprocess.Popen(
                command,
                cwd=home,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output_stream,
                stderr=error_stream,
                start_new_session=True,
                umask=0o077,
            )
        self._timer = threading.Timer(lifetime, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _signal(self, value: int) -> None:
        if self.process.poll() is not None:
            return
        try:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, value)
        except PermissionError:
            if self.process.poll() is None:
                raise

    def _expire(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self.timed_out = True
            try:
                self.stop(grace=0)
            except Exception:
                self.cleanup_failed = True

    def stop(self, grace: float = 8) -> None:
        with self._lock:
            self._timer.cancel()
            if not self._stopped and self.process.poll() is None:
                self._signal(signal.SIGTERM)
                try:
                    self.process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    self.forced = True
                    self._signal(signal.SIGKILL)
                    self.process.wait(timeout=5)
            self._stopped = True
        if self._timer is not threading.current_thread():
            self._timer.join(timeout=5)
            if self._timer.is_alive():
                self.cleanup_failed = True

    def healthy(self) -> bool:
        return not self.timed_out and self.process.poll() is None


def free_ports(count: int) -> list[int]:
    listeners: list[socket.socket] = []
    try:
        for _ in range(count):
            listener = socket.socket()
            listeners.append(listener)
            listener.bind(("127.0.0.1", 0))
        return [listener.getsockname()[1] for listener in listeners]
    finally:
        for listener in listeners:
            listener.close()


def loopback_config(config: dict[str, Any], port: int) -> dict[str, Any]:
    config = copy.deepcopy(config)
    servers = config.get("apps", {}).get("http", {}).get("servers", {})
    require(len(servers) == 1, "proxy_listener_contract")
    server = next(iter(servers.values()))
    require(server.get("listen") == [f":{port}"], "proxy_listener_contract")
    server["listen"] = [f"127.0.0.1:{port}"]
    return config


def tls_context(certificate: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(certificate))
    require(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED, "tls_policy")
    return context


def scan_files(directory: Path, canaries: Sequence[str]) -> None:
    needles = {
        encoded.encode()
        for value in canaries
        for encoded in (value, quote(value, safe=""), quote_plus(value), json.dumps(value)[1:-1])
        if encoded
    }
    overlap = max((len(needle) for needle in needles), default=1)
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            tail = b""
            while chunk := stream.read(65536):
                content = tail + chunk
                require(not any(needle in content for needle in needles), "canary_leak")
                tail = content[-overlap:]


def protocol_request(
    method: str, params: dict[str, Any] | None = None
) -> tuple[dict[str, str], dict[str, Any]]:
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        **params.get("_meta", {}),
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Mcp-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if "name" in params:
        headers["Mcp-Name"] = params["name"]
    return headers, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def result_of(response: httpx.Response) -> dict[str, Any]:
    require(response.status_code == 200, "unexpected_http_status")
    require("mcp-session-id" not in response.headers, "unexpected_stateful_session")
    body = response.json()
    require(
        isinstance(body, dict) and "error" not in body and isinstance(body.get("result"), dict),
        "rpc_result",
    )
    result: dict[str, Any] = body["result"]
    return result


def successful(response: httpx.Response) -> dict[str, Any]:
    result = result_of(response)
    require(not result.get("isError"), "unexpected_tool_error")
    content = result.get("structuredContent")
    if not isinstance(content, dict):
        raise CheckFailure("missing_structured_result")
    require(not content.get("failed") and not content.get("errors"), "unexpected_item_error")
    return dict(content)


def expected_error(response: httpx.Response, code: str) -> str:
    result = result_of(response)
    require(result.get("isError") is True, "expected_tool_rejection")
    require(result.get("structuredContent") is None, "error_is_structured_success")
    text = "\n".join(block.get("text", "") for block in result.get("content", []))
    require(code in text, "unexpected_rejection_code")
    return text


Outcome = Literal["success", "overload", "error"]


def classify(response: httpx.Response) -> Outcome:
    if response.status_code == 429 or (
        response.status_code == 503
        and response.text == "Server concurrency limit reached."
        and response.headers.get("Retry-After") == "1"
    ):
        return "overload"
    if response.status_code != 200:
        return "error"
    try:
        result = result_of(response)
        if result.get("isError"):
            text = "\n".join(block.get("text", "") for block in result.get("content", []))
            return "overload" if "code=ADMISSION_TIMEOUT" in text else "error"
        content = result.get("structuredContent")
        if not isinstance(content, dict) or content.get("errors") or content.get("failed"):
            return "error"
    except (CheckFailure, ValueError, TypeError, AttributeError):
        return "error"
    return "success"


@dataclass(frozen=True)
class Sample:
    latency_ms: float
    status: int
    outcome: Outcome


def aggregate(samples: Sequence[Sample], duration: float, concurrency: int) -> dict[str, Any]:
    if (
        not samples
        or not math.isfinite(duration)
        or duration <= 0
        or not 1 <= concurrency <= 32
        or any(
            not math.isfinite(item.latency_ms)
            or item.latency_ms < 0
            or item.outcome not in {"success", "overload", "error"}
            or (item.status != 0 and not 100 <= item.status <= 599)
            for item in samples
        )
    ):
        raise ValueError("Invalid aggregate inputs.")
    latencies = sorted(item.latency_ms for item in samples)
    return {
        "requests": len(samples),
        "concurrency": concurrency,
        "duration_seconds": round(duration, 6),
        "latency_ms": {
            f"p{percentile}": round(latencies[math.ceil(len(samples) * percentile / 100) - 1], 3)
            for percentile in (50, 95, 99)
        },
        "throughput_rps": round(len(samples) / duration, 3),
        "statuses": dict(
            Counter(str(item.status) if item.status else "transport_error" for item in samples)
        ),
        **{
            f"{outcome}_count": sum(item.outcome == outcome for item in samples)
            for outcome in ("success", "overload", "error")
        },
    }
