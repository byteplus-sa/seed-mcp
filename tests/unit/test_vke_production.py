"""Production APIG source gates, never live trust or launch acceptance."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_vke_chart import CHART, documents, render
from tests.unit.test_vke_staging import BACKEND, PUBLIC, staging


def production() -> dict[str, Any]:
    values = staging()
    values["service"].update(mode="apig-production", productionConfirmed=True)
    return values


def test_production_remains_private_and_preserves_runtime_boundaries(tmp_path: Path) -> None:
    items = documents(render(tmp_path, production()))
    service = next(item for item in items if item["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [
        {"name": "https", "port": 8443, "targetPort": "https", "protocol": "TCP"}
    ]
    assert "annotations" not in service["metadata"]
    assert "externalTrafficPolicy" not in service["spec"]
    policy = next(item for item in items if item["kind"] == "NetworkPolicy")["spec"]
    assert policy["podSelector"]["matchLabels"] == service["spec"]["selector"]
    assert policy["policyTypes"] == ["Ingress"]
    assert policy["ingress"] == [
        {
            "from": [{"ipBlock": {"cidr": "10.80.48.0/20"}}],
            "ports": [{"protocol": "TCP", "port": 8443}],
        }
    ]
    proxy = (CHART / "files/Caddyfile.apig-production").read_text()
    config = next(item for item in items if item["kind"] == "ConfigMap")
    assert config["data"]["Caddyfile"] == proxy
    deployment = next(item for item in items if item["kind"] == "Deployment")
    template = deployment["spec"]["template"]
    annotations = template["metadata"]["annotations"]
    assert annotations["checksum/proxy"] == hashlib.sha256(proxy.encode()).hexdigest()
    assert annotations["cluster-autoscaler.kubernetes.io/safe-to-evict-local-volumes"] == (
        "app-tmp,proxy-tmp"
    )
    assert "cluster-autoscaler.kubernetes.io/safe-to-evict" not in annotations
    pod = template["spec"]
    assert pod["terminationGracePeriodSeconds"] == 660
    assert pod["topologySpreadConstraints"][0]["minDomains"] == 2
    assert pod["topologySpreadConstraints"][0]["whenUnsatisfiable"] == "DoNotSchedule"
    assert deployment["spec"]["strategy"]["rollingUpdate"] == {
        "maxUnavailable": 0,
        "maxSurge": 1,
    }
    assert (
        next(item for item in items if item["kind"] == "PodDisruptionBudget")["spec"][
            "minAvailable"
        ]
        == 1
    )
    env = {item["name"]: item.get("value") for item in pod["containers"][0]["env"]}
    assert env["MCP_HOST"] == "127.0.0.1"
    assert env["STATE_BACKEND"] == "none"
    assert "MCP_TEMPORARY_UPLOAD_ENABLED" not in env
    assert "MCP_UPLOAD_CLIENT_SECRET_SHA256" not in env
    assert not any(key.startswith("TOS_") for key in env)
    assert "serviceAccountName" not in pod
    assert pod["automountServiceAccountToken"] is False
    assert not any(item["kind"] == "ServiceAccount" for item in items)
    assert not any("API_KEY" in key for key in env)
    assert not any(item["kind"] in ("Secret", "PersistentVolumeClaim") for item in items)


@pytest.mark.parametrize(
    "override",
    [
        {"backendHost": ""},
        {"backendHost": PUBLIC},
        {"backendHost": "bad..invalid"},
        {"service": {"productionConfirmed": False}},
        {"service": {"productionConfirmed": "true"}},
        {"service": {"subnetId": "subnet-unwanted"}},
        {"service": {"sourceRanges": []}},
        *[
            {"service": {"sourceRanges": [cidr]}}
            for cidr in (
                "10.0.0.0/7",
                "172.16.0.0/11",
                "192.168.0.0/15",
                "203.0.113.0/24",
            )
        ],
        {
            "temporaryUpload": {
                "enabled": True,
                "existingSecret": "synthetic-uploads",  # pragma: allowlist secret
            }
        },
    ],
)
def test_production_rejects_missing_gates_or_public_exposure(
    tmp_path: Path,
    override: dict[str, Any],
) -> None:
    values = production()
    for name, value in override.items():
        if name == "service":
            values[name].update(value)
        else:
            values[name] = value
    assert render(tmp_path, values).returncode != 0


@pytest.mark.parametrize("values", [{}, staging()])
def test_production_acknowledgement_is_not_valid_for_other_modes(
    tmp_path: Path,
    values: dict[str, Any],
) -> None:
    values = {**values, "service": {**values.get("service", {}), "productionConfirmed": True}}
    assert render(tmp_path, values).returncode != 0


@pytest.mark.parametrize("values", [{}, staging(), production()])
def test_versioned_tls_reference_changes_pod_template(
    tmp_path: Path, values: dict[str, Any]
) -> None:
    def template(overrides: dict[str, Any]) -> dict[str, Any]:
        return next(
            item for item in documents(render(tmp_path, overrides)) if item["kind"] == "Deployment"
        )["spec"]["template"]

    original = template(values)
    assert original == template(values)  # Same-name external data is not hashed by Helm.
    renewed = template({**values, "tlsSecretName": "renewed-tls-v2"})
    assert (
        original["metadata"]["annotations"]["checksum/runtime"]
        != renewed["metadata"]["annotations"]["checksum/runtime"]
    )
    assert (
        original["metadata"]["annotations"]["checksum/proxy"]
        == renewed["metadata"]["annotations"]["checksum/proxy"]
    )
    tls = next(item for item in renewed["spec"]["volumes"] if item["name"] == "tls")
    assert tls["secret"]["secretName"] == "renewed-tls-v2"  # pragma: allowlist secret


def test_all_modes_select_different_proxy_content(tmp_path: Path) -> None:
    hashes = set()
    for values in ({}, staging(), production()):
        deployment = next(
            item for item in documents(render(tmp_path, values)) if item["kind"] == "Deployment"
        )
        hashes.add(deployment["spec"]["template"]["metadata"]["annotations"]["checksum/proxy"])
    assert len(hashes) == 3
    assert production()["backendHost"] == BACKEND
