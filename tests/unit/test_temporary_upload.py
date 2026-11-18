"""Offline configuration, live entitlement and actual SDK signing checks."""

from __future__ import annotations

import base64
import hashlib
import json
from contextvars import copy_context
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from ark_mcp.config.env import Settings, settings_scope
from ark_mcp.providers.tos.client import TosGateway
from ark_mcp.security.credentials import (
    provider_scope,
    request_credentials_scope,
    require_upload_scope,
    upload_scope,
)
from ark_mcp.tools.media_prepare_upload import (
    MediaPrepareUploadInput,
    MediaPrepareUploadOutput,
)
from tests.integration.test_byok_http import CLIENT_SECRET, OTHER_SECRET, http_settings

DIGEST = hashlib.sha256(CLIENT_SECRET.encode("ascii")).hexdigest()


def upload_settings(tmp_path: Path, **overrides: object) -> Settings:
    return http_settings(
        tmp_path,
        **{
            "MCP_TEMPORARY_UPLOAD_ENABLED": True,
            "MCP_UPLOAD_CLIENT_SECRET_SHA256": DIGEST,
            "TOS_ACCESS_KEY": "synthetic-upload-ak",
            "TOS_SECRET_KEY": "synthetic-upload-sk",  # pragma: allowlist secret
            "TOS_BUCKET": "synthetic-upload-bucket",
            **overrides,
        },
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"MCP_TRANSPORT": "stdio"},
        {"MCP_UPLOAD_CLIENT_SECRET_SHA256": ""},
        {"TOS_ACCESS_KEY": "", "TOS_SECRET_KEY": ""},
        {"TOS_BUCKET": ""},
        {"TOS_BUCKET": "bad.bucket"},
        {"TOS_BUCKET": "-invalid"},
        {"TOS_REGION": "bad"},
        {"TOS_ENDPOINT": "http://tos-ap-southeast-1.bytepluses.com"},
        {"TOS_ENDPOINT": "https://tos-ap-southeast-1.bytepluses.com/"},
        {"TOS_ENDPOINT": "tos-ap-southeast-1.bytepluses.com:443"},
        {"TOS_ENDPOINT": "https://attacker.example.com"},
        {"OBJECT_STORAGE_BACKEND": "s3"},
    ],
)
def test_invalid_enabled_configuration_fails_closed(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValidationError):
        upload_settings(tmp_path, **overrides)


@pytest.mark.parametrize(
    "value",
    ["*", "A" * 64, "a" * 63, DIGEST + "," + DIGEST, DIGEST + ",", " " + DIGEST],
)
def test_invalid_enrollment_is_rejected_without_enabling(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValidationError):
        http_settings(tmp_path, MCP_UPLOAD_CLIENT_SECRET_SHA256=value)


def test_allowlist_has_a_bounded_size(tmp_path: Path) -> None:
    values = ",".join(f"{index:064x}" for index in range(1000))
    assert (
        len(upload_settings(tmp_path, MCP_UPLOAD_CLIENT_SECRET_SHA256=values).upload_client_digests)
        == 1000
    )
    with pytest.raises(ValidationError):
        upload_settings(tmp_path, MCP_UPLOAD_CLIENT_SECRET_SHA256=values + "," + f"{1000:064x}")


def test_disabled_default_needs_no_storage(tmp_path: Path) -> None:
    settings = http_settings(tmp_path)
    assert not settings.temporary_upload_enabled
    assert settings.upload_client_digests == ()
    assert "upload_client_secret_sha256=" not in repr(settings)


@pytest.mark.parametrize(
    "endpoint", ["tos-ap-southeast-1.bytepluses.com", "https://tos-ap-southeast-1.bytepluses.com"]
)
def test_official_endpoint_forms_are_accepted(tmp_path: Path, endpoint: str) -> None:
    assert upload_settings(tmp_path, TOS_ENDPOINT=endpoint).temporary_upload_enabled


@pytest.mark.parametrize("secret", [None, OTHER_SECRET])
def test_upload_requires_enrolled_live_secret(tmp_path: Path, secret: str | None) -> None:
    headers = [] if secret is None else [(b"x-mcp-client-secret", secret.encode("ascii"))]
    with (
        request_credentials_scope(headers),
        pytest.raises(PermissionError),
        upload_scope(upload_settings(tmp_path)),
    ):
        pytest.fail("Unregistered client reached upload scope")


def test_copied_upload_context_cannot_outlive_request(tmp_path: Path) -> None:
    with request_credentials_scope([(b"x-mcp-client-secret", CLIENT_SECRET.encode())]):
        with upload_scope(upload_settings(tmp_path)):
            principal = require_upload_scope()
            assert principal.transport == "http"
            assert principal.principal_id != DIGEST
            assert CLIENT_SECRET not in str(principal)
            copied = copy_context()
        with pytest.raises(PermissionError):
            require_upload_scope()
    with pytest.raises(PermissionError):
        copied.run(require_upload_scope)
    with pytest.raises(PermissionError), upload_scope(upload_settings(tmp_path)):
        pytest.fail("Expired request authorized")


