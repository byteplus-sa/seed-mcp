"""FastMCP server factory and module-level deployment entrypoint.

Tools are registered from the static catalog in ``tools/_catalog.py``; the
direct-call contract is ``specs/SPEC_DIRECT_EXECUTION.md``. Runtime resources
are created once by the FastMCP lifespan; importing this module only assembles
the declarative server surface.
"""

from __future__ import annotations

import contextlib
import os
import subprocess  # nosec B404
from datetime import UTC, datetime
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import truststore

truststore.inject_into_ssl()

from fastmcp import Context, FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from fastmcp.resources import ResourceContent, ResourceResult  # noqa: E402
from fastmcp.server.dependencies import get_context  # noqa: E402
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request

from ark_mcp.config.env import (  # noqa: E402
    Settings,
    get_settings,
    resolve_env_file,
    settings_scope,
)
from ark_mcp.execution import run_direct_call  # noqa: E402
from ark_mcp.observability.logger import info as log_info  # noqa: E402
from ark_mcp.observability.logger import set_level  # noqa: E402
from ark_mcp.observability.logger import warning as log_warning  # noqa: E402
from ark_mcp.observability.metrics import (  # noqa: E402
    MetricsMiddleware,
)
from ark_mcp.runtime import (  # noqa: E402
    RuntimeFactory,
    RuntimeState,
    build_lifespan,
    create_runtime_services,
    get_principal,
    get_runtime,
)
from ark_mcp.security.credentials import (  # noqa: E402
    endpoint_default,
    provider_scope,
    redact_request_secrets,
)
from ark_mcp.security.http_middleware import (  # noqa: E402
    ByokHeadersMiddleware,
    InFlightLimitMiddleware,
    RateLimitMiddleware,
    RequestBodyLimitMiddleware,
)
from ark_mcp.submissions import execute_submission  # noqa: E402
from ark_mcp.tools._catalog import (  # noqa: E402
    CATALOG,
    CatalogEntry,
    ToolDefinition,
    resolve_tool_definition,
)

SERVER_INSTRUCTIONS = (
    "BytePlus multimodal generation server: Seedance video, Seedream images, Seed Audio, "
    "and OmniHuman avatar video. "
    "Call ark_list_models first: `model` accepts only the exact "
    "configured IDs it returns, and it lists per-model limits and which optional services "
    "are enabled. Call tools directly; MCP background jobs and native tasks are unavailable. "
    "Calls have bounded admission and execution deadlines; timeouts do not cancel provider work. "
    "Poll Seedance tasks with gen_task_get and OmniHuman tasks with "
    "omnihuman_get_task; never resubmit a create tool to poll. "
    "Local persistence is explicit; persisted media uses seed-media:// resources. "
    "Reference private assets as "
    "asset://<asset_id> in Seedance."
)

HTTP_SERVER_INSTRUCTIONS = (
    "Seed MCP: customer-key ModelArk, Seed Speech and OmniHuman. "
    "Call ark_list_models first, then call provider tools directly in the foreground. "
    "Configure provider keys and X-MCP-Client-Secret privately in client HTTP headers, "
    "never prompts or tool arguments. No OAuth, signup or MCP bearer key is used. "
    "Poll existing video task IDs; never resubmit a create call to poll. "
    "Seedance non-dry and OmniHuman creates require a fresh idempotency_key per operation. "
    "Reuse identical arguments/key only for delivery recovery; never change keys to bypass "
    "an unresolved submission. Other provider tools do not have durable replay. "
    "HTTP output is temporary provider URLs: persist and persist_output must be false. "
    "Background tasks, uploads and artifact resources are not available over HTTP."
)


