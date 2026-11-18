"""Stateless HTTP lifecycle; local stdio persistence remains independent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ark_mcp.config.env import Settings
from ark_mcp.runtime import close_runtime_services, create_runtime_services
from ark_mcp.state.disabled import DisabledArtifactStore
from ark_mcp.state.stateless import ProviderAuthorizedTasks


def http_settings(path: Path, **values: object) -> Settings:
    return Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        MCP_IDENTITY_HMAC_KEY="a" * 64,
        ARTIFACT_DIR=str(path),
        **values,
    )


async def test_http_never_opens_database_or_creates_artifact_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("HTTP must not open SQLite or any state stores")

    monkeypatch.setattr("ark_mcp.runtime.sqlite3.connect", forbidden)
    monkeypatch.setattr("ark_mcp.runtime.build_state_stores", forbidden)
    path = tmp_path / "unused"
    first, second = await asyncio.gather(
        create_runtime_services(http_settings(path)), create_runtime_services(http_settings(path))
    )
    try:
        for runtime in (first, second):
            assert runtime.settings.state_backend == "none"
            assert runtime.budget_ledger is None
            assert isinstance(runtime.ownership_store, ProviderAuthorizedTasks)
            assert isinstance(runtime.artifact_store, DisabledArtifactStore)
        assert not path.exists()
    finally:
        await asyncio.gather(close_runtime_services(first), close_runtime_services(second))


async def test_http_close_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = await create_runtime_services(http_settings(tmp_path))
    close = AsyncMock(wraps=runtime.safe_downloader.close)
    monkeypatch.setattr(runtime.safe_downloader, "close", close)
    await asyncio.gather(close_runtime_services(runtime), close_runtime_services(runtime))
    close.assert_awaited_once()


async def test_stdio_retains_local_artifact_and_budget_state(tmp_path: Path) -> None:
    runtime = await create_runtime_services(Settings(_env_file=None, ARTIFACT_DIR=str(tmp_path)))
    try:
        assert runtime.settings.state_backend == "sqlite"
        assert runtime.budget_ledger is not None
        assert (tmp_path / "runtime.sqlite3").is_file()
        assert runtime.metrics_listener is None
    finally:
        await close_runtime_services(runtime)


@pytest.mark.parametrize(
    "values",
    [
        {"STATE_BACKEND": "sqlite"},
        {"STATE_BACKEND": "postgres"},
        {"DAILY_BUDGET_USD": 25},
    ],
)
def test_http_rejects_obsolete_persistent_configuration(tmp_path: Path, values: dict) -> None:
    with pytest.raises(ValueError):
        http_settings(tmp_path, **values)
