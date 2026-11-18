"""Forward-only hosted and isolated SQLite configuration checks."""

import os
from pathlib import Path

import pytest

from ark_mcp.config.env import Settings

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {"MCP_IDENTITY_HMAC_KEY": "a" * 64, "MCP_IDENTITY_KEY_VERSION": "1"}
LIMITS = {
    "RATE_LIMIT_RPM": "60",
    "MCP_HTTP_MAX_IN_FLIGHT": "64",
    "MCP_HTTP_MAX_BODY_BYTES": "2097152",
    "STATE_MAX_RECORDS": "100000",
}
DATABASE = {
    "STATE_BACKEND": "none",
    "POSTGRES_DSN": (
        "host=database.example.invalid dbname=synthetic user=synthetic sslmode=verify-full"
    ),
    "POSTGRES_SSL_ROOT_CERT": "/etc/seed-mcp/postgres/ca.crt",
}


@pytest.fixture(autouse=True)
def isolate_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("POSTGRES_"):
            monkeypatch.delenv(name, raising=False)


def test_hosted_postgres_requires_operator_identity_and_database_not_provider_keys() -> None:
    settings = Settings(_env_file=None, MCP_TRANSPORT="http", **IDENTITY, **DATABASE)
    assert settings.mcp_auth_mode == "byok"
    assert not settings.modelark_api_key
    assert not settings.seed_speech_api_key
    assert not settings.cv_api_key
    assert settings.state_backend == "none"


def test_isolated_single_instance_http_retains_sqlite_default() -> None:
    settings = Settings(_env_file=None, MCP_TRANSPORT="http", **IDENTITY)
    assert settings.state_backend == "none"


@pytest.mark.parametrize(("tool", "provider"), [(600, 600), (900, 30), (1, 3600)])
def test_postgres_does_not_change_http_shutdown_sizing(tool: int, provider: int) -> None:
    from ark_mcp.__main__ import graceful_shutdown_timeout_seconds

    settings = Settings(
        _env_file=None,
        MCP_TRANSPORT="http",
        **IDENTITY,
        **DATABASE,
        MCP_TOOL_TIMEOUT_SECONDS=tool,
        BYTEPLUS_REQUEST_TIMEOUT_MS=provider * 1000,
    )
    assert graceful_shutdown_timeout_seconds(settings) == max(tool, provider) + 30


@pytest.mark.parametrize("key", [*LIMITS, "MCP_IDENTITY_KEY_VERSION"])
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nan", "inf", ""])
def test_hosted_limits_fail_closed(key: str, value: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, MCP_TRANSPORT="http", **{**IDENTITY, key: value})


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, " a" * 32])
def test_hosted_hmac_requires_lowercase_32_byte_hex(value: str) -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            MCP_TRANSPORT="http",
            **{**IDENTITY, "MCP_IDENTITY_HMAC_KEY": value},
        )


@pytest.mark.parametrize(
    ("key", "default", "maximum"),
    [
        ("MCP_ADMISSION_TIMEOUT_SECONDS", "2.0", 30),
        ("MCP_TOOL_TIMEOUT_SECONDS", "600.0", 3600),
    ],
)
def test_hosted_direct_deadlines_are_configurable_and_bounded(
    key: str, default: str, maximum: int
) -> None:
    for value in ("0.01", default, str(maximum)):
        Settings(_env_file=None, MCP_TRANSPORT="http", **{**IDENTITY, key: value})
    for value in ("", "0", "-1", str(maximum + 0.01), "nan", "inf", "-inf", "invalid"):
        with pytest.raises(ValueError):
            Settings(_env_file=None, MCP_TRANSPORT="http", **{**IDENTITY, key: value})


def test_docker_has_byok_and_bounded_defaults() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    for key, value in {"MCP_AUTH_MODE": "byok", "MCP_IDENTITY_KEY_VERSION": "1", **LIMITS}.items():
        assert f"{key}={value}" in dockerfile
    assert "MCP_IDENTITY_HMAC_KEY=" not in dockerfile


def test_runtime_image_includes_only_the_private_state_inspector() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert (
        "COPY --chown=modelark:modelark scripts/inspect_runtime_state.py "
        "/app/scripts/inspect_runtime_state.py"
    ) in dockerfile
    assert "COPY scripts/ scripts/" not in dockerfile
