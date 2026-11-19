"""Offline stateless deployment checks for specs/SPEC_VKE_DEPLOYMENT.md."""

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


@pytest.fixture(autouse=True)
def isolate_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("POSTGRES_"):
            monkeypatch.delenv(name, raising=False)


def executable(variable: str, name: str) -> str:
    candidate = os.environ.get(variable) or shutil.which(name)
    if not candidate:
        helper = Path("/tmp/seed-vke-tools") / (f"darwin-arm64/{name}" if name == "helm" else name)
        if helper.is_file() and os.access(helper, os.X_OK):
            candidate = str(helper)
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
    kube_version: str = "1.30.0",
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
        "--kube-version",
        kube_version,
    )


def documents(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    assert result.returncode == 0, result.stderr
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def test_ci_values_lint_and_scalable_workload(tmp_path: Path) -> None:
    lint = helm(tmp_path, "lint", str(CHART), "-f", str(CHART / "values.ci.yaml"), "--strict")
    assert lint.returncode == 0, lint.stdout + lint.stderr
    rendered = documents(render(tmp_path))
    assert sorted(item["kind"] for item in rendered) == [
        "ConfigMap",
        "Deployment",
        "HorizontalPodAutoscaler",
        "PodDisruptionBudget",
        "Service",
    ]
    deployment = next(item for item in rendered if item["kind"] == "Deployment")
    assert "replicas" not in deployment["spec"]
    assert deployment["spec"]["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }
    selector = deployment["spec"]["selector"]["matchLabels"]
    pod = deployment["spec"]["template"]["spec"]
    assert pod["topologySpreadConstraints"] == [
        {
            "maxSkew": 1,
            "minDomains": 2,
            "topologyKey": "kubernetes.io/hostname",
            "whenUnsatisfiable": "DoNotSchedule",
            "labelSelector": {"matchLabels": selector},
        }
    ]
    pdb = next(item for item in rendered if item["kind"] == "PodDisruptionBudget")
    assert pdb["apiVersion"] == "policy/v1"
    assert pdb["spec"] == {"minAvailable": 1, "selector": {"matchLabels": selector}}
    hpa = next(item for item in rendered if item["kind"] == "HorizontalPodAutoscaler")
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["spec"] == {
        "scaleTargetRef": {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": deployment["metadata"]["name"],
        },
        "minReplicas": 2,
        "maxReplicas": 6,
        "metrics": [
            {
                "type": "Resource",
                "resource": {
                    "name": "cpu",
                    "target": {"type": "Utilization", "averageUtilization": 70},
                },
            }
        ],
        "behavior": {
            "scaleUp": {
                "stabilizationWindowSeconds": 0,
                "selectPolicy": "Min",
                "policies": [{"type": "Pods", "value": 2, "periodSeconds": 60}],
            },
            "scaleDown": {
                "stabilizationWindowSeconds": 300,
                "selectPolicy": "Min",
                "policies": [{"type": "Pods", "value": 1, "periodSeconds": 60}],
            },
        },
    }
    service = next(item for item in rendered if item["kind"] == "Service")
    assert service["spec"]["selector"] == selector
    assert service["spec"]["type"] == "LoadBalancer"
    assert "clusterIP" not in service["spec"]
    assert "volumeClaimTemplates" not in deployment["spec"]
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])
    assert "nodeSelector" not in pod


