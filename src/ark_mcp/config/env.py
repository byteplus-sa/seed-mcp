"""Environment configuration for the Ark Seed MCP server.

Loads custom environment variables (provider credentials, model bindings,
artifact storage, transport settings) via Pydantic Settings. FastMCP's own
settings (log level, etc.) are handled separately by FastMCP.

HTTP generation credentials are request-only BYOK headers, never tool arguments.
Startup generation credentials serve only trusted local stdio development.
Opt-in HTTP temporary upload preparation uses restricted operator TOS signing credentials.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, collapse_addresses, ip_network
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterator


def parse_trusted_proxy_cidrs(value: str) -> tuple[IPv4Network | IPv6Network, ...]:
    """Validate explicit proxy networks, normalizing mapped IPv6 to IPv4."""
    if not value.strip():
        return ()
    networks: list[IPv4Network | IPv6Network] = []
    try:
        for entry in value.split(","):
            cidr = entry.strip()
            if not re.fullmatch(r"[0-9a-fA-F:.]+/[0-9]{1,3}", cidr):
                raise ValueError
            network = ip_network(cidr, strict=True)
            if isinstance(network, IPv6Network) and network.network_address.ipv4_mapped:
                network = IPv4Network((network.network_address.ipv4_mapped, network.prefixlen - 96))
            networks.append(network)
        ipv4 = collapse_addresses(n for n in networks if isinstance(n, IPv4Network))
        ipv6 = collapse_addresses(n for n in networks if isinstance(n, IPv6Network))
        if any(n.prefixlen == 0 for n in ipv4) or any(n.prefixlen == 0 for n in ipv6):
            raise ValueError
    except ValueError:
        raise ValueError(
            "RATE_LIMIT_TRUSTED_PROXY_CIDRS must contain explicit IPv4/IPv6 CIDRs "
            "without host bits, empty entries or catch-all networks."
        ) from None
    return tuple(networks)


def resolve_env_file() -> str:
    """Return the env file to load, honoring an explicit absolute override.

    ``env_file`` is resolved by pydantic-settings relative to the process
    working directory. An MCP client that spawns this server from another
    directory therefore finds no ``.env``, and the server starts with no
    provider credentials and no provider tools. ``ARK_MCP_ENV_FILE`` lets a
    client point at the file explicitly instead of relying on the cwd.
    """
    override = os.environ.get("ARK_MCP_ENV_FILE", "").strip()
    return override or ".env"


def _warn_if_http_body_limit_blocks_media_upload(body_bytes: int) -> None:
    """Warn when the HTTP body limit cannot carry the largest media upload.

    ``MediaLimits.video_max_bytes`` (200 MiB) is the largest Base64 media the
    upload tool accepts, and Base64 inflates ~4/3x inside the JSON-RPC envelope.
    A body limit below that will 413 on inlined large uploads, so we warn — but
    do not fail — because an operator may intentionally keep a small body cap
    and route large media through ``media_upload`` (presign) or a file path.
    """
    from ark_mcp.observability.logger import warning as log_warning
    from ark_mcp.security.media_policy import MediaLimits

    video_max_bytes = MediaLimits().video_max_bytes
    inflated = (video_max_bytes * 4) // 3
    if body_bytes < inflated:
        log_warning(
            "http_body_limit_below_media_upload_max",
            mcp_http_max_body_bytes=body_bytes,
            media_video_max_bytes=video_max_bytes,
            note=(
                "Inlined Base64 media uploads larger than this body limit will be "
                "rejected with HTTP 413; use the presign/direct-upload path for large media."
            ),
        )


class SeedreamFamily(StrEnum):
    SEEDREAM_5_5 = "seedream_5_5"
    PRO = "pro"
    LITE = "lite"
    V4X = "4x"


class SeedanceFamily(StrEnum):
    STANDARD = "standard"
    FAST = "fast"
    MINI = "mini"
    SEEDANCE_2_5 = "seedance_2_5"
    SEEDANCE_2_5_FLASH = "seedance_2_5_flash"


SEEDANCE_2_5_FLASH_MODEL_ID = "dreamina-seedance-2-5-flash-261115"
SEEDANCE_DRAFT_MAX_AGE_DAYS = 14


class AuthMode(StrEnum):
    LOCAL = "local"
    BYOK = "byok"


class ImageModelBinding(BaseModel):
    model_id: str = Field(min_length=1)
    family: SeedreamFamily


class VideoModelBinding(BaseModel):
    model_id: str = Field(min_length=1)
    family: SeedanceFamily


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file.

    Uses ``validation_alias`` (not ``alias``) for environment variable name
    overrides so that field names are preserved for serialization and code
    access. See https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/.

    ``secrets_dir`` points to ``/run/secrets`` (Docker / Kubernetes) and
    emits a warning when the directory does not exist. Individual fields can
    also be overridden by placing a file named after the field (or its
    validation alias) in the secrets directory.
    """

    model_config = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=True,
        hide_input_in_errors=True,
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    # --- Provider credentials ------------------------------------------------

    modelark_api_key: str = Field(default="", validation_alias="BYTEPLUS_MODELARK_API_KEY")
    seed_speech_api_key: str = Field(
        default="",
        validation_alias="BYTEPLUS_SEED_SPEECH_API_KEY",
        description="Seed Speech API key for full-scene Seed Audio generation.",
    )

    cv_api_key: str = Field(
        default="",
        validation_alias="BYTEPLUS_CV_API_KEY",
        description="BytePlus Vision AI Bearer API key for OmniHuman.",
    )

    # --- Provider base URLs --------------------------------------------------

    modelark_base_url: str = Field(
        default="https://ark.ap-southeast.bytepluses.com/api/v3",
        validation_alias="BYTEPLUS_MODELARK_BASE_URL",
    )
    seed_audio_base_url: str = Field(
        default="https://voice.ap-southeast-1.bytepluses.com",
        validation_alias="BYTEPLUS_SEED_AUDIO_BASE_URL",
    )
    cv_base_url: str = Field(
        default="https://openapi.cv.bytepluses.com",
        validation_alias="BYTEPLUS_CV_BASE_URL",
        description="BytePlus Vision AI HTTPS API base URL.",
    )

    # --- OmniHuman feature flag ----------------------------------------------

    omnihuman_enabled: bool = Field(
        default=False,
        validation_alias="BYTEPLUS_OMNIHUMAN_ENABLED",
        description=(
            "Feature flag for OmniHuman 2.0 tools. Disabled by default. When false, no "
            "OmniHuman tools are registered even if BYTEPLUS_CV_API_KEY is configured."
        ),
    )
    omnihuman_req_key: str = Field(
        default="realman_avatar_picture_omni20_cv",
        min_length=1,
        validation_alias="BYTEPLUS_OMNIHUMAN_REQ_KEY",
        description="Vision AI service identifier sent as req_key for OmniHuman requests.",
    )

    # --- Model bindings ------------------------------------------------------

    seedream_prompt_optimization_mode: Literal["standard", "fast"] = Field(
        default="standard",
        validation_alias="SEEDREAM_PROMPT_OPTIMIZATION_MODE",
        description=(
            "Prompt optimization mode Seedream 5.0 Pro uses when a caller omits "
            "prompt_optimization: 'standard' for prompt-following quality, 'fast' for "
            "lower latency. Both are accepted by the provider. An explicit per-call "
            "value always wins, and other Seedream families send no mode regardless."
        ),
    )
    seedream_default_model: str = Field(
        default="dola-seedream-5-5-261028",
        validation_alias="SEEDREAM_DEFAULT_MODEL",
    )
    seedance_default_model: str = Field(
        default="dreamina-seedance-2-5-260628",
        validation_alias="SEEDANCE_DEFAULT_MODEL",
    )
    seedream_model_family: str = Field(
        default="",
        validation_alias="SEEDREAM_MODEL_FAMILY",
        description="Explicit family: 'seedream_5_5', 'pro', 'lite', or '4x'. Empty = infer from model ID.",
    )
    seedance_model_family: str = Field(
        default="",
        validation_alias="SEEDANCE_MODEL_FAMILY",
        description=(
            "Explicit family: 'standard', 'fast', 'mini', 'seedance_2_5', or "
            "'seedance_2_5_flash'. Empty = infer."
        ),
    )
    seedream_model_bindings: list[ImageModelBinding] = Field(
        default_factory=list,
        validation_alias="SEEDREAM_MODEL_BINDINGS",
    )
    seedance_model_bindings: list[VideoModelBinding] = Field(
        default_factory=list,
        validation_alias="SEEDANCE_MODEL_BINDINGS",
    )

    # --- MCP transport -------------------------------------------------------

    mcp_transport: str = Field(
        default="stdio",
        validation_alias=AliasChoices("MCP_TRANSPORT", "FASTMCP_TRANSPORT"),
    )
    mcp_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("MCP_HOST", "FASTMCP_HOST"),
    )
    mcp_port: int = Field(
        default=3000,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("MCP_PORT", "FASTMCP_PORT"),
    )
    metrics_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        validation_alias="MCP_METRICS_PORT",
        description=(
            "Private metrics listener port: 0 disables it, otherwise 1024-65535. "
            "Owned by the HTTP runtime and bound only to 127.0.0.1; ignored on stdio."
        ),
    )
    mcp_allowed_origins: str = Field(default="", validation_alias="MCP_ALLOWED_ORIGINS")
    mcp_allowed_hosts: str = Field(
        default="127.0.0.1,localhost,[::1]",
        validation_alias="MCP_ALLOWED_HOSTS",
    )
    mcp_auth_mode: AuthMode = Field(default=AuthMode.BYOK, validation_alias="MCP_AUTH_MODE")
    identity_hmac_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="MCP_IDENTITY_HMAC_KEY",
        description="Operator HMAC secret: 32 random bytes as lowercase hex. Required for HTTP.",
    )
    identity_key_version: int = Field(
        default=1,
        ge=1,
        validation_alias="MCP_IDENTITY_KEY_VERSION",
        description="HMAC version for ephemeral HTTP admission scopes; not task authorization.",
    )
    http_max_in_flight: int = Field(
        default=64,
        ge=1,
        validation_alias="MCP_HTTP_MAX_IN_FLIGHT",
        description="Per-pod HTTP admission cap, including requests waiting for providers.",
    )
    state_max_records: int = Field(
        default=100_000,
        ge=1,
        validation_alias="STATE_MAX_RECORDS",
        description="Maximum rows per ownership/budget table; new admissions fail closed at capacity.",
    )
    readiness_check_providers: bool = Field(
        default=False,
        validation_alias="READINESS_CHECK_PROVIDERS",
        description=(
            "When true, the /ready endpoint also checks provider connectivity. "
            "Increases probe latency by up to READINESS_PROVIDER_TIMEOUT_SECONDS "
            "per configured provider."
        ),
    )
    readiness_provider_timeout_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=10.0,
        validation_alias="READINESS_PROVIDER_TIMEOUT_SECONDS",
        description="Per-provider timeout for readiness connectivity checks.",
    )
    rate_limit_rpm: int = Field(
        default=60,
        ge=0,
        validation_alias="RATE_LIMIT_RPM",
        description=(
            "HTTP requests per minute per client IP per pod; resets at restart. "
            "0 disables rate limiting only on local/isolated configurations."
        ),
    )
    rate_limit_burst: int = Field(
        default=0,
        ge=0,
        validation_alias="RATE_LIMIT_BURST",
        description="Maximum burst size for the token bucket. 0 defaults to RATE_LIMIT_RPM.",
    )
    rate_limit_trusted_proxy_cidrs: str = Field(
        default="",
        validation_alias="RATE_LIMIT_TRUSTED_PROXY_CIDRS",
        description=(
            "Comma-separated explicit IPv4/IPv6 proxy CIDRs; empty trusts no proxy. "
            "Catch-all networks are rejected. X-Forwarded-For is used only when the "
            "immediate peer is trusted, stripping trusted hops from right to left."
        ),
    )

    # --- Artifact persistence ------------------------------------------------

    artifact_backend: Literal["filesystem", "object_storage"] = Field(
        default="filesystem",
        validation_alias="ARTIFACT_BACKEND",
        description=(
            "Durable artifact storage backend. 'filesystem' stores artifacts on "
            "local disk; 'object_storage' stores them in the configured TOS/S3 bucket."
        ),
    )
    state_backend: Literal["sqlite", "none"] | None = Field(
        default=None,
        validation_alias="STATE_BACKEND",
        description=(
            "Resolved automatically: 'none' for stateless HTTP, 'sqlite' for local stdio. "
            "HTTP cannot use a database; stdio retains local artifact bookkeeping."
        ),
    )
    artifact_sweep_interval_seconds: int = Field(
        default=3600,
        ge=60,
        validation_alias="ARTIFACT_SWEEP_INTERVAL_SECONDS",
        description="Interval in seconds between background artifact/state expiry sweeps.",
    )
    state_prune_max_age_days: int = Field(
        default=30,
        ge=1,
        validation_alias="STATE_PRUNE_MAX_AGE_DAYS",
        description=(
            "Maximum age in days for local stdio task-ownership, budget and cache rows. "
            "Unused by stateless HTTP."
        ),
    )
    artifact_dir: str = Field(default="~/.seed-mcp/artifacts", validation_alias="ARTIFACT_DIR")
    artifact_ttl_seconds: int = Field(default=604800, validation_alias="ARTIFACT_TTL_SECONDS")
    mcp_inline_media_max_bytes: int = Field(
        default=8388608, validation_alias="MCP_INLINE_MEDIA_MAX_BYTES"
    )
    artifact_download_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        validation_alias="ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS",
        description=(
            "Timeout in seconds for each attempt to download provider output into "
            "artifact storage (both filesystem and object-storage backends)."
        ),
    )
    artifact_download_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="ARTIFACT_DOWNLOAD_MAX_ATTEMPTS",
        description=(
            "Maximum attempts for a retryable provider output download "
            "(timeouts, network errors, 408/429/5xx). Downloads are side-effect free."
        ),
    )
    artifact_inline_fallback_max_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=0,
        validation_alias="ARTIFACT_INLINE_FALLBACK_MAX_BYTES",
        description=(
            "When inline Base64 output (Seed Audio, Seedream b64_json) cannot be stored, "
            "return it inline up to this decoded size instead of dropping it. 0 disables."
        ),
    )
    output_roots: str = Field(
        default="",
        validation_alias="OUTPUT_ROOTS",
        description=(
            "Comma-separated absolute directories where stdio tools may write files "
            "(output_path, output_dir, save_to, destination_path). The client's MCP roots "
            "are used when available; when neither is set, path writing is disabled."
        ),
    )
    mcp_http_max_body_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        validation_alias="MCP_HTTP_MAX_BODY_BYTES",
        description=(
            "Maximum Streamable HTTP request body in bytes. Defaults to 2 MiB; "
            "use HTTPS media references for larger inputs."
        ),
    )

    # --- TOS object storage -------------------------------------------------

    tos_credential_mode: Literal["static", "irsa"] = Field(
        default="static", validation_alias="TOS_CREDENTIAL_MODE"
    )
    tos_irsa_role_trn: str = Field(default="", validation_alias="TOS_IRSA_ROLE_TRN")
    tos_irsa_token_file: str = Field(default="", validation_alias="TOS_IRSA_TOKEN_FILE")
    tos_irsa_sts_endpoint: Literal[
        "https://sts.byteplusapi.com", "https://open.byteplusapi.com"
    ] = Field(default="https://sts.byteplusapi.com", validation_alias="TOS_IRSA_STS_ENDPOINT")
    tos_irsa_duration_seconds: int = Field(
        default=3600, ge=3600, le=43200, validation_alias="TOS_IRSA_DURATION_SECONDS"
    )
    tos_access_key: str = Field(default="", validation_alias="TOS_ACCESS_KEY")
    tos_secret_key: str = Field(default="", validation_alias="TOS_SECRET_KEY")
    tos_security_token: str = Field(default="", validation_alias="TOS_SECURITY_TOKEN")
    tos_bucket: str = Field(default="", validation_alias="TOS_BUCKET")
    tos_region: str = Field(default="ap-southeast-1", validation_alias="TOS_REGION")
    tos_endpoint: str = Field(
        default="tos-ap-southeast-1.bytepluses.com",
        validation_alias="TOS_ENDPOINT",
    )
    tos_presign_ttl_seconds: int = Field(
        default=1800,
        ge=60,
        le=604800,
        validation_alias="TOS_PRESIGN_TTL_SECONDS",
    )
    temporary_upload_enabled: bool = Field(
        default=False,
        validation_alias="MCP_TEMPORARY_UPLOAD_ENABLED",
        description="Enable HTTP-only temporary TOS upload preparation for enrolled clients.",
    )
    upload_client_secret_sha256: str = Field(
        default="",
        max_length=65000,
        repr=False,
        validation_alias="MCP_UPLOAD_CLIENT_SECRET_SHA256",
        description=(
            "Comma-separated SHA-256 digests of exact ASCII X-MCP-Client-Secret values. "
            "Operator enrollment grants upload permission; at most 1000 distinct digests."
        ),
    )

    @property
    def upload_client_digests(self) -> tuple[str, ...]:
        """Return operator-enrolled digests, never raw client secrets."""
        return (
            tuple(self.upload_client_secret_sha256.split(","))
            if self.upload_client_secret_sha256
            else ()
        )

    @field_validator("upload_client_secret_sha256")
    @classmethod
    def validate_upload_client_digests(cls, value: str) -> str:
        if not value:
            return value
        digests = value.split(",")
        if (
            len(digests) > 1000
            or len(set(digests)) != len(digests)
            or any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in digests)
        ):
            raise ValueError(
                "MCP_UPLOAD_CLIENT_SECRET_SHA256 requires 1-1000 distinct lowercase "
                "64-hex SHA-256 digests, comma-separated without whitespace."
            )
        return value

    # --- S3 object storage (Amazon S3 / S3-compatible) -----------------------

    s3_access_key: str = Field(default="", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", validation_alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", validation_alias="S3_REGION")
    s3_endpoint: str = Field(default="", validation_alias="S3_ENDPOINT")
    s3_presign_ttl_seconds: int = Field(
        default=1800,
        ge=60,
        le=604800,
        validation_alias="S3_PRESIGN_TTL_SECONDS",
    )
    object_storage_backend: Literal["tos", "s3"] = Field(
        default="tos",
        validation_alias="OBJECT_STORAGE_BACKEND",
    )

    # --- HTTP timeouts (milliseconds) ---------------------------------------

    connect_timeout_ms: int = Field(default=10000, validation_alias="BYTEPLUS_CONNECT_TIMEOUT_MS")
    request_timeout_ms: int = Field(
        default=600000,
        validation_alias="BYTEPLUS_REQUEST_TIMEOUT_MS",
        description=(
            "10-minute request timeout covers long synchronous generations "
            "(Seedream Pro can take 60-150s, longer under cold start or queue)."
        ),
    )

    media_upload_batch_max_bytes: int = Field(
        default=500 * 1024 * 1024,
        ge=1,
        validation_alias="MEDIA_UPLOAD_BATCH_MAX_BYTES",
        description="Maximum total decoded bytes accepted by one media_upload call.",
    )

    # --- Runtime policy -----------------------------------------------------

    admission_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=30,
        allow_inf_nan=False,
        validation_alias="MCP_ADMISSION_TIMEOUT_SECONDS",
        description=(
            "Finite provider admission wait in seconds, greater than 0 and at most 30. "
            "Covers owner and provider slot waiting, not the provider operation."
        ),
    )
    tool_timeout_seconds: float = Field(
        default=600.0,
        gt=0,
        le=3600,
        allow_inf_nan=False,
        validation_alias="MCP_TOOL_TIMEOUT_SECONDS",
        description=(
            "Finite cooperative tool deadline in seconds, greater than 0 and at most 3600. "
            "Starts at handler-wrapper entry; cleanup may outlast the deadline."
        ),
    )
    provider_max_concurrency: int = Field(
        default=5,
        ge=1,
        validation_alias="PROVIDER_MAX_CONCURRENCY",
    )
    principal_max_concurrency: int = Field(
        default=3,
        ge=1,
        validation_alias="PRINCIPAL_MAX_CONCURRENCY",
    )
    daily_budget_usd: float = Field(
        default=0.0,
        ge=0,
        validation_alias="DAILY_BUDGET_USD",
        description="Per-principal UTC daily limit. Zero records usage without blocking.",
    )
    persistence_cache_max_size: int = Field(
        default=10_000,
        ge=1,
        validation_alias="PERSISTENCE_CACHE_MAX_SIZE",
        description="Maximum number of provider task IDs cached in the artifact-resolution cache.",
    )
    persistence_cache_ttl_seconds: int = Field(
        default=86_400,
        ge=60,
        validation_alias="PERSISTENCE_CACHE_TTL_SECONDS",
        description=(
            "TTL in seconds for cached provider task to artifact mappings. "
            "Entries older than this are ignored on read."
        ),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        validation_alias="ARK_LOG_LEVEL",
    )

    # --- Convenience flags ---------------------------------------------------

    @property
    def has_modelark(self) -> bool:
        """Whether ModelArk credentials are configured (Seedream + Seedance)."""
        return bool(self.modelark_api_key)

    @property
    def has_seed_audio(self) -> bool:
        """Whether Seed Audio credentials are configured."""
        return bool(self.seed_speech_api_key)

    @property
    def has_omnihuman(self) -> bool:
        """Whether OmniHuman 2.0 is enabled and a Vision AI API key is configured."""
        return self.omnihuman_enabled and bool(self.cv_api_key)

    @property
    def has_tos(self) -> bool:
        """Whether TOS object storage credentials are configured."""
        if self.tos_credential_mode == "irsa":
            return bool(self.tos_irsa_role_trn and self.tos_irsa_token_file and self.tos_bucket)
        return bool(self.tos_access_key and self.tos_secret_key and self.tos_bucket)

    @property
    def has_s3(self) -> bool:
        """Whether S3 object storage credentials are configured."""
        return bool(self.s3_access_key and self.s3_secret_key and self.s3_bucket)

    @property
    def has_object_storage(self) -> bool:
        """Whether the *selected* object-storage backend is configured."""
        if self.object_storage_backend == "s3":
            return self.has_s3
        return self.has_tos

    @property
    def presign_ttl_seconds(self) -> int:
        """Presign TTL of the *selected* backend."""
        if self.object_storage_backend == "s3":
            return self.s3_presign_ttl_seconds
        return self.tos_presign_ttl_seconds

    @property
    def output_root_paths(self) -> list[str]:
        """Configured OUTPUT_ROOTS entries (unresolved, non-empty)."""
        return [item.strip() for item in self.output_roots.split(",") if item.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        """Parse the comma-separated allowed origins list."""
        if not self.mcp_allowed_origins:
            return []
        return [origin.strip() for origin in self.mcp_allowed_origins.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]

    @property
    def trusted_proxy_networks(self) -> tuple[IPv4Network | IPv6Network, ...]:
        return parse_trusted_proxy_cidrs(self.rate_limit_trusted_proxy_cidrs)

    @field_validator("rate_limit_trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        return ",".join(str(network) for network in parse_trusted_proxy_cidrs(value))

    @field_validator("metrics_port")
    @classmethod
    def validate_metrics_port(cls, value: int) -> int:
        if 0 < value < 1024:
            raise ValueError("MCP_METRICS_PORT must be 0 or between 1024 and 65535.")
        return value

    @field_validator("mcp_transport")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        allowed = {"stdio", "http"}
        if v not in allowed:
            raise ValueError(f"MCP_TRANSPORT must be one of {allowed}, got '{v}'")
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "modelark_base_url",
        "seed_audio_base_url",
        "cv_base_url",
    )
    @classmethod
    def validate_provider_url(cls, value: str, info: ValidationInfo) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            env_var_map = {
                "modelark_base_url": "BYTEPLUS_MODELARK_BASE_URL",
                "seed_audio_base_url": "BYTEPLUS_SEED_AUDIO_BASE_URL",
                "cv_base_url": "BYTEPLUS_CV_BASE_URL",
            }
            variable = env_var_map.get(info.field_name or "", "BYTEPLUS_PROVIDER_BASE_URL")
            raise ValueError(f"{variable} must use HTTPS and include a host")
        if parsed.username or parsed.password:
            raise ValueError("Provider base URLs must not contain credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_model_bindings(self) -> Settings:
        """Resolve compatibility settings without model-ID string inference."""
        expected_backend: Literal["none", "sqlite"] = (
            "none" if self.mcp_transport == "http" else "sqlite"
        )
        if self.state_backend is None:
            self.state_backend = expected_backend
        if self.state_backend != expected_backend:
            raise ValueError(
                "HTTP requires STATE_BACKEND=none; local stdio requires STATE_BACKEND=sqlite."
            )
        if not self.seedream_model_bindings:
            family = self.seedream_model_family.strip().lower()
            if not family:
                if self.seedream_default_model == "dola-seedream-5-5-261028":
                    family = SeedreamFamily.SEEDREAM_5_5
                elif self.seedream_default_model == "dola-seedream-5-0-pro-260628":
                    family = SeedreamFamily.PRO
                else:
                    raise ValueError(
                        "A custom SEEDREAM_DEFAULT_MODEL requires "
                        "SEEDREAM_MODEL_FAMILY or SEEDREAM_MODEL_BINDINGS."
                    )
            self.seedream_model_bindings = [
                ImageModelBinding(
                    model_id=self.seedream_default_model,
                    family=SeedreamFamily(family),
                )
            ]

        if not self.seedance_model_bindings:
            family = self.seedance_model_family.strip().lower()
            if not family:
                if self.seedance_default_model == "dreamina-seedance-2-0-260128":
                    family = SeedanceFamily.STANDARD
                elif self.seedance_default_model == "dreamina-seedance-2-5-260628":
                    family = SeedanceFamily.SEEDANCE_2_5
                elif self.seedance_default_model == SEEDANCE_2_5_FLASH_MODEL_ID:
                    family = SeedanceFamily.SEEDANCE_2_5_FLASH
                else:
                    raise ValueError(
                        "A custom SEEDANCE_DEFAULT_MODEL requires "
                        "SEEDANCE_MODEL_FAMILY or SEEDANCE_MODEL_BINDINGS."
                    )
            self.seedance_model_bindings = [
                VideoModelBinding(
                    model_id=self.seedance_default_model,
                    family=SeedanceFamily(family),
                )
            ]
            if self.seedance_default_model != SEEDANCE_2_5_FLASH_MODEL_ID:
                self.seedance_model_bindings.append(
                    VideoModelBinding(
                        model_id=SEEDANCE_2_5_FLASH_MODEL_ID,
                        family=SeedanceFamily.SEEDANCE_2_5_FLASH,
                    )
                )

        for label, bindings, default_model in (
            ("Seedream", self.seedream_model_bindings, self.seedream_default_model),
            ("Seedance", self.seedance_model_bindings, self.seedance_default_model),
        ):
            ids = [binding.model_id for binding in bindings]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} model bindings contain duplicate IDs.")
            if default_model not in ids:
                raise ValueError(
                    f"{label} default model '{default_model}' is missing from its bindings. "
                    f"Set the default model env var to one of the bound IDs: {ids}."
                )
        if self.artifact_ttl_seconds <= 0:
            raise ValueError("ARTIFACT_TTL_SECONDS must be positive")
        if self.mcp_inline_media_max_bytes <= 0:
            raise ValueError("MCP_INLINE_MEDIA_MAX_BYTES must be positive")
        if self.mcp_http_max_body_bytes <= 0:
            raise ValueError("MCP_HTTP_MAX_BODY_BYTES must be positive")
        if self.connect_timeout_ms <= 0 or self.request_timeout_ms <= 0:
            raise ValueError("Provider timeouts must be positive")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"Invalid MCP allowed origin: '{origin}'")
        if self.mcp_transport == "http":
            if self.daily_budget_usd:
                raise ValueError(
                    "Stateless HTTP requires DAILY_BUDGET_USD=0; enforce spend limits at the provider."
                )
            if self.mcp_auth_mode is not AuthMode.BYOK:
                raise ValueError(
                    "HTTP requires MCP_AUTH_MODE=byok; shared-key auth is not supported."
                )
            if not re.fullmatch(r"[a-f0-9]{64}", self.identity_hmac_key.get_secret_value()):
                raise ValueError(
                    "HTTP requires MCP_IDENTITY_HMAC_KEY: 32 random bytes as lowercase hex."
                )
            if self.rate_limit_rpm <= 0:
                raise ValueError("HTTP requires a positive RATE_LIMIT_RPM.")
            official_urls = (
                (self.modelark_base_url, "https://ark.ap-southeast.bytepluses.com/api/v3"),
                (self.seed_audio_base_url, "https://voice.ap-southeast-1.bytepluses.com"),
                (self.cv_base_url, "https://openapi.cv.bytepluses.com"),
            )
            if any(actual != expected for actual, expected in official_urls):
                raise ValueError("HTTP BYOK requires the fixed official provider base URLs.")
            if self.readiness_check_providers:
                raise ValueError(
                    "HTTP readiness must not call providers with operator credentials."
                )
        if self.tos_credential_mode == "irsa":
            if self.mcp_transport != "http" or not self.temporary_upload_enabled:
                raise ValueError("TOS_CREDENTIAL_MODE=irsa requires HTTP temporary uploads.")
            if self.tos_access_key or self.tos_secret_key or self.tos_security_token:
                raise ValueError("IRSA cannot be combined with static TOS credentials.")
            if not re.fullmatch(
                r"trn:iam::[0-9]+:role/[A-Za-z0-9+=,.@_-]{1,128}", self.tos_irsa_role_trn
            ):
                raise ValueError("TOS_IRSA_ROLE_TRN requires an exact IAM role TRN.")
            if (
                not Path(self.tos_irsa_token_file).is_absolute()
                or ".." in Path(self.tos_irsa_token_file).parts
            ):
                raise ValueError("TOS_IRSA_TOKEN_FILE requires an absolute projected-token path.")
        elif self.tos_irsa_role_trn or self.tos_irsa_token_file:
            raise ValueError("IRSA role/token configuration requires TOS_CREDENTIAL_MODE=irsa.")
        if bool(self.tos_access_key) != bool(self.tos_secret_key):
            raise ValueError("TOS_ACCESS_KEY and TOS_SECRET_KEY must both be set or both be empty.")
        if self.tos_access_key and not self.tos_endpoint:
            raise ValueError("TOS_ENDPOINT is required when TOS credentials are set.")
        if self.temporary_upload_enabled:
            if (
                self.mcp_transport != "http"
                or self.object_storage_backend != "tos"
                or not self.has_tos
                or not self.upload_client_digests
            ):
                raise ValueError(
                    "MCP_TEMPORARY_UPLOAD_ENABLED requires HTTP, OBJECT_STORAGE_BACKEND=tos, "
                    "TOS credentials/bucket and a nonempty MCP_UPLOAD_CLIENT_SECRET_SHA256 allowlist."
                )
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.tos_bucket):
                raise ValueError(
                    "Temporary uploads require a valid 3-63 character TOS bucket name."
                )
            if not re.fullmatch(r"[a-z]+(?:-[a-z]+)+-[0-9]+", self.tos_region):
                raise ValueError("Temporary uploads require a valid TOS_REGION.")
            official_host = f"tos-{self.tos_region}.bytepluses.com"
            if self.tos_endpoint not in {official_host, f"https://{official_host}"}:
                raise ValueError(
                    "Temporary uploads require the exact official HTTPS TOS regional endpoint."
                )
        if bool(self.s3_access_key) != bool(self.s3_secret_key):
            raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY must both be set or both be empty.")
        if self.s3_access_key and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when S3 credentials are set.")
        if self.object_storage_backend == "s3" and not self.has_s3:
            raise ValueError(
                "OBJECT_STORAGE_BACKEND=s3 requires S3_ACCESS_KEY, S3_SECRET_KEY, and S3_BUCKET."
            )
        if self.object_storage_backend == "tos" and self.has_s3 and not self.has_tos:
            raise ValueError(
                "OBJECT_STORAGE_BACKEND=tos but TOS credentials are missing while S3 "
                "credentials are set. Set OBJECT_STORAGE_BACKEND=s3 or provide TOS_*."
            )
        if self.artifact_backend == "object_storage" and not self.has_object_storage:
            raise ValueError("ARTIFACT_BACKEND=object_storage requires TOS_* or S3_* credentials.")
        return self


