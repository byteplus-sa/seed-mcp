"""Client uploader is explicit, stream-only and independent of MCP server settings."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import respx

from ark_mcp import file_upload
from tests.contract.test_files_api import BASE, FILE, URL


def test_import_does_not_construct_settings(monkeypatch) -> None:
    settings = Mock(side_effect=AssertionError("client must not construct server settings"))
    monkeypatch.setattr("ark_mcp.config.env.Settings", settings)
    importlib.reload(file_upload)
    settings.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--file", "/tmp/synthetic"],
        ["--file", "/tmp/synthetic", "--confirm-upload", "--api-key-env", "not-a-name"],
        ["--file", "/tmp/synthetic", "--confirm-upload"],
    ],
)
@respx.mock
def test_missing_consent_or_key_fails_before_upload(monkeypatch, arguments) -> None:
    monkeypatch.setattr(sys, "argv", ["seed-mcp-upload", *arguments])
    with pytest.raises(SystemExit) as caught:
        file_upload.main()
    assert caught.value.code == 2
    assert not respx.calls


@respx.mock
def test_stdout_has_id_but_no_signed_url_or_key(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "input.png"
    path.write_bytes(b"tiny-synthetic")
    route = respx.post(BASE + "/files").respond(200, json=FILE | {"download_url": URL})
    monkeypatch.setenv("UPLOAD_TEST_KEY", "synthetic-client-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed-mcp-upload",
            "--file",
            str(path),
            "--api-key-env",
            "UPLOAD_TEST_KEY",
            "--confirm-upload",
        ],
    )
    file_upload.main()
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert data["id"] == FILE["id"] and data["next_tool"] == "ark_file_get"
    assert URL not in output.out and "synthetic-client-key" not in output.out + output.err
    assert route.calls.last.request.headers["Authorization"] == "Bearer synthetic-client-key"
    assert route.call_count == 1


@respx.mock
async def test_client_does_not_retry_mutations(tmp_path: Path) -> None:
    from ark_mcp.domain.errors import ProviderError

    path = tmp_path / "input"
    path.write_bytes(b"synthetic")
    route = respx.post(BASE + "/files").respond(500, json={"error": {"code": "InternalError"}})
    with pytest.raises(ProviderError) as caught:
        await file_upload.upload_local_file(file_path=str(path), api_key="synthetic-client-key")
    assert caught.value.ambiguous_completion
    assert route.call_count == 1
