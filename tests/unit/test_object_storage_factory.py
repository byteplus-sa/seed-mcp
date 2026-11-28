"""Unit tests for the object-storage gateway factory."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.providers.object_storage import make_object_storage_gateway
from ark_mcp.providers.s3.client import S3Gateway


def _s3_settings() -> Settings:
    return Settings(
        _env_file=None,
        S3_ACCESS_KEY="ak-s3",
        S3_SECRET_KEY="sk-s3",  # pragma: allowlist secret
        S3_BUCKET="s3-bucket",
        OBJECT_STORAGE_BACKEND="s3",
    )


class TestMakeObjectStorageGateway:
    def test_s3_backend_returns_s3_gateway(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = Mock()
        monkeypatch.setattr("ark_mcp.providers.s3.client.boto3.client", client)
        gateway = make_object_storage_gateway(_s3_settings())
        assert isinstance(gateway, S3Gateway)
        client.assert_called_once()

    def test_s3_backend_without_credentials_raises(self) -> None:
        settings = _s3_settings().model_copy(
            update={"s3_access_key": "", "s3_secret_key": "", "s3_bucket": ""}
        )
        with pytest.raises(ValueError, match="S3 credentials are not configured"):
            make_object_storage_gateway(settings)
