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
        "--service-mode",
        "public-clb",
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


@pytest.mark.parametrize("mode", ["apig-staging", "apig-production"])
def test_apig_checks_backend_certificate_and_pins_mode(
    delivery: tuple[list[str], list[list[str]], Mock],
    mode: str,
) -> None:
    argv, calls, execute = delivery
    argv.extend(["--service-mode", mode, "--backend-host", "backend.example.invalid"])
    if mode == "apig-production":
        argv.append("--production-approved")
    original = execute.side_effect

    def backend(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        result = original(command, **options)
        if "-checkhost" in command:
            return subprocess.CompletedProcess(
                command, 0, "Hostname backend.example.invalid does match certificate\n"
            )
        return result

    execute.side_effect = backend
    assert script.main(argv) == 0
    check = next(command for command in calls if "-checkhost" in command)
    assert check[check.index("-checkhost") + 1] == "backend.example.invalid"
    lint = next(command for command in calls if "lint" in command)
    assert f"service.mode={mode}" in lint
    assert f"service.productionConfirmed={str(mode == 'apig-production').lower()}" in lint
    assert "backendHost=backend.example.invalid" in lint


@pytest.mark.parametrize(
    "extra",
    [
        ["--backend-host", "backend.example.invalid"],
        ["--service-mode", "apig-staging"],
        ["--service-mode", "apig-staging", "--backend-host", "mcp.example.com"],
        ["--service-mode", "apig-staging", "--backend-host", "bad,extra=value"],
        ["--service-mode", "apig-staging", "--backend-host", "bad..example.com"],
        ["--production-approved"],
        ["--service-mode", "apig-staging", "--production-approved"],
        ["--service-mode", "apig-production", "--backend-host", "backend.example.invalid"],
        ["--service-mode", "apig-production", "--production-approved"],
        [
            "--service-mode",
            "apig-production",
            "--production-approved",
            "--backend-host",
            "mcp.example.com",
        ],
    ],
)
def test_invalid_staging_mode_stops_before_commands(
    delivery: tuple[list[str], list[list[str]], Mock], extra: list[str]
) -> None:
    argv, _, execute = delivery
    assert script.main([*argv, *extra]) == 1
    execute.assert_not_called()


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
    assert workflow["concurrency"] == {
        "group": "byteplus-staging-delivery",
        "cancel-in-progress": "false",
    }
    config, job = workflow["jobs"]["configuration"], workflow["jobs"]["delivery"]
    for item in (config, job):
        assert "github.ref == 'refs/heads/main'" in item["if"]
        assert "github.repository == 'byteplus-sa/seed-mcp'" in item["if"]
    assert job["environment"] == "byteplus-production"
    assert config["outputs"] == {"runner_group": "${{ steps.config.outputs.runner_group }}"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["target"]["options"] == ["production"]
    assert inputs["target"]["default"] == "production"
    assert inputs["target"]["required"] == "true"
    assert inputs["operation"]["options"] == ["check", "deploy"]
    assert inputs["operation"]["default"] == "check"
    assert inputs["image"]["required"] == "true"
    assert config["timeout-minutes"] == "5"
    assert job["timeout-minutes"] == "30"
    assert "group" in job["runs-on"]
    assert job["runs-on"]["labels"] == ["self-hosted", "linux", "x64", "seed-mcp-vke"]
    assert "VKE_RUNNER_READY" not in source
    assert "VKE_RUNNER_GROUP" not in source
    assert config["steps"][0]["env"] == {
        "TARGET": "${{ inputs.target }}",
        "PRODUCTION_ENABLED": "${{ vars.VKE_PRODUCTION_ENABLED }}",
        "PRODUCTION_RUNNER_READY": "${{ vars.VKE_PRODUCTION_RUNNER_READY }}",
        "PRODUCTION_RUNNER_GROUP": "${{ vars.VKE_PRODUCTION_RUNNER_GROUP }}",
        "DEPLOY_IMAGE": "${{ inputs.image }}",
    }
    assert "secrets." not in source and "id-token: write" not in source
    for item in (config, job):
        for step in item["steps"]:
            if "uses" in step:
                assert len(step["uses"].split("@")[1]) == 40
            assert "${{ inputs." not in step.get("run", "")
    checkout = job["steps"][0]
    assert checkout["with"]["persist-credentials"] == "false"
    assert "upload-artifact" not in source


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, 0),
        ({"TARGET": "staging"}, 1),
        ({"TARGET": "unknown"}, 1),
        ({"TARGET": ""}, 1),
        ({"TARGET": None}, 1),
        ({"PRODUCTION_ENABLED": ""}, 1),
        ({"PRODUCTION_ENABLED": "false"}, 1),
        ({"PRODUCTION_ENABLED": None}, 1),
        ({"PRODUCTION_RUNNER_READY": ""}, 1),
        ({"PRODUCTION_RUNNER_READY": "false"}, 1),
        ({"PRODUCTION_RUNNER_READY": None}, 1),
        ({"PRODUCTION_RUNNER_GROUP": ""}, 1),
        ({"PRODUCTION_RUNNER_GROUP": None}, 1),
        ({"PRODUCTION_RUNNER_GROUP": "-bad"}, 1),
        ({"PRODUCTION_RUNNER_GROUP": "runner\ninjected"}, 1),
        ({"PRODUCTION_RUNNER_GROUP": "a" * 65}, 1),
        ({"DEPLOY_IMAGE": ""}, 1),
        ({"DEPLOY_IMAGE": None}, 1),
        ({"DEPLOY_IMAGE": "ghcr.io/byteplus-sa/seed-mcp:edge"}, 1),
        ({"DEPLOY_IMAGE": "ghcr.io/other/seed-mcp@sha256:" + "a" * 64}, 1),
        ({"DEPLOY_IMAGE": "ghcr.io/byteplus-sa/seed-mcp@sha256:" + "A" * 64}, 1),
        ({"DEPLOY_IMAGE": "ghcr.io/byteplus-sa/seed-mcp@sha256:" + "a" * 63}, 1),
    ],
)
def test_workflow_configuration_gates_run_before_private_queue(
    tmp_path: Path,
    overrides: dict[str, str | None],
    expected: int,
) -> None:
    workflow = yaml.load(
        (script.CHART.parents[2] / ".github/workflows/deploy-vke.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    run = workflow["jobs"]["configuration"]["steps"][0]["run"]
    output = tmp_path / "output"
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_OUTPUT": str(output),
        "TARGET": "production",
        "PRODUCTION_ENABLED": "true",
        # Legacy values cannot rescue absent production configuration.
        "RUNNER_READY": "true",
        "RUNNER_GROUP": "staging-runners",
        "PRODUCTION_RUNNER_READY": "true",
        "PRODUCTION_RUNNER_GROUP": "production-runners",
        "DEPLOY_IMAGE": "ghcr.io/byteplus-sa/seed-mcp@sha256:" + "a" * 64,
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key)
        else:
            env[key] = value
    result = subprocess.run(
        ["bash", "-c", run],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == expected
    if expected == 0:
        assert output.read_text() == "runner_group=production-runners\n"
    else:
        assert not output.exists()


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, 0),
        ({"TARGET": ""}, 1),
        ({"TARGET": None}, 1),
        ({"TARGET": "staging"}, 1),
        ({"TARGET": "unknown"}, 1),
        ({"TARGET": "staging", "SERVICE_MODE": "apig-staging", "PRODUCTION_APPROVED": ""}, 1),
        ({"TARGET": "staging", "SERVICE_MODE": "public-clb", "PRODUCTION_APPROVED": ""}, 1),
        ({"SERVICE_MODE": "apig-staging"}, 1),
        ({"SERVICE_MODE": "public-clb"}, 1),
        ({"SERVICE_MODE": ""}, 1),
        ({"SERVICE_MODE": None}, 1),
        ({"PREREQUISITES": ""}, 1),
        ({"PREREQUISITES": "false"}, 1),
        ({"PREREQUISITES": None}, 1),
        ({"PRODUCTION_APPROVED": ""}, 1),
        ({"PRODUCTION_APPROVED": "false"}, 1),
        ({"PRODUCTION_APPROVED": None}, 1),
        *[
            ({key: value}, 1)
            for key in (
                "OPERATION",
                "DEPLOY_IMAGE",
                "KUBE_FILE",
                "VALUES_FILE",
                "KUBE_CONTEXT",
                "API_SERVER",
                "NAMESPACE",
                "PUBLIC_HOST",
                "BACKEND_HOST",
                "IDENTITY_SECRET",
                "TLS_SECRET",
            )
            for value in ("", None)
        ],
    ],
)
@pytest.mark.parametrize("operation", ["check", "deploy"])
def test_workflow_delivery_mode_and_approval_pairing(
    overrides: dict[str, str | None],
    expected: int,
    operation: str,
) -> None:
    workflow = yaml.load(
        (script.CHART.parents[2] / ".github/workflows/deploy-vke.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    step = workflow["jobs"]["delivery"]["steps"][1]
    # A shell function intercepts the final invocation; no Python/helper/cluster runs.
    run = "python3() { printf '%s\\n' \"$@\"; }\n" + step["run"]
    env = dict.fromkeys(step["env"], "synthetic-reference")
    env.update(
        {
            "PATH": "/usr/bin:/bin",
            "TARGET": "production",
            "OPERATION": operation,
            "SERVICE_MODE": "apig-production",
            "PREREQUISITES": "true",
            "PRODUCTION_APPROVED": "true",
        }
    )
    for key, value in overrides.items():
        if value is None:
            env.pop(key)
        else:
            env[key] = value
    result = subprocess.run(
        ["bash", "-c", run],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == expected
    assert ("scripts/deploy_vke.py" in result.stdout) is (expected == 0)
    if expected == 0:
        argv = result.stdout.splitlines()
        assert argv[:2] == ["scripts/deploy_vke.py", operation]
        assert argv.count("scripts/deploy_vke.py") == 1
        assert argv[-2:] == ["--prerequisites-confirmed", "--production-approved"]
        assert argv[argv.index("--service-mode") + 1] == "apig-production"
        assert argv[argv.index("--backend-host") + 1] == env["BACKEND_HOST"]


def test_service_mode_has_no_implicit_clb_fallback(
    delivery: tuple[list[str], list[list[str]], Mock],
) -> None:
    argv, _, execute = delivery
    index = argv.index("--service-mode")
    del argv[index : index + 2]
    with pytest.raises(SystemExit):
        script.main(argv)
    execute.assert_not_called()
