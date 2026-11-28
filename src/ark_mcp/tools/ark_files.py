"""Managed Files tools; specs/SPEC_HOSTED_BYOK.md defines transport and authorization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import Context
from fastmcp.tools import ToolResult

from ark_mcp.domain.errors import ProviderError
from ark_mcp.domain.files import (
    FileDeleted,
    FileDeleteInput,
    FileGetInput,
    FileListInput,
    FilePage,
    FileUploadInput,
    ManagedFile,
)
from ark_mcp.providers.modelark.files import ModelArkFilesGateway
from ark_mcp.runtime import get_principal, get_runtime
from ark_mcp.security.credentials import provider_api_key
from ark_mcp.security.url_policy import UrlValidationError, validate_url
from ark_mcp.tools._errors import provider_error_result

UPLOAD_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
DELETE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}


@asynccontextmanager
async def _service(ctx: Context) -> AsyncIterator[ModelArkFilesGateway]:
    runtime = get_runtime(ctx)
    settings = runtime.settings
    gateway = ModelArkFilesGateway(
        api_key=provider_api_key(ctx, "modelark"),
        base_url=settings.modelark_base_url,
        timeout=settings.request_timeout_ms / 1000,
        connect_timeout=settings.connect_timeout_ms / 1000,
    )
    try:
        async with runtime.provider_limiters.acquire("modelark", get_principal(ctx)):
            yield gateway
    finally:
        await gateway.close()


async def ark_file_upload(input: FileUploadInput, ctx: Context) -> ManagedFile | ToolResult:
    """Upload one file to ModelArk-managed storage, with no bucket setup.

    HTTP accepts a public HTTPS source URL, not client-local paths or Base64.
    For local files on a hosted connection, run seed-mcp-upload on the client.
    Stdio also accepts an absolute regular-file path (512 MB maximum).
    Default purpose=agent. Keep the returned id; call ark_file_get until active
    and download_url is present, then pass that URL to Seedance/Seedream/Seed Audio.
    Do not pass file_id to generation or delete a reference while work is running.
    File retention defaults to seven days. URLs have separate 24-hour/100-download
    limits and are not renewed by reads. No automatic upload retry or polling.
    """
    if input.file_path is not None and get_runtime(ctx).settings.mcp_transport != "stdio":
        raise ValueError("HTTP cannot read client-local paths. Use seed-mcp-upload on the client.")
    if input.url is not None:
        try:
            await asyncio.to_thread(validate_url, input.url)
        except UrlValidationError:
            raise ValueError("The upload source must be a public HTTPS URL.") from None
    try:
        async with _service(ctx) as service:
            return await service.upload(**input.model_dump())
    except ProviderError as exc:
        return provider_error_result(exc)
    except OSError:
        raise ValueError("The local upload file could not be opened safely.") from None


async def ark_file_get(input: FileGetInput, ctx: Context) -> ManagedFile | ToolResult:
    """Retrieve authorized file metadata, processing status and any download_url.

    Poll the same ID while processing; never upload again to poll. An active file
    may lack a URL, especially purpose=user_data. Reads neither download bytes nor
    renew the link's 24-hour/100-download limit. Keep signed URLs private.
    Access follows the supplied ModelArk key, not a client-secret ownership ledger.
    """
    try:
        async with _service(ctx) as service:
            return await service.get_file(input.file_id)
    except ProviderError as exc:
        return provider_error_result(exc)


async def ark_file_list(input: FileListInput, ctx: Context) -> FilePage | ToolResult:
    """List one page of files authorized by the ModelArk key, newest first by default.

    Defaults to purpose=agent and 20 files. Continue with after=last_id only when
    has_more is true. Keys shared by multiple clients share provider-authorized
    file access. Results may contain sensitive download URLs; do not publish them.
    No local ownership filtering, pagination loop or URL renewal is performed.
    """
    try:
        async with _service(ctx) as service:
            return await service.list_files(input)
    except ProviderError as exc:
        return provider_error_result(exc)


async def ark_file_delete(input: FileDeleteInput, ctx: Context) -> FileDeleted | ToolResult:
    """Permanently delete one authorized file. Explicit confirm=true is required.

    This removes the provider file; it cannot be restored. Wait until every
    generation task using the reference has finished. Authorization comes from
    the ModelArk key, so this can affect other clients sharing that key.
    One DELETE is sent; uncertain outcomes are never automatically retried.
    """
    try:
        async with _service(ctx) as service:
            return await service.delete_file(input.file_id)
    except ProviderError as exc:
        return provider_error_result(exc)
