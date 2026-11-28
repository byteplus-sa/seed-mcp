"""Client-side streaming upload for hosted MCP; no server, settings or .env loading."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ark_mcp.domain.errors import ProviderError
from ark_mcp.providers.modelark.files import ModelArkFilesGateway

if TYPE_CHECKING:
    from ark_mcp.domain.files import FilePurpose, ManagedFile

MODELARK_ORIGIN = "https://ark.ap-southeast.bytepluses.com/api/v3"


async def upload_local_file(
    *,
    file_path: str,
    api_key: str,
    purpose: FilePurpose = "agent",
    expire_at: int | None = None,
) -> ManagedFile:
    """Stream one selected regular file directly to ModelArk, without retries or polling."""
    gateway = ModelArkFilesGateway(
        api_key=api_key,
        base_url=MODELARK_ORIGIN,
        timeout=600,
        connect_timeout=15,
    )
    try:
        async with asyncio.timeout(600):
            return await gateway.upload(file_path=file_path, purpose=purpose, expire_at=expire_at)
    finally:
        await gateway.close()


def main() -> None:
    """Upload only after explicit consent; print metadata without signed URLs or credentials."""
    parser = argparse.ArgumentParser(
        description="Upload a local file directly to ModelArk-managed storage, then use ark_file_get in MCP.",
    )
    parser.add_argument(
        "--file", required=True, help="Selected local regular file, at most 512 MB."
    )
    parser.add_argument(
        "--api-key-env",
        default="BYTEPLUS_MODELARK_API_KEY",
        help="Environment variable containing the ModelArk key; never pass the key itself.",
    )
    parser.add_argument("--purpose", choices=("agent", "user_data"), default="agent")
    parser.add_argument(
        "--expire-at",
        type=int,
        help="UTC Unix expiry, 1-30 days from now; provider default 7 days.",
    )
    parser.add_argument(
        "--confirm-upload",
        action="store_true",
        help="Confirm transfer of this exact file to ModelArk.",
    )
    args = parser.parse_args()
    if not args.confirm_upload:
        parser.error("Review the selected file and destination, then pass --confirm-upload.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.api_key_env):
        parser.error("--api-key-env must be an environment variable name, not a credential.")
    key = os.environ.get(args.api_key_env)
    if not key:
        parser.error("The selected API-key environment variable is empty. No .env files are read.")
    try:
        result = asyncio.run(
            upload_local_file(
                file_path=str(Path(args.file).absolute()),
                api_key=key,
                purpose=args.purpose,
                expire_at=args.expire_at,
            )
        )
    except ProviderError as exc:
        print(exc.error.model_dump_json(), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError):
        print(
            "Upload failed validation or local I/O. No automatic retry was attempted.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (TimeoutError, KeyboardInterrupt):
        print(
            "Upload interrupted; the provider may have accepted it. Do not upload again blindly.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "id": result.id,
                "status": result.status,
                "purpose": result.purpose,
                "bytes": result.bytes,
                "expire_at": result.expire_at,
                "next_tool": "ark_file_get",
            }
        )
    )


if __name__ == "__main__":
    main()
