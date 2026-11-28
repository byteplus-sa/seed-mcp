"""Offline CLI contract for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "configure_http_client.py"
URL = "https://mcp.example.com/mcp"
CLIENTS = ("codex", "claude-code")
PROVIDERS = {
    "modelark": ("X-ModelArk-Api-Key", "SEED_MCP_MODELARK_KEY"),
    "seed-speech": ("X-Seed-Speech-Api-Key", "SEED_MCP_SEED_SPEECH_KEY"),
}
ENV_OPTIONS = (
    "--client-secret-env",
    "--modelark-key-env",
    "--seed-speech-key-env",
    "--seedance-endpoint-env",
    "--seedream-endpoint-env",
)
PROVIDER_GROUPS = [
    group
    for size in range(1, len(PROVIDERS) + 1)
    for group in itertools.combinations(PROVIDERS, size)
]


def invoke(
    directory: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(SCRIPT), *arguments],
        cwd=directory,
        env={} if env is None else env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


def parse_config(result: subprocess.CompletedProcess[str], client: str) -> dict[str, Any]:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    if client == "codex":
        return tomllib.loads(result.stdout)
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def expected_config(
    client: str,
    headers: dict[str, str],
    *,
    name: str = "seed-mcp",
    url: str = URL,
    timeout: int = 660,
) -> dict[str, Any]:
    if client == "codex":
        return {
            "mcp_servers": {
                name: {"url": url, "tool_timeout_sec": timeout, "env_http_headers": headers}
            }
        }
    return {
        "mcpServers": {
            name: {
                "type": "http",
                "url": url,
                "timeout": timeout * 1000,
                "headers": {header: "${" + variable + "}" for header, variable in headers.items()},
            }
        }
    }


def assert_rejected(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "error: invalid configuration arguments; use --help for usage.\n"


@pytest.mark.parametrize("client", CLIENTS)
def test_default_configuration_is_one_parseable_snippet(tmp_path: Path, client: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL)
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": "SEED_MCP_MODELARK_KEY",
        },
    )


@pytest.mark.parametrize("client", CLIENTS)
@pytest.mark.parametrize("providers", PROVIDER_GROUPS)
def test_each_provider_combination_emits_only_selected_headers(
    tmp_path: Path, client: str, providers: tuple[str, ...]
) -> None:
    arguments = [argument for provider in providers for argument in ("--provider", provider)]
    result = invoke(tmp_path, "--client", client, "--url", URL, *arguments)
    headers = dict(PROVIDERS[provider] for provider in providers)
    assert parse_config(result, client) == expected_config(client, headers)


@pytest.mark.parametrize("client", CLIENTS)
def test_client_secret_is_an_explicit_opt_in(tmp_path: Path, client: str) -> None:
    result = invoke(
        tmp_path,
        "--client",
        client,
        "--url",
        URL,
        "--client-secret-env",
        "SEED_MCP_CLIENT_SECRET",
    )
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": "SEED_MCP_MODELARK_KEY",
            "X-MCP-Client-Secret": "SEED_MCP_CLIENT_SECRET",  # pragma: allowlist secret
        },
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_custom_sources_endpoints_name_and_timeout(tmp_path: Path, client: str) -> None:
    result = invoke(
        tmp_path,
        "--client",
        client,
        "--url",
        URL,
        "--name",
        "Team_2-mcp",
        "--provider",
        "seed-speech",
        "--provider",
        "modelark",
        "--modelark-key-env",
        "PRIVATE_MODELARK",
        "--seed-speech-key-env",
        "PRIVATE_SPEECH",
        "--client-secret-env",
        "PRIVATE_OWNER",
        "--seedance-endpoint-env",
        "VIDEO_ENDPOINT",
        "--seedream-endpoint-env",
        "IMAGE_ENDPOINT",
        "--tool-timeout-seconds",
        "17",
    )
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": "PRIVATE_MODELARK",
            "X-Seed-Speech-Api-Key": "PRIVATE_SPEECH",
            "X-MCP-Client-Secret": "PRIVATE_OWNER",  # pragma: allowlist secret
            "X-ModelArk-Seedance-Endpoint": "VIDEO_ENDPOINT",
            "X-ModelArk-Seedream-Endpoint": "IMAGE_ENDPOINT",
        },
        name="Team_2-mcp",
        timeout=17,
    )


@pytest.mark.parametrize("client", CLIENTS)
@pytest.mark.parametrize("option", ("--seedance-endpoint-env", "--seedream-endpoint-env"))
def test_endpoint_sources_are_independently_optional(
    tmp_path: Path, client: str, option: str
) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL, option, "PRODUCT_ENDPOINT")
    product = "Seedance" if option == "--seedance-endpoint-env" else "Seedream"
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": "SEED_MCP_MODELARK_KEY",
            f"X-ModelArk-{product}-Endpoint": "PRODUCT_ENDPOINT",
        },
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_output_is_deterministic_independent_of_provider_order_and_duplicates(
    tmp_path: Path, client: str
) -> None:
    outputs = []
    for providers in (
        ("modelark", "seed-speech"),
        ("seed-speech", "modelark", "modelark"),
    ):
        arguments = [argument for provider in providers for argument in ("--provider", provider)]
        result = invoke(tmp_path, "--client", client, "--url", URL, *arguments)
        parse_config(result, client)
        outputs.append(result.stdout)
    assert len(set(outputs)) == 1


@pytest.mark.parametrize("client", CLIENTS)
def test_hostile_environment_values_are_never_expanded(tmp_path: Path, client: str) -> None:
    dummy_value = 'SYNTHETIC_ONLY_"\\\n${OTHER}\n[unsafe.table]\n$(touch should-not-exist)'
    env = dict.fromkeys(
        [
            "SEED_MCP_MODELARK_KEY",
            "SEED_MCP_SEED_SPEECH_KEY",
            "SEED_MCP_CLIENT_SECRET",
            "VIDEO_ENDPOINT",
            "IMAGE_ENDPOINT",
            "BYTEPLUS_MODELARK_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "LANGUAGE",
        ],
        dummy_value,
    )
    env.update(
        HOME=str(tmp_path),
        CODEX_HOME=str(tmp_path / "codex"),
        CLAUDE_CONFIG_DIR=str(tmp_path / "claude"),
        ARK_MCP_ENV_FILE=str(tmp_path / ".env"),
    )
    arguments = (
        "--client",
        client,
        "--url",
        URL,
        "--provider",
        "modelark",
        "--provider",
        "seed-speech",
        "--seedance-endpoint-env",
        "VIDEO_ENDPOINT",
        "--seedream-endpoint-env",
        "IMAGE_ENDPOINT",
    )
    baseline = invoke(tmp_path, *arguments)
    result = invoke(tmp_path, *arguments, env=env)
    parse_config(result, client)
    assert result.stdout == baseline.stdout
    assert "SYNTHETIC_ONLY" not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("client", CLIENTS)
def test_existing_client_and_environment_files_are_ignored_and_unchanged(
    tmp_path: Path, client: str
) -> None:
    arguments = ("--client", client, "--url", URL)
    baseline = invoke(tmp_path, *arguments)
    files = {
        filename: b"SYNTHETIC_FILE_CONTENT: invalid configuration\n"
        for filename in (".env", ".mcp.json", ".claude.json", "config.toml", "settings.json")
    }
    for filename, content in files.items():
        (tmp_path / filename).write_bytes(content)
    result = invoke(
        tmp_path,
        *arguments,
        env={
            "HOME": str(tmp_path),
            "CODEX_HOME": str(tmp_path),
            "CLAUDE_CONFIG_DIR": str(tmp_path),
            "ARK_MCP_ENV_FILE": str(tmp_path / ".env"),
        },
    )
    parse_config(result, client)
    assert result.stdout == baseline.stdout
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == files


@pytest.mark.parametrize("client", CLIENTS)
@pytest.mark.parametrize("timeout", ("1", "3600"))
def test_timeout_boundaries(tmp_path: Path, client: str, timeout: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL, "--tool-timeout-seconds", timeout)
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": "SEED_MCP_MODELARK_KEY",
        },
        timeout=int(timeout),
    )


@pytest.mark.parametrize("name", ("a", "0", "_", "-", "A" * 64))
@pytest.mark.parametrize("client", CLIENTS)
def test_server_name_boundaries(tmp_path: Path, client: str, name: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL, f"--name={name}")
    config = parse_config(result, client)
    assert list(config["mcp_servers" if client == "codex" else "mcpServers"]) == [name]


@pytest.mark.parametrize("client", CLIENTS)
def test_dash_prefixed_server_name_is_not_interpreted_as_help(tmp_path: Path, client: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL, "--name", "-h")
    config = parse_config(result, client)
    assert list(config["mcp_servers" if client == "codex" else "mcpServers"]) == ["-h"]


@pytest.mark.parametrize("variable", ("_", "a", "_9", "A" * 128))
@pytest.mark.parametrize("client", CLIENTS)
def test_environment_name_boundaries(tmp_path: Path, client: str, variable: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", URL, "--modelark-key-env", variable)
    assert parse_config(result, client) == expected_config(
        client,
        {
            "X-ModelArk-Api-Key": variable,
        },
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://mcp.example.com",
        "https://MCP.EXAMPLE.COM:443/mcp/",
        "https://mcp.example.com.:65535/mcp",
        "https://localhost:1/mcp",
        "https://127.0.0.1/mcp",
        "https://[::1]:443/mcp",
        "https://[2001:db8::1]/mcp",
        'https://mcp.example.com/path"quoted',
        "https://mcp.example.com/a%20b/%3F%23",
        "https://mcp.example.com/caf\u00e9/\U0001f680",
    ),
)
@pytest.mark.parametrize("client", CLIENTS)
def test_https_urls_round_trip_without_normalization(tmp_path: Path, client: str, url: str) -> None:
    result = invoke(tmp_path, "--client", client, "--url", url)
    config = parse_config(result, client)
    assert config["mcp_servers" if client == "codex" else "mcpServers"]["seed-mcp"]["url"] == url


@pytest.mark.parametrize(
    "url", ("http://localhost:8000/mcp", "http://127.0.0.1/mcp", "http://[::1]/mcp")
)
@pytest.mark.parametrize("client", CLIENTS)
def test_loopback_http_requires_explicit_permission(tmp_path: Path, client: str, url: str) -> None:
    assert_rejected(invoke(tmp_path, "--client", client, "--url", url))
    result = invoke(tmp_path, "--client", client, "--url", url, "--allow-loopback-http")
    parse_config(result, client)


INVALID_URLS = (
    "",
    "/mcp",
    "//mcp.example.com/mcp",
    "mcp.example.com/mcp",
    "https:/mcp.example.com/mcp",
    "https:///mcp",
    "https://",
    "ftp://mcp.example.com/mcp",
    "https://user:password@mcp.example.com/mcp",  # pragma: allowlist secret
    "https://user@mcp.example.com/mcp",
    "https://@mcp.example.com/mcp",
    "https://mcp.example.com/mcp?secret=SYNTHETIC",
    "https://mcp.example.com/mcp?",
    "https://mcp.example.com/mcp#SYNTHETIC",
    "https://mcp.example.com/mcp#",
    " https://mcp.example.com/mcp",
    "https://mcp.example.com/mcp ",
    "https://mcp.example.com/a b",
    "https://mcp.example.com/a\tb",
    "https://mcp.example.com/a\rb",
    "https://mcp.example.com/a\nb",
    "https://mcp.example.com/a\x1bb",
    "https://mcp.example.com/a\x7fb",
    "https://mcp.example.com/a\x85b",
    "https://mcp.example.com/a\u200bb",
    "https://mcp.example.com/a\u00a0b",
    "https://mcp.example.com\\@other.example/mcp",
    "https://mcp.example.com/a\\b",
    "https://mcp.example.com:/mcp",
    "https://mcp.example.com:0/mcp",
    "https://mcp.example.com:65536/mcp",
    "https://mcp.example.com:-1/mcp",
    "https://mcp.example.com:+443/mcp",
    "https://mcp.example.com:abc/mcp",
    "https://mcp.example.com:443:444/mcp",
    "https://mcp.example.com:\uff14\uff14\uff13/mcp",
    "https://:443/mcp",
    "https://.example.com/mcp",
    "https://example..com/mcp",
    "https://example.com../mcp",
    "https://-example.com/mcp",
    "https://example-.com/mcp",
    "https://exam_ple.com/mcp",
    "https://exam%70le.com/mcp",
    'https://exa"mple.com/mcp',
    "https://exa'mple.com/mcp",
    "https://example.com;bad/mcp",
    "https://*/mcp",
    "https://./mcp",
    f"https://{'a' * 64}.example.com/mcp",
    f"https://{'.'.join(['a' * 63] * 4)}/mcp",
    "https://999.1.1.1/mcp",
    "https://127.0.0.01/mcp",
    "https://127.1/mcp",
    "https://2130706433/mcp",
    "https://[::1/mcp",
    "https://::1/mcp",
    "https://[invalid]/mcp",
    "https://[v1.host]/mcp",
    "https://[127.0.0.1]/mcp",
    "https://[::1]suffix/mcp",
    "https://[::1]:/mcp",
    "https://[::1]:65536/mcp",
    "https://[::1]%zone/mcp",
    "https://[fe80::1%25lo0]/mcp",
    "http://example.com/mcp",
    "http://localhost.example.com/mcp",
    "http://127.0.0.2/mcp",
    "http://0.0.0.0/mcp",
    "http://localhost./mcp",
    "http://[::ffff:127.0.0.1]/mcp",
    "http://[0:0:0:0:0:0:0:1]/mcp",
)


@pytest.mark.parametrize("url", INVALID_URLS)
@pytest.mark.parametrize("client", CLIENTS)
def test_invalid_urls_are_rejected_without_echoing_values(
    tmp_path: Path, client: str, url: str
) -> None:
    assert_rejected(invoke(tmp_path, "--client", client, "--url", url, "--allow-loopback-http"))


@pytest.mark.parametrize(
    "name", ("", "a" * 65, "bad.name", "bad name", "\u00e9", '"]\n[evil]', "../bad", "bad\\name")
)
def test_invalid_server_names_are_rejected_without_echoing(tmp_path: Path, name: str) -> None:
    assert_rejected(invoke(tmp_path, "--client", "codex", "--url", URL, "--name", name))


@pytest.mark.parametrize("option", ENV_OPTIONS)
@pytest.mark.parametrize(
    "variable",
    ("", "A" * 129, "1BAD", "BAD-NAME", "BAD.NAME", "${KEY}", "bad value", "A\nB", "\u00e9KEY"),
)
def test_all_environment_source_options_validate_names(
    tmp_path: Path, option: str, variable: str
) -> None:
    assert_rejected(invoke(tmp_path, "--client", "codex", "--url", URL, option, variable))


@pytest.mark.parametrize("provider", ("seed-speech",))
@pytest.mark.parametrize("option", ("--seedance-endpoint-env", "--seedream-endpoint-env"))
def test_endpoint_sources_require_selected_modelark(
    tmp_path: Path, provider: str, option: str
) -> None:
    assert_rejected(
        invoke(tmp_path, "--client", "codex", "--url", URL, "--provider", provider, option, "EP")
    )


@pytest.mark.parametrize("client", CLIENTS)
@pytest.mark.parametrize(
    "arguments",
    [
        ("--provider", "vision-cv"),
        ("--omnihuman-key-env", "RETIRED_PROVIDER_KEY"),
    ],
)
def test_retired_avatar_options_are_rejected(
    tmp_path: Path, client: str, arguments: tuple[str, str]
) -> None:
    assert_rejected(invoke(tmp_path, "--client", client, "--url", URL, *arguments))


@pytest.mark.parametrize("first,second", list(itertools.combinations(ENV_OPTIONS, 2)))
def test_duplicate_sources_across_selected_headers_are_rejected(
    tmp_path: Path, first: str, second: str
) -> None:
    assert_rejected(
        invoke(
            tmp_path,
            "--client",
            "codex",
            "--url",
            URL,
            "--provider",
            "modelark",
            "--provider",
            "seed-speech",
            first,
            "SAME_SOURCE",
            second,
            "SAME_SOURCE",
        )
    )


def test_custom_source_cannot_reuse_selected_default_source(tmp_path: Path) -> None:
    assert_rejected(
        invoke(
            tmp_path,
            "--client",
            "codex",
            "--url",
            URL,
            "--client-secret-env",
            "SEED_MCP_MODELARK_KEY",
        )
    )


@pytest.mark.parametrize("client", CLIENTS)
def test_unselected_source_duplicates_are_ignored(tmp_path: Path, client: str) -> None:
    result = invoke(
        tmp_path,
        "--client",
        client,
        "--url",
        URL,
        "--seed-speech-key-env",
        "SEED_MCP_MODELARK_KEY",
    )
    baseline = invoke(tmp_path, "--client", client, "--url", URL)
    parse_config(result, client)
    assert result.stdout == baseline.stdout


@pytest.mark.parametrize(
    "timeout", ("", "0", "-1", "3601", "1.5", "true", "SYNTHETIC", "9" * 5000, "\uff11", "1_0")
)
def test_invalid_timeouts_are_rejected_without_echoing(tmp_path: Path, timeout: str) -> None:
    assert_rejected(
        invoke(tmp_path, "--client", "codex", "--url", URL, "--tool-timeout-seconds", timeout)
    )


@pytest.mark.parametrize(
    "arguments",
    (
        (),
        ("--client", "codex"),
        ("--url", URL),
        ("--client", "SYNTHETIC"),
        ("--client", "claude"),
        ("--client", "codex", "--url", URL, "--provider", ""),
        ("--client", "codex", "--url", URL, "--provider", "SYNTHETIC"),
        ("--client", "codex", "--url", URL, "--provider", "ModelArk"),
        ("--client", "codex", "--url", URL, "--auth", "SYNTHETIC"),
        ("--client", "codex", "--url", URL, "--SYNTHETIC"),
        ("--client", "codex", "--url", URL, "--allow-loopback-http=SYNTHETIC"),
        ("--client", "codex", "--url", URL, "SYNTHETIC"),
        ("--client", "codex", "--url", URL, "--name"),
        ("--client", "codex", "--url", URL, "--modelark-key-env"),
        ("--cli", "codex", "--url", URL),
        ("@SYNTHETIC",),
    ),
)
def test_cli_errors_are_generic_and_value_free(tmp_path: Path, arguments: tuple[str, ...]) -> None:
    assert_rejected(invoke(tmp_path, *arguments))


def test_equals_form_flags_are_supported(tmp_path: Path) -> None:
    result = invoke(tmp_path, "--client=codex", f"--url={URL}", "--provider=modelark")
    baseline = invoke(tmp_path, "--client", "codex", "--url", URL)
    parse_config(result, "codex")
    assert result.stdout == baseline.stdout


@pytest.mark.parametrize("flag", ("-h", "--help"))
def test_help_describes_private_environment_and_preflight_limit(tmp_path: Path, flag: str) -> None:
    result = invoke(tmp_path, flag)
    assert result.returncode == 0
    assert result.stderr == ""
    for phrase in (
        "--client",
        "codex",
        "claude-code",
        "--provider",
        "--tool-timeout-seconds",
        "--allow-loopback-http",
        *ENV_OPTIONS,
        "private client process environment",
        "preflight",
        "authenticate",
    ):
        assert phrase in result.stdout


GUARDED_RUNNER = textwrap.dedent(
    """\
    import ast
    import builtins
    import importlib
    import io
    import os
    import sys

    script, *arguments = sys.argv[1:]
    with open(script, encoding="utf-8") as source_file:
        source = source_file.read()
    tree = ast.parse(source, script)
    for node in ast.walk(tree):
        modules = (
            [alias.name for alias in node.names] if isinstance(node, ast.Import)
            else [node.module] if isinstance(node, ast.ImportFrom)
            else []
        )
        for module in modules:
            assert module and module.split(".")[0] in sys.stdlib_module_names
            importlib.import_module(module)
    code = compile(tree, script, "exec")

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden side effect")

    class NoEnvironment:
        __getitem__ = forbidden
        __setitem__ = forbidden
        __delitem__ = forbidden
        __iter__ = forbidden
        __len__ = forbidden
        __contains__ = forbidden
        get = forbidden
        keys = forbidden
        values = forbidden
        items = forbidden
        copy = forbidden

    os.environ = NoEnvironment()
    os.environb = NoEnvironment()
    os.getenv = forbidden
    os.getenvb = forbidden
    builtins.open = forbidden
    io.open = forbidden
    for name in ("open", "stat", "lstat", "access", "listdir", "scandir", "getcwd"):
        setattr(os, name, forbidden)

    def audit(event, args):
        if event == "open" or event.startswith(("os.", "socket.", "subprocess.", "ctypes.")):
            forbidden()

    sys.addaudithook(audit)
    sys.argv = [script, *arguments]
    exec(code, {"__name__": "__main__", "__file__": script})
    """
)


@pytest.mark.parametrize(
    "arguments",
    (
        ("--client", "codex", "--url", URL),
        ("--client", "codex", "--url", URL, "--client-secret-env", "PRIVATE_CLIENT_SECRET"),
        ("--client", "claude-code", "--url", URL, "--seedance-endpoint-env", "VIDEO_EP"),
        ("--help",),
        (),
        ("--client", "codex", "--url", "https://bad:port"),
        ("--client", "SYNTHETIC", "--url", URL),
        ("--unknown", "SYNTHETIC"),
        ("--client",),
    ),
)
def test_generation_help_and_errors_have_no_environment_file_network_or_client_access(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", GUARDED_RUNNER, str(SCRIPT), *arguments],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    baseline = invoke(tmp_path, *arguments)
    assert result.returncode == baseline.returncode
    assert result.stdout == baseline.stdout
    assert result.stderr == baseline.stderr
    assert "forbidden side effect" not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
