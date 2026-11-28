"""Unit tests for validate() and get_settings() in environment configuration."""

from __future__ import annotations

from ipaddress import ip_network
from pathlib import Path

import pytest
from pydantic import ValidationError

from ark_mcp.config.env import Settings, get_settings, resolve_env_file, validate


class TestHostedProxySettings:
    def test_defaults_and_retired_switch_are_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_TRUST_PROXY_HEADERS", "true")
        settings = Settings(_env_file=None)
        assert settings.rate_limit_trusted_proxy_cidrs == ""
        assert settings.trusted_proxy_networks == ()
        assert "rate_limit_trust_proxy_headers" not in Settings.model_fields

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("", ()),
            ("  ", ()),
            ("127.0.0.1/32", ("127.0.0.1/32",)),
            (" 10.0.0.0/8 , 2001:DB8::/32 ", ("10.0.0.0/8", "2001:db8::/32")),
            ("::ffff:127.0.0.1/128", ("127.0.0.1/32",)),
            ("::ffff:10.0.0.0/104", ("10.0.0.0/8",)),
        ],
    )
    def test_environment_networks_are_validated_and_canonicalized(
        self, monkeypatch: pytest.MonkeyPatch, value: str, expected: tuple[str, ...]
    ) -> None:
        monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_CIDRS", value)
        settings = Settings(_env_file=None)
        assert settings.trusted_proxy_networks == tuple(map(ip_network, expected))
        assert settings.model_dump(mode="json")["rate_limit_trusted_proxy_cidrs"] == ",".join(
            expected
        )

    @pytest.mark.parametrize(
        "value",
        [
            "*",
            "0.0.0.0/0",
            "::/0",
            "::ffff:0.0.0.0/96",
            "0.0.0.0/1,128.0.0.0/1",
            "::/1,8000::/1",
            "127.0.0.1",
            "localhost/32",
            "10.0.0.1/8",
            "127.0.0.1/33",
            "fe80::%lo0/64",
            "127.0.0.1/32,",
            ",127.0.0.1/32",
            "127.0.0.1/32,,::1/128",
            "127.0.0.1/255.255.255.255",
            "127.0.0.1/32\ninvalid",
        ],
    )
    def test_invalid_and_catchall_networks_fail_startup(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_CIDRS", value)
        with pytest.raises(ValidationError, match="RATE_LIMIT_TRUSTED_PROXY_CIDRS"):
            Settings(_env_file=None)

    def test_null_network_configuration_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="RATE_LIMIT_TRUSTED_PROXY_CIDRS"):
            Settings(_env_file=None, RATE_LIMIT_TRUSTED_PROXY_CIDRS=None)

    def test_metrics_are_disabled_by_default(self) -> None:
        assert Settings(_env_file=None).metrics_port == 0

    @pytest.mark.parametrize("transport", ["stdio", "http"])
    @pytest.mark.parametrize("port", [0, 1024, 9100, 65535])
    def test_metrics_port_is_available_to_runtime(
        self, monkeypatch: pytest.MonkeyPatch, transport: str, port: int
    ) -> None:
        monkeypatch.setenv("MCP_METRICS_PORT", str(port))
        monkeypatch.setenv("MCP_TRANSPORT", transport)
        monkeypatch.setenv("MCP_IDENTITY_HMAC_KEY", "a" * 64)
        assert Settings(_env_file=None).metrics_port == port

    @pytest.mark.parametrize("value", ["-1", "1", "1023", "65536", "1.5", "invalid", "null"])
    def test_invalid_metrics_ports_fail_startup(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("MCP_METRICS_PORT", value)
        with pytest.raises(ValidationError, match="MCP_METRICS_PORT"):
            Settings(_env_file=None)


class TestDirectExecutionSettings:
    @pytest.mark.parametrize(
        ("field", "variable", "default", "maximum"),
        [
            ("admission_timeout_seconds", "MCP_ADMISSION_TIMEOUT_SECONDS", 2.0, 30.0),
            ("tool_timeout_seconds", "MCP_TOOL_TIMEOUT_SECONDS", 600.0, 3600.0),
        ],
    )
    def test_defaults_and_finite_positive_bounds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        variable: str,
        default: float,
        maximum: float,
    ) -> None:
        assert getattr(Settings(_env_file=None), field) == default
        for value in (0.001, default, maximum):
            monkeypatch.setenv(variable, str(value))
            assert getattr(Settings(_env_file=None), field) == value

    @pytest.mark.parametrize(
        "variable", ["MCP_ADMISSION_TIMEOUT_SECONDS", "MCP_TOOL_TIMEOUT_SECONDS"]
    )
    @pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "1e309", "invalid"])
    def test_invalid_environment_values_are_rejected(
        self, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
    ) -> None:
        monkeypatch.setenv(variable, value)
        with pytest.raises(ValidationError, match=variable):
            Settings(_env_file=None)

    @pytest.mark.parametrize(
        ("variable", "maximum"),
        [
            ("MCP_ADMISSION_TIMEOUT_SECONDS", 30.0),
            ("MCP_TOOL_TIMEOUT_SECONDS", 3600.0),
        ],
    )
    def test_values_above_maximum_are_rejected(
        self, monkeypatch: pytest.MonkeyPatch, variable: str, maximum: float
    ) -> None:
        monkeypatch.setenv(variable, str(maximum + 0.001))
        with pytest.raises(ValidationError, match=variable):
            Settings(_env_file=None)

    @pytest.mark.parametrize(
        "variable", ["MCP_ADMISSION_TIMEOUT_SECONDS", "MCP_TOOL_TIMEOUT_SECONDS"]
    )
    def test_null_configuration_is_rejected(self, variable: str) -> None:
        with pytest.raises(ValidationError, match=variable):
            Settings(_env_file=None, **{variable: None})

    def test_understanding_settings_are_absent(self) -> None:
        settings = Settings(_env_file=None)
        for field in (
            "seed_understanding_default_model",
            "seed_understanding_model_family",
            "seed_understanding_model_bindings",
            "seed_audio_understanding_model",
            "seed_understanding_timeout_ms",
            "has_understanding",
        ):
            assert not hasattr(settings, field)
            assert field not in Settings.model_fields

    @pytest.mark.parametrize(
        "variable",
        [
            "SEED_UNDERSTANDING_DEFAULT_MODEL",
            "SEED_UNDERSTANDING_MODEL_FAMILY",
            "SEED_UNDERSTANDING_MODEL_BINDINGS",
            "SEED_AUDIO_UNDERSTANDING_MODEL",
            "SEED_UNDERSTANDING_TIMEOUT_MS",
        ],
    )
    def test_retired_environment_values_no_longer_affect_configuration(
        self, monkeypatch: pytest.MonkeyPatch, variable: str
    ) -> None:
        expected = Settings(_env_file=None).model_dump()
        monkeypatch.setenv(variable, "invalid-retired-setting")
        assert Settings(_env_file=None).model_dump() == expected


