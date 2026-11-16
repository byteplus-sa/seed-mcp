"""Validate private host configuration without executing or printing its values."""

from __future__ import annotations

import math
import os
import re
import stat
import sys
from pathlib import Path

IDENTITY_SETTINGS = frozenset({"MCP_IDENTITY_HMAC_KEY", "MCP_IDENTITY_KEY_VERSION"})
HOSTED_SETTINGS = IDENTITY_SETTINGS | {
    "MCP_AUTH_MODE",
    "MCP_PUBLIC_HOST",
    "MCP_ALLOWED_ORIGINS",
    "BYTEPLUS_OMNIHUMAN_ENABLED",
    "DAILY_BUDGET_USD",
    "RATE_LIMIT_RPM",
    "RATE_LIMIT_BURST",
    "MCP_HTTP_MAX_IN_FLIGHT",
    "MCP_HTTP_MAX_BODY_BYTES",
    "PROVIDER_MAX_CONCURRENCY",
    "PRINCIPAL_MAX_CONCURRENCY",
    "STATE_BACKEND",
    "STATE_MAX_RECORDS",
    "STATE_PRUNE_MAX_AGE_DAYS",
    "ARK_LOG_LEVEL",
}


def load_environment(path: Path, *, expected_uid: int = 0) -> dict[str, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, encoding="utf-8") as stream:
        metadata = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != expected_uid
        ):
            raise ValueError("The .env must be a root-owned regular file with mode 0600.")
        if metadata.st_size > 65536:
            raise ValueError("The .env exceeds 64 KiB.")
        return parse_environment(stream.read(65537))


def parse_environment(content: str) -> dict[str, str]:
    if len(content.encode()) > 65536:
        raise ValueError("The .env exceeds 64 KiB.")
    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Use one KEY=value assignment per line.")
        if key in values:
            raise ValueError("Duplicate setting.")
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if any(character in value for character in "$`"):
            raise ValueError("Settings must be literal values without interpolation.")
        values[key] = value
    return values


def validate_identity(values: dict[str, str]) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", values.get("MCP_IDENTITY_HMAC_KEY", "")):
        raise ValueError("MCP_IDENTITY_HMAC_KEY must be 32 random bytes as 64 lowercase hex.")
    if not re.fullmatch(r"[1-9][0-9]*", values.get("MCP_IDENTITY_KEY_VERSION", "")):
        raise ValueError("MCP_IDENTITY_KEY_VERSION must be a positive integer.")


def validate_authentication(values: dict[str, str]) -> None:
    if values.get("MCP_AUTH_MODE", "byok") != "byok":
        raise ValueError("Hosted MCP_AUTH_MODE must be byok.")
    validate_identity(values)


def validate_environment(values: dict[str, str]) -> None:
    if set(values) - HOSTED_SETTINGS:
        raise ValueError(
            "Hosted configuration accepts only operator settings; customer keys and job settings are forbidden."
        )
    host = values.get("MCP_PUBLIC_HOST", "")
    if not re.fullmatch(r"([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", host):
        raise ValueError("MCP_PUBLIC_HOST must be a DNS hostname.")
    if host == "example.com" or host.endswith(".example.com"):
        raise ValueError("Replace the example MCP_PUBLIC_HOST.")
    validate_authentication(values)
    for key in (
        "DAILY_BUDGET_USD",
        "RATE_LIMIT_RPM",
        "RATE_LIMIT_BURST",
        "MCP_HTTP_MAX_IN_FLIGHT",
        "MCP_HTTP_MAX_BODY_BYTES",
        "STATE_MAX_RECORDS",
        "STATE_PRUNE_MAX_AGE_DAYS",
        "PROVIDER_MAX_CONCURRENCY",
        "PRINCIPAL_MAX_CONCURRENCY",
    ):
        value = values.get(key, "")
        if key != "DAILY_BUDGET_USD" and not re.fullmatch(r"0|[1-9][0-9]*", value):
            raise ValueError(f"{key} must be an integer.")
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"{key} must be positive.") from None
        if (
            not math.isfinite(number)
            or number < 0
            or (number == 0 and key != "RATE_LIMIT_BURST")
            or (key != "DAILY_BUDGET_USD" and not number.is_integer())
        ):
            raise ValueError(
                f"{key} must be positive; request and concurrency limits must be integers."
            )
    if float(values["STATE_PRUNE_MAX_AGE_DAYS"]) < 14:
        raise ValueError("STATE_PRUNE_MAX_AGE_DAYS must be at least 14.")
    if values.get("STATE_BACKEND", "sqlite") != "sqlite":
        raise ValueError("Hosted state must use single-instance SQLite.")
    if values.get("BYTEPLUS_OMNIHUMAN_ENABLED", "false") not in {"true", "false"}:
        raise ValueError("BYTEPLUS_OMNIHUMAN_ENABLED must be true or false.")
    if values.get("ARK_LOG_LEVEL", "INFO") not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Invalid ARK_LOG_LEVEL.")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_env.py /path/to/private/.env", file=sys.stderr)
        return 2
    try:
        validate_environment(load_environment(Path(sys.argv[1])))
    except (OSError, UnicodeError, ValueError) as error:
        message = str(error) if type(error) is ValueError else "Cannot read the private .env file."
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
