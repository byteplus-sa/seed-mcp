"""Infrastructure ownership checks for specs/SPEC_VKE_DEPLOYMENT.md."""

import re
from pathlib import Path

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
    }
    for forbidden in (
        "provisioner ",
        'data "',
        "kubeconfig",
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
        assert forbidden not in (ROOT / "main.tf").read_text()
    assert not re.search(r"(?m)^\s*(access_key|secret_key|session_token)\s*=", source)


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
