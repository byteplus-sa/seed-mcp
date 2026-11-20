"""Private runner delivery is explicit, fail-closed and never leaks command output."""

from __future__ import annotations

import base64
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from scripts import deploy_vke as script


@pytest.fixture
def delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], list[list[str]], Mock]:
    parent = (tmp_path / "operator").resolve()
    parent.mkdir(mode=0o700)
    for name in ("kubeconfig", "values.yaml"):
        path = parent / name
        path.write_text("private-canary")
        path.chmod(0o600)
    argv = [
        "check",
        "--kubeconfig",
        str(parent / "kubeconfig"),
        "--values",
        str(parent / "values.yaml"),
        "--context",
        "approved-context",
        "--api-server",
        "https://10.80.0.5:6443",
        "--namespace",
        "seed-mcp",
        "--image",
        "ghcr.io/byteplus-sa/seed-mcp@sha256:" + "a" * 64,
        "--public-host",
        "mcp.example.com",
        "--identity-secret",
        "seed-mcp-identity",
        "--tls-secret",
        "seed-mcp-tls",
        "--prerequisites-confirmed",
    ]
    monkeypatch.setattr(script.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        script.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.80.0.5", 6443))],
    )
    monkeypatch.setattr(script.ssl, "SSLContext", lambda _: Mock())
    calls: list[list[str]] = []

    def execute(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert options["capture_output"] is True
        assert options["check"] is True
        env = options["env"]
        assert isinstance(env, dict)
        assert not any(name in env for name in ("KUBECONFIG", "HTTPS_PROXY", "BYTEPLUS_ACCESS_KEY"))
        assert set(env) == {
            "PATH",
            "HOME",
            "LANG",
            "HELM_CACHE_HOME",
            "HELM_CONFIG_HOME",
            "HELM_DATA_HOME",
            "HELM_PLUGINS",
        }
        body: object = {}
        if "view" in command:
            body = {
                "clusters": [
                    {
                        "cluster": {
                            "server": "https://10.80.0.5:6443",
                            "certificate-authority-data": "REDACTED",
                        }
                    }
                ],
                "users": [{"user": {"token": "REDACTED"}}],
            }
        elif "version" in command:
            body = {
                "serverVersion": {"major": "1", "minor": "36"},
                "clientVersion": {"major": "1", "minor": "36"},
            }
        elif "nodes" in command:
            body = {
                "items": [
                    {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
                    {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
                ]
            }
        elif "--raw=/apis/metrics.k8s.io/v1beta1/nodes" in command:
            body = {"items": [{}, {}]}
        elif "seed-mcp-identity" in command:
            body = {
                "data": {
                    "MCP_IDENTITY_HMAC_KEY": base64.b64encode(b"a" * 64).decode(),
                    "MCP_IDENTITY_KEY_VERSION": base64.b64encode(b"1").decode(),
                }
            }
        elif "seed-mcp-tls" in command:
            body = {
                "type": "kubernetes.io/tls",
                "data": {
                    "tls.crt": base64.b64encode(b"private-canary").decode(),
                    "tls.key": base64.b64encode(b"private-canary").decode(),
                },
            }
        text = (
            "Hostname mcp.example.com does match certificate\n"
            if "-checkhost" in command
            else json.dumps(body)
        )
        return subprocess.CompletedProcess(command, 0, text, "private-canary")

    executor = Mock(side_effect=execute)
    monkeypatch.setattr(script.subprocess, "run", executor)
    return argv, calls, executor


def test_check_does_not_dispatch_helm_or_echo_secrets(
    delivery: tuple[list[str], list[list[str]], Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv, calls, _ = delivery
    assert script.main(argv) == 0
    assert not any("upgrade" in call for call in calls)
    assert not any("apply" in call or "create" in call for call in calls)
    assert "private-canary" not in str(capsys.readouterr())


def test_deploy_dispatches_once_with_no_retry_or_automatic_rollback(
    delivery: tuple[list[str], list[list[str]], Mock],
) -> None:
    argv, calls, _ = delivery
    argv[0] = "deploy"
    assert script.main(argv) == 0
    creates = [call for call in calls if "upgrade" in call]
    assert len(creates) == 1
    assert "--install" in creates[0] and "--wait" in creates[0]
    assert "--atomic" not in creates[0] and "--rollback-on-failure" not in creates[0]
    assert "--create-namespace" not in creates[0]


@pytest.mark.parametrize(
    "option,value",
    [
        ("--image", "ghcr.io/byteplus-sa/seed-mcp:latest"),
        ("--context", "invalid\ncontext"),
        ("--namespace", "default"),
        ("--identity-secret", "seed-mcp-tls"),
        ("--public-host", "hostname,extra=value"),
    ],
)
def test_invalid_inputs_stop_before_any_command(
    delivery: tuple[list[str], list[list[str]], Mock],
    option: str,
    value: str,
) -> None:
    argv, _, execute = delivery
    argv[argv.index(option) + 1] = value
    assert script.main(argv) == 1
    execute.assert_not_called()


def test_acknowledgement_is_required_before_commands(
    delivery: tuple[list[str], list[list[str]], Mock],
) -> None:
    argv, _, execute = delivery
    argv.remove("--prerequisites-confirmed")
    assert script.main(argv) == 1
    execute.assert_not_called()


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666])
def test_private_file_permissions(
    delivery: tuple[list[str], list[list[str]], Mock], mode: int
) -> None:
    argv, _, execute = delivery
    Path(argv[argv.index("--kubeconfig") + 1]).chmod(mode)
    assert script.main(argv) == 1
    execute.assert_not_called()


def test_private_file_rejects_symlinks_and_checkout(tmp_path: Path) -> None:
    parent = tmp_path.resolve()
    target = parent / "retained"
    target.write_text("private-canary")
    target.chmod(0o600)
    alias = parent / "alias"
    alias.symlink_to(target)
    with pytest.raises(ValueError):
        script.private_file(alias)
    with pytest.raises(ValueError):
        script.private_file(script.CHART / "values.yaml")


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "169.254.169.254", "::1"])
def test_private_server_rejects_non_rfc1918_addresses(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    monkeypatch.setattr(
        script.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(ValueError):
        script.private_server("https://api.example.com")


@pytest.mark.parametrize(
    "server", ["http://10.0.0.1", "https://key@10.0.0.1", "https://10.0.0.1/path"]
)
def test_private_server_rejects_invalid_origins(server: str) -> None:
    with pytest.raises(ValueError):
        script.private_server(server)


def test_uncertain_delivery_is_not_retried_or_logged(
    delivery: tuple[list[str], list[list[str]], Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv, calls, execute = delivery
    argv[0] = "deploy"
    original = execute.side_effect

    def fail(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        if "upgrade" in command:
            calls.append(command)
            raise subprocess.TimeoutExpired(command, 960, output="private-canary")
        return original(command, **options)

    execute.side_effect = fail
    assert script.main(argv) == 1
    assert len([call for call in calls if "upgrade" in call]) == 1
    output = capsys.readouterr()
    assert "private-canary" not in str(output)
    assert "Outcome may be partial" in output.err


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-api",
        "exec",
        "insecure",
        "missing-ca",
        "version-skew",
        "nodes",
        "metrics",
        "identity",
        "tls-type",
        "tls-host",
        "tls-expiry",
    ],
)
def test_failed_prerequisites_never_dispatch_or_leak(
    delivery: tuple[list[str], list[list[str]], Mock],
    capsys: pytest.CaptureFixture[str],
    fault: str,
) -> None:
    argv, calls, execute = delivery
    argv[0] = "deploy"
    original = execute.side_effect

    def fail(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        result = original(command, **options)
        if "-checkhost" in command:
            if fault == "tls-host":
                return subprocess.CompletedProcess(
                    command, 0, "Hostname does NOT match certificate"
                )
            return result
        if "-checkend" in command and fault == "tls-expiry":
            raise subprocess.CalledProcessError(1, command, output="private-canary")
        body = json.loads(result.stdout)
        if "view" in command:
            cluster, user = body["clusters"][0]["cluster"], body["users"][0]["user"]
            if fault == "wrong-api":
                cluster["server"] = "https://private-canary.invalid"
            elif fault == "exec":
                user["exec"] = {"command": "private-canary"}
            elif fault == "insecure":
                cluster["insecure-skip-tls-verify"] = True
            elif fault == "missing-ca":
                cluster.pop("certificate-authority-data")
        elif "version" in command and fault == "version-skew":
            body["clientVersion"]["minor"] = "30"
        elif "nodes" in command and fault == "nodes":
            body["items"][0]["spec"] = {"unschedulable": True}
        elif "--raw=/apis/metrics.k8s.io/v1beta1/nodes" in command and fault == "metrics":
            body["items"] = []
        elif "seed-mcp-identity" in command and fault == "identity":
            body["data"]["MCP_IDENTITY_HMAC_KEY"] = base64.b64encode(b"private-canary").decode()
        elif "seed-mcp-tls" in command and fault == "tls-type":
            body["type"] = "Opaque"
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "private-canary")

    execute.side_effect = fail
    assert script.main(argv) == 1
    assert not any("upgrade" in command for command in calls)
    output = capsys.readouterr()
    assert "private-canary" not in str(output)
    assert "No Helm dispatch" in output.err


def test_workflow_is_manual_main_only_protected_and_workflow_group_isolated() -> None:
    source = (script.CHART.parents[2] / ".github/workflows/deploy-vke.yml").read_text()
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    config, job = workflow["jobs"]["configuration"], workflow["jobs"]["delivery"]
    for item in (config, job):
        assert "github.ref == 'refs/heads/main'" in item["if"]
        assert "github.repository == 'byteplus-sa/seed-mcp'" in item["if"]
    assert job["environment"] == "byteplus-staging"
    assert "group" in job["runs-on"]
    assert job["runs-on"]["labels"] == ["self-hosted", "linux", "x64", "seed-mcp-vke"]
    assert "VKE_RUNNER_READY" in source
    assert "secrets." not in source and "id-token: write" not in source
    for step in job["steps"]:
        if "uses" in step:
            assert len(step["uses"].split("@")[1]) == 40
        assert "${{ inputs." not in step.get("run", "")
    checkout = job["steps"][0]
    assert checkout["with"]["persist-credentials"] == "false"
    assert "upload-artifact" not in source
