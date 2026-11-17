"""Private generation never creates a server-issued client credential."""

import os
import re
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate_identity_secret.py"


def generate(purpose: str, path: Path, *, umask: int = -1) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), purpose, str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        umask=umask,
    )


@pytest.mark.parametrize("purpose", ["operator", "client"])
@pytest.mark.parametrize("umask", [0o000, 0o077, 0o777])
def test_generation_creates_private_random_secret_without_console_output(
    tmp_path: Path, purpose: str, umask: int
) -> None:
    contents = []
    for index in range(2):
        path = tmp_path / str(index)
        result = generate(purpose, path, umask=umask)
        assert result.returncode == 0
        assert not result.stdout and not result.stderr
        assert path.stat().st_mode & 0o777 == 0o600
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        content = path.read_text()
        if purpose == "operator":
            values = dict(line.split("=", 1) for line in content.splitlines())
            assert set(values) == {"MCP_IDENTITY_HMAC_KEY", "MCP_IDENTITY_KEY_VERSION"}
            assert values["MCP_IDENTITY_KEY_VERSION"] == "1"
            secret = values["MCP_IDENTITY_HMAC_KEY"]
        else:
            secret = content.strip()
        assert re.fullmatch("[a-f0-9]{64}", secret)
        contents.append(secret)
    assert contents[0] != contents[1]


@pytest.mark.parametrize("purpose", ["operator", "client"])
@pytest.mark.parametrize("kind", ["existing", "symlink", "fifo", "directory"])
def test_generation_refuses_existing_paths_without_replacement(
    tmp_path: Path, kind: str, purpose: str
) -> None:
    path = tmp_path / "secret"
    target = tmp_path / "target"
    target.write_text("retained")
    if kind == "existing":
        path.write_text("retained")
    elif kind == "symlink":
        path.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.mkdir()
    before = path.lstat()
    result = generate(purpose, path)
    assert result.returncode == 1
    assert not result.stdout
    assert result.stderr == (
        "Cannot create secret file. Use a new path in a same-owner mode-0700 directory.\n"
    )
    after = path.lstat()
    assert (after.st_ino, after.st_mode, after.st_mtime_ns) == (
        before.st_ino,
        before.st_mode,
        before.st_mtime_ns,
    )
    assert target.read_text() == "retained"
    if kind == "existing":
        assert path.read_text() == "retained"
    if kind == "symlink":
        assert path.is_symlink()


@pytest.mark.parametrize("mode", [0o500, 0o750, 0o755, 0o770, 0o1700])
def test_generation_rejects_non_private_modes_without_chmod(tmp_path: Path, mode: int) -> None:
    directory = tmp_path / "parent"
    directory.mkdir()
    directory.chmod(mode)
    try:
        result = generate("operator", directory / "secret")
        assert result.returncode == 1
        assert not result.stdout
        assert stat.S_IMODE(directory.stat().st_mode) == mode
        assert list(directory.iterdir()) == []
    finally:
        directory.chmod(0o700)


def test_generation_rejects_symlink_parent_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "private"
    target.mkdir(mode=0o700)
    directory = tmp_path / "alias"
    directory.symlink_to(target, target_is_directory=True)
    result = generate("client", directory / "secret")
    assert result.returncode == 1
    assert not result.stdout
    assert directory.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert list(target.iterdir()) == []


def test_generation_requires_private_parent_and_rejects_old_purpose(tmp_path: Path) -> None:
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    for purpose, path in [
        ("operator", directory / "secret"),
        ("operator", tmp_path / "missing" / "secret"),
        ("api_key", tmp_path / "secret"),
    ]:
        assert generate(purpose, path).returncode != 0
        assert not path.exists()


def test_concurrent_generators_cannot_replace_each_other(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: generate("client", path), range(2)))
    assert sorted(result.returncode for result in results) == [0, 1]
    assert re.fullmatch("[a-f0-9]{64}\n", path.read_text())


def test_help_is_offline_and_old_helper_is_removed() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert "operator" in result.stdout and "client" in result.stdout
    assert not (ROOT / "scripts/generate_mcp_key.py").exists()
    assert not (ROOT / "scripts/byteplus_deploy/generate_identity_secret.py").exists()
