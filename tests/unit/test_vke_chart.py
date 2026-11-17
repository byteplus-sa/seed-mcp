"""Offline checks for specs/SPEC_VKE_DEPLOYMENT.md."""

import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/seed-mcp"
CADDYFILE = CHART / "files/Caddyfile"


def executable(variable: str, name: str) -> str:
    candidate = os.environ.get(variable) or shutil.which(name)
    if not candidate:
        pytest.skip(f"Install {name} or set {variable} for infrastructure validation")
    return candidate


def test_shared_caddyfile_has_closed_public_surface() -> None:
    config = CADDYFILE.read_text()
    assert "admin off" in config
    assert "output discard" in config
    assert "auto_https off" in config
    assert "@public path /mcp /health" in config
    assert "header_up X-Forwarded-For {http.request.remote.host}" in config
    assert "header_up -Forwarded" in config
    assert "flush_interval -1" in config
    assert 'respond "Not Found" 404' in config
    assert "trusted_proxies" not in config
    assert "log {" in config


def test_shared_caddyfile_adapts_with_real_binary() -> None:
    result = subprocess.run(
        [executable("CADDY_BIN", "caddy"), "adapt", "--config", str(CADDYFILE)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "MCP_PUBLIC_HOST": "mcp.example.test",
            "MCP_PROXY_PORT": "8443",
            "MCP_PORT": "3000",
            "MCP_TLS_CERT_FILE": "/tls/tls.crt",
            "MCP_TLS_KEY_FILE": "/tls/tls.key",
            "MCP_HTTP_MAX_BODY_BYTES": "2097152",
            "MCP_PROXY_GRACE_PERIOD": "630s",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["admin"]["disabled"]
    assert config["logging"]["logs"]["default"]["writer"] == {"output": "discard"}
    server = next(iter(config["apps"]["http"]["servers"].values()))
    assert server.get("logs") is None
    assert "trusted_proxies" not in server
    assert set(server["protocols"]) == {"h1", "h2"}
    assert (
        not server["automatic_https"].get("disable_redirects")
        or server["automatic_https"]["disable"]
    )


def helm(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable("HELM_BIN", "helm"), *arguments],
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def render(
    tmp_path: Path,
    overrides: dict[str, Any] | None = None,
    *,
    release: str = "synthetic",
) -> subprocess.CompletedProcess[str]:
    override_file = tmp_path / "overrides.json"
    override_file.write_text(json.dumps(overrides or {}))
    return helm(
        tmp_path,
        "template",
        release,
        str(CHART),
        "-f",
        str(CHART / "values.ci.yaml"),
        "-f",
        str(override_file),
    )


def documents(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    assert result.returncode == 0, result.stderr
    return [document for document in yaml.safe_load_all(result.stdout) if document]


@pytest.mark.parametrize("page", ["runtime.md", "deployment.md", "observability.md"])
def test_operator_examples_target_the_rendered_release_pod(tmp_path: Path, page: str) -> None:
    rendered = documents(render(tmp_path, release="seed-mcp"))
    stateful = next(item for item in rendered if item["kind"] == "StatefulSet")
    expected_pod = stateful["metadata"]["name"] + "-0"
    content = (ROOT / "docs" / page).read_text()
    targets = re.findall(
        r"kubectl -n seed-mcp (?:exec|port-forward --address 127\.0\.0\.1) (?:pod/)?(\S+)",
        content,
    )
    assert targets, f"No private diagnostic pod targets found in {page}"
    assert set(targets) == {expected_pod}


def test_ci_values_lint_and_single_writer_storage(tmp_path: Path) -> None:
    lint = helm(tmp_path, "lint", str(CHART), "-f", str(CHART / "values.ci.yaml"), "--strict")
    assert lint.returncode == 0, lint.stdout + lint.stderr
    rendered = documents(render(tmp_path))
    assert sorted(item["kind"] for item in rendered) == [
        "ConfigMap",
        "Service",
        "Service",
        "StatefulSet",
        "StorageClass",
    ]
    stateful = next(item for item in rendered if item["kind"] == "StatefulSet")
    assert stateful["spec"]["replicas"] == 1
    assert stateful["spec"]["persistentVolumeClaimRetentionPolicy"] == {
        "whenDeleted": "Retain",
        "whenScaled": "Retain",
    }
    claims = stateful["spec"]["volumeClaimTemplates"]
    assert len(claims) == 1
    assert claims[0]["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claims[0]["spec"]["volumeMode"] == "Filesystem"
    storage = next(item for item in rendered if item["kind"] == "StorageClass")
    assert storage["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
    assert storage["provisioner"] == "ebs.csi.volcengine.com"
    assert storage["reclaimPolicy"] == "Retain"
    assert storage["volumeBindingMode"] == "WaitForFirstConsumer"
    assert storage["parameters"] == {
        "ChargeType": "PostPaid",
        "fsType": "ext4",
        "type": "ESSD_PL0",
        "zone": "ap-southeast-1a",
        "projectName": "default",
        "encrypted": "false",
    }


@pytest.mark.parametrize("metrics", [False, True])
@pytest.mark.parametrize(("tool", "provider"), [(600, 600), (900, 30), (1, 3600)])
def test_pod_security_ports_and_shutdown(
    tmp_path: Path, metrics: bool, tool: int, provider: int
) -> None:
    rendered = documents(
        render(
            tmp_path,
            {
                "app": {
                    "metricsEnabled": metrics,
                    "toolTimeoutSeconds": tool,
                    "providerTimeoutSeconds": provider,
                }
            },
        )
    )
    stateful = next(item for item in rendered if item["kind"] == "StatefulSet")
    pod = stateful["spec"]["template"]["spec"]
    assert pod["terminationGracePeriodSeconds"] == max(tool, provider) + 60
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 1001,
        "runAsGroup": 1001,
        "fsGroup": 1001,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert pod["nodeSelector"] == {"topology.kubernetes.io/zone": "ap-southeast-1a"}
    app, proxy = pod["containers"]
    app_env = {entry["name"]: entry for entry in app["env"]}
    proxy_env = {entry["name"]: entry["value"] for entry in proxy["env"]}
    assert app_env["MCP_HOST"]["value"] == "127.0.0.1"
    assert app_env["MCP_PORT"]["value"] == "3000"
    assert app_env["RATE_LIMIT_TRUSTED_PROXY_CIDRS"]["value"] == "127.0.0.1/32"
    assert app_env["MCP_AUTH_MODE"]["value"] == "byok"
    assert app_env["STATE_BACKEND"]["value"] == "sqlite"
    assert app_env["MCP_METRICS_PORT"]["value"] == ("9000" if metrics else "0")
    assert app_env["MCP_HTTP_MAX_BODY_BYTES"]["value"] == "2097152"
    assert app_env["BYTEPLUS_REQUEST_TIMEOUT_MS"]["value"] == str(provider * 1000)
    assert proxy_env["MCP_PROXY_GRACE_PERIOD"] == f"{max(tool, provider) + 30}s"
    assert proxy_env["MCP_HTTP_MAX_BODY_BYTES"] == app_env["MCP_HTTP_MAX_BODY_BYTES"]["value"]
    for name in ("MCP_IDENTITY_HMAC_KEY", "MCP_IDENTITY_KEY_VERSION"):
        assert app_env[name] == {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": "synthetic-identity", "key": name}},
        }
    assert not any("API_KEY" in name for name in app_env)
    assert "ports" not in app
    assert proxy["ports"] == [{"name": "https", "containerPort": 8443, "protocol": "TCP"}]
    assert proxy["image"] == "caddy:2.11.9-alpine"
    assert "@sha256:" in app["image"]
    for container in (app, proxy):
        assert "envFrom" not in container
        assert container["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        }
        assert set(container["resources"]) == {"requests", "limits"}
        assert set(container["resources"]["limits"]) == {"cpu", "memory", "ephemeral-storage"}
    assert all(mount["name"] != "tls" for mount in app["volumeMounts"])
    assert all(mount["name"] != "state" for mount in proxy["volumeMounts"])
    assert "http://127.0.0.1:3000/ready" in app["readinessProbe"]["exec"]["command"][-1]
    assert "http://127.0.0.1:3000/health" in app["livenessProbe"]["exec"]["command"][-1]
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert volumes["tls"]["secret"]["defaultMode"] == 0o440
    assert volumes["app-tmp"]["emptyDir"]["sizeLimit"] == "128Mi"
    assert volumes["proxy-tmp"]["emptyDir"]["sizeLimit"] == "128Mi"
    services = [item for item in rendered if item["kind"] == "Service"]
    assert all(
        service["spec"]["ports"]
        == [{"name": "https", "port": 443, "targetPort": "https", "protocol": "TCP"}]
        for service in services
    )
    public = next(service for service in services if service["spec"].get("type") == "LoadBalancer")
    assert public["spec"]["externalTrafficPolicy"] == "Local"
    assert public["spec"]["loadBalancerSourceRanges"] == ["192.0.2.0/24"]
    annotations = public["metadata"]["annotations"]
    prefix = "service.beta.kubernetes.io/volcengine-loadbalancer-"
    assert annotations[prefix + "subnet-id"] == "subnet-synthetic"
    assert annotations[prefix + "address-type"] == "PUBLIC"
    configmap = next(item for item in rendered if item["kind"] == "ConfigMap")
    assert configmap["data"]["Caddyfile"].rstrip() == CADDYFILE.read_text().rstrip()


@pytest.mark.parametrize(
    "overrides",
    [
        {"prerequisitesConfirmed": False},
        {"image": ""},
        {"image": "example.invalid/seed-mcp:latest"},
        {"image": "example.invalid/seed-mcp:0.3.0"},
        {"image": "example.invalid/seed-mcp@sha256:abc"},
        {"publicHost": ""},
        {"publicHost": "https://mcp.example.invalid/mcp"},
        {"publicHost": "example.invalid\nrespond secret"},
        {"identitySecret": {"name": ""}},
        {"identitySecret": {"name": "synthetic-tls"}},
        {"identitySecret": {"hmacKey": "MCP_IDENTITY_KEY_VERSION"}},
        {"tlsSecretName": ""},
        {"service": {"subnetId": ""}},
        {"service": {"sourceRanges": []}},
        {"service": {"sourceRanges": ["0.0.0.0/0"]}},
        {"service": {"sourceRanges": ["999.0.0.0/24"]}},
        {"service": {"sourceRanges": ["192.0.2.1/33"]}},
        {"storage": {"zone": ""}},
        {"storage": {"sizeGiB": 0}},
        {"storage": {"encrypted": True}},
        {"storage": {"accessModes": ["ReadWriteMany"]}},
        {"storage": {"reclaimPolicy": "Delete"}},
        {"storage": {"project": "API_KEY"}},
        {"app": None},
        {"app": {"toolTimeoutSeconds": 3601}},
        {"app": {"providerTimeoutSeconds": 0}},
        {"app": {"maxBodyBytes": 0}},
        {"app": {"maxInFlight": 0}},
        {"app": {"stateMaxRecords": 0}},
        {"app": {"host": "0.0.0.0"}},
        {"app": {"trustedProxyCidrs": ["0.0.0.0/0"]}},
        {"resources": {"app": {"cpuLimitMillis": 0}}},
        {"resources": {"proxy": {"memoryRequestMiB": 8193}}},
        {"resources": {"app": {"cpuRequestMillis": 3000, "cpuLimitMillis": 1000}}},
        {"resources": {"proxy": {"memoryRequestMiB": 512, "memoryLimitMiB": 64}}},
        {"BYTEPLUS_MODELARK_API_KEY": "synthetic-provider-key"},  # pragma: allowlist secret
        {
            "env": {
                "BYTEPLUS_MODELARK_API_KEY": "synthetic-provider-key"  # pragma: allowlist secret
            }
        },
        {"app": {"API_KEY": "synthetic-provider-key"}},  # pragma: allowlist secret
        {"identitySecret": {"hmacKey": "BYTEPLUS_API_KEY"}},
        {"identitySecret": {"hmacKey": "b" * 64}},
        {"identitySecret": {"value": "b" * 64}},
        {"identitySecret": {"hmac": "b" * 64}},
        {"MCP_IDENTITY_HMAC_KEY": "b" * 64},
        {"tls": {"key": "synthetic-private-key"}},
        {"unknownConfig": True},
        {"config": {"unknown": True}},
        {"replicas": 2},
        {"replicaCount": 2},
        {"autoscaling": {"enabled": True}},
        {"hpa": {"enabled": True}},
        {"app": {"replicas": 2}},
    ],
)
def test_chart_rejects_unsafe_or_unknown_values(tmp_path: Path, overrides: dict[str, Any]) -> None:
    result = render(tmp_path, overrides)
    assert result.returncode != 0, result.stdout


def test_chart_accepts_bounded_options_and_decimal_environment(tmp_path: Path) -> None:
    rendered = documents(
        render(
            tmp_path,
            {
                "imagePullSecrets": ["existing-registry"],
                "storage": {"encrypted": True, "kmsPrerequisitesConfirmed": True},
                "app": {
                    "stateMaxRecords": 1000000,
                    "maxBodyBytes": 16777216,
                    "omnihumanEnabled": True,
                },
            },
        )
    )
    storage = next(item for item in rendered if item["kind"] == "StorageClass")
    assert storage["parameters"]["encrypted"] == "true"
    pod = next(item for item in rendered if item["kind"] == "StatefulSet")["spec"]["template"][
        "spec"
    ]
    assert pod["imagePullSecrets"] == [{"name": "existing-registry"}]
    app_env = {entry["name"]: entry.get("value") for entry in pod["containers"][0]["env"]}
    assert app_env["STATE_MAX_RECORDS"] == "1000000"
    assert app_env["MCP_HTTP_MAX_BODY_BYTES"] == "16777216"
    assert app_env["BYTEPLUS_OMNIHUMAN_ENABLED"] == "true"


def test_chart_preserves_verified_byoe_bindings_and_operator_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ark_mcp.config.env import Settings

    models = {
        "seedream": {
            "defaultModel": "ep-verified-image",
            "bindings": [{"model_id": "ep-verified-image", "family": "seedream_5_5"}],
        },
        "seedance": {
            "defaultModel": "ep-verified-video",
            "bindings": [
                {"model_id": "ep-verified-video", "family": "seedance_2_5"},
                {"model_id": "ep-verified-flash", "family": "seedance_2_5_flash"},
            ],
        },
    }
    rendered = documents(
        render(
            tmp_path,
            {
                "models": models,
                "app": {
                    "dailyBudgetUsd": 12.5,
                    "providerMaxConcurrency": 7,
                    "principalMaxConcurrency": 2,
                    "rateLimitBurst": 20,
                },
            },
        )
    )
    stateful = next(item for item in rendered if item["kind"] == "StatefulSet")
    env = {
        entry["name"]: entry["value"]
        for entry in stateful["spec"]["template"]["spec"]["containers"][0]["env"]
        if "value" in entry
    }
    for name, value in {**env, "MCP_IDENTITY_HMAC_KEY": "a" * 64}.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.seedream_default_model == "ep-verified-image"
    assert settings.seedance_default_model == "ep-verified-video"
    assert [binding.model_dump(mode="json") for binding in settings.seedance_model_bindings] == (
        models["seedance"]["bindings"]
    )
    assert settings.daily_budget_usd == 12.5
    assert settings.provider_max_concurrency == 7
    assert settings.principal_max_concurrency == 2
    assert settings.rate_limit_burst == 20
    assert not settings.modelark_api_key


@pytest.mark.parametrize(
    "values",
    [
        {"defaultModel": "ep-custom", "bindings": []},
        {"bindings": [{"model_id": "ep-other", "family": "seedream_5_5"}]},
        {"bindings": [{"model_id": "ep-other", "family": "unverified"}]},
        {"bindings": [{"model_id": "ep-other", "family": "seedance_2_5"}]},
        {
            "defaultModel": "ep-custom",
            "bindings": [
                {"model_id": "ep-custom", "family": "seedream_5_5"},
                {"model_id": "ep-custom", "family": "pro"},
            ],
        },
        {"defaultModel": "ep-custom\ninjected"},
    ],
)
def test_chart_rejects_incomplete_or_invalid_image_bindings(
    tmp_path: Path, values: dict[str, Any]
) -> None:
    assert render(tmp_path, {"models": {"seedream": values}}).returncode != 0


@pytest.mark.parametrize(
    "values",
    [
        {"dailyBudgetUsd": -1},
        {"dailyBudgetUsd": "nan"},
        {"providerMaxConcurrency": 0},
        {"principalMaxConcurrency": 0},
        {"rateLimitBurst": -1},
    ],
)
def test_chart_rejects_invalid_operator_limits(tmp_path: Path, values: dict[str, Any]) -> None:
    assert render(tmp_path, {"app": values}).returncode != 0


def test_operator_examples_never_acknowledge_readiness() -> None:
    for filename in ("values.yaml", "values.example.yaml"):
        assert yaml.safe_load((CHART / filename).read_text())["prerequisitesConfirmed"] is False
    ci = yaml.safe_load((CHART / "values.ci.yaml").read_text())
    assert ci["image"].startswith("example.invalid/")
    assert ci["publicHost"].endswith(".invalid")


def test_chart_packaging_excludes_ci_and_private_values(tmp_path: Path) -> None:
    source = tmp_path / "chart"
    shutil.copytree(CHART, source)
    for filename in ("values.private.yaml", "privatevalues.yaml", "secrets.private.yaml", ".env"):
        (source / filename).write_text("synthetic-only")
    result = helm(tmp_path, "package", str(source), "--destination", str(tmp_path))
    assert result.returncode == 0, result.stderr
    with tarfile.open(next(tmp_path.glob("*.tgz"))) as archive:
        names = archive.getnames()
    assert "seed-mcp/files/Caddyfile" in names
    assert not any("private" in name or name.endswith(("values.ci.yaml", ".env")) for name in names)


def test_caddy_validate_with_temporary_certificate(tmp_path: Path) -> None:
    binary = executable("CADDY_BIN", "caddy")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mcp.example.test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=5))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("mcp.example.test")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "tls.crt", tmp_path / "tls.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    result = subprocess.run(
        [binary, "validate", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "MCP_PUBLIC_HOST": "mcp.example.test",
            "MCP_PROXY_PORT": "8443",
            "MCP_PORT": "3000",
            "MCP_TLS_CERT_FILE": str(cert_path),
            "MCP_TLS_KEY_FILE": str(key_path),
            "MCP_HTTP_MAX_BODY_BYTES": "2097152",
            "MCP_PROXY_GRACE_PERIOD": "630s",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
