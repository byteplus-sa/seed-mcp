"""Configuration-only checks never authorize provider calls or expose request values."""

from __future__ import annotations

import asyncio
import json
from contextvars import copy_context
from typing import TYPE_CHECKING, Any, cast

import pytest

from ark_mcp.config.env import settings_scope
from ark_mcp.config.model_capabilities import get_capability_registry
from ark_mcp.security.credentials import request_credentials_scope
from ark_mcp.tools.ark_list_models import ArkListModelsInput, ark_list_models
from tests.integration.test_byok_http import http_settings

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Context

    from ark_mcp.config.env import Settings

KEY = "synthetic-preflight-provider-canary"
CLIENT_SECRET = "b1" * 32  # pragma: allowlist secret
HEADERS = [(b"x-modelark-api-key", KEY.encode()), (b"x-mcp-client-secret", CLIENT_SECRET.encode())]


async def inspect_connection(
    settings: Settings,
    headers: list[tuple[bytes, bytes]],
    **input_values: Any,
) -> dict[str, Any]:
    with settings_scope(settings), request_credentials_scope(headers):
        await asyncio.sleep(0)
        result = await ark_list_models(
            ArkListModelsInput(check_connection=True, **input_values), cast("Context", object())
        )
        return result.model_dump(mode="json")


async def test_default_discovery_never_needs_or_inspects_live_headers(tmp_path: Path) -> None:
    settings = http_settings(tmp_path)
    with settings_scope(settings):
        result = await ark_list_models(ArkListModelsInput(), cast("Context", object()))
    assert result.model_dump()["connection"] is None
    with settings_scope(settings), request_credentials_scope(HEADERS):
        authenticated = await ark_list_models(ArkListModelsInput(), cast("Context", object()))
    assert authenticated == result


@pytest.mark.parametrize("key_present", [False, True])
@pytest.mark.parametrize("secret_present", [False, True])
async def test_preflight_reports_presence_not_authentication(
    tmp_path: Path, key_present: bool, secret_present: bool
) -> None:
    settings = http_settings(tmp_path, BYTEPLUS_MODELARK_API_KEY="startup-must-not-count")
    headers = ([HEADERS[0]] if key_present else []) + ([HEADERS[1]] if secret_present else [])
    result = await inspect_connection(settings, headers)
    check = result["connection"]
    assert check["configuration_valid"] is key_present
    assert check["modelark_key_present"] is key_present
    assert check["client_secret_present"] is secret_present
    assert check["authentication_verified"] is False
    assert check["provider_calls_made"] is False
    assert check["issues"] == ([] if key_present else ["missing_modelark_key"])
    assert len(check["routes"]) == 2
    assert all(route["configured"] for route in check["routes"])
    text = json.dumps(result)
    assert KEY not in text and CLIENT_SECRET not in text and "startup-must-not-count" not in text
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    ("kind", "tool", "header"),
    [
        ("image", "seedream_generate_image", b"x-modelark-seedream-endpoint"),
        ("video", "seedance_create_task", b"x-modelark-seedance-endpoint"),
    ],
)
async def test_unregistered_endpoint_is_not_echoed_or_given_capabilities(
    tmp_path: Path, kind: str, tool: str, header: bytes
) -> None:
    unknown = b"ep-private-unverified-customer-id"
    result = await inspect_connection(
        http_settings(tmp_path), [*HEADERS, (header, unknown)], kind=kind
    )
    check = result["connection"]
    assert check["configuration_valid"] is False
    assert check["issues"] == []
    assert check["routes"] == [
        {
            "tool": tool,
            "source": "request_header",
            "configured": False,
            "model_id": None,
            "family": None,
            "issue": "endpoint_not_configured",
        }
    ]
    assert unknown.decode() not in json.dumps(result)
    assert {model["kind"] for model in result["models"]} == {kind}


async def test_custom_bindings_and_wrong_product_are_distinguished(tmp_path: Path) -> None:
    settings = http_settings(
        tmp_path,
        SEEDANCE_DEFAULT_MODEL="ep-video",
        SEEDANCE_MODEL_BINDINGS=[{"model_id": "ep-video", "family": "seedance_2_5"}],
        SEEDREAM_DEFAULT_MODEL="ep-image",
        SEEDREAM_MODEL_BINDINGS=[{"model_id": "ep-image", "family": "seedream_5_5"}],
    )
    default = (await inspect_connection(settings, HEADERS))["connection"]
    assert default["configuration_valid"] is True
    assert {route["model_id"] for route in default["routes"]} == {"ep-image", "ep-video"}
    assert all(route["source"] == "server_default" for route in default["routes"])
    wrong = await inspect_connection(
        settings, [*HEADERS, (b"x-modelark-seedance-endpoint", b"ep-image")], kind="video"
    )
    assert wrong["connection"]["routes"][0]["issue"] == "endpoint_not_configured"


async def test_concurrent_headers_and_settings_do_not_leak(tmp_path: Path) -> None:
    settings = http_settings(tmp_path)
    valid, unknown, missing = await asyncio.gather(
        inspect_connection(settings, HEADERS, kind="image"),
        inspect_connection(
            settings, [*HEADERS, (b"x-modelark-seedream-endpoint", b"ep-unknown")], kind="image"
        ),
        inspect_connection(settings, [], kind="image"),
    )
    assert valid["connection"]["configuration_valid"] is True
    assert unknown["connection"]["routes"][0]["configured"] is False
    assert missing["connection"]["modelark_key_present"] is False


async def test_preflight_requires_live_http_and_rejects_unsupported_kind(tmp_path: Path) -> None:
    settings = http_settings(tmp_path)
    with pytest.raises(ValueError, match=r"image|video"):
        await inspect_connection(settings, HEADERS, kind="understanding")
    with settings_scope(settings), pytest.raises(PermissionError, match="current HTTP request"):
        await ark_list_models(ArkListModelsInput(check_connection=True), cast("Context", object()))
    with pytest.raises(ValueError, match="HTTP"):
        await inspect_connection(settings.model_copy(update={"mcp_transport": "stdio"}), HEADERS)


async def test_expired_header_context_cannot_pass_configuration_check(tmp_path: Path) -> None:
    with settings_scope(http_settings(tmp_path)), request_credentials_scope(HEADERS):
        copied = copy_context()

    async def inspect() -> None:
        await ark_list_models(ArkListModelsInput(check_connection=True), cast("Context", object()))

    with pytest.raises(PermissionError, match="current HTTP request"):
        await asyncio.create_task(inspect(), context=copied)


@pytest.mark.parametrize("kind", ["image", "video"])
def test_unknown_endpoint_errors_explain_binding_without_echoing_input(
    tmp_path: Path, kind: str
) -> None:
    unknown = "ep-private-unknown-value"
    with settings_scope(http_settings(tmp_path)):
        registry = get_capability_registry()
        resolve = registry.resolve_image_model if kind == "image" else registry.resolve_video_model
        with pytest.raises(ValueError, match="ENDPOINT_NOT_CONFIGURED") as error:
            resolve(unknown)
    assert unknown not in str(error.value)
    assert "operator" in str(error.value)
    assert "GetEndpoint" in str(error.value)
