"""Behavioral tests for the protected deployment workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts.byteplus_deploy.private import make_configuration_values, replace_provider_keys
from scripts.byteplus_deploy.workspace import Workspace, read_private, validate_config

SYNTHETIC_PROVIDER = "test-key"


@pytest.fixture
def deployment_config() -> dict[str, object]:
    return {
        "name": "team-demo",
        "region": "ap-southeast-1",
        "zone_id": "ap-southeast-1a",
        "image_id": "image-demo",
        "instance_type": "ecs.c3i.large",
        "key_pair_name": "demo-public-key",
        "ark_mcp_image": "ghcr.io/example/ark-mcp@sha256:" + "a" * 64,
    }


def test_minimum_defaults_keep_ssh_closed(deployment_config: dict[str, object]) -> None:
    config = validate_config(deployment_config)
    assert config["data_disk_size_gib"] == 40
    assert config["admin_cidrs"] == []
    assert config["public_hostname"] is None
    assert config["instance_deletion_protection"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("name", "../escape"),
        ("region", "localhost/evil"),
        ("zone_id", "another-region-a"),
        ("admin_cidrs", ["0.0.0.0/0"]),
        ("data_disk_size_gib", True),
        ("data_disk_size_gib", 39),
        ("public_hostname", ""),
        ("ark_mcp_image", "ghcr.io/example/ark-mcp:latest"),
        ("BYTEPLUS_MODELARK_API_KEY", "synthetic-secret"),
        ("instance_deletion_protection", False),
        ("existing_vpc_id", "vpc-unapproved"),
    ],
)
def test_invalid_configuration_is_rejected_without_echoing_values(
    deployment_config: dict[str, object], key: str, value: object
) -> None:
    deployment_config[key] = value
    with pytest.raises(ValueError) as error:
        validate_config(deployment_config)
    assert "synthetic-secret" not in str(error.value)


def test_workspace_creation_preserves_source_and_protects_files(
    deployment_config: dict[str, object], tmp_path: Path
) -> None:
    workspace = Workspace.create(tmp_path / "deployment", validate_config(deployment_config))
    assert workspace.path.stat().st_mode & 0o777 == 0o700
    assert (workspace.path / "config.json").stat().st_mode & 0o777 == 0o600
    assert (workspace.module / ".terraform.lock.hcl").exists()
    assert not list((workspace.path / "source").rglob("terraform.tfstate"))
    assert not list((workspace.path / "source").rglob(".env"))
    assert not (workspace.path / "source/src").exists()
    assert (workspace.path / "source/scripts/byteplus_deploy/signing.py").is_file()
    with pytest.raises(FileExistsError):
        Workspace.create(workspace.path, validate_config(deployment_config))


def test_new_configuration_keeps_omnihuman_but_drops_retired_products() -> None:
    payload, _ = make_configuration_values(
        {
            "BYTEPLUS_MODELARK_API_KEY": SYNTHETIC_PROVIDER,
            "BYTEPLUS_SEED_SPEECH_API_KEY": SYNTHETIC_PROVIDER,
            "BYTEPLUS_CV_API_KEY": SYNTHETIC_PROVIDER,
            "BYTEPLUS_OMNIHUMAN_ENABLED": "true",
            "BYTEPLUS_VOD_MEDIAKIT_API_KEY": SYNTHETIC_PROVIDER,
            "BYTEPLUS_MODELARK_3D_ENABLED": "true",
        },
        "mcp.team.test",
    )
    values = dict(line.split("=", 1) for line in payload.decode().splitlines())
    assert values["BYTEPLUS_OMNIHUMAN_ENABLED"] == "true"
    assert values["BYTEPLUS_CV_API_KEY"] == SYNTHETIC_PROVIDER
    assert values["BYTEPLUS_SEED_SPEECH_API_KEY"] == SYNTHETIC_PROVIDER
    assert values["MCP_AUTH_MODE"] == "api_key"
    assert values["ARTIFACT_BACKEND"] == "filesystem"
    assert not any(key.startswith("BYTEPLUS_VOD_") for key in values)
    assert "BYTEPLUS_MODELARK_3D_ENABLED" not in values


def test_provider_rotation_preserves_storage_credentials_and_shared_state() -> None:
    retained_values = dict.fromkeys(
        ("TOS_ACCESS_KEY", "TOS_SECRET_KEY", "S3_ACCESS_KEY", "S3_SECRET_KEY"),
        SYNTHETIC_PROVIDER,
    )
    retained_values.update(
        MCP_API_KEY_SHA256="a" * 64,
        FASTMCP_TASKS_ENCRYPTION_KEY="test-key-" * 8,
        ARTIFACT_BACKEND="object_storage",
    )
    retained = "".join(f"{key}={value}\n" for key, value in retained_values.items()).encode()
    payload = replace_provider_keys(
        retained + f"BYTEPLUS_MODELARK_API_KEY={SYNTHETIC_PROVIDER}\n".encode(),
        {"BYTEPLUS_CV_API_KEY": SYNTHETIC_PROVIDER},
    )
    assert payload.startswith(retained)
    values = dict(line.split("=", 1) for line in payload.decode().splitlines())
    assert values["BYTEPLUS_MODELARK_API_KEY"] == ""
    assert values["BYTEPLUS_SEED_SPEECH_API_KEY"] == ""
    assert values["BYTEPLUS_CV_API_KEY"] == SYNTHETIC_PROVIDER
    assert "BYTEPLUS_VOD_MEDIAKIT_API_KEY" not in values


def test_private_input_rejects_symlink_fifo_and_wrong_mode(tmp_path: Path) -> None:
    private = tmp_path / "secret"
    private.write_text("synthetic")
    with pytest.raises(ValueError):
        read_private(private)
    private.chmod(0o600)
    assert read_private(private) == b"synthetic"
    link = tmp_path / "link"
    link.symlink_to(private)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    for path in (link, fifo):
        with pytest.raises((OSError, ValueError)):
            read_private(path)


def test_journal_survives_reopen_and_second_writer_is_rejected(
    deployment_config: dict[str, object], tmp_path: Path
) -> None:
    workspace = Workspace.create(tmp_path / "deployment", validate_config(deployment_config))
    with workspace.lock():
        workspace.save_journal({"version": 1, "operations": {"prepare": {"id": "ivk-demo"}}})
        with pytest.raises(ValueError, match="in use"), workspace.lock():
            pass
    reopened = Workspace(workspace.path)
    assert reopened.journal()["operations"]["prepare"]["id"] == "ivk-demo"
    assert json.loads(read_private(workspace.path / "journal.json"))["version"] == 1


def test_fingerprint_excludes_terraform_runtime_but_detects_source_changes(
    deployment_config: dict[str, object], tmp_path: Path
) -> None:
    workspace = Workspace.create(tmp_path / "deployment", deployment_config)
    original = workspace.fingerprint()
    (workspace.module / ".terraform").mkdir()
    (workspace.module / ".terraform/provider").write_text("cache")
    (workspace.module / "terraform.tfstate").write_text("runtime state")
    (workspace.module / "terraform.tfvars.json").write_text("{}")
    assert workspace.fingerprint() == original
    source = workspace.module / "outputs.tf"
    source.write_text(source.read_text() + "\n")
    assert workspace.fingerprint() != original
    (workspace.module / "unexpected.tf").write_text("")
    with pytest.raises(ValueError, match="Unexpected"):
        workspace.fingerprint()


def test_fingerprint_rejects_source_symlink(
    deployment_config: dict[str, object], tmp_path: Path
) -> None:
    workspace = Workspace.create(tmp_path / "deployment", deployment_config)
    source = workspace.module / "outputs.tf"
    source.unlink()
    source.symlink_to(tmp_path / "outside")
    with pytest.raises((ValueError, OSError)):
        workspace.fingerprint()


def test_fingerprint_rejects_modified_frozen_infrastructure_signer(
    deployment_config: dict[str, object], tmp_path: Path
) -> None:
    workspace = Workspace.create(tmp_path / "deployment", deployment_config)
    signer = workspace.path / "source/scripts/byteplus_deploy/signing.py"
    signer.write_text(signer.read_text() + "\n")
    with pytest.raises(ValueError, match="CLI or signer changed"):
        workspace.fingerprint()
