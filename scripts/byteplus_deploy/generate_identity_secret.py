"""Create a private operator HMAC env file or client isolation secret, never an MCP key."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("purpose", choices=("operator", "client"))
    parser.add_argument("output_file", type=Path, help="New file in an existing private directory.")
    args = parser.parse_args(argv)
    if os.name != "posix":
        parser.error("Secret generation requires a POSIX host with private file permissions.")
    try:
        parent = args.output_file.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise ValueError
        secret = os.urandom(32).hex()
        content = (
            f"MCP_IDENTITY_HMAC_KEY={secret}\nMCP_IDENTITY_KEY_VERSION=1\n"
            if args.purpose == "operator"
            else secret + "\n"
        )
        descriptor = os.open(
            args.output_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        print(
            "Cannot create secret file. Use a new path in a same-owner mode-0700 directory.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