@pytest.mark.parametrize("replicas", [2, 4, 6])
def test_hpa_disabled_has_bounded_fixed_replicas(tmp_path: Path, replicas: int) -> None:
    rendered = documents(
        render(tmp_path, {"autoscaling": {"enabled": False}, "replicaCount": replicas})
    )
    assert not any(item["kind"] == "HorizontalPodAutoscaler" for item in rendered)
    deployment = next(item for item in rendered if item["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == replicas
    assert any(item["kind"] == "PodDisruptionBudget" for item in rendered)


def test_hpa_overrides_preserve_bounded_steps_and_do_not_set_replicas(tmp_path: Path) -> None:
    rendered = documents(
        render(
            tmp_path,
            {
                "replicaCount": 5,
                "autoscaling": {
                    "minReplicas": 3,
                    "maxReplicas": 4,
                    "targetCPUUtilizationPercentage": 80,
                    "scaleDownStabilizationSeconds": 600,
                },
            },
        )
    )
    deployment = next(item for item in rendered if item["kind"] == "Deployment")
    hpa = next(item for item in rendered if item["kind"] == "HorizontalPodAutoscaler")["spec"]
    assert "replicas" not in deployment["spec"]
    assert (hpa["minReplicas"], hpa["maxReplicas"]) == (3, 4)
    assert hpa["metrics"][0]["resource"]["target"]["averageUtilization"] == 80
    assert hpa["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == 600
    assert hpa["behavior"]["scaleUp"]["policies"][0]["value"] == 2
    assert hpa["behavior"]["scaleDown"]["policies"][0]["value"] == 1


@pytest.mark.parametrize("group", ["identitySecret"])
def test_schema_requires_complete_existing_references(group: str) -> None:
    from jsonschema import Draft7Validator

    schema = json.loads((CHART / "values.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    reference_schema = schema["properties"][group]
    for required in reference_schema["required"]:
        assert required in reference_schema["properties"]
        fields = {key: "synthetic-reference" for key in reference_schema["properties"]}
        fields.pop(required)
        validator = Draft7Validator({**schema, **reference_schema})
        errors = list(validator.iter_errors(fields))
        assert any(error.validator == "required" for error in errors)


def test_chart_has_no_legacy_storage_source_or_resources(tmp_path: Path) -> None:
    assert not (CHART / "templates/statefulset.yaml").exists()
    assert not (CHART / "templates/storageclass.yaml").exists()
    service_source = (CHART / "templates/service.yaml").read_text()
    assert "Legacy headless Service" not in service_source
    assert "clusterIP: None" not in service_source
    assert "state cutover" not in (CHART / "values.yaml").read_text()
    rendered = documents(render(tmp_path))
    assert not any(
        item["kind"]
        in {"StatefulSet", "PersistentVolumeClaim", "PersistentVolume", "StorageClass", "Secret"}
        for item in rendered
    )
    notes = (CHART / "templates/NOTES.txt").read_text()
    assert "historical database compatibility" in notes
    assert "WAL/database backups" not in notes
    assert "CSI is not a new application prerequisite" in notes


@pytest.mark.parametrize("version", ["1.27.16", "1.28.15", "1.29.9"])
def test_chart_rejects_kubernetes_below_min_domains_floor(tmp_path: Path, version: str) -> None:
    assert render(tmp_path, kube_version=version).returncode != 0


@pytest.mark.parametrize("version", ["1.30.0", "1.30.0-rc.1", "1.34.0"])
def test_chart_accepts_supported_kubernetes_source_versions(tmp_path: Path, version: str) -> None:
    metadata = yaml.safe_load((CHART / "Chart.yaml").read_text())
    assert metadata["kubeVersion"] == ">=1.30.0-0"
    documents(render(tmp_path, kube_version=version))


@pytest.mark.parametrize("hpa", [False, True])
@pytest.mark.parametrize("selected_version", [False, True])
@pytest.mark.parametrize("upload_mode", ["disabled", "static", "irsa"])
def test_rendered_kubernetes_schemas_offline(
    tmp_path: Path, hpa: bool, selected_version: bool, upload_mode: str
) -> None:
    binary = executable("KUBECONFORM_BIN", "kubeconform")
    version = os.environ.get("KUBERNETES_DEPLOYMENT_VERSION") if selected_version else "1.30.0"
    if not version:
        pytest.skip("Set KUBERNETES_DEPLOYMENT_VERSION to the operator-selected VKE version")
    location = os.environ.get("KUBERNETES_SCHEMA_LOCATION")
    if not location:
        pytest.skip("Set KUBERNETES_SCHEMA_LOCATION to cached strict versioned schemas")
    # No default/remote schema fallback: missing local schemas are fatal.
    assert Path(location).is_absolute() and "://" not in location
    upload = (
        irsa_values()
        if upload_mode == "irsa"
        else {
            "enabled": upload_mode == "static",
            "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
        }
    )
    rendered = render(
        tmp_path,
        {
            "autoscaling": {"enabled": hpa},
            "temporaryUpload": upload,
        },
        kube_version=version,
    )
    documents(rendered)
    validation = subprocess.run(
        [
            binary,
            "-strict",
            "-summary",
            "-kubernetes-version",
            version,
            "-schema-location",
            location,
        ],
        input=rendered.stdout,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert validation.returncode == 0, validation.stdout + validation.stderr


@pytest.mark.parametrize(
    "override",
    [
        {"app": {"maxInFlight": 20}},
        {"app": {"rateLimitRpm": 90}},
        {
            "models": {
                "seedance": {
                    "bindings": [
                        {"model_id": "dreamina-seedance-2-5-260628", "family": "seedance_2_5"}
                    ]
                }
            }
        },
        {"identitySecret": {"name": "retained-identity"}},  # pragma: allowlist secret
        {"tlsSecretName": "renewed-tls"},  # pragma: allowlist secret
        {"publicHost": "another.example.invalid"},
    ],
)
def test_runtime_checksum_covers_nonsecret_configuration(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    def annotations(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
        deployment = next(item for item in documents(result) if item["kind"] == "Deployment")
        return deployment["spec"]["template"]["metadata"]["annotations"]

    original = annotations(render(tmp_path))
    changed = annotations(render(tmp_path, override))
    assert re.fullmatch(r"[a-f0-9]{64}", original["checksum/runtime"])
    assert original["checksum/proxy"] == changed["checksum/proxy"]
    assert original["checksum/runtime"] != changed["checksum/runtime"]


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
    deployment = next(item for item in rendered if item["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
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
    assert "nodeSelector" not in pod
    app, proxy = pod["containers"]
    app_env = {entry["name"]: entry for entry in app["env"]}
    proxy_env = {entry["name"]: entry["value"] for entry in proxy["env"]}
    assert app_env["MCP_HOST"]["value"] == "127.0.0.1"
    assert app_env["MCP_PORT"]["value"] == "3000"
    assert app_env["RATE_LIMIT_TRUSTED_PROXY_CIDRS"]["value"] == "127.0.0.1/32"
    assert app_env["MCP_AUTH_MODE"]["value"] == "byok"
    assert app_env["STATE_BACKEND"]["value"] == "none"
    assert "ARTIFACT_DIR" not in app_env
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
    assert not any(name.startswith("POSTGRES_") for name in app_env)
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
    assert all(mount["name"] != "database-ca" for mount in proxy["volumeMounts"])
    assert "http://127.0.0.1:3000/ready" in app["readinessProbe"]["exec"]["command"][-1]
    assert "http://127.0.0.1:3000/health" in app["livenessProbe"]["exec"]["command"][-1]
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert volumes["tls"]["secret"]["defaultMode"] == 0o440
    assert volumes["app-tmp"]["emptyDir"]["sizeLimit"] == "128Mi"
    assert volumes["proxy-tmp"]["emptyDir"]["sizeLimit"] == "128Mi"
    assert "database-ca" not in volumes


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
        {"databaseSecret": None},
        {"databaseSecret": {"name": ""}},
        {"databaseSecret": {"key": ""}},
        {"databaseSecret": {"key": None}},
        {"databaseSecret": {"name": "synthetic-identity"}},
        {"databaseSecret": {"name": "synthetic-tls"}},
        {"databaseCA": None},
        {"databaseCA": {"name": ""}},
        {"databaseCA": {"key": ""}},
        {"databaseCA": {"key": "../ca.crt"}},
        {"databaseCA": {"key": "API_KEY"}},
        {"databaseSecret": {"dsn": "synthetic-raw-secret"}},
        {"databaseSecret": {"value": "synthetic-raw-secret"}},
        {"databaseCA": {"certificate": "synthetic-raw-certificate"}},
        {"POSTGRES_DSN": "synthetic-raw-secret"},
        {"postgres": {"dsn": "synthetic-raw-secret"}},
        {"postgres": {"password": "synthetic-raw-secret"}},  # pragma: allowlist secret
        {"postgres": {"sslmode": "disable"}},
        {"postgres": {"poolMinSize": 9, "poolMaxSize": 8}},
        {"postgres": {"lockTimeoutSeconds": 3, "statementTimeoutSeconds": 2}},
        {"postgres": {"poolMinSize": 2, "poolMaxSize": 1}},
        {"postgres": {"operationTimeoutSeconds": "nan"}},
        {"postgres": {"cleanupTimeoutSeconds": "inf"}},
        {"postgres": None},
        {"stateBackend": "sqlite"},
        {"STATE_BACKEND": "sqlite"},
        {"app": {"stateBackend": "sqlite"}},
        {"app": {"state_backend": "sqlite"}},
        {"postgres": {"stateBackend": "sqlite"}},
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
        {"replicaCount": 1},
        {"replicaCount": 7},
        {"replicaCount": 2.5},
        {"autoscaling": {"enabled": False}, "replicaCount": 1},
        {"autoscaling": {"enabled": False, "minReplicas": 5, "maxReplicas": 4}},
        {"autoscaling": None},
        {"autoscaling": {"enabled": "true"}},
        {"autoscaling": {"minReplicas": 1}},
        {"autoscaling": {"maxReplicas": 7}},
        {"autoscaling": {"minReplicas": 5, "maxReplicas": 4}},
        {"autoscaling": {"targetCPUUtilizationPercentage": 0}},
        {"autoscaling": {"targetCPUUtilizationPercentage": 101}},
        {"autoscaling": {"scaleDownStabilizationSeconds": 299}},
        {"autoscaling": {"scaleDownStabilizationSeconds": 3601}},
        {"autoscaling": {"behavior": {"scaleDown": {"selectPolicy": "Disabled"}}}},
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
                "app": {
                    "maxBodyBytes": 16777216,
                    "omnihumanEnabled": True,
                },
            },
        )
    )
    pod = next(item for item in rendered if item["kind"] == "Deployment")["spec"]["template"][
        "spec"
    ]
    assert pod["imagePullSecrets"] == [{"name": "existing-registry"}]
    app_env = {entry["name"]: entry.get("value") for entry in pod["containers"][0]["env"]}
    assert "STATE_MAX_RECORDS" not in app_env
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
                    "dailyBudgetUsd": 0,
                    "providerMaxConcurrency": 7,
                    "principalMaxConcurrency": 2,
                    "rateLimitBurst": 20,
                },
            },
        )
    )
    deployment = next(item for item in rendered if item["kind"] == "Deployment")
    env = {
        entry["name"]: entry["value"]
        for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        if "value" in entry
    }
    for name, value in {
        **env,
        "MCP_IDENTITY_HMAC_KEY": "a" * 64,
        "POSTGRES_DSN": "host=database.example.invalid dbname=synthetic user=synthetic sslmode=verify-full",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.seedream_default_model == "ep-verified-image"
    assert settings.seedance_default_model == "ep-verified-video"
    assert [binding.model_dump(mode="json") for binding in settings.seedance_model_bindings] == (
        models["seedance"]["bindings"]
    )
    assert settings.daily_budget_usd == 0
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
        {"defaultModel": "ep-custom", "bindings": []},
        {"bindings": [{"model_id": "ep-other", "family": "seedance_2_5"}]},
        {"bindings": [{"model_id": "ep-other", "family": "seedream_5_5"}]},
        {
            "defaultModel": "ep-custom",
            "bindings": [
                {"model_id": "ep-custom", "family": "seedance_2_5"},
                {"model_id": "ep-custom", "family": "seedance_2_5_flash"},
            ],
        },
    ],
)
def test_chart_rejects_incomplete_or_invalid_video_bindings(
    tmp_path: Path, values: dict[str, Any]
) -> None:
    assert render(tmp_path, {"models": {"seedance": values}}).returncode != 0


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


@pytest.mark.parametrize("enabled", [False, True])
def test_temporary_upload_maps_only_explicit_existing_secret(tmp_path: Path, enabled: bool) -> None:
    rendered = documents(
        render(
            tmp_path,
            {
                "temporaryUpload": {
                    "enabled": enabled,
                    "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
                }
            },
        )
    )
    pod = next(item for item in rendered if item["kind"] == "Deployment")["spec"]["template"][
        "spec"
    ]
    app, proxy = pod["containers"]
    env = {entry["name"]: entry for entry in app["env"]}
    assert env["MCP_TEMPORARY_UPLOAD_ENABLED"]["value"] == str(enabled).lower()
    keys = {
        "TOS_ACCESS_KEY",
        "TOS_SECRET_KEY",
        "TOS_BUCKET",
        "TOS_REGION",
        "TOS_ENDPOINT",
        "MCP_UPLOAD_CLIENT_SECRET_SHA256",
        "TOS_SECURITY_TOKEN",
    }
    if enabled:
        assert env["OBJECT_STORAGE_BACKEND"]["value"] == "tos"
        for key in keys:
            ref = env[key]["valueFrom"]["secretKeyRef"]
            assert ref["name"] == "synthetic-uploads" and ref["key"] == key
            assert ref.get("optional", False) is (key == "TOS_SECURITY_TOKEN")
    else:
        assert not keys.intersection(env)
    assert not keys.intersection(entry["name"] for entry in proxy["env"])
    assert not any(item["kind"] == "Secret" for item in rendered)
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])


