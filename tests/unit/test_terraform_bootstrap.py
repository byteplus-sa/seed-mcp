"""Offline checks for the BytePlus host activation boundary."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "terraform" / "byteplus" / "scripts"


@pytest.fixture
def validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ark_host_environment", SCRIPTS / "check_env.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def configured_environment() -> dict[str, str]:
    return {
        "MCP_PUBLIC_HOST": "mcp.team.test",
        "MCP_IDENTITY_HMAC_KEY": "a" * 64,
        "MCP_IDENTITY_KEY_VERSION": "1",
        "DAILY_BUDGET_USD": "25",
        "RATE_LIMIT_RPM": "60",
        "MCP_HTTP_MAX_IN_FLIGHT": "64",
        "MCP_HTTP_MAX_BODY_BYTES": "2097152",
        "STATE_MAX_RECORDS": "100000",
        "STATE_PRUNE_MAX_AGE_DAYS": "30",
        "RATE_LIMIT_BURST": "30",
        "PRINCIPAL_MAX_CONCURRENCY": "3",
        "PROVIDER_MAX_CONCURRENCY": "5",
    }


def test_valid_environment_round_trip(
    validator: ModuleType, configured_environment: dict[str, str], tmp_path: Path
) -> None:
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{key}='{value}'" for key, value in configured_environment.items()))
    path.chmod(0o600)
    values = validator.load_environment(path, expected_uid=os.getuid())
    assert values == configured_environment
    validator.validate_environment(values)


def test_byok_environment_is_the_host_default(
    validator: ModuleType, configured_environment: dict[str, str]
) -> None:
    assert "MCP_AUTH_MODE" not in configured_environment
    validator.validate_environment(configured_environment)


def test_host_accepts_only_operator_identity_secrets(validator: ModuleType) -> None:
    assert set(validator.IDENTITY_SETTINGS) == {
        "MCP_IDENTITY_HMAC_KEY",
        "MCP_IDENTITY_KEY_VERSION",
    }


def test_removed_vod_key_cannot_enable_host(
    validator: ModuleType, configured_environment: dict[str, str]
) -> None:
    synthetic_provider = "test-key"
    configured_environment["BYTEPLUS_VOD_MEDIAKIT_API_KEY"] = synthetic_provider
    with pytest.raises(ValueError, match="only operator"):
        validator.validate_environment(configured_environment)


@pytest.mark.parametrize("filename", [".env.example", "deploy/compose/.env.example"])
def test_environment_templates_keep_retained_services_only(filename: str) -> None:
    values = {
        line.partition("=")[0]
        for line in (ROOT / filename).read_text().splitlines()
        if line and line[0].isupper() and "=" in line
    }
    assert {
        "BYTEPLUS_OMNIHUMAN_ENABLED",
        "MCP_IDENTITY_HMAC_KEY",
        "MCP_IDENTITY_KEY_VERSION",
        "STATE_MAX_RECORDS",
        "MCP_HTTP_MAX_IN_FLIGHT",
    } <= values
    if filename.startswith("deploy/"):
        assert not any("API_KEY" in key for key in values)
    assert not any(
        key.startswith(("BYTEPLUS_VOD_", "SEED3D_", "HYPER3D_", "HITEM3D_", "SEED_SPEECH_ASR_"))
        or key
        in {
            "BYTEPLUS_MODELARK_ACCESS_KEY",
            "BYTEPLUS_MODELARK_SECRET_KEY",
            "BYTEPLUS_MODELARK_SESSION_TOKEN",
            "BYTEPLUS_MODELARK_OPENAPI_BASE_URL",
            "BYTEPLUS_MODELARK_REGION",
            "BYTEPLUS_MODELARK_PROJECT_NAME",
            "BYTEPLUS_MODELARK_PRICING_REFRESH_SECONDS",
            "BYTEPLUS_MODELARK_3D_ENABLED",
            "SEEDANCE_ASSET_PREFLIGHT",
        }
        or key.startswith("BYTEPLUS_MODELARK_ASSET")
        for key in values
    )


@pytest.mark.parametrize(
    ("mode", "digest"),
    [
        ("local", "a" * 64),
        ("jwt", "a" * 64),
        ("unknown", "a" * 64),
        ("api_key", "a" * 64),
        ("byok", ""),
        ("byok", "invalid"),
        ("byok", "A" * 64),
        ("api_key", ""),
        ("api_key", "invalid"),
        ("api_key", "A" * 64),
    ],
)
def test_host_rejects_unsafe_auth_configuration(
    validator: ModuleType,
    configured_environment: dict[str, str],
    mode: str,
    digest: str,
) -> None:
    configured_environment.update(MCP_AUTH_MODE=mode, MCP_IDENTITY_HMAC_KEY=digest)
    with pytest.raises(ValueError):
        validator.validate_environment(configured_environment)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MCP_PUBLIC_HOST", "mcp.example.com"),
        ("MCP_IDENTITY_HMAC_KEY", ""),
        ("MCP_IDENTITY_KEY_VERSION", "0"),
        ("REDIS_PASSWORD", "invalid:/"),
        ("FASTMCP_TASKS_ENCRYPTION_KEY", "short"),
        ("BYTEPLUS_MODELARK_API_KEY", ""),
        ("DAILY_BUDGET_USD", "0"),
        ("DAILY_BUDGET_USD", "nan"),
        ("DAILY_BUDGET_USD", "inf"),
        ("RATE_LIMIT_RPM", "1.5"),
        ("PRINCIPAL_MAX_CONCURRENCY", "-1"),
    ],
)
def test_invalid_host_settings_fail_closed(
    validator: ModuleType, configured_environment: dict[str, str], key: str, value: str
) -> None:
    configured_environment[key] = value
    with pytest.raises(ValueError):
        validator.validate_environment(configured_environment)


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_environment_rejects_wrong_permissions(
    validator: ModuleType, tmp_path: Path, mode: int
) -> None:
    path = tmp_path / ".env"
    path.write_text("VALUE=test")
    path.chmod(mode)
    with pytest.raises(ValueError, match="0600"):
        validator.load_environment(path, expected_uid=os.getuid())


def test_environment_rejects_symlinks_and_missing_files(
    validator: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.write_text("VALUE=test")
    target.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    for path in (link, tmp_path / "missing"):
        with pytest.raises(OSError):
            validator.load_environment(path, expected_uid=os.getuid())


def test_environment_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    os.mkfifo(path, 0o600)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_env.py"), str(path)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "regular file" in result.stderr


def test_environment_rejects_wrong_owner(validator: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("VALUE=test")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="root-owned"):
        validator.load_environment(path, expected_uid=os.getuid() + 1)


@pytest.mark.parametrize("body", ["VALUE=a\nVALUE=b", "VALUE=$(id)", "export VALUE=x", "x" * 65537])
def test_environment_rejects_ambiguous_or_oversized_input(
    validator: ModuleType, tmp_path: Path, body: str
) -> None:
    path = tmp_path / ".env"
    path.write_text(body)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        validator.load_environment(path, expected_uid=os.getuid())


def test_malformed_hmac_does_not_echo_credentials(
    validator: ModuleType, configured_environment: dict[str, str]
) -> None:
    invalid_value = "private-value"
    configured_environment["MCP_IDENTITY_HMAC_KEY"] = invalid_value
    with pytest.raises(ValueError) as error:
        validator.validate_environment(configured_environment)
    assert invalid_value not in str(error.value)


def test_activate_runs_only_after_preflight_checks(tmp_path: Path) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "operations"
    for name in ("id", "mountpoint", "python3", "install", "docker", "systemctl"):
        executable = commands / name
        body = "printf '0\\n'" if name == "id" else 'printf "%s\\n" "$0 $*" >> "$COMMAND_LOG"'
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o700)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "activate.sh")],
        env={**os.environ, "PATH": f"{commands}:/usr/bin:/bin", "COMMAND_LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    operations = log.read_text()
    assert operations.index("mountpoint") < operations.index("check_env.py")
    assert operations.index("check_env.py") < operations.index("config --quiet")
    assert operations.index("config --quiet") < operations.index("restart ark-mcp.service")
    assert "-o 1001 -g 1001 /srv/ark-mcp/byok-state" in operations
    assert "redis" not in operations


def test_activate_refuses_to_start_without_persistent_mount(tmp_path: Path) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    for name, body in {
        "id": "printf '0\\n'",
        "mountpoint": "exit 1",
        "docker": "echo 'UNEXPECTED_DOCKER_CALL'; exit 91",
        "systemctl": "echo 'UNEXPECTED_SYSTEMCTL_CALL'; exit 92",
    }.items():
        executable = commands / name
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o700)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "activate.sh")],
        env={**os.environ, "PATH": f"{commands}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "persistent" in result.stderr.lower()
    assert "UNEXPECTED_" not in result.stdout
    assert "UNEXPECTED_" not in result.stderr


def test_activate_does_not_start_services_when_environment_check_fails(tmp_path: Path) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    for name, body in {
        "id": "printf '0\\n'",
        "mountpoint": "exit 0",
        "python3": "echo 'Configuration rejected' >&2; exit 1",
        "install": "echo 'UNEXPECTED_DIRECTORY_WRITE'; exit 91",
        "docker": "echo 'UNEXPECTED_DOCKER_CALL'; exit 92",
        "systemctl": "echo 'UNEXPECTED_SYSTEMCTL_CALL'; exit 93",
    }.items():
        executable = commands / name
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o700)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "activate.sh")],
        env={**os.environ, "PATH": f"{commands}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Configuration rejected" in result.stderr
    assert "UNEXPECTED_" not in result.stdout + result.stderr


@pytest.mark.parametrize("filename", ["activate.sh", "install.sh"])
def test_host_scripts_have_valid_bash_syntax(filename: str) -> None:
    subprocess.run(["bash", "-n", str(SCRIPTS / filename)], check=True)


def test_host_bootstrap_never_formats_or_executes_secret_files() -> None:
    for path in SCRIPTS.glob("*.sh"):
        content = path.read_text()
        assert "mkfs" not in content
        assert "wipefs" not in content
        assert "source " not in content
        assert "set -x" not in content
        assert "curl " not in content


def test_docker_and_application_wait_for_persistent_storage() -> None:
    for filename in ("docker-storage.conf", "ark-mcp.service"):
        content = (SCRIPTS / filename).read_text()
        assert "RequiresMountsFor=/srv/ark-mcp" in content
        assert "ExecStartPre=/usr/bin/mountpoint -q /srv/ark-mcp" in content
        assert (
            "ExecStartPre=/usr/bin/python3 /opt/ark-mcp/check_env.py /srv/ark-mcp/config/.env"
            in content
        )
        assert content.index("ExecStartPre=/usr/bin/mountpoint") < content.index(
            "ExecStartPre=/usr/bin/python3"
        )
    content = (SCRIPTS / "ark-mcp.service").read_text()
    assert "--no-build" in content
    assert "TimeoutStopSec=720" in content


def test_installer_is_retryable_but_does_not_start_unconfigured_stack() -> None:
    content = (SCRIPTS / "ark-mcp-install.service").read_text()
    assert "Restart=on-failure" in content
    assert "RestartSec=30" in content
    installer = (SCRIPTS / "install.sh").read_text()
    assert "VERSION_ID" in installer
    assert "24.04" in installer
    assert "amd64" in installer
    assert "systemctl start ark-mcp" not in installer


def test_terraform_ci_runs_mocked_plans_with_runner_scoped_provider_cache() -> None:
    content = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    workflow = yaml.load(content, Loader=yaml.BaseLoader)
    assert all("runner." not in value for value in workflow["env"].values())
    job = workflow["jobs"]["validate"]
    assert all("runner." not in value for value in job.get("env", {}).values())
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert 'printf \'TF_DATA_DIR=%s/ark-terraform\\n\' "$RUNNER_TEMP" >> "$GITHUB_ENV"' in (
        commands
    )
    assert "terraform -chdir=deploy/terraform/byteplus test -no-color" in commands
    assert "init -backend=false -input=false -lockfile=readonly" in commands
    assert "sha256sum --check" in commands
    assert "secrets." not in content
    for event in ("pull_request", "push"):
        assert "deploy/terraform/**" in workflow["on"][event]["paths"]
        assert "deploy/compose/**" in workflow["on"][event]["paths"]
