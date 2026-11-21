"""Infrastructure ownership checks for specs/SPEC_VKE_DEPLOYMENT.md."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "deploy/terraform/vke"


def test_terraform_owns_only_dedicated_network_and_vke_resources() -> None:
    source = "\n".join(path.read_text() for path in ROOT.glob("*.tf"))
    resources = re.findall(r'resource\s+"([^"]+)"\s+"([^"]+)"', source)
    assert set(resources) == {
        ("bytepluscc_vpc_vpc", "dedicated"),
        ("bytepluscc_vpc_subnet", "private"),
        ("bytepluscc_natgateway_ngw", "egress"),
        ("bytepluscc_vpc_eip", "egress"),
        ("bytepluscc_natgateway_snatentry", "private"),
        ("bytepluscc_vpc_route_table", "private_egress"),
        ("bytepluscc_vke_cluster", "dedicated"),
        ("bytepluscc_vke_node_pool", "application"),
        ("bytepluscc_vke_node_pool", "burst"),
        ("bytepluscc_apig_gateway", "public"),
    }
    for forbidden in (
        "provisioner ",
        'data "',
        "bytepluscc_vke_kubeconfig",
        "initialize_script",
        "pre_script",
        "password =",
        "secret_key =",
        "access_key =",
        "session_token =",
        "helm_release",
        "kubernetes_secret",
        "bytepluscc_vke_addon",
    ):
        assert forbidden not in source
    assert not re.search(
        r"(?m)^\s*(access_key|secret_key|session_token|api_key|iam_user_ak|iam_user_sk)\s*=",
        source,
    )


def test_terraform_keeps_fresh_state_and_locked_provider() -> None:
    versions = (ROOT / "versions.tf").read_text()
    assert 'path = "seed-mcp-vke.tfstate"' in versions
    assert 'source  = "byteplus-sdk/bytepluscc"' in versions
    assert 'version = "= 0.0.63"' in versions
    lockfile = (ROOT / ".terraform.lock.hcl").read_text()
    assert 'provider "registry.terraform.io/byteplus-sdk/bytepluscc"' in lockfile
    assert 'version     = "0.0.63"' in lockfile
    assert '"h1:' in lockfile
    assert '"zh:' in lockfile
    example = (ROOT / "terraform.tfvars.example").read_text()
    assert re.search(r"fresh_state_confirmed\s*=\s*false", example)
    assert "prerequisitesConfirmed = false" in (ROOT / "outputs.tf").read_text()


def test_optional_gateway_is_infrastructure_only_and_has_no_logging_credentials() -> None:
    source = (ROOT / "gateway.tf").read_text()
    assert "count = var.public_gateway_enabled ? 1 : 0" in source
    assert "project_name = var.project_name" in source
    assert 'type         = "standard"' in source
    assert 'instance_spec_code = "1c2g"' in source
    assert 'clb_spec_code      = "small_1"' in source
    assert 'public_network_billing_type = "traffic"' in source
    assert "try(self.log_spec.enable == false, false)" in source
    assert "before any routes or BYOK traffic" in source
    assert "do not retry creation automatically" in source
    assert not re.search(r"(?m)^\s*log_spec\s*=", source)
    assert re.search(r"monitor_spec\s*=\s*\{ enable = false \}", source)
    assert not re.search(r"(?m)^\s*trace_spec\s*=", source)
    assert "try(self.trace_spec.enable == false, false)" in source
    for forbidden in ("custom_log", "request_headers", "apm_trace_spec", "tls_trace_spec"):
        assert forbidden not in source
    example = (ROOT / "terraform.tfvars.example").read_text()
    assert re.search(r"public_gateway_enabled\s*=\s*false", example)
    assert re.search(r'gateway_secondary_zone_id\s*=\s*""', example)
    outputs = (ROOT / "outputs.tf").read_text()
    assert 'output "public_gateway_id"' in outputs
    assert "no service, route, default domain" in outputs


def test_all_terraform_runs_use_mocked_plans_only() -> None:
    test = (ROOT / "tests/deployment.tftest.hcl").read_text()
    assert 'mock_provider "bytepluscc"' in test
    runs = re.findall(r'run "([^"]+)"', test)
    commands = re.findall(r"command\s*=\s*(\w+)", test)
    assert len(runs) >= 12
    assert len(commands) == len(runs)
    assert set(commands) == {"plan"}
    assert "expect_failures = [var.fresh_state_confirmed]" in test
    assert "expect_failures = [var.node_count]" in test
    assert "expect_failures = [var.vpc_cidr]" in test


@pytest.mark.parametrize("minor", [27, 28, 29])
def test_terraform_mocks_reject_versions_below_chart_floor(minor: int) -> None:
    test = (ROOT / "tests/deployment.tftest.hcl").read_text()
    run = re.search(rf'run "reject_kubernetes_1_{minor}" \{{(.*?)\n\}}', test, re.DOTALL)
    assert run is not None
    assert f'kubernetes_version = "1.{minor}"' in run[1]
    assert "expect_failures = [var.kubernetes_version]" in run[1]


def test_terraform_version_floor_is_not_a_maintained_release_or_inventory_claim() -> None:
    variables = (ROOT / "variables.tf").read_text()
    version = variables.split('variable "kubernetes_version" {', 1)[1].split('\nvariable "', 1)[0]
    assert ">= 30" in version
    assert ">=1.30" in version
    assert "currently maintained regional VKE" in version
    assert "operator-verified" in version.lower()
    assert "not an availability or maintenance claim" in version
    assert "default" not in version
    test = (ROOT / "tests/deployment.tftest.hcl").read_text()
    assert 'run "accept_kubernetes_compatibility_floor_only"' in test
    assert "not regional VKE inventory" in test
    assert 'kubernetes_version = "1.30"' in test


def test_safe_outputs_remove_application_storage_coupling_not_cloud_resources() -> None:
    source = (ROOT / "main.tf").read_text()
    outputs = (ROOT / "outputs.tf").read_text()
    variables = (ROOT / "variables.tf").read_text()
    assert "single-writer" not in source
    assert "exactly one replica" not in variables
    assert "storage =" not in outputs
    assert "var.zone_id" not in outputs
    assert "var.project_name" not in outputs
    assert "VKE-admin-owned CCM" in outputs
    assert "CSI is not an application prerequisite" in outputs
    assert "Preserve legacy volumes" not in outputs
    assert "do not decommission cloud resources" in outputs
    assert "surge/draining capacity" in outputs
    assert "metrics API and existing identity/TLS Secrets" in outputs
    assert "PostgreSQL" not in outputs
    assert "AZ-failure resilience" in variables
    assert re.search(r"auto_scaling = \{\s+enabled\s+= false", source)
    assert "depends_on = [bytepluscc_vpc_route_table.private_egress]" in source
