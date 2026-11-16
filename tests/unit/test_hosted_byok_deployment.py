"""Forward-only hosted configuration checks for specs/SPEC_HOSTED_BYOK.md."""

from pathlib import Path

import pytest
import yaml
from scripts.byteplus_deploy.private import make_configuration_values, validator
from scripts.byteplus_deploy.secrets import parse_bundle

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {"MCP_IDENTITY_HMAC_KEY": "a" * 64, "MCP_IDENTITY_KEY_VERSION": "1"}
LIMITS = {
    "RATE_LIMIT_RPM": "60",
    "MCP_HTTP_MAX_IN_FLIGHT": "64",
    "MCP_HTTP_MAX_BODY_BYTES": "2097152",
    "STATE_MAX_RECORDS": "100000",
}


def test_hosted_configuration_requires_only_operator_identity() -> None:
    payload = make_configuration_values(IDENTITY, "mcp.team.test")
    values = dict(line.split("=", 1) for line in payload.decode().splitlines())
    assert values.items() >= IDENTITY.items() | LIMITS.items()
    assert values["MCP_AUTH_MODE"] == "byok"
    assert not any("API_KEY" in key or "DOCKET" in key or "REDIS" in key for key in values)
    validator().validate_environment(values)


@pytest.mark.parametrize(
    "key",
    [
        "BYTEPLUS_MODELARK_API_KEY",
        "BYTEPLUS_SEED_SPEECH_API_KEY",
        "BYTEPLUS_CV_API_KEY",
        "BYTEPLUS_VOD_MEDIAKIT_API_KEY",
        "TOS_SECRET_KEY",
        "S3_SECRET_KEY",
        "MCP_API_KEY_SHA256",
        "MCP_CLIENT_SECRET",
        "FASTMCP_DOCKET_URL",
        "FASTMCP_TASKS_ENCRYPTION_KEY",
        "REDIS_PASSWORD",
    ],
)
@pytest.mark.parametrize("value", ["", "synthetic-customer-secret"])
def test_hosted_inputs_reject_customer_and_retired_secrets(key: str, value: str) -> None:
    with pytest.raises(ValueError) as caught:
        make_configuration_values({**IDENTITY, key: value}, "mcp.team.test")
    assert value == "" or value not in str(caught.value)


@pytest.mark.parametrize("key", [*LIMITS, "MCP_IDENTITY_KEY_VERSION"])
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "1e3", "nan", "inf", ""])
def test_hosted_limits_fail_closed(key: str, value: str) -> None:
    with pytest.raises(ValueError):
        make_configuration_values({**IDENTITY, key: value}, "mcp.team.test")


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, " a" * 32])
def test_hosted_hmac_requires_lowercase_32_byte_hex(value: str) -> None:
    with pytest.raises(ValueError) as caught:
        make_configuration_values({**IDENTITY, "MCP_IDENTITY_HMAC_KEY": value}, "mcp.team.test")
    assert value == "" or value not in str(caught.value)


def test_secret_bundle_cannot_hold_customer_credentials() -> None:
    import json

    synthetic_customer = "test-key"
    assert parse_bundle(json.dumps(IDENTITY)) == IDENTITY
    with pytest.raises(ValueError):
        parse_bundle(json.dumps({**IDENTITY, "BYTEPLUS_MODELARK_API_KEY": synthetic_customer}))


def test_compose_has_explicit_operator_environment_and_no_job_backend() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose/compose.yaml").read_text())
    assert set(compose["services"]) == {"ark-mcp", "caddy"}
    app = compose["services"]["ark-mcp"]
    assert "env_file" not in app
    assert "ports" not in app
    assert app["environment"]["MCP_AUTH_MODE"] == "byok"
    assert app["environment"]["RATE_LIMIT_TRUST_PROXY_HEADERS"] == "false"
    assert not any(
        "API_KEY" in key or "DOCKET" in key or "REDIS" in key for key in app["environment"]
    )
    assert not any("redis" in volume for volume in compose["volumes"])
    assert app["environment"]["STATE_BACKEND"] == "sqlite"
    assert app["deploy"]["replicas"] == 1


def test_docker_has_byok_and_bounded_defaults() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    for key, value in {"MCP_AUTH_MODE": "byok", "MCP_IDENTITY_KEY_VERSION": "1", **LIMITS}.items():
        assert f"{key}={value}" in dockerfile
    assert "MCP_IDENTITY_HMAC_KEY=" not in dockerfile
