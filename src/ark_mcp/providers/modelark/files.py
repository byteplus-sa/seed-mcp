"""Bounded, single-attempt ModelArk Files API with streamed local uploads."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel

from ark_mcp.domain.errors import NormalizedProviderError, ProviderError
from ark_mcp.domain.files import (
    MAX_FILE_BYTES,
    FileDeleted,
    FileGetInput,
    FileListInput,
    FilePage,
    FilePurpose,
    ManagedFile,
    validate_expiry,
)
from ark_mcp.domain.submissions import IDENTIFIER_PATTERN
from ark_mcp.execution import authorize_provider_request, record_accepted_receipt
from ark_mcp.providers.base import retry_after_seconds, safe_provider_text
from ark_mcp.providers.modelark.client import ModelArkGateway
from ark_mcp.security.credentials import redact_request_secrets
from ark_mcp.sqlite_io import drain_task

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class LocalFileUpload(httpx.AsyncByteStream):
    """Stable regular-file handle, bounded multipart stream, no filesystem persistence."""

    def __init__(self, path: str, fields: dict[str, str]) -> None:
        source = Path(path)
        if not source.is_absolute():
            raise ValueError("file_path must be absolute.")
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            raise ValueError("This platform does not provide safe no-follow file upload support.")
        descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        self._file: BinaryIO = os.fdopen(descriptor, "rb")
        try:
            self._stat = os.fstat(self._file.fileno())
            if not stat.S_ISREG(self._stat.st_mode):
                raise ValueError("Only regular files may be uploaded.")
            if not 0 < self._stat.st_size <= MAX_FILE_BYTES:
                raise ValueError("Upload must contain 1-512000000 bytes (512 MB).")
            self.boundary = uuid4().hex
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)[:200] or "upload.bin"
            prefix = "".join(
                f'--{self.boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                for key, value in fields.items()
            )
            prefix += (
                f'--{self.boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            )
            self._prefix = prefix.encode("ascii")
            self._suffix = f"\r\n--{self.boundary}--\r\n".encode("ascii")
            self.length = len(self._prefix) + self._stat.st_size + len(self._suffix)
        except BaseException:
            self._file.close()
            raise

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._prefix
        remaining = self._stat.st_size
        while remaining:
            chunk = await drain_task(
                asyncio.create_task(asyncio.to_thread(self._file.read, min(CHUNK_BYTES, remaining)))
            )
            if not chunk:
                raise ValueError("Source file changed during upload; do not retry blindly.")
            remaining -= len(chunk)
            yield chunk
        current = os.fstat(self._file.fileno())
        if (current.st_size, current.st_mtime_ns) != (self._stat.st_size, self._stat.st_mtime_ns):
            raise ValueError("Source file changed during upload; do not retry blindly.")
        yield self._suffix

    async def aclose(self) -> None:
        self._file.close()


class ModelArkFilesGateway(ModelArkGateway):
    """No automatic retries, downloads, TOS configuration, or account-state caching."""

    def _redact(self, value: str) -> str:
        for secret in sorted({self._api_key, quote(self._api_key, safe="")}, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return redact_request_secrets(value)

    def _contains_credential(self, value: Any) -> bool:
        if isinstance(value, str):
            return self._redact(value) != value
        if isinstance(value, dict):
            return any(self._contains_credential(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_credential(item) for item in value)
        return False

    def _safe_id(self, value: object) -> str | None:
        if not isinstance(value, str) or not re.fullmatch(IDENTIFIER_PATTERN, value):
            return None
        if self._redact(value) != value or safe_provider_text(value) != value:
            return None
        return value

    async def _send[T: BaseModel](
        self,
        method: str,
        path: str,
        model: type[T],
        *,
        expected_id: str | None = None,
        upload: bool = False,
        **kwargs: Any,
    ) -> T:
        client = await self._ensure_client()
        mutation = method != "GET"
        correlation = str(uuid4())
        headers = self._headers()
        headers.pop("Content-Type", None)
        headers.update(kwargs.pop("headers", {}))
        headers["X-Request-Id"] = correlation
        operation = "upload_file" if upload else "delete_file" if mutation else "read_files"
        await authorize_provider_request(side_effect=mutation)
        try:
            async with client.stream(
                method, self.base_url + path, headers=headers, **kwargs
            ) as response:
                request_id = self._safe_id(self.extract_request_id(response)) or correlation
                raw = bytearray()
                async for chunk in response.aiter_bytes(CHUNK_BYTES):
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise self.invalid_response(
                            operation,
                            http_status=response.status_code,
                            request_id=request_id,
                            mutation=mutation,
                        )
                    raw.extend(chunk)
                if not 200 <= response.status_code < 300:
                    try:
                        error = json.loads(raw)
                    except ValueError:
                        error = {}
                    if isinstance(error, dict):
                        error = error.get("error", error)
                    if not isinstance(error, dict):
                        error = {}
                    raise ProviderError(
                        NormalizedProviderError(
                            provider="modelark",
                            operation=operation,
                            http_status=response.status_code,
                            request_id=request_id,
                            message=safe_provider_text(
                                self._redact(str(error.get("message", ""))),
                                "Files API request failed.",
                            ),
                            code=safe_provider_text(self._redact(str(error.get("code", ""))))
                            or None,
                            ambiguous_completion=mutation and response.status_code >= 500,
                            retryable=not mutation
                            and (response.status_code == 429 or response.status_code >= 500),
                            retry_after_seconds=retry_after_seconds(
                                response.headers.get("Retry-After")
                            ),
                        )
                    )
                try:
                    result = model.model_validate_json(raw)
                    if expected_id is not None and getattr(result, "id", None) != expected_id:
                        raise ValueError("Mismatched response identifier.")
                    # Reject any credential echo without ever returning raw response diagnostics.
                    if self._contains_credential(result.model_dump()):
                        raise ValueError("Provider echoed a credential.")
                    if isinstance(result, ManagedFile):
                        if result.error:
                            result.error.code = safe_provider_text(result.error.code) or None
                            result.error.message = safe_provider_text(result.error.message) or None
                        if upload:
                            record_accepted_receipt(result.id, request_id, resource="file")
                    if isinstance(result, FilePage):
                        for item in result.data:
                            if item.error:
                                item.error.code = safe_provider_text(item.error.code) or None
                                item.error.message = safe_provider_text(item.error.message) or None
                    return result.model_copy(update={"request_id": request_id})
                except ValueError:
                    raise self.invalid_response(
                        operation,
                        http_status=response.status_code,
                        request_id=request_id,
                        mutation=mutation,
                    ) from None
        except httpx.RequestError as exc:
            error = self.normalize_transport_error(operation, exc, side_effect=mutation).error
            raise ProviderError(error.model_copy(update={"request_id": correlation})) from None
        except (OSError, ValueError):
            raise ProviderError(
                NormalizedProviderError(
                    provider="modelark",
                    operation=operation,
                    code="UPLOAD_IO_ERROR",
                    message="File transfer failed; the provider outcome may be unknown. Do not upload again automatically.",
                    request_id=correlation,
                    retryable=False,
                    ambiguous_completion=mutation,
                )
            ) from None

    async def upload(
        self,
        *,
        url: str | None = None,
        file_path: str | None = None,
        purpose: FilePurpose = "agent",
        expire_at: int | None = None,
    ) -> ManagedFile:
        """Upload once; callers retrieve the returned ID for readiness and download_url."""
        if (url is None) == (file_path is None):
            raise ValueError("Provide exactly one upload source.")
        validate_expiry(expire_at)
        fields: dict[str, str] = {"purpose": purpose}
        if expire_at is not None:
            fields["expire_at"] = str(expire_at)
        if url is not None:
            fields["url"] = url
            return await self._send(
                "POST",
                "/files",
                ManagedFile,
                upload=True,
                files={key: (None, value) for key, value in fields.items()},
            )
        if file_path is None:
            raise ValueError("Provide a local file path when url is omitted.")
        stream = LocalFileUpload(file_path, fields)
        try:
            return await self._send(
                "POST",
                "/files",
                ManagedFile,
                upload=True,
                content=stream,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={stream.boundary}",
                    "Content-Length": str(stream.length),
                },
            )
        finally:
            await stream.aclose()

    async def get_file(self, file_id: str) -> ManagedFile:
        """Retrieve a single authorized file; no URL renewal or download."""
        FileGetInput(file_id=file_id)
        return await self._send("GET", f"/files/{file_id}", ManagedFile, expected_id=file_id)

    async def list_files(self, params: FileListInput) -> FilePage:
        """Return one bounded page without traversal or inferred ownership."""
        result = await self._send(
            "GET", "/files", FilePage, params=params.model_dump(exclude_none=True)
        )
        if len(result.data) > params.limit:
            raise self.invalid_response(
                "read_files", http_status=200, request_id=result.request_id, mutation=False
            )
        return result

    async def delete_file(self, file_id: str) -> FileDeleted:
        """Permanently delete one file in a single provider request."""
        FileGetInput(file_id=file_id)
        return await self._send("DELETE", f"/files/{file_id}", FileDeleted, expected_id=file_id)
