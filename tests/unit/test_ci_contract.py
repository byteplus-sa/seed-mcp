"""CI must exercise the currently shipped direct HTTP surface."""

import re
from pathlib import Path

import yaml

from ark_mcp.config.env import Settings
from ark_mcp.tools._catalog import CATALOG

ROOT = Path(__file__).resolve().parents[2]


def test_container_smoke_inventory_matches_default_http_catalog() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["container"]["steps"]
        if step.get("name") == "Exercise health endpoint"
    )
    match = re.search(r"\.result\.tools \| length == (\d+)", step["run"])
    assert match is not None
    settings = Settings.model_construct(mcp_transport="http", omnihuman_enabled=False)
    assert int(match[1]) == sum(entry.gate(settings) for entry in CATALOG)
    assert "BYTEPLUS_MODELARK_API_KEY" not in step["run"]
    assert '"dry_run":true' in step["run"]


def test_readiness_ci_checks_maintained_scripts_and_real_proxy() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["quality"]["steps"]}
    assert steps["Type check"]["run"] == "make typecheck"
    types = (ROOT / "Makefile").read_text()
    for name in (
        "live_smoke_test.py",
        "live_smoke_test_variations.py",
        "generate_identity_secret.py",
        "inspect_runtime_state.py",
        "hosted_acceptance.py",
    ):
        assert f"scripts/{name}" in types
    acceptance = steps["Mock-provider HTTPS acceptance and bounded load"]["run"]
    assert 'scripts/hosted_acceptance.py --caddy-bin "$CADDY_BIN"' in acceptance
    assert "--execute" not in acceptance


def test_ci_secret_scan_enforces_findings_without_regenerating_baseline() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["quality"]["steps"]}
    command = steps["Secret scan"]["run"]
    assert "git ls-files -z" in command
    assert "xargs -0" in command
    assert "detect-secrets-hook --no-verify --baseline .secrets.baseline" in command
    assert "detect-secrets scan" not in command
    assert "|| true" not in command


def test_infrastructure_ci_does_not_apply_or_use_retired_vm_workflow() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/terraform.yml").read_text())
    scripts = "\n".join(step.get("run", "") for step in workflow["jobs"]["validate"]["steps"])
    assert "deploy/terraform/vke test" in scripts
    assert "helm lint deploy/helm/seed-mcp" in scripts
    assert "-lockfile=readonly" in scripts
    for retired in (
        "deploy/compose",
        "deploy/terraform/byteplus",
        "byteplus_deploy",
        "activate.sh",
    ):
        assert retired not in scripts
    assert not re.search(r"\b(?:apply|destroy|kubectl)\b", scripts)


def test_hooks_keep_plain_yaml_checks_and_use_shared_typecheck() -> None:
    configuration = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooks = {hook["id"]: hook for repo in configuration["repos"] for hook in repo["hooks"]}
    template_exclusion = re.compile(hooks["check-yaml"]["exclude"])
    assert template_exclusion.search("deploy/helm/seed-mcp/templates/statefulset.yaml")
    assert not template_exclusion.search("deploy/helm/seed-mcp/values.yaml")
    assert not template_exclusion.search(".github/workflows/ci.yml")
    assert hooks["mypy"]["entry"] == "make typecheck"