@lru_cache(maxsize=1)
def _process_settings() -> Settings:
    return Settings()


_request_settings: ContextVar[Settings | None] = ContextVar("request_settings", default=None)


class SettingsResolver:
    """Resolve immutable server configuration without mutating process defaults."""

    def __call__(self) -> Settings:
        return _request_settings.get() or _process_settings()

    def cache_clear(self) -> None:
        _process_settings.cache_clear()


get_settings = SettingsResolver()


@contextmanager
def settings_scope(settings: Settings) -> Iterator[None]:
    token = _request_settings.set(settings)
    try:
        yield
    finally:
        _request_settings.reset(token)


def has_request_settings() -> bool:
    return _request_settings.get() is not None


def refresh_settings() -> Settings:
    """Force-reload settings from environment (e.g. after config change)."""
    get_settings.cache_clear()
    return get_settings()


def validate() -> None:
    """Validate required environment variables at startup.

    Called by ``make check-env``.  Raises if essential configuration is
    missing or invalid.  Provider credentials are optional (the server
    degrades gracefully by not registering tools for absent credentials),
    but base URLs and model bindings must be syntactically valid.
    """
    settings = get_settings()
    if not settings.modelark_base_url.startswith("https://"):
        raise ValueError("BYTEPLUS_MODELARK_BASE_URL must use HTTPS")
    if not settings.seed_audio_base_url.startswith("https://"):
        raise ValueError("BYTEPLUS_SEED_AUDIO_BASE_URL must use HTTPS")
    if settings.artifact_ttl_seconds <= 0:
        raise ValueError("ARTIFACT_TTL_SECONDS must be positive")
    if settings.mcp_inline_media_max_bytes <= 0:
        raise ValueError("MCP_INLINE_MEDIA_MAX_BYTES must be positive")
