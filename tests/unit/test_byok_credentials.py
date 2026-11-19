"""Request-only credentials and credential-scoped installation identity."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from fastmcp import Context

from ark_mcp.config.env import Settings
from ark_mcp.security.credentials import (
    PROVIDER_HEADERS,
    has_client_secret,
    provider_api_key,
    provider_scope,
    request_credentials_scope,
    request_principal,
)


def http_settings() -> Settings:
    return Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_AUTH_MODE="byok",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        BYTEPLUS_MODELARK_API_KEY="operator-key-must-not-be-used",  # pragma: allowlist secret
    )


def test_default_state_directory_does_not_share_ark_mcp_state() -> None:
    assert Settings(_env_file=None).artifact_dir == "~/.seed-mcp/artifacts"


def headers(key: str = "customer-a", secret: str = "b" * 64) -> list[tuple[bytes, bytes]]:
    return [
        (b"x-modelark-api-key", key.encode()),
        (b"x-mcp-client-secret", secret.encode()),
    ]


def context(settings: Settings) -> Context:
    return cast(
        "Context",
        SimpleNamespace(lifespan_context={"runtime": SimpleNamespace(settings=settings)}),
    )


def identity(settings: Settings, supplied: list[tuple[bytes, bytes]]) -> tuple[str, str]:
    with request_credentials_scope(supplied), provider_scope(settings, "modelark"):
        principal = request_principal()
        return principal.tenant_id, principal.principal_id


def test_identity_separates_credentials_and_shared_key_installations() -> None:
    settings = http_settings()
    first = identity(settings, headers())
    other_key = identity(settings, headers(key="customer-b"))
    other_client = identity(settings, headers(secret="c" * 64))
    assert first[0] != other_key[0]
    assert first[0] == other_client[0]
    assert first[1] != other_client[1]
    assert first == identity(http_settings(), headers())


def test_unrelated_provider_key_does_not_change_identity() -> None:
    settings = http_settings()
    assert identity(settings, headers()) == identity(
        settings, [*headers(), (b"x-seed-speech-api-key", b"speech-key")]
    )


@pytest.mark.parametrize(
    "extra",
    [
        [(b"X-ModelArk-Api-Key", b"duplicate")],
        [(b"authorization", b"Bearer not-an-mcp-token")],
        [(b"x-seed-speech-api-key", b"")],
        [(b"x-seed-speech-api-key", b"space key")],
        [(b"x-seed-speech-api-key", b"bad\nheader")],
        [(b"x-seed-speech-api-key", b"\xff")],
        [(b"x-seed-speech-api-key", b"x" * 4097)],
    ],
)
def test_invalid_headers_are_rejected_without_echo(extra: list[tuple[bytes, bytes]]) -> None:
    with pytest.raises(ValueError) as caught, request_credentials_scope(headers() + extra):
        pytest.fail("Malformed header accepted")
    assert "customer-a" not in str(caught.value)
    assert "not-an-mcp-token" not in str(caught.value)


@pytest.mark.parametrize("header", PROVIDER_HEADERS.values())
@pytest.mark.parametrize("secret_first", [False, True])
def test_reused_client_secret_is_rejected_before_binding(header: str, secret_first: bool) -> None:
    reused = "ab" * 32
    supplied = [
        (header.upper().encode(), reused.encode()),
        (b"X-MCP-Client-Secret", reused.encode()),
    ]
    if secret_first:
        supplied.reverse()
    with (
        pytest.raises(ValueError, match=r"^CREDENTIAL_REUSE:") as caught,
        request_credentials_scope(supplied),
    ):
        pytest.fail("Reused client secret accepted")
    message = str(caught.value)
    assert reused not in message
    assert "32 random bytes" in message
    assert "64 lowercase hex" in message
    assert "private client header configuration" in message
    assert "Keep your provider API keys unchanged" in message
    with pytest.raises(PermissionError):
        has_client_secret()
    with request_credentials_scope(headers()), provider_scope(http_settings(), "modelark"):
        assert provider_api_key(context(http_settings()), "modelark") == "customer-a"


def test_reuse_check_includes_unselected_provider_keys() -> None:
    supplied = [*headers(), (b"x-seed-speech-api-key", b"b" * 64)]
    with (
        pytest.raises(ValueError, match=r"^CREDENTIAL_REUSE:"),
        request_credentials_scope(supplied),
    ):
        pytest.fail("Unselected provider key reused as client secret")


def test_reuse_check_does_not_reject_provider_key_equality_without_client_secret() -> None:
    with request_credentials_scope(
        [(header.encode(), b"ab" * 32) for header in PROVIDER_HEADERS.values()]
    ):
        assert has_client_secret() is False


def test_independent_secret_allows_equal_provider_keys() -> None:
    supplied = [(header.encode(), b"ab" * 32) for header in PROVIDER_HEADERS.values()] + [
        (b"x-mcp-client-secret", b"cd" * 32)
    ]
    settings = http_settings()
    with request_credentials_scope(supplied):
        for provider in PROVIDER_HEADERS:
            with provider_scope(settings, provider):
                assert provider_api_key(context(settings), provider) == "ab" * 32


def test_provider_scope_requires_client_secret_and_matching_provider_key() -> None:
    settings = http_settings()
    with (
        request_credentials_scope([(b"x-modelark-api-key", b"customer-a")]),
        pytest.raises(PermissionError),
        provider_scope(settings, "modelark"),
    ):
        pytest.fail("Missing client secret accepted")
    with (
        request_credentials_scope(headers()),
        pytest.raises(PermissionError),
        provider_scope(settings, "seed-speech"),
    ):
        pytest.fail("A ModelArk key authorized Seed Speech")


def test_http_never_falls_back_to_operator_key() -> None:
    with pytest.raises(PermissionError):
        provider_api_key(context(http_settings()), "modelark")


async def test_simultaneous_requests_keep_keys_and_principals_separate() -> None:
    settings = http_settings()
    ready = asyncio.Event()
    entered = 0

    async def invoke(key: str) -> tuple[str, str]:
        nonlocal entered
        with request_credentials_scope(headers(key=key)), provider_scope(settings, "modelark"):
            entered += 1
            if entered == 2:
                ready.set()
            await ready.wait()
            return (
                provider_api_key(context(settings), "modelark"),
                request_principal().tenant_id,
            )

    results = await asyncio.gather(invoke("customer-a"), invoke("customer-b"))
    assert results[0][0] == "customer-a"
    assert results[1][0] == "customer-b"
    assert results[0][1] != results[1][1]
    with pytest.raises(PermissionError):
        request_principal()


async def test_copied_task_context_cannot_use_credentials_after_request_ends() -> None:
    settings = http_settings()
    resume = asyncio.Event()

    async def delayed() -> None:
        await resume.wait()
        with pytest.raises(PermissionError):
            provider_api_key(context(settings), "modelark")

    with request_credentials_scope(headers()), provider_scope(settings, "modelark"):
        task = asyncio.create_task(delayed())
    resume.set()
    await task
