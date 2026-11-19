"""Mock-only OIDC exchange, rotation, fail-closed configuration and SDK signing."""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError
from tos.credential import Credentials

from ark_mcp.config.env import Settings, settings_scope
from ark_mcp.providers.tos.client import TosGateway
from ark_mcp.providers.tos.credentials import IrsaCredentialError, IrsaCredentialsProvider
from tests.unit.test_temporary_upload import upload_settings

TOKEN = "synthetic.projected.token"
AK = "synthetic-irsa-ak"
SK = "synthetic-irsa-sk"  # pragma: allowlist secret
STS_TOKEN = "synthetic-irsa-session-token"


def irsa_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return upload_settings(
        tmp_path,
        **{
            "TOS_CREDENTIAL_MODE": "irsa",
            "TOS_ACCESS_KEY": "",
            "TOS_SECRET_KEY": "",
            "TOS_SECURITY_TOKEN": "",
            "TOS_IRSA_ROLE_TRN": "trn:iam::3000000000:role/synthetic-signing",
            "TOS_IRSA_TOKEN_FILE": str(tmp_path / "projected-token"),
            **overrides,
        },
    )


def response_body(expires: float, **overrides: Any) -> dict:
    return {
        "ResponseMetadata": {"RequestId": "synthetic-request"},
        "Result": {
            "Credentials": {
                "AccessKeyId": AK,
                "SecretAccessKey": SK,
                "SessionToken": STS_TOKEN,
                "ExpiredTime": datetime.fromtimestamp(expires, UTC).isoformat(),
                **overrides,
            }
        },
    }


def mock_exchange(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original = httpx.Client

    def factory(**kwargs: Any) -> httpx.Client:
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"].connect == 5
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("ark_mcp.providers.tos.credentials.httpx.Client", factory)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1800000000.0]
    monkeypatch.setattr(
        "ark_mcp.providers.tos.credentials.time",
        SimpleNamespace(time=lambda: now[0], monotonic=lambda: now[0]),
    )
    return now


@pytest.mark.parametrize(
    "overrides",
    [
        {"TOS_CREDENTIAL_MODE": "ambient"},
        {"TOS_CREDENTIAL_MODE": "static"},
        {"MCP_TRANSPORT": "stdio"},
        {"MCP_TEMPORARY_UPLOAD_ENABLED": False},
        {"TOS_ACCESS_KEY": "synthetic", "TOS_SECRET_KEY": "synthetic"},  # pragma: allowlist secret
        {"TOS_SECURITY_TOKEN": "synthetic"},
        {"TOS_IRSA_ROLE_TRN": ""},
        {"TOS_IRSA_ROLE_TRN": "trn:iam::*:role/*"},
        {"TOS_IRSA_ROLE_TRN": "role/name"},
        {"TOS_IRSA_TOKEN_FILE": ""},
        {"TOS_IRSA_TOKEN_FILE": "relative/token"},
        {"TOS_IRSA_TOKEN_FILE": "/tmp/../token"},
        {"TOS_IRSA_STS_ENDPOINT": "http://sts.byteplusapi.com"},
        {"TOS_IRSA_STS_ENDPOINT": "https://sts.volcengineapi.com"},
        {"TOS_IRSA_STS_ENDPOINT": "https://attacker.invalid"},
        {"TOS_IRSA_STS_ENDPOINT": "https://sts.byteplusapi.com/"},
        {"TOS_IRSA_DURATION_SECONDS": 3599},
        {"TOS_IRSA_DURATION_SECONDS": 43201},
    ],
)
def test_configuration_rejects_ambiguous_or_unsafe_modes(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValidationError):
        irsa_settings(tmp_path, **overrides)


@pytest.mark.parametrize(
    "endpoint", ["https://sts.byteplusapi.com", "https://open.byteplusapi.com"]
)
def test_irsa_has_storage_without_static_keys_or_startup_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    client = MagicMock(side_effect=AssertionError("No startup exchange"))
    monkeypatch.setattr("ark_mcp.providers.tos.credentials.httpx.Client", client)
    settings = irsa_settings(tmp_path, TOS_IRSA_STS_ENDPOINT=endpoint)
    provider = IrsaCredentialsProvider(settings)
    assert settings.has_tos and settings.has_object_storage
    assert not settings.tos_access_key and not settings.tos_secret_key
    assert TOKEN not in repr(provider)
    provider.close()
    client.assert_not_called()


def test_rotation_rereads_token_and_reuses_one_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    token_file = tmp_path / "projected-token"
    token_file.write_text(TOKEN)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "sts.byteplusapi.com"
        assert dict(request.url.params) == {"Action": "AssumeRoleWithOIDC", "Version": "2018-01-01"}
        assert "authorization" not in request.headers
        return httpx.Response(200, json=response_body(clock[0] + 3600))

    mock_exchange(monkeypatch, handler)
    provider = IrsaCredentialsProvider(irsa_settings(tmp_path))
    first = provider.get_credentials()
    assert provider.get_credentials() is first
    token_file.write_text("rotated.projected.token")
    clock[0] += 3301
    provider.get_credentials()
    assert len(requests) == 2
    forms = [parse_qs(request.content.decode()) for request in requests]
    assert forms[0]["OIDCToken"] == [TOKEN]
    assert forms[1]["OIDCToken"] == ["rotated.projected.token"]
    assert forms[0]["RoleSessionName"] == forms[1]["RoleSessionName"]
    assert forms[0]["DurationSeconds"] == ["3600"]
    assert forms[0]["RoleTrn"] == [irsa_settings(tmp_path).tos_irsa_role_trn]
    assert provider._snapshot is not None
    assert SK not in repr(provider._snapshot)
    provider.close()
    assert provider._snapshot is None
    with pytest.raises(IrsaCredentialError, match="closed"):
        provider.get_credentials()


