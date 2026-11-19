"""CI enforces direct HTTP gates and offline quality checks."""

import re
from pathlib import Path

import pytest
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
        "hosted_acceptance.py",
    ):
        assert f"scripts/{name}" in types
    assert "inspect_runtime_state.py" not in types
    assert not (ROOT / "scripts/inspect_runtime_state.py").exists()
    assert "$(UV) run mypy src" in types
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
    assert "scripts/prepare_vke_terraform.py validate" in scripts
    helper = (ROOT / "scripts/prepare_vke_terraform.py").read_text()
    assert '"test"' in helper
    assert "helm lint deploy/helm/seed-mcp" in scripts
    assert "-lockfile=readonly" in helper
    assert "tests/unit/test_tos_irsa.py" in scripts
    assert "tests/integration/test_tos_irsa.py" in scripts
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
    assert template_exclusion.search("deploy/helm/seed-mcp/templates/deployment.yaml")
    assert not template_exclusion.search("deploy/helm/seed-mcp/values.yaml")
    assert not template_exclusion.search(".github/workflows/ci.yml")
    assert hooks["mypy"]["entry"] == "make typecheck"


def test_ci_offline_tests_exclude_postgres_and_preserve_quality_gates() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = {step["name"]: step for step in workflow["jobs"]["quality"]["steps"]}
    offline = steps["Offline tests with coverage"]
    assert offline["env"]["COVERAGE_FILE"] == ".coverage.offline"
    for flag in (
        "--disable-socket",
        "--allow-unix-socket",
        "--cov=ark_mcp",
        "--cov-branch",
        "--cov-report=",
        "--cov-fail-under=85",
    ):
        assert flag in offline["run"].split()
    for gate in (
        "Verify lockfile and install",
        "Lint and format check",
        "Type check",
        "Mock-provider HTTPS acceptance and bounded load",
        "Static security scan",
        "Dependency vulnerability audit",
        "Secret scan",
        "Build wheel and source distribution",
        "Smoke-test installed wheel",
    ):
        assert gate in steps
        assert "continue-on-error" not in steps[gate]
    for name in ("docs.yml", "codeql.yml", "terraform.yml"):
        assert (ROOT / ".github/workflows" / name).is_file()


@pytest.mark.parametrize("lane", ["offline"])
def test_ci_uploads_hidden_coverage_as_required_pinned_artifacts(lane: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["quality" if lane == "offline" else "postgres"]
    upload = next(
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", upload["uses"])
    assert upload["with"]["name"] == f"coverage-{lane}"
    assert upload["with"]["path"] == f".coverage.{lane}"
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["if-no-files-found"] == "error"


def test_ci_kubernetes_schema_check_is_strict_pinned_and_floor_aware() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    env = workflow["env"]
    assert env["KUBERNETES_FLOOR_VERSION"] == "1.30.0"
    assert re.fullmatch(r"[0-9a-f]{40}", env["KUBERNETES_SCHEMA_COMMIT"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["KUBECONFORM_SHA256"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", env["KUBECONFORM_VERSION"])
    assert int(env["KUBERNETES_CHECK_VERSION"].split(".")[1]) >= 30
    steps = {step["name"]: step for step in workflow["jobs"]["quality"]["steps"]}
    install = steps["Install checksum-verified validation tools"]["run"]
    assert "releases/download/v${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" in install
    assert '"$KUBECONFORM_SHA256"' in install
    assert "sha256sum --check" in install
    assert "KUBECONFORM_BIN=" in install
    command = steps["Strict Kubernetes floor and upstream compatibility"]["run"]
    assert '"$KUBERNETES_FLOOR_VERSION" "$KUBERNETES_CHECK_VERSION"' in command
    assert "kubeconform -strict -summary -exit-on-error" in command
    assert '-kubernetes-version "$version"' in command
    assert '-cache "$schema_cache"' in command
    assert "/${KUBERNETES_SCHEMA_COMMIT}/{{.NormalizedKubernetesVersion}}" in command
    assert "{{.StrictSuffix}}" in command
    assert "for autoscaling in true false" in command
    assert "for upload_mode in disabled static irsa" in command
    assert "temporaryUpload.irsa.prerequisitesConfirmed=true" in command
    assert "serviceaccount-v1" in command
    assert "for version in 1.27.0 1.28.0 1.29.0" in command
    assert "grep -F 'requires kubeVersion'" in command
    assert 'test -s "$schema_cache/$key"' in command
    assert 'cp "$schema_cache/$key" "$directory/$schema.json"' in command
    assert "KUBERNETES_SCHEMA_LOCATION=" in command
    assert "KUBERNETES_DEPLOYMENT_VERSION=" in command
    assert '>> "$GITHUB_ENV"' in command
    for forbidden in ("-ignore-missing-schemas", "-insecure-skip-tls-verify", "-skip ", "kubectl"):
        assert forbidden not in command
