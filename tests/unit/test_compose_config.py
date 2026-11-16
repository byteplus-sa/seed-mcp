"""Offline deployment invariants for the single-instance BYOK Compose kit."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ark_mcp.config.env import Settings


def test_application_stop_grace_exceeds_default_request_timeout() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "deploy/compose/compose.yaml").read_text())
    grace = compose["services"]["ark-mcp"].get("stop_grace_period")
    assert grace is not None
    assert grace.endswith("s")
    seconds = int(grace[:-1])
    assert seconds >= Settings(_env_file=None).request_timeout_ms / 1000 + 60


def test_compose_cli_renders_only_operator_settings() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is not installed.")
    version = subprocess.run([docker, "compose", "version"], capture_output=True, check=False)
    if version.returncode:
        pytest.skip("Docker Compose plugin is not installed.")
    root = Path(__file__).resolve().parents[2]
    synthetic_provider = "test-key"
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "MCP_PUBLIC_HOST": "mcp.team.test",
        "MCP_IDENTITY_HMAC_KEY": "a" * 64,
        "BYTEPLUS_MODELARK_API_KEY": synthetic_provider,
        "BYTEPLUS_SEED_SPEECH_API_KEY": synthetic_provider,
        "BYTEPLUS_CV_API_KEY": synthetic_provider,
        "FASTMCP_DOCKET_URL": "redis://invalid",
        "MCP_AUTH_MODE": "local",
    }
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(root / "deploy/compose/compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    compose = json.loads(result.stdout)
    assert set(compose["services"]) == {"ark-mcp", "caddy"}
    rendered = compose["services"]["ark-mcp"]["environment"]
    assert not any("API_KEY" in key or "DOCKET" in key for key in rendered)
    assert synthetic_provider not in result.stdout
    settings = Settings(_env_file=None, **rendered)
    assert settings.mcp_auth_mode == "byok"
    assert settings.mcp_http_max_body_bytes == 2097152
    assert settings.http_max_in_flight == 64
    assert settings.rate_limit_rpm == 60