def _direct_handler(
    entry: CatalogEntry,
    handler: Callable[..., Awaitable[Any]],
    settings: Settings,
    *,
    read_only: bool,
) -> Callable[..., Awaitable[Any]]:
    async def invoke(*args: Any, **kwargs: Any) -> Any:
        if settings.mcp_transport != "http" or entry.provider is None:
            return await handler(*args, **kwargs)
        with provider_scope(settings, entry.provider):
            bound = signature(handler).bind(*args, **kwargs)
            request = bound.arguments.get("input")
            default = endpoint_default(entry.name)
            if default and request is not None and getattr(request, "model", None) is None:
                bound.arguments["input"] = type(request).model_validate(
                    {**request.model_dump(), "model": default}
                )
            return await execute_submission(
                bound.arguments["ctx"],
                entry.name,
                bound.arguments["input"],
                lambda: handler(*bound.args, **bound.kwargs),
            )

    @wraps(handler)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if get_context().client_extension_settings("io.modelcontextprotocol/tasks") is not None:
            raise ToolError(
                "Seed MCP does not support background execution. "
                "Call the tool without the tasks extension opt-in."
            )
        try:
            with settings_scope(settings):
                return await run_direct_call(
                    lambda: invoke(*args, **kwargs),
                    timeout_seconds=settings.tool_timeout_seconds,
                    read_only=read_only,
                )
        except (PermissionError, ValueError) as exc:
            raise ToolError(redact_request_secrets(str(exc))) from None
        except ToolError as exc:
            raise ToolError(redact_request_secrets(str(exc))) from None
        except Exception:
            raise ToolError(
                "Provider operation could not complete safely. Its outcome may be unknown; "
                "do not automatically resubmit billable work."
            ) from None

    guarded.__dict__["__signature__"] = signature(handler, eval_str=True)
    return guarded


def register_tools(server: FastMCP, settings: Settings) -> None:
    """Register every catalog tool whose settings gate passes."""
    skipped: list[str] = []
    for entry, definition in _gated_tool_definitions(settings, skipped):
        server.tool(
            name=entry.name,
            annotations={**definition.annotations},
            output_schema=definition.output_model.model_json_schema(),
        )(
            _direct_handler(
                entry,
                definition.handler,
                settings,
                read_only=bool(definition.annotations.get("readOnlyHint", False)),
            )
        )
    if skipped:
        log_info(
            "tools_skipped", tools=skipped, reason="provider not configured or feature disabled"
        )


def _gated_tool_definitions(
    settings: Settings, skipped: list[str]
) -> list[tuple[CatalogEntry, ToolDefinition]]:
    definitions: list[tuple[CatalogEntry, ToolDefinition]] = []
    for entry in CATALOG:
        if entry.gate(settings):
            definitions.append((entry, resolve_tool_definition(entry)))
        else:
            skipped.append(entry.name)
    return definitions


