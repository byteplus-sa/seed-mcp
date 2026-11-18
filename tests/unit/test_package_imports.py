"""State maintenance must not import application startup or developer dotenv."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "ark_mcp",
        "ark_mcp.config.env",
        "ark_mcp.state.stateless",
    ],
)
def test_state_import_does_not_initialize_the_server(module: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys; importlib.import_module(sys.argv[1]); "
            "assert 'ark_mcp.server' not in sys.modules",
            module,
        ],
        env={**os.environ, "ARK_MCP_ENV_FILE": "/nonexistent/synthetic-do-not-read.env"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr


def test_public_package_exports_remain_available() -> None:
    import ark_mcp
    from ark_mcp.server import create_server, mcp

    assert ark_mcp.create_server is create_server
    assert ark_mcp.mcp is mcp
    with pytest.raises(AttributeError):
        ark_mcp.__getattr__("not_an_export")