@pytest.mark.parametrize(
    "values",
    [
        None,
        {"enabled": "true"},
        {"enabled": True},
        {"enabled": True, "existingSecret": ""},
        {"enabled": True, "existingSecret": "synthetic-identity"},  # pragma: allowlist secret
        {"enabled": True, "existingSecret": "synthetic-tls"},  # pragma: allowlist secret
        {"enabled": True, "existingSecret": "invalid/name"},  # pragma: allowlist secret
        {
            "enabled": True,
            "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
            "TOS_SECRET_KEY": "raw",  # pragma: allowlist secret
        },
    ],
)
def test_chart_rejects_invalid_upload_configuration(tmp_path: Path, values: dict | None) -> None:
    assert render(tmp_path, {"temporaryUpload": values}).returncode != 0


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


def irsa_values(**overrides: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
        "credentialsMode": "irsa",
        "irsa": {
            "prerequisitesConfirmed": True,
            "serviceAccountName": "synthetic-tos-signer",
            "roleTrn": "trn:iam::3000000000:role/synthetic-signing",
            **overrides,
        },
    }


def test_irsa_projects_token_only_to_app_without_static_keys(tmp_path: Path) -> None:
    from tests.unit.test_tos_irsa import irsa_settings

    rendered = documents(render(tmp_path, {"temporaryUpload": irsa_values()}))
    account = next(item for item in rendered if item["kind"] == "ServiceAccount")
    assert account["metadata"]["name"] == "synthetic-tos-signer"
    assert account["automountServiceAccountToken"] is False
    assert "annotations" not in account["metadata"]
    assert not any(item["kind"] in {"Secret", "Role", "RoleBinding"} for item in rendered)
    pod = next(item for item in rendered if item["kind"] == "Deployment")["spec"]["template"][
        "spec"
    ]
    assert pod["serviceAccountName"] == account["metadata"]["name"]
    assert pod["automountServiceAccountToken"] is False
    app, proxy = pod["containers"]
    assert {
        "name": "irsa-token",
        "mountPath": "/var/run/secrets/seed-mcp/irsa",
        "readOnly": True,
    } in app["volumeMounts"]
    assert not any(mount["name"] == "irsa-token" for mount in proxy["volumeMounts"])
    volume = next(item for item in pod["volumes"] if item["name"] == "irsa-token")
    assert volume["projected"] == {
        "defaultMode": 0o440,
        "sources": [
            {
                "serviceAccountToken": {
                    "audience": "sts.volcengine.com",
                    "expirationSeconds": 3600,
                    "path": "token",
                }
            }
        ],
    }
    env = {entry["name"]: entry for entry in app["env"]}
    assert not {"TOS_ACCESS_KEY", "TOS_SECRET_KEY", "TOS_SECURITY_TOKEN"}.intersection(env)
    assert env["TOS_CREDENTIAL_MODE"]["value"] == "irsa"
    assert env["TOS_IRSA_STS_ENDPOINT"]["value"] == "https://sts.byteplusapi.com"
    assert not any("API_KEY" in name or name.startswith("VOLCENGINE_") for name in env)
    assert not any(entry["name"].startswith("TOS_") for entry in proxy["env"])
    for key in ("TOS_BUCKET", "TOS_REGION", "TOS_ENDPOINT", "MCP_UPLOAD_CLIENT_SECRET_SHA256"):
        assert env[key]["valueFrom"]["secretKeyRef"]["name"] == "synthetic-uploads"
    settings = irsa_settings(
        tmp_path,
        **{
            key: json.loads(entry["value"]) if key.endswith("_MODEL_BINDINGS") else entry["value"]
            for key, entry in env.items()
            if "value" in entry
        },
    )
    assert settings.has_tos and settings.tos_irsa_duration_seconds == 3600


@pytest.mark.parametrize(
    "overrides",
    [
        {"prerequisitesConfirmed": False},
        {"serviceAccountName": ""},
        {"serviceAccountName": "default"},
        {"roleTrn": ""},
        {"roleTrn": "trn:iam::*:role/*"},
        {"stsEndpoint": "https://sts.volcengineapi.com"},
        {"stsEndpoint": "https://attacker.invalid"},
        {"durationSeconds": 3599},
        {"durationSeconds": 43201},
        {"accessKey": "not-accepted"},
    ],
)
def test_irsa_rejects_unverified_or_unsafe_values(tmp_path: Path, overrides: dict) -> None:
    assert render(tmp_path, {"temporaryUpload": irsa_values(**overrides)}).returncode != 0


def test_irsa_requires_uploads_and_explicit_mode(tmp_path: Path) -> None:
    values = irsa_values()
    values["enabled"] = False
    assert render(tmp_path, {"temporaryUpload": values}).returncode != 0
    values["enabled"] = True
    values["credentialsMode"] = "static"
    assert render(tmp_path, {"temporaryUpload": values}).returncode != 0


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
