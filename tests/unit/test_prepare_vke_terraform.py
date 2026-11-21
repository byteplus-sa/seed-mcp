"""Preparation cannot reuse state, inherit credentials or execute a live plan."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts import prepare_vke_terraform as script


def test_preparation_copies_only_reviewed_source_and_unset_operator_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "root"
    source.mkdir()
    for name in script.SOURCE_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((script.ROOT / name).read_bytes())
    for name in ("terraform.tfstate", "operator.tfvars", ".env", "review.tfplan"):
        (source / name).write_text("must not copy")
    (source / ".terraform").mkdir()
    monkeypatch.setattr(script, "ROOT", source)
    execute = Mock(side_effect=AssertionError("Preparation must not execute commands."))
    monkeypatch.setattr(script.subprocess, "run", execute)

    destination = tmp_path / "staging"
    assert script.main(["prepare", str(destination)]) == 0
    expected = {*script.SOURCE_FILES, "terraform.tfvars"}
    assert {
        str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
    } == expected
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    for path in destination.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    inputs = (destination / "terraform.tfvars").read_text()
    assert "fresh_state_confirmed = false" in inputs
    for field, value in (("node_count", "2"), ("burst_node_max_count", "0")):
        assert any(
            line.split("=")[1].strip() == value
            for line in inputs.splitlines()
            if line.startswith(field)
        )
    for field in (
        "zone_id",
        "kubernetes_version",
        "node_instance_type",
        "gateway_secondary_zone_id",
    ):
        assert any(
            line.split("=")[1].strip() == '""'
            for line in inputs.splitlines()
            if line.startswith(field)
        )
    assert "gateway.tf" in script.SOURCE_FILES
    assert any(
        line.split("=")[1].strip() == "false"
        for line in inputs.splitlines()
        if line.startswith("public_gateway_enabled")
    )
    assert "remain unset" in capsys.readouterr().out
    execute.assert_not_called()


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_preparation_never_replaces_existing_paths(tmp_path: Path, kind: str) -> None:
    retained = tmp_path / "retained"
    retained.mkdir()
    marker = retained / "terraform.tfstate"
    marker.write_text("existing unrelated state")
    destination = tmp_path / "staging"
    if kind == "directory":
        destination.mkdir()
        (destination / "marker").write_text("retained")
    elif kind == "file":
        destination.write_text("retained")
    else:
        destination.symlink_to(retained)
    before = destination.lstat()
    assert script.main(["prepare", str(destination)]) == 1
    after = destination.lstat()
    assert (before.st_ino, before.st_mode, before.st_mtime_ns) == (
        after.st_ino,
        after.st_mode,
        after.st_mtime_ns,
    )
    assert marker.read_text() == "existing unrelated state"


@pytest.mark.parametrize("mode", [0o750, 0o755, 0o777])
def test_preparation_refuses_nonprivate_parent(tmp_path: Path, mode: int) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=mode)
    parent.chmod(mode)
    assert script.main(["prepare", str(parent / "staging")]) == 1
    assert list(parent.iterdir()) == []
    assert stat.S_IMODE(parent.stat().st_mode) == mode


def test_preparation_refuses_relative_and_symlink_parent_paths(tmp_path: Path) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert script.main(["prepare", "relative-staging"]) == 1
    assert script.main(["prepare", str(alias / "staging")]) == 1
    assert not (tmp_path / "staging").exists()


def test_preparation_refuses_symlink_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "root"
    source.mkdir()
    retained = tmp_path / "retained"
    retained.write_text("do not copy")
    (source / "main.tf").symlink_to(retained)
    monkeypatch.setattr(script, "ROOT", source)
    destination = tmp_path / "staging"
    assert script.main(["prepare", str(destination)]) == 1
    assert list(destination.iterdir()) == []
    assert retained.read_text() == "do not copy"


def test_validation_isolates_source_environment_and_all_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "terraform"
    monkeypatch.setattr(script.shutil, "which", lambda _: str(executable))
    for name in (
        "BYTEPLUS_ACCESS_KEY",
        "BYTEPLUS_SECRET_KEY",
        "BYTEPLUS_SESSION_TOKEN",
        "BYTEPLUS_MODELARK_API_KEY",
        "TF_VAR_node_count",
        "TF_CLI_ARGS",
        "TF_CLI_ARGS_test",
        "TF_CLI_CONFIG_FILE",
        "TF_WORKSPACE",
        "TF_PLUGIN_CACHE_DIR",
        "TF_TOKEN_app_terraform_io",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "must-not-forward")
    calls = []

    def execute(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(options["cwd"]))
        env = options["env"]
        assert isinstance(env, dict)
        assert all("must-not-forward" not in str(value) for value in env.values())
        assert set(env) == {
            "PATH",
            "HOME",
            "TMPDIR",
            "TF_DATA_DIR",
            "TF_IN_AUTOMATION",
            "TF_INPUT",
            "CHECKPOINT_DISABLE",
        }
        assert Path(env["HOME"]).is_dir()
        assert not (cwd / "terraform.tfvars").exists()
        assert not (cwd / "seed-mcp-vke.tfstate").exists()
        assert (cwd / "tests/deployment.tftest.hcl").is_file()
        assert (cwd / ".terraform.lock.hcl").read_bytes() == (
            script.ROOT / ".terraform.lock.hcl"
        ).read_bytes()
        assert options["check"] is True
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({"terraform_version": "1.17.1"}))

    monkeypatch.setattr(script.subprocess, "run", execute)
    assert script.main(["validate", "--terraform-bin", str(executable)]) == 0
    assert [command[1:] for command in calls] == [
        ["version", "-json"],
        ["fmt", "-check", "-recursive"],
        ["init", "-backend=false", "-input=false", "-lockfile=readonly", "-no-color"],
        ["validate", "-no-color"],
        ["test", "-no-color"],
    ]
    assert all(command[0] == str(executable) for command in calls)


@pytest.mark.parametrize("version", ["1.16.0", "1.17.0", "2.0.0", "1.18.0-beta1", "invalid"])
def test_validation_rejects_unsupported_versions_before_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda _: str(tmp_path / "terraform"))
    execute = Mock(
        return_value=subprocess.CompletedProcess([], 0, json.dumps({"terraform_version": version}))
    )
    monkeypatch.setattr(script.subprocess, "run", execute)
    assert script.main(["validate"]) == 1
    assert execute.call_count == 1


def test_validation_missing_binary_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda _: None)
    execute = Mock()
    monkeypatch.setattr(script.subprocess, "run", execute)
    assert script.main(["validate"]) == 1
    execute.assert_not_called()


@pytest.mark.parametrize("output", ["not-json", "[]", "null", '{"terraform_version": 1171}'])
def test_validation_rejects_malformed_version_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda _: str(tmp_path / "terraform"))
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, output))
    monkeypatch.setattr(script.subprocess, "run", execute)
    assert script.main(["validate"]) == 1
    assert execute.call_count == 1


@pytest.mark.parametrize("failure", ["failed", "timeout"])
def test_validation_stops_without_retry_and_bounds_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    monkeypatch.setattr(script.shutil, "which", lambda _: str(tmp_path / "terraform"))
    error = (
        subprocess.CalledProcessError(1, ["private-canary"], output="private-canary")
        if failure == "failed"
        else subprocess.TimeoutExpired(["private-canary"], 30, output="private-canary")
    )
    execute = Mock(side_effect=error)
    monkeypatch.setattr(script.subprocess, "run", execute)
    assert script.main(["validate"]) == 1
    assert "private-canary" not in capsys.readouterr().err
    assert execute.call_count == 1


def test_cli_has_no_live_or_destructive_commands(tmp_path: Path) -> None:
    for command in ("plan", "apply", "destroy", "import"):
        with pytest.raises(SystemExit) as exc:
            script.main([command])
        assert exc.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_version_floor_matches_root_contract() -> None:
    assert 'required_version = ">= 1.17.1, < 2.0.0"' in (script.ROOT / "versions.tf").read_text()
    assert script.MIN_TERRAFORM == (1, 17, 1)


def test_only_burst_live_desired_count_is_ignored() -> None:
    source = (script.ROOT / "main.tf").read_text()
    baseline, burst = source.split('resource "bytepluscc_vke_node_pool" "burst"', 1)
    assert "ignore_changes" not in baseline
    assert burst.count("ignore_changes") == 1
    assert "ignore_changes = [auto_scaling.desired_replicas]" in burst
    assert "node_config = local.worker_node_config" in baseline
    assert "node_config = local.worker_node_config" in burst
