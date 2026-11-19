"""Prepare dedicated VKE Terraform source or run isolated mock-only checks.

Implements the preparation boundary in specs/SPEC_VKE_DEPLOYMENT.md.
Never obtains credentials, runs a live plan, applies resources or loads .env.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "terraform" / "vke"
SOURCE_FILES = (
    "main.tf",
    "variables.tf",
    "outputs.tf",
    "versions.tf",
    ".terraform.lock.hcl",
    "terraform.tfvars.example",
    "tests/deployment.tftest.hcl",
)
MIN_TERRAFORM = (1, 17, 1)


def _copy_source(destination: Path) -> None:
    """Copy only reviewed source; exclude state, credentials and operator inputs."""
    for name in SOURCE_FILES:
        source = ROOT / name
        if not stat.S_ISREG(source.lstat().st_mode):
            raise ValueError("Terraform source must contain regular files, not symlinks.")
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(source.read_bytes())


def prepare(destination: Path) -> None:
    """Create a new private operator directory without touching existing state."""
    if not destination.is_absolute() or destination.name in ("", ".", ".."):
        raise ValueError("Supply a new absolute directory path.")
    parent = destination.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError("The existing parent must be same-owner, mode 0700 and not a symlink.")
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    _copy_source(destination)
    with (destination / "terraform.tfvars").open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write((destination / "terraform.tfvars.example").read_bytes())
    print(
        "Prepared private Terraform source. Regional inputs and fresh-state approval remain unset."
    )


def validate(terraform_bin: str) -> None:
    """Check copied source with no operator environment, backend or live provider plans."""
    executable = shutil.which(terraform_bin)
    if executable is None:
        raise ValueError("Terraform is unavailable; install a reviewed Terraform >=1.17.1,<2.0.")
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="seed-vke-validation-") as temporary:
        scratch = Path(temporary)
        source = scratch / "source"
        source.mkdir(mode=0o700)
        home = scratch / "home"
        home.mkdir(mode=0o700)
        _copy_source(source)
        # Do not inherit TF_VAR_*, CLI flags, tokens, CLI config or provider credentials.
        env = {
            "PATH": os.defpath,
            "HOME": str(home),
            "TMPDIR": str(scratch),
            "TF_DATA_DIR": str(scratch / "data"),
            "TF_IN_AUTOMATION": "true",
            "TF_INPUT": "false",
            "CHECKPOINT_DISABLE": "1",
        }
        version = subprocess.run(
            [executable, "version", "-json"],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        metadata = json.loads(version.stdout)
        value = metadata.get("terraform_version") if isinstance(metadata, dict) else None
        match = (
            re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", value) if isinstance(value, str) else None
        )
        if match is None or not (MIN_TERRAFORM <= tuple(map(int, match.groups())) < (2, 0, 0)):
            raise ValueError("Use a stable reviewed Terraform >=1.17.1,<2.0.")
        for arguments in (
            ["fmt", "-check", "-recursive"],
            ["init", "-backend=false", "-input=false", "-lockfile=readonly", "-no-color"],
            ["validate", "-no-color"],
            ["test", "-no-color"],
        ):
            print(f"Terraform {arguments[0]}: isolated source and mock providers.", flush=True)
            subprocess.run(
                [executable, *arguments],
                cwd=source,
                env=env,
                check=True,
                timeout=300,
            )
    print(
        "Source checks passed. No live plan, cloud provisioning or capacity acceptance was performed."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="Create a new private dedicated source copy.")
    preparation.add_argument("directory", type=Path, help="New absolute path in a private parent.")
    validation = commands.add_parser(
        "validate", help="Run isolated Terraform checks and mock plans."
    )
    validation.add_argument(
        "--terraform-bin", default="terraform", help="Reviewed Terraform binary."
    )
    args = parser.parse_args(argv)
    if os.name != "posix":
        parser.error("Preparation requires POSIX private file permissions.")
    try:
        if args.command == "prepare":
            prepare(args.directory)
        else:
            validate(args.terraform_bin)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Exception details can include Terraform output or operator paths; keep stderr bounded.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Terraform preparation failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