@pytest.fixture
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-modelark")
    monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "sk-test-speech")
    monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.test.example.com/api/v3")
    monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.test.example.com")
    monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "3600")
    monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "8388608")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestValidate:
    """Tests for the validate() function."""

    def test_validate_passes_with_https_urls(self, clean_settings: None) -> None:
        validate()

    def test_validate_passes_with_default_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_settings.cache_clear()
        monkeypatch.delenv("BYTEPLUS_MODELARK_BASE_URL", raising=False)
        monkeypatch.delenv("BYTEPLUS_SEED_AUDIO_BASE_URL", raising=False)
        validate()
        get_settings.cache_clear()

    def test_validate_rejects_non_https_modelark_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "http://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "3600")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "8388608")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="BYTEPLUS_MODELARK_BASE_URL must use HTTPS"):
            validate()
        get_settings.cache_clear()

    def test_validate_rejects_non_https_seed_audio_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "http://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "3600")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "8388608")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="BYTEPLUS_SEED_AUDIO_BASE_URL must use HTTPS"):
            validate()
        get_settings.cache_clear()

    def test_validate_rejects_zero_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "0")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "8388608")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="ARTIFACT_TTL_SECONDS must be positive"):
            validate()
        get_settings.cache_clear()

    def test_validate_rejects_negative_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "-1")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "8388608")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="ARTIFACT_TTL_SECONDS must be positive"):
            validate()
        get_settings.cache_clear()

    def test_validate_rejects_zero_media_max_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "3600")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "0")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="MCP_INLINE_MEDIA_MAX_BYTES must be positive"):
            validate()
        get_settings.cache_clear()

    def test_validate_rejects_negative_media_max_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://ark.example.com/api/v3")
        monkeypatch.setenv("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.example.com")
        monkeypatch.setenv("ARTIFACT_TTL_SECONDS", "3600")
        monkeypatch.setenv("MCP_INLINE_MEDIA_MAX_BYTES", "-100")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="MCP_INLINE_MEDIA_MAX_BYTES must be positive"):
            validate()
        get_settings.cache_clear()