class HardenedFastMCP(FastMCP):
    """FastMCP subclass that applies ASGI body and rate-limit middleware for HTTP."""

    def __init__(
        self,
        *args: Any,
        app_settings: Settings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._app_settings = app_settings

    def http_app(self, *args: Any, **kwargs: Any) -> Any:
        if self._app_settings is None or self._app_settings.mcp_transport != "http":
            raise ValueError("Create HTTP servers with MCP_TRANSPORT=http and BYOK settings.")
        if self._app_settings.mcp_transport == "http":
            asgi_middleware = [
                Middleware(
                    InFlightLimitMiddleware,
                    max_in_flight=self._app_settings.http_max_in_flight,
                ),
                Middleware(
                    RequestBodyLimitMiddleware,
                    max_bytes=self._app_settings.mcp_http_max_body_bytes,
                ),
            ]
            if self._app_settings.rate_limit_rpm > 0:
                asgi_middleware.append(
                    Middleware(
                        RateLimitMiddleware,
                        rpm=self._app_settings.rate_limit_rpm,
                        burst=(
                            self._app_settings.rate_limit_burst or self._app_settings.rate_limit_rpm
                        ),
                        trusted_proxy_cidrs=self._app_settings.trusted_proxy_networks,
                    )
                )
            asgi_middleware.append(Middleware(ByokHeadersMiddleware, settings=self._app_settings))
            asgi_middleware.extend(kwargs.get("middleware") or [])
            kwargs["middleware"] = asgi_middleware
            kwargs["stateless_http"] = True
            kwargs["json_response"] = True
            kwargs["host_origin_protection"] = True
            kwargs["allowed_hosts"] = self._app_settings.allowed_hosts
            kwargs["allowed_origins"] = self._app_settings.allowed_origins
        return super().http_app(*args, **kwargs)


def _disabled_http_guardrails(settings: Settings) -> list[str]:
    if settings.mcp_transport != "http":
        return []
    disabled = []
    if not settings.daily_budget_usd:
        disabled.append("DAILY_BUDGET_USD")
    if settings.rate_limit_rpm <= 0:
        disabled.append("RATE_LIMIT_RPM")
    return disabled


def _local_export_status(settings: Settings) -> str:
    if settings.mcp_transport != "stdio":
        return "disabled (stdio only)"
    roots = settings.output_root_paths
    if not roots:
        return "request-dependent (use client MCP roots or configure OUTPUT_ROOTS)"
    for root in roots:
        if "\0" in root:
            continue
        try:
            absolute = Path(root).expanduser().is_absolute()
        except (RuntimeError, ValueError):
            continue
        if absolute:
            return "configured; needs request preflight"
    return "not configured (OUTPUT_ROOTS has no usable absolute roots)"


def _seedream_default_family(settings: Settings) -> str:
    return next(
        binding.family.value
        for binding in settings.seedream_model_bindings
        if binding.model_id == settings.seedream_default_model
    )


def create_server(
    settings: Settings | None = None,
    *,
    runtime_factory: RuntimeFactory = create_runtime_services,
) -> FastMCP:
    """Build an isolated server with a once-per-server runtime lifespan."""
    resolved_settings = settings or get_settings()
    set_level(resolved_settings.log_level)
    runtime_state = RuntimeState()
    server: FastMCP = HardenedFastMCP(
        "Ark Seed Multimodal",
        instructions=(
            HTTP_SERVER_INSTRUCTIONS
            if resolved_settings.mcp_transport == "http"
            else SERVER_INSTRUCTIONS
        ),
        auth=None,
        mask_error_details=True,
        lifespan=build_lifespan(resolved_settings, runtime_factory, runtime_state),
        middleware=[MetricsMiddleware()],
        app_settings=resolved_settings,
    )

    async def get_artifact(artifact_id: str, ctx: Context) -> ResourceResult:
        """Return persisted media after canonical ID and ownership checks."""
        try:
            parsed_artifact_id = UUID(artifact_id, version=4)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid artifact ID format: '{artifact_id}'") from exc
        if str(parsed_artifact_id) != artifact_id:
            raise ValueError(f"Invalid artifact ID format: '{artifact_id}'")

        runtime = get_runtime(ctx)
        artifact = await runtime.artifact_store.get(
            artifact_id,
            auth=get_principal(ctx),
        )
        log_info(
            "artifact_served",
            artifact_id=artifact_id,
            media_type=artifact.media_type,
            mime_type=artifact.mime_type,
            bytes=len(artifact.data),
        )
        return ResourceResult(
            contents=[ResourceContent(content=artifact.data, mime_type=artifact.mime_type)],
            meta={"artifact_id": artifact_id, "media_type": artifact.media_type},
        )

    async def health_status() -> str:
        """Return credential-free configuration diagnostics, not authorization or readiness."""
        stamp = _build_stamp()
        return (
            "Ark Seed MCP Server\n"
            f"Build: {stamp}\n"
            "Status: healthy\n"
            "Diagnostics: configuration only; provider authorization is not checked; "
            "filesystem readiness is not checked\n"
            f"ModelArk configured: {resolved_settings.has_modelark}\n"
            f"Seedream default model: {resolved_settings.seedream_default_model}\n"
            f"Seedream default family: {_seedream_default_family(resolved_settings)}\n"
            f"Seed Audio configured: {resolved_settings.has_seed_audio}\n"
            f"OmniHuman configured: {resolved_settings.has_omnihuman}\n"
            f"TOS configured: {resolved_settings.has_tos}\n"
            f"S3 configured: {resolved_settings.has_s3}\n"
            f"Object storage backend: {resolved_settings.object_storage_backend}\n"
            f"Artifact backend: {resolved_settings.artifact_backend}\n"
            f"Transport: {resolved_settings.mcp_transport}\n"
            f"Local export: {_local_export_status(resolved_settings)}\n"
        )

    if resolved_settings.mcp_transport == "stdio":
        server.resource("seed-media://artifacts/{artifact_id}")(get_artifact)
        server.resource("seed-health://status")(health_status)

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    @server.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        runtime = runtime_state.runtime
        if runtime is None:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        try:
            await runtime.ownership_store.ping()
            artifact_root = Path(runtime.settings.artifact_dir).expanduser().resolve()
            if not artifact_root.is_dir() or not os.access(artifact_root, os.W_OK):
                raise RuntimeError("Artifact storage is not writable.")
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)

        if (
            resolved_settings.mcp_transport == "http"
            or not resolved_settings.readiness_check_providers
        ):
            return JSONResponse({"status": "ready"})

        providers: dict[str, str] = {}
        timeout = resolved_settings.readiness_provider_timeout_seconds

        if resolved_settings.has_modelark:
            from ark_mcp.providers.modelark.client import ModelArkGateway

            modelark_gw = ModelArkGateway(
                api_key=resolved_settings.modelark_api_key,
                base_url=resolved_settings.modelark_base_url,
                timeout=resolved_settings.request_timeout_ms / 1000,
                connect_timeout=resolved_settings.connect_timeout_ms / 1000,
            )
            try:
                providers["modelark"] = (
                    "reachable"
                    if await modelark_gw.health_check(timeout_seconds=timeout)
                    else "unreachable"
                )
            finally:
                await modelark_gw.close()

        if resolved_settings.has_seed_audio:
            from ark_mcp.providers.seed_speech.client import SeedSpeechGateway

            audio_gw = SeedSpeechGateway(
                api_key=resolved_settings.seed_speech_api_key,
                base_url=resolved_settings.seed_audio_base_url,
                timeout=resolved_settings.request_timeout_ms / 1000,
                connect_timeout=resolved_settings.connect_timeout_ms / 1000,
            )
            try:
                providers["seed_audio"] = (
                    "reachable"
                    if await audio_gw.health_check(timeout_seconds=timeout)
                    else "unreachable"
                )
            finally:
                await audio_gw.close()

        if resolved_settings.has_omnihuman:
            from ark_mcp.providers.vision_cv.client import VisionCvGateway

            cv_gw = VisionCvGateway(
                api_key=resolved_settings.cv_api_key,
                base_url=resolved_settings.cv_base_url,
                timeout=resolved_settings.request_timeout_ms / 1000,
                connect_timeout=resolved_settings.connect_timeout_ms / 1000,
            )
            try:
                providers["vision_cv"] = (
                    "reachable"
                    if await cv_gw.health_check(timeout_seconds=timeout)
                    else "unreachable"
                )
            finally:
                await cv_gw.close()

        all_reachable = all(v == "reachable" for v in providers.values())
        if all_reachable:
            return JSONResponse({"status": "ready", "providers": providers})
        return JSONResponse(
            {"status": "degraded", "providers": providers},
            status_code=503,
        )

    async def metrics(_request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if resolved_settings.mcp_transport == "stdio":
        server.custom_route("/metrics", methods=["GET"])(metrics)

    register_tools(server, resolved_settings)
    if resolved_settings.mcp_transport == "stdio" and not (
        resolved_settings.has_modelark
        or resolved_settings.has_seed_audio
        or resolved_settings.has_omnihuman
    ):
        log_warning(
            "no_provider_credentials_configured",
            detail=(
                "No generation provider credentials resolved. Configure ModelArk, Seed Audio "
                "or OmniHuman credentials to enable generation. The env file is read relative "
                "to the server's working directory; set ARK_MCP_ENV_FILE to an absolute path, "
                "or launch the server with its working directory at the repository root."
            ),
            env_file=resolve_env_file(),
            cwd=str(Path.cwd()),
        )
    disabled_guardrails = _disabled_http_guardrails(resolved_settings)
    if disabled_guardrails:
        log_warning(
            "http_guardrails_disabled",
            disabled=disabled_guardrails,
            detail="Set DAILY_BUDGET_USD and RATE_LIMIT_RPM for shared HTTP; see docs/self-hosting.md.",
        )
    log_info(
        "server_ready",
        transport=resolved_settings.mcp_transport,
        auth_mode=resolved_settings.mcp_auth_mode.value,
        modelark_configured=resolved_settings.has_modelark,
        seed_audio_configured=resolved_settings.has_seed_audio,
        omnihuman_configured=resolved_settings.has_omnihuman,
        object_storage_backend=resolved_settings.object_storage_backend,
        artifact_backend=resolved_settings.artifact_backend,
        log_level=resolved_settings.log_level,
    )
    return server


mcp: FastMCP = create_server()


def _build_stamp() -> str:
    """Return a short build-identity stamp (git SHA + import time)."""
    sha = _git_sha()
    installed = datetime.now(UTC).isoformat()
    if sha:
        return f"git:{sha} installed:{installed}"
    return f"installed:{installed}"


def _git_sha() -> str | None:
    """Return the short (7-char) git SHA of HEAD, or None on failure."""
    with contextlib.suppress(Exception):
        result = subprocess.run(  # nosec B603, B607
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent.parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    return None