def test_refresh_failure_backoff_never_serves_expired_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=response_body(clock[0] + 3600))
        return httpx.Response(403, json={"token": TOKEN, "secret": SK})

    mock_exchange(monkeypatch, handler)
    provider = IrsaCredentialsProvider(irsa_settings(tmp_path))
    initial = provider.get_credentials()
    clock[0] += 3301
    assert provider.get_credentials() is initial
    assert provider.get_credentials() is initial
    assert len(requests) == 2
    clock[0] += 240
    with pytest.raises(IrsaCredentialError) as exc:
        provider.get_credentials()
    assert TOKEN not in str(exc.value) and SK not in str(exc.value)
    assert len(requests) == 3
    with pytest.raises(IrsaCredentialError):
        provider.get_credentials()
    assert len(requests) == 3


def test_concurrent_requests_single_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=response_body(clock[0] + 3600))

    mock_exchange(monkeypatch, handler)
    provider = IrsaCredentialsProvider(irsa_settings(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: provider.get_credentials(), range(16)))
    assert len(calls) == 1
    assert all(result is results[0] for result in results)


@pytest.mark.parametrize(
    "kind",
    [
        "redirect",
        "denied",
        "error",
        "malformed",
        "large",
        "missing",
        "expired",
        "naive",
        "transport",
    ],
)
def test_exchange_errors_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[float], kind: str
) -> None:
    (tmp_path / "projected-token").write_text(TOKEN)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if kind == "transport":
            raise httpx.ReadTimeout(TOKEN + SK)
        if kind == "redirect":
            return httpx.Response(307, headers={"Location": "https://attacker.invalid"})
        if kind == "denied":
            return httpx.Response(403, text=TOKEN + SK)
        if kind == "error":
            return httpx.Response(
                200, json={"ResponseMetadata": {"Error": {"Message": TOKEN + SK}}}
            )
        if kind == "malformed":
            return httpx.Response(200, text=TOKEN + SK)
        if kind == "large":
            return httpx.Response(200, content=b" " * 65537)
        changes = {
            "missing": {"SessionToken": ""},
            "expired": {"ExpiredTime": datetime.fromtimestamp(clock[0] + 59, UTC).isoformat()},
            "naive": {"ExpiredTime": "2030-01-01T00:00:00"},
        }
        return httpx.Response(200, json=response_body(clock[0] + 3600, **changes[kind]))

    mock_exchange(monkeypatch, handler)
    with pytest.raises(IrsaCredentialError) as exc:
        IrsaCredentialsProvider(irsa_settings(tmp_path)).get_credentials()
    assert TOKEN not in str(exc.value) and SK not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize("token", [None, "", " " * 10, "x" * 65537, "abc def"])
def test_missing_or_invalid_projected_tokens_never_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    if token is not None:
        (tmp_path / "projected-token").write_text(token)
    client = MagicMock(side_effect=AssertionError("No invalid-token exchange"))
    monkeypatch.setattr("ark_mcp.providers.tos.credentials.httpx.Client", client)
    with pytest.raises(IrsaCredentialError):
        IrsaCredentialsProvider(irsa_settings(tmp_path)).get_credentials()
    client.assert_not_called()


async def test_post_get_and_form_token_use_one_credential_snapshot(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.get_credentials.side_effect = [
        Credentials(AK, SK, STS_TOKEN),
        AssertionError("No second credential fetch within a signing pair"),
    ]
    with settings_scope(irsa_settings(tmp_path)):
        gateway = TosGateway(credentials_provider=provider)
        try:
            _, fields, reference = await gateway.prepare_upload(
                key="temporary-references/synthetic/image/exact",
                mime_type="image/png",
                size_bytes=1234,
            )
        finally:
            await gateway.close()
    provider.get_credentials.assert_called_once()
    assert fields["x-tos-security-token"] == STS_TOKEN
    policy = json.loads(base64.b64decode(fields["policy"]))
    assert {"x-tos-security-token": STS_TOKEN} in policy["conditions"]
    query = parse_qs(urlsplit(reference).query)
    assert query["X-Tos-Security-Token"] == [STS_TOKEN]
    assert query["X-Tos-Credential"][0].startswith(AK + "/")
    assert query["X-Tos-Expires"] == ["86400"]
    assert SK not in json.dumps(fields) + reference


def test_gateway_cannot_silently_use_no_credentials(tmp_path: Path) -> None:
    with settings_scope(irsa_settings(tmp_path)), pytest.raises(ValueError, match="lifespan"):
        TosGateway()
