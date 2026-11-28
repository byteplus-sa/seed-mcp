"""Shared fixtures for contract tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ark_mcp.config.env import get_settings


@pytest.fixture
def all_services_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "BYTEPLUS_MODELARK_API_KEY": "sk-test",  # pragma: allowlist secret
        "BYTEPLUS_SEED_SPEECH_API_KEY": "sk-test",  # pragma: allowlist secret
        "S3_ACCESS_KEY": "ak-test-s3",  # pragma: allowlist secret
        "S3_SECRET_KEY": "sk-test-s3",  # pragma: allowlist secret
        "S3_BUCKET": "test-bucket",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