class TestGetSettingsCaching:
    """Tests for get_settings() lru_cache behavior."""

    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test")
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second
        get_settings.cache_clear()

    def test_returns_new_instance_after_cache_clear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-1")
        get_settings.cache_clear()
        first = get_settings()
        get_settings.cache_clear()
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-2")
        second = get_settings()
        assert first is not second
        assert first.modelark_api_key == "sk-test-1"  # pragma: allowlist secret
        assert second.modelark_api_key == "sk-test-2"  # pragma: allowlist secret
        get_settings.cache_clear()

    def test_cache_returns_same_instance_even_after_env_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-1")
        get_settings.cache_clear()
        first = get_settings()
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-test-2")
        second = get_settings()
        assert first is second
        get_settings.cache_clear()


class TestSettingsFromEnv:
    """Tests for Settings loading from environment variables."""

    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_API_KEY", "sk-from-env")
        settings = Settings(_env_file=None)
        assert settings.modelark_api_key == "sk-from-env"  # pragma: allowlist secret

    def test_seed_speech_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_SEED_SPEECH_API_KEY", "sk-speech-env")
        settings = Settings(_env_file=None)
        assert settings.seed_speech_api_key == "sk-speech-env"  # pragma: allowlist secret

    def test_transport_http_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "http")
        monkeypatch.setenv("MCP_AUTH_MODE", "byok")
        monkeypatch.setenv("MCP_IDENTITY_HMAC_KEY", "a" * 64)
        settings = Settings(_env_file=None)
        assert settings.mcp_transport == "http"

    def test_transport_stdio_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        settings = Settings(_env_file=None)
        assert settings.mcp_transport == "stdio"

    def test_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "8080")
        settings = Settings(_env_file=None)
        assert settings.mcp_port == 8080

    def test_host_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        settings = Settings(_env_file=None)
        assert settings.mcp_host == "0.0.0.0"

    def test_fastmcp_alias_for_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_TRANSPORT", "http")
        monkeypatch.setenv("MCP_AUTH_MODE", "byok")
        monkeypatch.setenv("MCP_IDENTITY_HMAC_KEY", "a" * 64)
        settings = Settings(_env_file=None)
        assert settings.mcp_transport == "http"

    def test_byok_identity_and_limits_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "http")
        monkeypatch.setenv("MCP_AUTH_MODE", "byok")
        monkeypatch.setenv("MCP_IDENTITY_HMAC_KEY", "a" * 64)
        monkeypatch.setenv("MCP_IDENTITY_KEY_VERSION", "2")
        monkeypatch.setenv("MCP_HTTP_MAX_BODY_BYTES", "1024")
        monkeypatch.setenv("MCP_HTTP_MAX_IN_FLIGHT", "8")
        monkeypatch.setenv("STATE_MAX_RECORDS", "100")
        monkeypatch.setenv("RATE_LIMIT_RPM", "10")
        settings = Settings(_env_file=None)
        assert settings.identity_hmac_key.get_secret_value() == "a" * 64
        assert settings.identity_key_version == 2
        assert settings.mcp_http_max_body_bytes == 1024
        assert settings.http_max_in_flight == 8
        assert settings.state_max_records == 100
        assert settings.rate_limit_rpm == 10

    def test_fastmcp_alias_for_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "192.168.1.1")
        settings = Settings(_env_file=None)
        assert settings.mcp_host == "192.168.1.1"

    def test_fastmcp_alias_for_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_PORT", "9000")
        settings = Settings(_env_file=None)
        assert settings.mcp_port == 9000

    def test_allowed_origins_with_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_ALLOWED_ORIGINS", " https://a.com , https://b.com ")
        settings = Settings(_env_file=None)
        assert settings.allowed_origins == ["https://a.com", "https://b.com"]

    def test_allowed_origins_single_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://only.com")
        settings = Settings(_env_file=None)
        assert settings.allowed_origins == ["https://only.com"]

    def test_artifact_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTIFACT_DIR", "/tmp/custom-artifacts")
        settings = Settings(_env_file=None)
        assert settings.artifact_dir == "/tmp/custom-artifacts"

    def test_connect_timeout_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_CONNECT_TIMEOUT_MS", "5000")
        settings = Settings(_env_file=None)
        assert settings.connect_timeout_ms == 5000

    def test_request_timeout_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_REQUEST_TIMEOUT_MS", "60000")
        settings = Settings(_env_file=None)
        assert settings.request_timeout_ms == 60000

    def test_base_url_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BYTEPLUS_MODELARK_BASE_URL", "https://custom.ark.com/api/v3")
        settings = Settings(_env_file=None)
        assert settings.modelark_base_url == "https://custom.ark.com/api/v3"


