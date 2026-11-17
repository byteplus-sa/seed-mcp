"""Private real HTTP worker. Provider mocks live in this process, never its parent."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import httpx
import respx
from scripts.hosted_acceptance_support.runtime import (
    BODY_LIMIT,
    IMAGE_MODEL,
    MODELARK,
    TOOL_TIMEOUT,
    VIDEO_MODEL,
    require,
)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


def serve(directory: Path, port: int, mode: str) -> None:
    from starlette.middleware import Middleware

    from ark_mcp.config.env import Settings
    from ark_mcp.server import create_server

    values: dict[str, str] = json.loads(os.environ.pop("ACCEPTANCE_FIXTURES"))
    lock = threading.Lock()

    def record(label: str) -> None:
        with lock, (directory / "dispatches.log").open("a") as stream:
            stream.write(label + "\n")

    def reject() -> NoReturn:
        record("mock_violation")
        raise RuntimeError("Unexpected mock dispatch.")

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            reject()

    sys.addaudithook(audit)

    class ForwardProbe:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            headers = scope.get("headers", [])
            if scope["type"] == "http" and (b"x-acceptance-probe", b"1") in headers:
                mapped = dict(headers)
                checks = {
                    "proxy_peer": scope.get("client", ("",))[0] == "127.0.0.1",
                    "proxy_xff": [value for key, value in headers if key == b"x-forwarded-for"]
                    == [b"127.0.0.1"],
                    "proxy_proto": mapped.get(b"x-forwarded-proto") == b"https",
                    "proxy_host": mapped.get(b"x-forwarded-host") == b"127.0.0.1",
                    "proxy_forwarded": b"forwarded" not in mapped,
                }
                for label, valid in checks.items():
                    if not valid:
                        record(label + "_failed")
                record("proxy_verified" if all(checks.values()) else "mock_violation")
            await self.app(scope, receive, send)

    async def respond(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("authorization")
        if authorization == f"Bearer {values['invalid_key']}":
            record("invalid_key")
            return httpx.Response(
                401,
                json={"error": {"code": "SYNTHETIC_INVALID_KEY", "message": values["invalid_key"]}},
            )
        if (
            authorization != f"Bearer {values['key']}"
            or "x-mcp-client-secret" in request.headers
            or "x-modelark-api-key" in request.headers
            or values["secret"].encode() in request.content
        ):
            reject()
        if request.method == "GET":
            record("poll")
            task_ids = request.url.params.get("filter.task_ids", "").split(",")
            if not task_ids or any(
                not task_id.startswith("cgt-acceptance-") for task_id in task_ids
            ):
                reject()
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": task_id,
                            "model": VIDEO_MODEL,
                            "status": "succeeded",
                            "content": {"video_url": "https://example.com/acceptance.mp4"},
                        }
                        for task_id in task_ids
                    ]
                },
            )
        payload = json.loads(request.content)
        image = request.url.path.endswith("/images/generations")
        if payload.get("model") != (IMAGE_MODEL if image else VIDEO_MODEL):
            reject()
        prompt = payload["prompt"] if image else payload["content"][0]["text"]
        if prompt in {"slow", "disconnect"}:
            record(prompt)
            await asyncio.Event().wait()
        if prompt == "transport-failure":
            record("transport_failure")
            raise httpx.ReadError(
                " ".join(values[name] for name in ("key", "secret", "media")), request=request
            )
        if prompt == "provider-failure":
            record("provider_failure")
            return httpx.Response(
                503,
                json={"error": {"code": "SYNTHETIC_FAILURE", "message": values["key"]}},
                headers={"X-Request-Id": values["secret"]},
            )
        if prompt not in {"load", values["prompt"]}:
            reject()
        record("image" if image else "video")
        await asyncio.sleep(0.02)
        body = (
            {"data": [{"url": "https://example.com/acceptance.png"}]}
            if image
            else {"id": "cgt-acceptance-" + os.urandom(8).hex()}
        )
        return httpx.Response(200, json=body, headers={"X-Request-Id": "req-acceptance"})

    def unexpected(request: httpx.Request) -> httpx.Response:
        reject()

    settings = Settings.model_validate(
        {
            "MCP_TRANSPORT": "http",
            "MCP_HOST": "127.0.0.1",
            "MCP_IDENTITY_HMAC_KEY": values["hmac"],
            "MCP_IDENTITY_KEY_VERSION": 1,
            "MCP_ALLOWED_HOSTS": "127.0.0.1,localhost",
            "ARTIFACT_DIR": str(directory / "state"),
            "SEEDREAM_DEFAULT_MODEL": IMAGE_MODEL,
            "SEEDREAM_MODEL_BINDINGS": [{"model_id": IMAGE_MODEL, "family": "pro"}],
            "SEEDANCE_DEFAULT_MODEL": VIDEO_MODEL,
            "SEEDANCE_MODEL_BINDINGS": [{"model_id": VIDEO_MODEL, "family": "seedance_2_5"}],
            "BYTEPLUS_OMNIHUMAN_ENABLED": mode == "omni",
            "MCP_ADMISSION_TIMEOUT_SECONDS": 0.05,
            "MCP_TOOL_TIMEOUT_SECONDS": TOOL_TIMEOUT,
            "PROVIDER_MAX_CONCURRENCY": 1,
            "PRINCIPAL_MAX_CONCURRENCY": 1,
            "MCP_HTTP_MAX_BODY_BYTES": BODY_LIMIT,
            "MCP_HTTP_MAX_IN_FLIGHT": 1 if mode == "inflight" else 8,
            "RATE_LIMIT_RPM": 1 if mode == "rate" else 60000,
            "RATE_LIMIT_BURST": 2 if mode == "rate" else 10000,
            "RATE_LIMIT_TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
        }
    )
    require(
        not any((settings.modelark_api_key, settings.seed_speech_api_key, settings.cv_api_key)),
        "worker_environment_credentials",
    )
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        router.post(f"{MODELARK}/images/generations").mock(side_effect=respond)
        router.post(f"{MODELARK}/contents/generations/tasks").mock(side_effect=respond)
        router.get(f"{MODELARK}/contents/generations/tasks").mock(side_effect=respond)
        router.route().mock(side_effect=unexpected)
        create_server(settings).run(
            transport="http",
            host="127.0.0.1",
            port=port,
            show_banner=False,
            log_level="info",
            middleware=[Middleware(ForwardProbe)],
            uvicorn_config={
                "proxy_headers": False,
                "access_log": False,
                "timeout_graceful_shutdown": 5,
            },
        )


if __name__ == "__main__":
    try:
        serve(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
    except KeyboardInterrupt:
        pass
    except Exception as error:
        frames = traceback.extract_tb(error.__traceback__)
        sys.stderr.write(
            json.dumps(
                {
                    "worker_failure": type(error).__name__,
                    "frames": [{"function": frame.name, "line": frame.lineno} for frame in frames],
                }
            )
            + "\n"
        )
        raise SystemExit(1) from None
