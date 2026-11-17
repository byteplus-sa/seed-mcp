"""Pure stdout client snippets for specs/SPEC_HOSTED_BYOK.md."""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from urllib.parse import urlsplit

DEFAULT_OPTIONS = {
    "--client": "",
    "--url": "",
    "--name": "seed-mcp",
    "--client-secret-env": "SEED_MCP_CLIENT_SECRET",
    "--modelark-key-env": "SEED_MCP_MODELARK_KEY",
    "--seed-speech-key-env": "SEED_MCP_SEED_SPEECH_KEY",
    "--omnihuman-key-env": "SEED_MCP_OMNIHUMAN_KEY",
    "--tool-timeout-seconds": "660",
}
PROVIDER_HEADERS = {
    "modelark": ("X-ModelArk-Api-Key", "--modelark-key-env"),
    "seed-speech": ("X-Seed-Speech-Api-Key", "--seed-speech-key-env"),
    "vision-cv": ("X-OmniHuman-Api-Key", "--omnihuman-key-env"),
}
ENDPOINT_HEADERS = {
    "--seedance-endpoint-env": "X-ModelArk-Seedance-Endpoint",
    "--seedream-endpoint-env": "X-ModelArk-Seedream-Endpoint",
}
HELP = """\
Usage: python scripts/configure_http_client.py --client codex|claude-code --url URL

Print one TOML (Codex) or JSON (Claude Code) snippet to stdout.
This generator never reads environment values, writes files, contacts a server,
or runs or changes a client. Key values belong in the private client process environment,
never in these flags. The connection preflight cannot authenticate them upstream.

Options:
  --client codex|claude-code       Required output format.
  --url URL                       Required absolute HTTPS MCP endpoint.
  --name NAME                     Server name (default: seed-mcp), 1-64 ASCII
                                  letters, digits, underscores or hyphens.
  --provider PROVIDER             Repeat for modelark, seed-speech or vision-cv.
                                  Default: modelark. Repeats are deduplicated.
  --client-secret-env VAR         Default: SEED_MCP_CLIENT_SECRET.
  --modelark-key-env VAR          Default: SEED_MCP_MODELARK_KEY.
  --seed-speech-key-env VAR       Default: SEED_MCP_SEED_SPEECH_KEY.
  --omnihuman-key-env VAR         Default: SEED_MCP_OMNIHUMAN_KEY.
  --seedance-endpoint-env VAR     Optional video endpoint source; needs modelark.
  --seedream-endpoint-env VAR     Optional image endpoint source; needs modelark.
  --tool-timeout-seconds INTEGER  1-3600 (default: 660). Claude uses milliseconds.
  --allow-loopback-http           Allow HTTP only for literal localhost,
                                  127.0.0.1 or ::1, for isolated tests.
  -h, --help                     Show this help.

VAR names must match [A-Za-z_][A-Za-z0-9_]{0,127}. Selected headers must use
distinct variables, including an independent client secret. Endpoints must be
exact registered server bindings. URLs cannot contain credentials, queries,
fragments, whitespace, controls or backslashes. No credential/auth-value flags.
"""
ERROR = "error: invalid configuration arguments; use --help for usage.\n"


def parse_options(arguments: list[str]) -> tuple[dict[str, str], set[str], bool]:
    options = dict(DEFAULT_OPTIONS)
    allowed = options.keys() | ENDPOINT_HEADERS.keys() | {"--provider"}
    providers: set[str] = set()
    seen: set[str] = set()
    allow_loopback_http = False
    remaining = iter(arguments)
    for argument in remaining:
        if argument in {"--help", "-h"}:
            options["--help"] = ""
            continue
        option, separator, value = argument.partition("=")
        if option in seen and option != "--provider":
            raise ValueError
        seen.add(option)
        if option == "--allow-loopback-http":
            if separator:
                raise ValueError
            allow_loopback_http = True
            continue
        if option not in allowed:
            raise ValueError
        if not separator:
            value = next(remaining, "")
            if not value or value.startswith("--"):
                raise ValueError
        if option == "--provider":
            if value not in PROVIDER_HEADERS:
                raise ValueError
            providers.add(value)
        else:
            options[option] = value
    return options, providers or {"modelark"}, allow_loopback_http


def validate_url(url: str, *, allow_loopback_http: bool) -> None:
    if not url or any(
        character.isspace() or not character.isprintable() or character == "\\" for character in url
    ):
        raise ValueError
    if "?" in url or "#" in url:
        raise ValueError
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError
    authority = re.fullmatch(
        r"(?:\[([0-9A-Fa-f:.]+)\]|([A-Za-z0-9.-]+))(?::([0-9]+))?", parsed.netloc
    )
    if authority is None:
        raise ValueError
    ipv6, hostname, port = authority.groups()
    if ipv6 is not None:
        ipaddress.IPv6Address(ipv6)
        hostname = ipv6.lower()
    elif re.fullmatch(r"[0-9.]+", hostname):
        ipaddress.IPv4Address(hostname)
    else:
        hostname = hostname.removesuffix(".")
        if len(hostname) > 253 or any(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is None
            for label in hostname.split(".")
        ):
            raise ValueError
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError
    if parsed.scheme == "http" and (
        not allow_loopback_http or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError


def select_headers(options: dict[str, str], providers: set[str]) -> dict[str, str]:
    for option, value in options.items():
        if option.endswith("-env") and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value) is None:
            raise ValueError
    headers = {
        header: options[option]
        for provider, (header, option) in PROVIDER_HEADERS.items()
        if provider in providers
    }
    headers["X-MCP-Client-Secret"] = options["--client-secret-env"]
    for option, header in ENDPOINT_HEADERS.items():
        if option in options:
            if "modelark" not in providers:
                raise ValueError
            headers[header] = options[option]
    if len(set(headers.values())) != len(headers):
        raise ValueError
    return headers


def render_config(
    client: str, name: str, url: str, timeout_seconds: int, headers: dict[str, str]
) -> str:
    if client == "claude-code":
        return (
            json.dumps(
                {
                    "mcpServers": {
                        name: {
                            "type": "http",
                            "url": url,
                            "timeout": timeout_seconds * 1000,
                            "headers": {
                                header: "${" + variable + "}"
                                for header, variable in headers.items()
                            },
                        }
                    }
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    table = "mcp_servers." + json.dumps(name)
    lines = [
        f"[{table}]",
        f"url = {json.dumps(url, ensure_ascii=False)}",
        f"tool_timeout_sec = {timeout_seconds}",
        "",
        f"[{table}.env_http_headers]",
    ]
    lines.extend(
        f"{json.dumps(header)} = {json.dumps(variable)}" for header, variable in headers.items()
    )
    return "\n".join(lines) + "\n"


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        options, providers, allow_loopback_http = parse_options(arguments)
        if "--help" in options:
            sys.stdout.write(HELP)
            return 0
        client = options["--client"]
        name = options["--name"]
        if (
            client not in {"codex", "claude-code"}
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None
        ):
            raise ValueError
        url = options["--url"]
        validate_url(url, allow_loopback_http=allow_loopback_http)
        timeout = options["--tool-timeout-seconds"]
        if re.fullmatch(r"[0-9]+", timeout) is None:
            raise ValueError
        timeout_seconds = int(timeout)
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError
        headers = select_headers(options, providers)
        rendered = render_config(client, name, url, timeout_seconds, headers)
    except ValueError:
        sys.stderr.write(ERROR)
        return 2
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