class TestStateAndArtifactBackend:
    """Settings for the state and durable-artifact backends."""

    def test_object_storage_backend_without_credentials_fails(self) -> None:
        with pytest.raises(
            ValidationError,
            match="ARTIFACT_BACKEND=object_storage requires S3_\\* credentials",
        ):
            Settings(_env_file=None, ARTIFACT_BACKEND="object_storage")

    def test_state_backend_accepts_only_sqlite(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, STATE_BACKEND="redis")

    def test_state_backend_sqlite_is_accepted(self) -> None:
        settings = Settings(_env_file=None, STATE_BACKEND="sqlite")
        assert settings.state_backend == "sqlite"

    def test_object_storage_backend_with_s3_credentials_passes(self) -> None:
        settings = Settings(
            _env_file=None,
            ARTIFACT_BACKEND="object_storage",
            S3_ACCESS_KEY="ak-s3",
            S3_SECRET_KEY="sk-s3",  # pragma: allowlist secret
            S3_BUCKET="bucket",
        )
        assert settings.artifact_backend == "object_storage"
        assert settings.has_object_storage is True


class TestEnvFileResolution:
    """``env_file`` is cwd-relative, so an absolute override must be honored."""

    def test_defaults_to_dot_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARK_MCP_ENV_FILE", raising=False)
        assert resolve_env_file() == ".env"

    def test_absolute_override_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARK_MCP_ENV_FILE", "/srv/ark/secrets.env")
        assert resolve_env_file() == "/srv/ark/secrets.env"

    def test_blank_override_falls_back_to_dot_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARK_MCP_ENV_FILE", "   ")
        assert resolve_env_file() == ".env"

    def test_override_loads_settings_from_that_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        env_file = tmp_path / "custom.env"
        env_file.write_text(
            "BYTEPLUS_MODELARK_API_KEY=sk-from-custom-file\n"  # pragma: allowlist secret
        )
        for name in (
            "BYTEPLUS_MODELARK_API_KEY",
            "BYTEPLUS_SEED_SPEECH_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)

        settings = Settings(_env_file=str(env_file))

        assert settings.modelark_api_key == "sk-from-custom-file"  # pragma: allowlist secret
        assert settings.has_modelark is True