def test_provider_scope_is_not_upload_entitlement(tmp_path: Path) -> None:
    settings = upload_settings(tmp_path)
    with (
        request_credentials_scope(
            [
                (b"x-mcp-client-secret", CLIENT_SECRET.encode()),
                (b"x-modelark-api-key", b"synthetic-key"),
            ]
        ),
        provider_scope(settings, "modelark"),
        pytest.raises(PermissionError),
    ):
        require_upload_scope()


@pytest.mark.parametrize(
    "arguments",
    [
        {"media_type": "file"},
        {"mime_type": "text/html"},
        {"mime_type": "IMAGE/PNG"},
        {"mime_type": "image/png;charset=utf-8"},
        {"mime_type": "image/png\r\nX-Test: 1"},
        {"size_bytes": 0},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"size_bytes": 1.0},
        {"size_bytes": "1"},
        {"size_bytes": 10 * 1024 * 1024 + 1},
        {"file_path": "/private/file.png"},
        {"data": "AA=="},
        {"key_prefix": "outside"},
        {"expires_in_seconds": 3600},
        {"TOS_SECRET_KEY": "not-accepted"},  # pragma: allowlist secret
    ],
)
def test_metadata_rejects_untrusted_inputs(arguments: dict) -> None:
    with pytest.raises(ValidationError):
        MediaPrepareUploadInput.model_validate(
            {"media_type": "image", "mime_type": "image/png", "size_bytes": 100, **arguments}
        )


@pytest.mark.parametrize(
    "media_type,mime,size",
    [
        ("image", "image/png", 10 * 1024 * 1024),
        ("audio", "audio/wav", 10 * 1024 * 1024),
        ("video", "video/mp4", 200 * 1024 * 1024),
    ],
)
def test_category_boundary_sizes(media_type: str, mime: str, size: int) -> None:
    assert (
        MediaPrepareUploadInput(media_type=media_type, mime_type=mime, size_bytes=size).size_bytes
        == size
    )
    with pytest.raises(ValidationError):
        MediaPrepareUploadInput(media_type=media_type, mime_type=mime, size_bytes=size + 1)


@pytest.mark.parametrize("sts", ["", "synthetic-sts-token"])
async def test_actual_sdk_signing_is_offline_and_restricted(tmp_path: Path, sts: str) -> None:
    settings = upload_settings(tmp_path, TOS_SECURITY_TOKEN=sts)
    key = "temporary-references/synthetic-owner/video/synthetic-id"
    with settings_scope(settings):
        gateway = TosGateway()
        try:
            url, fields, reference = await gateway.prepare_upload(
                key=key, mime_type="video/mp4", size_bytes=1234
            )
        finally:
            await gateway.close()
    assert url == "https://synthetic-upload-bucket.tos-ap-southeast-1.bytepluses.com/"
    policy = json.loads(base64.b64decode(fields["policy"], validate=True))
    assert ["content-length-range", 1234, 1234] in policy["conditions"]
    for name in (
        "key",
        "Content-Type",
        "x-tos-acl",
        "x-tos-storage-class",
        "x-tos-forbid-overwrite",
        "x-tos-object-expires",
    ):
        assert {name: fields[name]} in policy["conditions"]
    assert {"bucket": settings.tos_bucket} in policy["conditions"]
    assert fields["x-tos-acl"] == "private"
    assert fields["x-tos-forbid-overwrite"] == "true"
    assert fields["x-tos-object-expires"] == "1"
    assert fields["x-tos-storage-class"] == "STANDARD"
    assert fields.get("x-tos-security-token", "") == sts
    if sts:
        assert {"x-tos-security-token": sts} in policy["conditions"]
    query = parse_qs(urlsplit(reference).query)
    assert urlsplit(reference).scheme == "https"
    assert urlsplit(reference).path == "/" + key
    assert query["X-Tos-Expires"] == ["86400"]
    assert settings.tos_secret_key not in json.dumps(fields) + reference
    assert CLIENT_SECRET not in json.dumps(fields) + reference
    assert "file" not in fields


def test_all_tool_fields_are_described() -> None:
    for model in (MediaPrepareUploadInput, MediaPrepareUploadOutput):
        assert all(field.description for field in model.model_fields.values())


def test_schema_mime_enum_matches_runtime_allowlist() -> None:
    from ark_mcp.security.media_policy import get_media_limits

    limits = get_media_limits()
    by_category = {
        "image": limits.ALLOWED_IMAGE_MIMES,
        "audio": limits.ALLOWED_AUDIO_MIMES,
        "video": limits.ALLOWED_VIDEO_MIMES,
    }
    advertised = MediaPrepareUploadInput.model_json_schema()["properties"]["mime_type"]["enum"]
    assert set(advertised) == set().union(*by_category.values())
    for mime in advertised:
        category = mime.split("/", 1)[0]
        assert (
            MediaPrepareUploadInput(media_type=category, mime_type=mime, size_bytes=1).mime_type
            == mime
        )
        with pytest.raises(ValidationError):
            MediaPrepareUploadInput(
                media_type="video" if category != "video" else "image",
                mime_type=mime,
                size_bytes=1,
            )
