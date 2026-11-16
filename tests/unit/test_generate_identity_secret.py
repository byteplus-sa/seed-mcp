"""Private generation never creates a server-issued client credential."""

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/byteplus_deploy/generate_identity_secret.py"


def generate(purpose: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), purpose, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("purpose", ["operator", "client"])
def test_generation_creates_private_random_secret_without_console_output(
    tmp_path: Path, purpose: str
) -> None:
    contents = []
    for index in range(2):
        path = tmp_path / str(index)
        result = generate(purpose, path)
        assert result.returncode == 0
        assert not result.stdout and not result.stderr
        assert path.stat().st_mode & 0o777 == 0o600
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


@pytest.mark.parametrize("kind", ["existing", "symlink", "fifo", "directory"])
def test_generation_refuses_existing_paths_without_replacement(tmp_path: Path, kind: str) -> None:
    import os

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
    result = generate("operator", path)
    assert result.returncode == 1
    assert not result.stdout
    assert "retained" not in result.stderr
    assert target.read_text() == "retained"
    if kind == "existing":
        assert path.read_text() == "retained"
    if kind == "symlink":
        assert path.is_symlink()


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
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=True
    )
    assert "operator" in result.stdout and "client" in result.stdout
    assert not (ROOT / "scripts/generate_mcp_key.py").exists()
