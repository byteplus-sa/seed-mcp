"""Ephemeral BYOK boundary for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

from ark_mcp.security.auth_context import PrincipalContext

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from fastmcp import Context

    from ark_mcp.config.env import Settings

CredentialProvider = Literal["modelark", "seed-speech", "vision-cv"]

PROVIDER_HEADERS: dict[CredentialProvider, str] = {
    "modelark": "x-modelark-api-key",
    "seed-speech": "x-seed-speech-api-key",
    "vision-cv": "x-omnihuman-api-key",
}
ENDPOINT_HEADERS = {
    "seedance_create_task": "x-modelark-seedance-endpoint",
    "seedream_generate_image": "x-modelark-seedream-endpoint",
}
INSTALLATION_HEADER_NAME = "x-mcp-client-secret"
_SECRET_HEADERS = frozenset((*PROVIDER_HEADERS.values(), INSTALLATION_HEADER_NAME))
_HEADERS = _SECRET_HEADERS | frozenset(ENDPOINT_HEADERS.values()) | {"authorization"}


@dataclass(slots=True)
class _RequestLifetime:
    active: bool = True


@dataclass(frozen=True, slots=True)
class _RequestCredentials:
    values: dict[str, str] = field(repr=False)
    lifetime: _RequestLifetime = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ProviderContext:
    provider: CredentialProvider | Literal["tos-upload"]
    principal: PrincipalContext
    request: _RequestCredentials = field(repr=False)


_request: ContextVar[_RequestCredentials | None] = ContextVar("byok_request", default=None)
_provider: ContextVar[_ProviderContext | None] = ContextVar("byok_provider", default=None)


@contextmanager
def request_credentials_scope(headers: Sequence[tuple[bytes, bytes]]) -> Iterator[None]:
    """Accept only raw live-request headers; never restore a task snapshot."""
    values: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        if name not in _HEADERS:
            continue
        if name in values:
            raise ValueError(f"Duplicate {name} header.")
        if name == "authorization":
            raise ValueError(
                "This endpoint uses provider-specific BYOK headers, not Authorization. "
                "Configure X-ModelArk-Api-Key, X-Seed-Speech-Api-Key or X-OmniHuman-Api-Key."
            )
        try:
            value = raw_value.decode("ascii")
        except UnicodeDecodeError:
            raise ValueError(f"Invalid {name} header.") from None
        if not 1 <= len(value) <= 4096 or any(not 33 <= ord(char) <= 126 for char in value):
            raise ValueError(f"Invalid {name} header.")
        if name == INSTALLATION_HEADER_NAME and not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError(
                "X-MCP-Client-Secret must be 32 random bytes encoded as lowercase hex."
            )
        if name in ENDPOINT_HEADERS.values() and not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value):
            raise ValueError(f"Invalid {name} header.")
        values[name] = value
    credentials = _RequestCredentials(values=values, lifetime=_RequestLifetime())
    token = _request.set(credentials)
    try:
        yield
    finally:
        credentials.lifetime.active = False
        credentials.values.clear()
        _request.reset(token)


def _live_request() -> _RequestCredentials:
    request = _request.get()
    if request is None or not request.lifetime.active:
        raise PermissionError("BYOK requires credentials on the current HTTP request.")
    return request


def has_provider_credential(provider: CredentialProvider) -> bool:
    """Inspect presence only; a syntactically valid header is not provider authorization."""
    return PROVIDER_HEADERS[provider] in _live_request().values


def has_client_secret() -> bool:
    """Report client-secret header presence only within a live HTTP request."""
    return INSTALLATION_HEADER_NAME in _live_request().values


def _digest(settings: Settings, domain: str, *parts: str) -> str:
    payload = json.dumps(
        [domain, settings.identity_key_version, *parts], separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hmac.new(
        bytes.fromhex(settings.identity_hmac_key.get_secret_value()), payload, hashlib.sha256
    ).hexdigest()


@contextmanager
def provider_scope(settings: Settings, provider: CredentialProvider) -> Iterator[None]:
    """Scope ephemeral admission to a provider credential and installation secret."""
    if settings.mcp_transport == "stdio":
        yield
        return
    request = _live_request()
    key = request.values.get(PROVIDER_HEADERS[provider])
    secret = request.values.get(INSTALLATION_HEADER_NAME)
    if key is None:
        raise PermissionError(f"Configure {PROVIDER_HEADERS[provider]} in your MCP client headers.")
    if secret is None:
        raise PermissionError("Configure X-MCP-Client-Secret in your MCP client headers.")
    origin = {
        "modelark": settings.modelark_base_url,
        "seed-speech": settings.seed_audio_base_url,
        "vision-cv": settings.cv_base_url,
    }[provider]
    tenant = _digest(settings, "seed-mcp:credential", provider, origin, key)
    owner = _digest(settings, "seed-mcp:owner", tenant, secret)
    context = _ProviderContext(
        provider=provider,
        principal=PrincipalContext(principal_id=owner, tenant_id=tenant, transport="http"),
        request=request,
    )
    token = _provider.set(context)
    try:
        yield
    finally:
        _provider.reset(token)


@contextmanager
def upload_scope(settings: Settings) -> Iterator[None]:
    """Authorize an enrolled live client for operator-funded TOS upload preparation."""
    request = _live_request()
    secret = request.values.get(INSTALLATION_HEADER_NAME)
    if not settings.temporary_upload_enabled or secret is None:
        raise PermissionError(
            "Temporary upload access requires operator enrollment and X-MCP-Client-Secret."
        )
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    enrolled = False
    for candidate in settings.upload_client_digests:
        enrolled |= hmac.compare_digest(digest, candidate)
    if not enrolled:
        raise PermissionError("Temporary upload access requires operator enrollment.")
    tenant = _digest(settings, "seed-mcp:upload-tenant", settings.tos_bucket)
    owner = _digest(settings, "seed-mcp:upload-owner", tenant, secret)
    context = _ProviderContext(
        provider="tos-upload",
        principal=PrincipalContext(principal_id=owner, tenant_id=tenant, transport="http"),
        request=request,
    )
    token = _provider.set(context)
    try:
        yield
    finally:
        _provider.reset(token)


def require_upload_scope() -> PrincipalContext:
    """Reject direct handler calls outside the live, authorized upload invocation."""
    principal = request_principal()
    bound = _provider.get()
    if bound is None or bound.provider != "tos-upload":
        raise PermissionError("Temporary upload requires its live authorized invocation.")
    return principal


def request_principal() -> PrincipalContext:
    """Return only the principal bound to the current live provider invocation."""
    request = _live_request()
    provider = _provider.get()
    if provider is None or provider.request is not request:
        raise PermissionError("Provider scope is unavailable outside a live tool invocation.")
    return provider.principal


def provider_api_key(ctx: Context, provider: CredentialProvider) -> str:
    """Resolve the selected request credential; local development uses explicit settings."""
    settings = ctx.lifespan_context["runtime"].settings
    if settings.mcp_transport == "stdio":
        key = {
            "modelark": settings.modelark_api_key,
            "seed-speech": settings.seed_speech_api_key,
            "vision-cv": settings.cv_api_key,
        }[provider]
        if not key:
            raise PermissionError(f"Configure the {provider} API key for local stdio.")
        return str(key)
    request_principal()
    bound = _provider.get()
    if bound is None or bound.provider != provider:
        raise PermissionError("The tool may only use its selected provider credential.")
    return _live_request().values[PROVIDER_HEADERS[provider]]


def endpoint_default(tool_name: str) -> str | None:
    """Read a syntactically valid endpoint default; the tool validates registry membership."""
    header = ENDPOINT_HEADERS.get(tool_name)
    request = _request.get()
    if header is None or request is None or not request.lifetime.active:
        return None
    return request.values.get(header)


def redact_request_secrets(text: str) -> str:
    """Remove current secrets, including URL-encoded echoes, without retaining fingerprints."""
    request = _request.get()
    if request is None or not request.lifetime.active:
        return text
    secrets = [value for key, value in request.values.items() if key in _SECRET_HEADERS]
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        text = text.replace(quote(secret, safe=""), "[REDACTED]")
    return text
