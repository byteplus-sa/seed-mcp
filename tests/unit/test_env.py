"""Configuration contracts for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import pytest

from ark_mcp.config.env import AuthMode, Settings


def _http_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "MCP_TRANSPORT": "http",
            "MCP_AUTH_MODE": "byok",
            "MCP_IDENTITY_HMAC_KEY": "a" * 64,
            **overrides,
        },
    )


class TestSettings:
    """Tests for the Settings model."""

    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.modelark_base_url == "https://ark.ap-southeast.bytepluses.com/api/v3"
        assert settings.seed_audio_base_url == "https://voice.ap-southeast-1.bytepluses.com"
        assert settings.cv_base_url == "https://openapi.cv.bytepluses.com"
        assert settings.mcp_transport == "stdio"
        assert settings.mcp_host == "127.0.0.1"
        assert settings.mcp_port == 3000
        assert settings.artifact_backend == "filesystem"
        assert settings.artifact_ttl_seconds == 604800
        assert settings.mcp_inline_media_max_bytes == 8388608

    def test_http_admission_defaults_are_bounded(self) -> None:
        settings = _http_settings()
        assert settings.mcp_http_max_body_bytes == 2 * 1024 * 1024
        assert settings.http_max_in_flight == 64
        assert settings.state_max_records == 100_000
        assert settings.trusted_proxy_networks == ()

    def test_has_modelark_false_when_empty(self) -> None:
        settings = Settings(_env_file=None)
        assert not settings.has_modelark

    def test_has_modelark_true_when_set(self) -> None:
        settings = Settings(_env_file=None, BYTEPLUS_MODELARK_API_KEY="sk-test")
        assert settings.has_modelark

    def test_has_seed_audio_false_when_empty(self) -> None:
        settings = Settings(_env_file=None)
        assert not settings.has_seed_audio

    def test_has_seed_audio_true_when_set(self) -> None:
        settings = Settings(_env_file=None, BYTEPLUS_SEED_SPEECH_API_KEY="sk-test")
        assert settings.has_seed_audio

    def test_removed_premium_settings_do_not_add_bindings(self) -> None:
        settings = Settings(
            _env_file=None,
            BYTEPLUS_MODELARK_SEEDANCE_2_5_PREMIUM_ENABLED=True,
            SEEDANCE_2_5_PREMIUM_MODEL="ep-retired",
        )
        bindings = {b.model_id: b.family for b in settings.seedance_model_bindings}
        assert "seedance_2_5_premium" not in bindings.values()
        assert "ep-retired" not in bindings
        assert "seedance_2_5_premium_enabled" not in Settings.model_fields
        assert "seedance_2_5_premium_model" not in Settings.model_fields

    def test_seedance_default_model_is_2_5(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.seedance_default_model == "dreamina-seedance-2-5-260628"
        bindings = {b.model_id: b.family for b in settings.seedance_model_bindings}
        assert bindings == {
            "dreamina-seedance-2-5-260628": "seedance_2_5",
            "dreamina-seedance-2-5-flash-261115": "seedance_2_5_flash",
        }

    def test_flash_default_model_infers_family_without_duplicates(self) -> None:
        settings = Settings(
            _env_file=None, SEEDANCE_DEFAULT_MODEL="dreamina-seedance-2-5-flash-261115"
        )
        assert len(settings.seedance_model_bindings) == 1
        assert settings.seedance_model_bindings[0].family == "seedance_2_5_flash"

    def test_explicit_bindings_do_not_automatically_add_flash(self) -> None:
        settings = Settings(
            _env_file=None,
            SEEDANCE_MODEL_BINDINGS=[
                {"model_id": "dreamina-seedance-2-5-260628", "family": "seedance_2_5"}
            ],
        )
        assert len(settings.seedance_model_bindings) == 1

    def test_custom_flash_endpoint_requires_and_accepts_explicit_family(self) -> None:
        settings = Settings(
            _env_file=None,
            SEEDANCE_DEFAULT_MODEL="ep-flash",
            SEEDANCE_MODEL_FAMILY="seedance_2_5_flash",
        )
        assert settings.seedance_model_bindings[0].model_id == "ep-flash"
        assert settings.seedance_model_bindings[0].family == "seedance_2_5_flash"

    def test_2_0_only_bindings_without_default_explain_the_fix(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            Settings(
                _env_file=None,
                SEEDANCE_MODEL_BINDINGS=[
                    {"model_id": "dreamina-seedance-2-0-260128", "family": "standard"}
                ],
            )
        message = str(excinfo.value)
        assert "default model 'dreamina-seedance-2-5-260628' is missing" in message
        assert "dreamina-seedance-2-0-260128" in message

    def test_removed_premium_binding_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Input should be"):
            Settings(
                _env_file=None,
                SEEDANCE_MODEL_BINDINGS=[
                    {
                        "model_id": "ep-retired",
                        "family": "seedance_2_5_premium",
                    },
                ],
            )

    def test_removed_premium_default_family_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a valid SeedanceFamily"):
            Settings(
                _env_file=None,
                SEEDANCE_DEFAULT_MODEL="ep-retired",
                SEEDANCE_MODEL_FAMILY="seedance_2_5_premium",
            )

    def test_omnihuman_disabled_by_default(self) -> None:
        settings = Settings(_env_file=None)
        assert not settings.omnihuman_enabled
        assert not settings.has_omnihuman
        assert settings.cv_base_url == "https://openapi.cv.bytepluses.com"
        assert settings.omnihuman_req_key == "realman_avatar_picture_omni20_cv"

    def test_omnihuman_requires_both_flag_and_key(self) -> None:
        assert not Settings(_env_file=None, BYTEPLUS_OMNIHUMAN_ENABLED=True).has_omnihuman
        assert not Settings(
            _env_file=None,
            BYTEPLUS_CV_API_KEY="cv-key",  # pragma: allowlist secret
        ).has_omnihuman
        assert Settings(
            _env_file=None,
            BYTEPLUS_OMNIHUMAN_ENABLED=True,
            BYTEPLUS_CV_API_KEY="cv-key",  # pragma: allowlist secret
        ).has_omnihuman

    def test_cv_base_url_override_requires_https(self) -> None:
        settings = Settings(_env_file=None, BYTEPLUS_CV_BASE_URL="https://cv.example.com/")
        assert settings.cv_base_url == "https://cv.example.com"
        with pytest.raises(ValueError, match="BYTEPLUS_CV_BASE_URL must use HTTPS"):
            Settings(_env_file=None, BYTEPLUS_CV_BASE_URL="http://cv.example.com")

    def test_allowed_origins_empty(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.allowed_origins == []

    def test_allowed_origins_parsed(self) -> None:
        settings = Settings(_env_file=None, MCP_ALLOWED_ORIGINS="https://a.com,https://b.com")
        assert settings.allowed_origins == ["https://a.com", "https://b.com"]

    def test_invalid_transport_raises(self) -> None:
        with pytest.raises(ValueError):
            Settings(_env_file=None, MCP_TRANSPORT="invalid")

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "0.0.0.0"])
    def test_http_requires_byok_even_on_loopback(self, host: str) -> None:
        with pytest.raises(ValueError, match="HTTP requires MCP_AUTH_MODE=byok"):
            _http_settings(MCP_HOST=host, MCP_AUTH_MODE="local")

    @pytest.mark.parametrize("mode", ["api_key", "jwt", ""])
    def test_retired_auth_modes_are_rejected(self, mode: str) -> None:
        with pytest.raises(ValueError, match="MCP_AUTH_MODE"):
            _http_settings(MCP_AUTH_MODE=mode)
        assert set(AuthMode) == {"local", "byok"}

    def test_http_defaults_to_byok_without_operator_provider_credentials(self) -> None:
        settings = Settings(_env_file=None, MCP_TRANSPORT="http", MCP_IDENTITY_HMAC_KEY="a" * 64)
        assert settings.mcp_auth_mode is AuthMode.BYOK
        assert not settings.has_modelark
        assert not settings.has_seed_audio
        assert not settings.has_omnihuman

    def test_stdio_needs_no_hmac_or_provider_credentials(self) -> None:
        settings = Settings(_env_file=None, MCP_TRANSPORT="stdio", MCP_AUTH_MODE="local")
        assert settings.identity_hmac_key.get_secret_value() == ""
        assert settings.mcp_auth_mode is AuthMode.LOCAL

    @pytest.mark.parametrize("key", ["", "short", "g" * 64, "a" * 63, "A" * 64, "a" * 65])
    def test_http_requires_lowercase_hex_identity_hmac(self, key: str) -> None:
        with pytest.raises(ValueError, match="MCP_IDENTITY_HMAC_KEY"):
            _http_settings(MCP_IDENTITY_HMAC_KEY=key)

    def test_identity_hmac_is_masked_in_settings(self) -> None:
        settings = _http_settings()
        assert "a" * 64 not in repr(settings)
        assert "a" * 64 not in settings.model_dump_json()
        assert settings.identity_key_version == 1

    @pytest.mark.parametrize(
        "name",
        [
            "MCP_IDENTITY_KEY_VERSION",
            "MCP_HTTP_MAX_BODY_BYTES",
            "MCP_HTTP_MAX_IN_FLIGHT",
            "STATE_MAX_RECORDS",
            "RATE_LIMIT_RPM",
        ],
    )
    @pytest.mark.parametrize("value", [0, -1])
    def test_http_limits_and_identity_version_must_be_positive(self, name: str, value: int) -> None:
        with pytest.raises(ValueError, match=name):
            _http_settings(**{name: value})

    def test_local_rate_limiting_can_be_disabled(self) -> None:
        assert Settings(_env_file=None, RATE_LIMIT_RPM=0).rate_limit_rpm == 0

    @pytest.mark.parametrize(
        "name,official",
        [
            ("BYTEPLUS_MODELARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3"),
            ("BYTEPLUS_SEED_AUDIO_BASE_URL", "https://voice.ap-southeast-1.bytepluses.com"),
            ("BYTEPLUS_CV_BASE_URL", "https://openapi.cv.bytepluses.com"),
        ],
    )
    @pytest.mark.parametrize(
        "suffix", ["/other", "/../other", "?query=1", "#fragment", "/%2e%2e/other"]
    )
    def test_http_rejects_confused_provider_origins(
        self, name: str, official: str, suffix: str
    ) -> None:
        with pytest.raises(ValueError, match="fixed official provider base URLs"):
            _http_settings(**{name: official + suffix})

    @pytest.mark.parametrize(
        "name",
        ["BYTEPLUS_MODELARK_BASE_URL", "BYTEPLUS_SEED_AUDIO_BASE_URL", "BYTEPLUS_CV_BASE_URL"],
    )
    @pytest.mark.parametrize(
        "url,error",
        [
            ("https://provider.example.com", "fixed official provider base URLs"),
            (
                "https://user:test-password@provider.example.com",  # pragma: allowlist secret
                "must not contain credentials",
            ),
            ("http://provider.example.com", "must use HTTPS"),
        ],
    )
    def test_http_rejects_untrusted_provider_urls(self, name: str, url: str, error: str) -> None:
        with pytest.raises(ValueError, match=error):
            _http_settings(**{name: url})

    def test_http_rejects_provider_readiness_probes(self) -> None:
        with pytest.raises(ValueError, match="HTTP readiness must not call providers"):
            _http_settings(READINESS_CHECK_PROVIDERS=True)

    def test_settings_have_no_retired_bearer_configuration(self) -> None:
        aliases = {
            field.validation_alias
            for field in Settings.model_fields.values()
            if isinstance(field.validation_alias, str)
        }
        assert not any(alias.startswith("MCP_JWT_") for alias in aliases)
        assert aliases.isdisjoint({"MCP_API_KEY_SHA256", "MCP_TENANT_CLAIM", "MCP_PUBLIC_BASE_URL"})

    @pytest.mark.parametrize("retention", [1, 7, 13])
    @pytest.mark.parametrize("model", ["dreamina-seedance-2-5-260628", "ep-draft"])
    def test_authenticated_draft_models_reject_short_ownership_retention(
        self, retention: int, model: str
    ) -> None:
        with pytest.raises(ValueError, match="STATE_PRUNE_MAX_AGE_DAYS must be at least 14"):
            _http_settings(
                SEEDANCE_DEFAULT_MODEL=model,
                SEEDANCE_MODEL_FAMILY="seedance_2_5",
                STATE_PRUNE_MAX_AGE_DAYS=retention,
            )

    @pytest.mark.parametrize("retention", [14, 30])
    @pytest.mark.parametrize("model", ["dreamina-seedance-2-5-260628", "ep-draft"])
    def test_authenticated_draft_models_accept_full_ownership_retention(
        self, retention: int, model: str
    ) -> None:
        settings = _http_settings(
            SEEDANCE_DEFAULT_MODEL=model,
            SEEDANCE_MODEL_FAMILY="seedance_2_5",
            STATE_PRUNE_MAX_AGE_DAYS=retention,
        )
        assert settings.state_prune_max_age_days == retention

    def test_nondefault_draft_binding_requires_full_ownership_retention(self) -> None:
        with pytest.raises(ValueError, match="STATE_PRUNE_MAX_AGE_DAYS must be at least 14"):
            _http_settings(
                SEEDANCE_DEFAULT_MODEL="ep-flash",
                SEEDANCE_MODEL_BINDINGS=[
                    {"model_id": "ep-flash", "family": "seedance_2_5_flash"},
                    {"model_id": "ep-draft", "family": "seedance_2_5"},
                ],
                STATE_PRUNE_MAX_AGE_DAYS=7,
            )

    @pytest.mark.parametrize(
        "transport,auth_mode,provider_key,model,family",
        [
            ("stdio", "local", "sk-test", "ep-draft", "seedance_2_5"),
            ("stdio", "local", "", "ep-draft", "seedance_2_5"),
            ("http", "byok", "", "ep-flash", "seedance_2_5_flash"),
            ("http", "byok", "", "ep-legacy", "standard"),
        ],
    )
    def test_configurations_without_authenticated_drafts_keep_short_retention(
        self, transport: str, auth_mode: str, provider_key: str, model: str, family: str
    ) -> None:
        settings = Settings(
            _env_file=None,
            BYTEPLUS_MODELARK_API_KEY=provider_key,
            MCP_TRANSPORT=transport,
            MCP_AUTH_MODE=auth_mode,
            MCP_IDENTITY_HMAC_KEY="a" * 64,
            SEEDANCE_DEFAULT_MODEL=model,
            SEEDANCE_MODEL_FAMILY=family,
            STATE_PRUNE_MAX_AGE_DAYS=1,
        )
        assert settings.state_prune_max_age_days == 1

    def test_timeout_defaults(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.connect_timeout_ms == 10000
        assert settings.request_timeout_ms == 600000

    def test_persistence_cache_defaults(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.persistence_cache_max_size == 10_000
        assert settings.persistence_cache_ttl_seconds == 86_400

    def test_persistence_cache_env_overrides(self) -> None:
        settings = Settings(
            _env_file=None,
            PERSISTENCE_CACHE_MAX_SIZE=500,
            PERSISTENCE_CACHE_TTL_SECONDS=3600,
        )
        assert settings.persistence_cache_max_size == 500
        assert settings.persistence_cache_ttl_seconds == 3600

    def test_readiness_defaults(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.readiness_check_providers is False
        assert settings.readiness_provider_timeout_seconds == 2.0

    def test_readiness_env_overrides(self) -> None:
        settings = Settings(
            _env_file=None,
            READINESS_CHECK_PROVIDERS=True,
            READINESS_PROVIDER_TIMEOUT_SECONDS=5.0,
        )
        assert settings.readiness_check_providers is True
        assert settings.readiness_provider_timeout_seconds == 5.0

    def test_rate_limit_defaults(self) -> None:
        settings = _http_settings()
        assert settings.rate_limit_rpm == 60
        assert settings.rate_limit_burst == 0

    def test_rate_limit_env_overrides(self) -> None:
        settings = Settings(
            _env_file=None,
            RATE_LIMIT_RPM=60,
            RATE_LIMIT_BURST=10,
        )
        assert settings.rate_limit_rpm == 60
        assert settings.rate_limit_burst == 10

    def test_model_bindings(self) -> None:
        settings = Settings(
            _env_file=None,
            SEEDREAM_DEFAULT_MODEL="custom-model",
            SEEDANCE_DEFAULT_MODEL="custom-video",
            SEEDREAM_MODEL_FAMILY="lite",
            SEEDANCE_MODEL_FAMILY="fast",
        )
        assert settings.seedream_default_model == "custom-model"
        assert settings.seedance_default_model == "custom-video"

    def test_custom_model_requires_explicit_family(self) -> None:
        with pytest.raises(ValueError, match="custom SEEDREAM_DEFAULT_MODEL"):
            Settings(_env_file=None, SEEDREAM_DEFAULT_MODEL="custom-model")

    def test_json_model_bindings_are_explicit(self) -> None:
        settings = Settings(
            _env_file=None,
            SEEDREAM_DEFAULT_MODEL="image-a",
            SEEDREAM_MODEL_BINDINGS=[{"model_id": "image-a", "family": "4x"}],
            SEEDANCE_DEFAULT_MODEL="video-a",
            SEEDANCE_MODEL_BINDINGS=[{"model_id": "video-a", "family": "mini"}],
        )
        assert settings.seedream_model_bindings[0].family == "4x"
        assert settings.seedance_model_bindings[0].family == "mini"


class TestS3Config:
    """Tests for S3 object storage configuration."""

    def test_has_s3_false_when_empty(self) -> None:
        settings = Settings(_env_file=None)
        assert not settings.has_s3

    def test_has_s3_true_when_set(self) -> None:
        settings = Settings(
            _env_file=None,
            S3_ACCESS_KEY="ak-test",
            S3_SECRET_KEY="sk-test",  # pragma: allowlist secret
            S3_BUCKET="test-bucket",
            OBJECT_STORAGE_BACKEND="s3",
        )
        assert settings.has_s3

    def test_object_storage_backend_defaults_to_tos(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.object_storage_backend == "tos"

    def test_has_object_storage_reflects_selected_backend(self) -> None:
        settings = Settings(
            _env_file=None,
            S3_ACCESS_KEY="ak",
            S3_SECRET_KEY="sk",  # pragma: allowlist secret
            S3_BUCKET="bucket",
            OBJECT_STORAGE_BACKEND="s3",
        )
        assert settings.has_object_storage is True

        settings_tos = Settings(
            _env_file=None,
            TOS_ACCESS_KEY="ak",
            TOS_SECRET_KEY="sk",  # pragma: allowlist secret
            TOS_BUCKET="bucket",
            TOS_ENDPOINT="tos-test.example.com",
        )
        assert settings_tos.has_object_storage is True

    def test_presign_ttl_seconds_returns_selected_backend_ttl(self) -> None:
        settings = Settings(
            _env_file=None,
            S3_ACCESS_KEY="ak",
            S3_SECRET_KEY="sk",  # pragma: allowlist secret
            S3_BUCKET="bucket",
            S3_PRESIGN_TTL_SECONDS=3600,
            OBJECT_STORAGE_BACKEND="s3",
        )
        assert settings.presign_ttl_seconds == 3600

    def test_s3_ak_sk_must_both_be_set(self) -> None:
        with pytest.raises(ValueError, match="S3_ACCESS_KEY and S3_SECRET_KEY"):
            Settings(_env_file=None, S3_ACCESS_KEY="ak")

    def test_backend_s3_requires_credentials(self) -> None:
        with pytest.raises(ValueError, match="OBJECT_STORAGE_BACKEND=s3 requires"):
            Settings(_env_file=None, OBJECT_STORAGE_BACKEND="s3")

    def test_backend_tos_with_s3_creds_missing_tos_raises_guidance(self) -> None:
        with pytest.raises(ValueError, match="OBJECT_STORAGE_BACKEND=tos but TOS credentials"):
            Settings(
                _env_file=None,
                S3_ACCESS_KEY="ak",
                S3_SECRET_KEY="sk",  # pragma: allowlist secret
                S3_BUCKET="bucket",
                OBJECT_STORAGE_BACKEND="tos",
            )
